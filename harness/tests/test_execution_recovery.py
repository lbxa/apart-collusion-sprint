import asyncio
import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import openai
import pytest
from deepagents.backends.sandbox import BaseSandbox
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver

from veracity_harness.agents import BudgetExceeded, ModelBudget, ParticipantAgent
from veracity_harness.config import ModelSettings, load_experiment
from veracity_harness.runner import ROOT, run_experiment
from veracity_harness.spending import CampaignSpending, ModelPrice


class NoShell(BaseSandbox):
    @property
    def id(self):
        return "recovery-fixture"

    def execute(self, command, *, timeout=None):
        raise AssertionError("This regression must not execute a game action")

    def upload_files(self, files):
        raise AssertionError("No file transfer expected")

    def download_files(self, paths):
        raise AssertionError("No file transfer expected")


class FlakyModel(BaseChatModel):
    calls: int = 0
    status_code: int = 502

    @property
    def _llm_type(self):
        return "transient-recovery-fixture"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        if self.calls == 1:
            request = httpx.Request("POST", "http://unused")
            raise openai.APIStatusError(
                "Private server detail must stay out of ordinary logs",
                response=httpx.Response(self.status_code, request=request),
                body=None,
            )
        return ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(
                        content="Done",
                        response_metadata={"cost": 0.001},
                    )
                )
            ]
        )


def agent(tmp_path, model, **kwargs):
    return ParticipantAgent(
        "juror-1",
        NoShell(),
        tmp_path / "memory",
        InMemorySaver(),
        ModelSettings(
            name="fixture/model", max_tokens=256, calls_per_episode=10, turn_timeout_seconds=600
        ),
        model=model,
        system_prompt="Fixture instructions.",
        **kwargs,
    )


@pytest.mark.parametrize("status", [408, 429, 502, 503, 504])
async def test_transient_provider_failure_can_continue_with_a_new_budgeted_request(
    tmp_path, status
):
    spending = CampaignSpending(tmp_path / "spending.sqlite", Decimal(1))
    price = ModelPrice(
        id="fixture/model",
        context_length=1000,
        pricing={"prompt": "0.000001", "completion": "0.000002"},
    )
    model = FlakyModel(status_code=status)
    participant = agent(tmp_path, model, spending=spending, price=price)
    first = await participant.act("case", 1, tmp_path / "first.jsonl")
    assert first.status == "failed"
    assert getattr(first, "recoverable", False) is True
    assert first.http_status == status
    assert model.calls == 1  # No hidden retry inside an opportunity.
    assert spending.snapshot()["unresolved_requests"] == 1
    second = await participant.act("case", 2, tmp_path / "second.jsonl")
    assert second.status == "completed" and model.calls == 2
    assert spending.snapshot()["requests"] == 2
    assert spending.snapshot()["charged_usd"] == "0.001"
    assert spending.snapshot()["unresolved_requests"] == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
async def test_invalid_provider_request_is_not_retryable(tmp_path, status):
    participant = agent(tmp_path, FlakyModel(status_code=status))
    result = await participant.act("case", 1, tmp_path / "trace.jsonl")
    assert result.status == "failed"
    assert getattr(result, "recoverable", False) is False
    assert getattr(result, "http_status", None) == status


def test_turn_deadline_stops_new_requests_before_reserving_money(monkeypatch, tmp_path):
    now = [0.0]
    monkeypatch.setattr("veracity_harness.agents.time", SimpleNamespace(monotonic=lambda: now[0]))
    settings = ModelSettings(name="fixture/model", turn_timeout_seconds=600, max_tokens=256)
    spending = CampaignSpending(tmp_path / "spending.sqlite", Decimal(1))
    price = ModelPrice(
        id=settings.name,
        context_length=1000,
        pricing={"prompt": "0.000001", "completion": "0.000002"},
    )
    budget = ModelBudget(settings, spending, price)
    budget.begin_turn()
    now[0] = 601
    with pytest.raises(BudgetExceeded, match="time"):
        budget.on_chat_model_start({}, [[HumanMessage("Observe")]], run_id="too-late")
    assert budget.calls == 0 and spending.snapshot()["requests"] == 0


async def test_inflight_response_finishes_then_turn_yields_at_next_request(monkeypatch, tmp_path):
    now = [0.0]
    monkeypatch.setattr("veracity_harness.agents.time", SimpleNamespace(monotonic=lambda: now[0]))

    class SlowResponse(BaseChatModel):
        calls: int = 0

        @property
        def _llm_type(self):
            return "request-boundary-fixture"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            now[0] = 601
            reply = (
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_todos",
                            "id": "one",
                            "args": {"todos": []},
                        }
                    ],
                )
                if self.calls == 1
                else AIMessage(content="Done")
            )
            return ChatResult(generations=[ChatGeneration(message=reply)])

    model = SlowResponse()
    participant = agent(tmp_path, model)
    result = await participant.act("case", 1, tmp_path / "trace.jsonl")
    assert result.status == "yielded"
    assert model.calls == participant.budget.calls == 1
    assert any(
        e["event"] == "model_end"
        for e in map(json.loads, (tmp_path / "trace.calls.jsonl").read_text().splitlines())
    )


async def test_interrupted_tool_is_marked_unknown_and_never_automatically_reexecuted(tmp_path):
    class CheckHistory(BaseChatModel):
        saw_interruption: bool = False

        @property
        def _llm_type(self):
            return "interrupted-tool-history-fixture"

        def bind_tools(self, tools, **kwargs):
            return self

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            result = next(
                (
                    m
                    for m in messages
                    if isinstance(m, ToolMessage) and m.tool_call_id == "uncertain-action"
                ),
                None,
            )
            assert result is not None, "Missing tool result would poison the next provider request"
            assert result.status == "error" and "unknown" in result.content.lower()
            self.saw_interruption = True
            return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Done"))])

    model = CheckHistory()
    participant = agent(tmp_path, model)
    await participant.graph.aupdate_state(
        {"configurable": {"thread_id": "juror-1"}},
        {
            "messages": [
                HumanMessage("Old opportunity"),
                AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "execute",
                            "id": "uncertain-action",
                            "args": {"command": "never repeat"},
                        }
                    ],
                ),
            ]
        },
        as_node="model",
    )
    result = await participant.act("case", 2, tmp_path / "trace.jsonl")
    assert result.status == "completed" and model.saw_interruption
    events = [
        json.loads(line) for line in (tmp_path / "trace.calls.jsonl").read_text().splitlines()
    ]
    assert any(e["event"] == "history_recovery" for e in events)


async def test_startup_failure_records_safe_stage_and_http_status(monkeypatch, tmp_path):
    import docker.errors

    class UnavailableEngine:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            raise docker.errors.APIError(
                "Private Docker URL and credentials",
                response=SimpleNamespace(status_code=503),
                explanation="Private Docker response body",
            )

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr("veracity_harness.runner.LocalEngine", UnavailableEngine)
    experiment = load_experiment(
        ROOT / "harness/examples/discovery.toml", model_name="fixture/model"
    )
    with pytest.raises(docker.errors.APIError):
        await run_experiment(experiment, tmp_path, model=FlakyModel())
    manifest = json.loads(next(tmp_path.glob("run-*/run.json")).read_text())
    assert manifest["status"] == "failed"
    assert manifest["error_details"] == {
        "stage": "engine_startup",
        "error_type": "APIError",
        "http_status": 503,
    }
    assert "Private Docker" not in json.dumps(manifest)


async def test_bad_rate_store_fails_before_catalog_or_reservation(monkeypatch, tmp_path):
    from veracity_harness.ratelimit import RateLimitStoreError

    blocked = tmp_path / "not-a-directory"
    blocked.write_text("file")
    monkeypatch.setenv("VERACITY_RATE_DB", str(blocked / "rate.sqlite"))

    async def unexpected_catalog(*args):
        raise AssertionError("Catalog access must follow rate-store preflight")

    monkeypatch.setattr("veracity_harness.runner.fetch_cloudflare_price", unexpected_catalog)
    experiment = load_experiment(
        ROOT / "harness/examples/discovery.toml", model_name="fixture/model"
    )
    experiment = experiment.model_copy(
        update={
            "model": experiment.model.model_copy(update={"provider": "cloudflare"}),
        }
    )
    spending = CampaignSpending(tmp_path / "budget.sqlite", Decimal(1))
    with pytest.raises(RateLimitStoreError, match="VERACITY_RATE_DB"):
        await run_experiment(experiment, tmp_path / "runs", spending=spending)
    assert spending.snapshot()["requests"] == 0
    assert not (tmp_path / "runs").exists()


@pytest.mark.parametrize("provider", ["openrouter", "cloudflare"])
async def test_catalog_rejection_is_retained_before_engine_startup(monkeypatch, tmp_path, provider):
    async def rejected_catalog(*args):
        raise openai.APIStatusError(
            "Private authentication detail",
            response=httpx.Response(401, request=httpx.Request("GET", "http://unused")),
            body=None,
        )

    monkeypatch.setattr("veracity_harness.runner.fetch_model_price", rejected_catalog)
    monkeypatch.setattr("veracity_harness.runner.fetch_cloudflare_price", rejected_catalog)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fixture-account")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fixture-not-a-credential")
    experiment = load_experiment(
        ROOT / "harness/examples/discovery.toml", model_name="fixture/model", provider=provider
    )
    spending = CampaignSpending(tmp_path / "budget.sqlite", Decimal(1))
    with pytest.raises(openai.APIStatusError):
        await run_experiment(experiment, tmp_path, spending=spending)
    manifests = list(tmp_path.glob("run-*/run.json"))
    assert len(manifests) == 1, "Catalog failures must leave an auditable run record"
    manifest = json.loads(manifests[0].read_text())
    assert manifest["error_details"] == {
        "stage": "model_catalog",
        "error_type": "APIStatusError",
        "http_status": 401,
    }
    assert spending.snapshot()["requests"] == 0
    assert "Private authentication" not in json.dumps(manifest)


def test_cancelled_request_retains_its_hold_and_explicit_audit(tmp_path):
    settings = ModelSettings(name="fixture/model", max_tokens=256)
    spending = CampaignSpending(tmp_path / "budget.sqlite", Decimal(1))
    price = ModelPrice(
        id=settings.name,
        context_length=1000,
        pricing={"prompt": "0.000001", "completion": "0.000002"},
    )
    budget = ModelBudget(settings, spending, price)
    budget.audit_path = tmp_path / "calls.jsonl"
    budget.begin_turn()
    budget.on_chat_model_start({}, [[HumanMessage("Observe")]], run_id="interrupted")
    before = spending.snapshot()
    budget.cancel_pending()
    assert spending.snapshot() == before
    events = [json.loads(line) for line in budget.audit_path.read_text().splitlines()]
    assert [e["event"] for e in events] == ["model_start", "model_cancelled"]
    assert events[-1]["request_id"] == "interrupted"


async def test_hard_watchdog_cancels_hung_request_and_retains_its_hold(monkeypatch, tmp_path):
    original_timeout = asyncio.timeout
    durations = []
    watchdog = None

    def accelerated_timeout(duration):
        nonlocal watchdog
        durations.append(duration)
        watchdog = original_timeout(None)
        return watchdog

    monkeypatch.setattr(
        "veracity_harness.agents.asyncio",
        SimpleNamespace(timeout=accelerated_timeout, CancelledError=asyncio.CancelledError),
    )

    class HungModel(FlakyModel):
        async def _agenerate(self, *args, **kwargs):
            # Expire only after the request has reserved its hold. A fixed 20 ms
            # deadline could fire during graph setup on a loaded machine.
            assert watchdog is not None
            watchdog.reschedule(asyncio.get_running_loop().time())
            await asyncio.Event().wait()

    spending = CampaignSpending(tmp_path / "budget.sqlite", Decimal(1))
    price = ModelPrice(
        id="fixture/model",
        context_length=1000,
        pricing={"prompt": "0.000001", "completion": "0.000002"},
    )
    participant = agent(tmp_path, HungModel(), spending=spending, price=price)
    result = await asyncio.wait_for(participant.act("case", 1, tmp_path / "trace.jsonl"), 5)
    assert result.status == "timeout" and result.recoverable
    assert result.error_type == "TimeoutError" and result.failure_kind == "turn_timeout"
    assert durations == [1290]  # Two 600 s intervals, one rate window, 30 s tool grace.
    assert spending.snapshot()["requests"] == spending.snapshot()["unresolved_requests"] == 1
    assert not participant.budget.pending_requests
    events = [
        json.loads(line) for line in (tmp_path / "trace.calls.jsonl").read_text().splitlines()
    ]
    assert [event["event"] for event in events] == ["model_start", "model_cancelled"]
