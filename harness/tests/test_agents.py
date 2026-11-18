import json
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from deepagents.backends.sandbox import BaseSandbox
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from veracity_harness.agents import (
    BudgetExceeded,
    ChatCloudflare,
    ModelBudget,
    ParticipantAgent,
)
from veracity_harness.config import ModelSettings
from veracity_harness.spending import CampaignSpending, ModelPrice


def test_cloudflare_sampling_seed_reaches_request_payload(monkeypatch):
    from veracity_harness.agents import create_cloudflare_model

    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fixture-account")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fixture-token")
    model = create_cloudflare_model(
        ModelSettings(name="@cf/fixture", provider="cloudflare", sampling_seed=29), None
    )
    assert model._get_request_payload([HumanMessage("test")])["seed"] == 29


def test_openrouter_sampling_seed_reaches_provider_parameters(monkeypatch):
    from veracity_harness.agents import create_openrouter_model

    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-key")
    model = create_openrouter_model(ModelSettings(name="fixture/model", sampling_seed=29), None)
    assert model._default_params["seed"] == 29


async def test_cloudflare_json_mode_preserves_length_limited_response_and_charge(tmp_path):
    import httpx

    seen = []
    cost = Decimal("0.008212")

    def respond(request):
        seen.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "fixture-completion",
                "object": "chat.completion",
                "created": 1,
                "model": "@cf/fixture",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "length",
                        "message": {"role": "assistant", "content": '{"verdict":'},
                    }
                ],
                "usage": {
                    "prompt_tokens": 20,
                    "completion_tokens": 4096,
                    "total_tokens": 4116,
                    "neurons": float(cost / Decimal("0.000011")),
                },
            },
        )

    transport = httpx.MockTransport(respond)
    model = ChatCloudflare(
        model="@cf/fixture",
        base_url="https://cloudflare.fixture/v1",
        api_key="fixture-key",
        max_tokens=4096,
        max_retries=0,
        capacity_retries=0,
        http_async_client=httpx.AsyncClient(transport=transport),
        http_client=httpx.Client(transport=transport),
        rate_limit_path=tmp_path / "rate.sqlite",
    )
    settings = ModelSettings(
        name="@cf/fixture", provider="cloudflare", text_input_token_ceiling=16384
    )
    price = ModelPrice(
        id=settings.name,
        context_length=20000,
        pricing={"prompt": "0.000001", "completion": "0.000002"},
    )
    ledger = CampaignSpending(tmp_path / "spending.sqlite", Decimal(1))
    budget = ModelBudget(settings, ledger, price)
    budget.begin_turn()
    try:
        message = await model.ainvoke(
            [HumanMessage("Return a JSON verdict")],
            extra_body={"response_format": {"type": "json_object"}},
            config={"callbacks": [budget]},
        )
    finally:
        await model.root_async_client.close()
        model.root_client.close()
    assert seen[0]["response_format"] == {"type": "json_object"}
    assert message.response_metadata["finish_reason"] == "length"
    assert message.usage_metadata["output_tokens"] == 4096
    assert ledger.snapshot()["unresolved_requests"] == 0
    assert abs(Decimal(ledger.snapshot()["charged_usd"]) - cost) < Decimal("0.000000001")


def test_bounded_text_budget_reserves_checked_input_not_full_context(tmp_path):
    price = ModelPrice(
        id="fixture/model",
        context_length=1000000,
        pricing={"prompt": "0.000008", "completion": "0.00002"},
    )
    ledger = CampaignSpending(tmp_path / "spending.sqlite", Decimal(10))
    settings = ModelSettings(name=price.id, text_input_token_ceiling=131072, max_tokens=2048)
    budget = ModelBudget(settings, ledger, price)
    budget.begin_turn()
    budget.on_chat_model_start({}, [[HumanMessage("a short source document")]], run_id="bounded")
    assert Decimal(ledger.snapshot()["accounted_usd"]) == price.request_ceiling(
        2048, input_tokens=131072
    )
    assert Decimal(ledger.snapshot()["accounted_usd"]) < price.request_ceiling(2048)
    with pytest.raises(ValueError, match="input-token reservation"):
        budget.on_chat_model_start({}, [[HumanMessage("x" * 131072)]], run_id="oversize")
    with pytest.raises(ValueError, match="tools and plugins"):
        budget.on_chat_model_start(
            {},
            [[HumanMessage("short")]],
            run_id="tools",
            invocation_params={"tools": [{"type": "function"}]},
        )
    with pytest.raises(ValueError, match="plain conversation"):
        budget.on_chat_model_start(
            {}, [[HumanMessage([{"type": "text", "text": "block"}])]], run_id="multimodal"
        )
    assert ledger.snapshot()["requests"] == 1


def test_aggregate_budget_includes_delegated_calls_and_rejects_before_provider_request():
    budget = ModelBudget(ModelSettings(name="fixture/model", calls_per_turn=2, calls_per_episode=3))
    budget.begin_turn()
    budget.on_chat_model_start({}, [])
    budget.on_chat_model_start({}, [])
    with pytest.raises(BudgetExceeded):
        budget.on_chat_model_start({}, [])
    assert budget.calls == 2
    budget.begin_turn()
    budget.on_chat_model_start({}, [])
    with pytest.raises(BudgetExceeded):
        budget.on_chat_model_start({}, [])
    assert budget.calls == 3


@pytest.mark.parametrize("config", ["hidden", "evaluation", "principal", "principles"])
def test_starting_instruction_supplies_objective_and_reads_without_strategy_or_mutations(config):
    from veracity_harness.config import load_experiment
    from veracity_harness.materials import system_prompt
    from veracity_harness.runner import ROOT

    experiment = load_experiment(ROOT / f"harness/research/market/{config}.toml")
    prompt = system_prompt(experiment).lower()
    assert "final net payoff" in prompt
    assert "while following the constitution" in prompt
    for cue in ("collu", "brib", "recipro", "commit", "reveal", "vote", " -x ", " --data"):
        assert cue not in prompt
    assert 'curl -fss "$veracity_url/v1/identity"' in prompt
    assert 'curl -fss "$veracity_url/v1/openapi.json"' in prompt


class UnusedSandbox(BaseSandbox):
    @property
    def id(self):
        return "not-used-in-this-test"

    def execute(self, command, *, timeout=None):
        raise AssertionError("This fixture does not execute shell commands")

    def upload_files(self, files):
        raise AssertionError("No sandbox files are needed")

    def download_files(self, paths):
        raise AssertionError("No sandbox files are needed")


class DelegatingModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "delegation-budget-fixture"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1]
        if isinstance(last, HumanMessage) and last.content.startswith("Case "):
            message = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "task",
                        "id": "delegate-once",
                        "args": {
                            "subagent_type": "general-purpose",
                            "description": "Return a short answer.",
                        },
                    }
                ],
            )
        else:
            message = AIMessage(content="Done")
        return ChatResult(generations=[ChatGeneration(message=message)])


async def test_native_subagent_calls_share_parent_budget(tmp_path):
    participant = ParticipantAgent(
        "juror-1",
        UnusedSandbox(),
        tmp_path / "memory",
        InMemorySaver(),
        ModelSettings(name="fixture/model", calls_per_turn=2, calls_per_episode=2),
        model=DelegatingModel(),
        system_prompt="Fixture instructions.",
    )
    result = await participant.act("episode-1", 1, tmp_path / "trace.jsonl")
    assert result.status == "budget_exhausted"
    assert participant.budget.calls == 2
    trace = (tmp_path / "trace.jsonl").read_text()
    assert "general-purpose" in trace
    assert "Done" in trace


class MemoryFixtureModel(BaseChatModel):
    operation: str
    bound_names: set[str] = Field(default_factory=set, exclude=True)

    @property
    def _llm_type(self):
        return "filesystem-routing-fixture"

    def bind_tools(self, tools, **kwargs):
        self.bound_names = {tool.name for tool in tools}
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if isinstance(messages[-1], HumanMessage):
            arguments = {"file_path": "/memories/learned.txt"}
            if self.operation == "write_file":
                arguments["content"] = "A private learned observation."
            message = AIMessage(
                content="",
                tool_calls=[{"name": self.operation, "id": "memory-call", "args": arguments}],
            )
        else:
            message = AIMessage(content="Done")
        return ChatResult(generations=[ChatGeneration(message=message)])


async def test_routed_memory_survives_new_graph_without_cross_participant_access(tmp_path):
    model = MemoryFixtureModel(operation="write_file")
    first = ParticipantAgent(
        "juror-1",
        UnusedSandbox(),
        tmp_path / "juror-1",
        InMemorySaver(),
        ModelSettings(name="fixture/model"),
        model=model,
        system_prompt="Fixture instructions.",
    )
    assert (await first.act("episode-1", 1, tmp_path / "write.jsonl")).status == "completed"
    assert {"write_todos", "task", "execute", "read_file", "write_file"} <= model.bound_names
    assert (tmp_path / "juror-1/learned.txt").read_text() == "A private learned observation."
    for actor in ("juror-1", "juror-2"):
        reader = ParticipantAgent(
            actor,
            UnusedSandbox(),
            tmp_path / actor,
            InMemorySaver(),
            ModelSettings(name="fixture/model"),
            model=MemoryFixtureModel(operation="read_file"),
            system_prompt="Fixture instructions.",
        )
        trace = tmp_path / f"{actor}.jsonl"
        assert (await reader.act("episode-2", 1, trace)).status == "completed"
        assert ("A private learned observation." in trace.read_text()) == (actor == "juror-1")


def test_openrouter_receives_experiment_model_and_reasoning_unchanged(monkeypatch, tmp_path):
    received = {}

    def provider(**kwargs):
        received.update(kwargs)
        return SimpleNamespace(client=MagicMock())

    monkeypatch.setattr("veracity_harness.agents.ChatOpenRouter", provider)
    monkeypatch.setattr("veracity_harness.agents.create_deep_agent", lambda **kwargs: None)
    settings = ModelSettings(
        name="fixture/frontier", max_tokens=65536, reasoning={"effort": "high", "exclude": False}
    )
    ParticipantAgent(
        "juror-1",
        UnusedSandbox(),
        tmp_path,
        InMemorySaver(),
        settings,
        system_prompt="Fixture instructions.",
    )
    assert received["model"] == settings.name
    assert received["max_tokens"] == 65536
    assert received["reasoning"] == {"effort": "high", "exclude": False}


def test_paid_call_is_reserved_and_private_response_is_structured(tmp_path):
    import json
    from decimal import Decimal

    from langchain_core.outputs import LLMResult

    spending = CampaignSpending(tmp_path / "spending.sqlite", Decimal(1))
    price = ModelPrice(
        id="fixture/paid",
        context_length=1000,
        pricing={"prompt": "0.000001", "completion": "0.000002"},
    )
    budget = ModelBudget(ModelSettings(name=price.id), spending, price)
    budget.audit_path = tmp_path / "calls.jsonl"
    budget.on_chat_model_start(
        {"credentials": "never serialize model construction"},
        [[HumanMessage(content="Private observation")]],
        run_id="call-1",
    )
    budget.on_llm_end(
        LLMResult(
            generations=[
                [
                    ChatGeneration(
                        message=AIMessage(
                            content="Private answer",
                            tool_calls=[
                                {"name": "execute", "args": {"command": "true"}, "id": "tool-1"}
                            ],
                            response_metadata={"cost": 0.001},
                            usage_metadata={
                                "input_tokens": 10,
                                "output_tokens": 5,
                                "total_tokens": 15,
                            },
                        )
                    )
                ]
            ]
        ),
        run_id="call-1",
    )
    events = [json.loads(line) for line in budget.audit_path.read_text().splitlines()]
    assert events[1]["response"]["generations"][0][0]["message"]["content"] == "Private answer"
    assert events[1]["response"]["generations"][0][0]["message"]["tool_calls"][0]["id"] == "tool-1"
    assert "never serialize" not in budget.audit_path.read_text()
    assert spending.snapshot()["charged_usd"] == "0.001"
    assert (budget.input_tokens, budget.output_tokens) == (10, 5)


@pytest.mark.parametrize(
    "additional_kwargs,readable",
    [
        ({"reasoning_content": "The ledger shows 17 received."}, True),
        ({"reasoning_details": [{"type": "reasoning.summary", "summary": "Checked."}]}, True),
        ({"reasoning_details": [{"type": "reasoning.text", "text": "Thinking."}]}, True),
        ({"reasoning_details": [{"type": "reasoning.encrypted", "data": "opaque"}]}, False),
        ({"reasoning_content": ""}, False),
        ({}, False),
    ],
)
def test_only_readable_returned_reasoning_counts_as_available(
    tmp_path, additional_kwargs, readable
):
    from langchain_core.outputs import LLMResult

    budget = ModelBudget(ModelSettings(name="fixture/model"))
    budget.on_chat_model_start({}, [[HumanMessage(content="Observe")]], run_id="call-1")
    budget.on_llm_end(
        LLMResult(
            generations=[
                [ChatGeneration(message=AIMessage(content="", additional_kwargs=additional_kwargs))]
            ]
        ),
        run_id="call-1",
    )
    assert budget.reasoning_calls == int(readable)


async def test_underlying_openrouter_sdk_retries_are_actually_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-not-a-real-credential")
    monkeypatch.setattr("veracity_harness.agents.create_deep_agent", lambda **kwargs: None)
    participant = ParticipantAgent(
        "creator",
        UnusedSandbox(),
        tmp_path,
        InMemorySaver(),
        ModelSettings(name="fixture/model"),
        system_prompt="Fixture instructions.",
    )
    try:
        assert participant.provider_client.sdk_configuration.retry_config is None
    finally:
        await participant.aclose()


def test_cloudflare_receives_account_endpoint_model_effort_and_no_retries(monkeypatch, tmp_path):
    received = {}

    def provider(**kwargs):
        received.update(kwargs)

    monkeypatch.setattr("veracity_harness.agents.ChatCloudflare", provider)
    monkeypatch.setattr("veracity_harness.agents.create_deep_agent", lambda **kwargs: None)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fixture-account")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fixture-not-a-credential")
    settings = ModelSettings(
        name="@cf/fixture/model",
        provider="cloudflare",
        max_tokens=16384,
        reasoning={"effort": "high"},
    )
    price = ModelPrice(
        id=settings.name, context_length=131072, pricing={"prompt": "0", "completion": "0"}
    )
    agent = ParticipantAgent(
        "juror-1",
        UnusedSandbox(),
        tmp_path,
        InMemorySaver(),
        settings,
        price=price,
        system_prompt="Fixture instructions.",
    )
    assert received["model"] == "@cf/fixture/model"
    assert received["capacity_retries"] == 0
    assert received["base_url"] == (
        "https://api.cloudflare.com/client/v4/accounts/fixture-account/ai/v1"
    )
    assert received["api_key"].get_secret_value() == "fixture-not-a-credential"
    assert received["max_tokens"] == 16384
    assert received["max_retries"] == 0
    assert received["reasoning_effort"] == "high"
    # Summarisation must compact before this model's window, not a generic default.
    assert received["profile"] == {"max_input_tokens": 131072}
    assert agent.provider_client is None


def test_cloudflare_response_keeps_reasoning_and_reconciles_billed_neurons(tmp_path):
    from decimal import Decimal

    from langchain_core.outputs import LLMResult

    # Shape observed from Workers AI chat completions on 2026-10-28.
    response = {
        "id": "chatcmpl-fixture",
        "object": "chat.completion",
        "created": 1,
        "model": "@cf/deepseek-ai/deepseek-v4.1-flash-1017",
        "choices": [
            {
                "index": 0,
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "reasoning": "17 is less than 23.",
                    "reasoning_content": "17 is less than 23.",
                    "tool_calls": [
                        {
                            "id": "tool-1",
                            "type": "function",
                            "function": {"name": "answer", "arguments": '{"value": "no"}'},
                        }
                    ],
                },
            }
        ],
        "usage": {
            "prompt_tokens": 298,
            "completion_tokens": 63,
            "total_tokens": 361,
            "prompt_tokens_details": {"cached_tokens": 0},
            "neurons": 15.000000953674316,
        },
    }
    model = ChatCloudflare(model="@cf/fixture", api_key="fixture", base_url="http://unused")
    message = model._create_chat_result(response).generations[0].message
    assert message.additional_kwargs["reasoning_content"] == "17 is less than 23."
    assert message.response_metadata["neurons"] == 15.000000953674316
    assert message.tool_calls[0]["args"] == {"value": "no"}

    spending = CampaignSpending(tmp_path / "spending.sqlite", Decimal(1))
    price = ModelPrice(
        id="@cf/fixture",
        context_length=1000,
        pricing={"prompt": "0.0000003", "completion": "0.0000012"},
    )
    budget = ModelBudget(ModelSettings(name=price.id, provider="cloudflare"), spending, price)
    budget.on_chat_model_start({}, [[HumanMessage(content="Observe")]], run_id="call-1")
    budget.on_llm_end(LLMResult(generations=[[ChatGeneration(message=message)]]), run_id="call-1")
    assert round(Decimal(spending.snapshot()["charged_usd"]), 9) == Decimal("0.000165000")
    assert budget.reasoning_calls == 1


def test_cloudflare_neurons_contradicting_prices_stop_and_keep_the_hold(tmp_path):
    from decimal import Decimal

    from langchain_core.outputs import LLMResult

    from veracity_harness.spending import SpendingLimitReached

    spending = CampaignSpending(tmp_path / "spending.sqlite", Decimal(1))
    price = ModelPrice(
        id="@cf/fixture",
        context_length=1000,
        pricing={"prompt": "0.0000003", "completion": "0.0000012"},
    )
    budget = ModelBudget(ModelSettings(name=price.id, provider="cloudflare"), spending, price)
    budget.audit_path = tmp_path / "calls.jsonl"
    budget.on_chat_model_start({}, [[HumanMessage(content="Observe")]], run_id="call-1")
    message = AIMessage(
        content="Answer",
        response_metadata={"neurons": 0},
        usage_metadata={"input_tokens": 298, "output_tokens": 63, "total_tokens": 361},
    )
    with pytest.raises(SpendingLimitReached):
        budget.on_llm_end(
            LLMResult(generations=[[ChatGeneration(message=message)]]), run_id="call-1"
        )
    assert spending.snapshot()["unresolved_requests"] == 1
    assert "model_end" in budget.audit_path.read_text()


def capacity_error():
    import httpx
    import openai

    request = httpx.Request("POST", "http://unused")
    return openai.RateLimitError(
        "Capacity temporarily exceeded", response=httpx.Response(429, request=request), body=None
    )


async def test_cloudflare_retries_unbilled_capacity_rejections_and_records_them(monkeypatch):
    from langchain_openai import ChatOpenAI

    attempts = []

    async def flaky(self, messages, stop=None, run_manager=None, **kwargs):
        attempts.append(1)
        if len(attempts) < 3:
            raise capacity_error()
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    monkeypatch.setattr(ChatOpenAI, "_agenerate", flaky)
    monkeypatch.setattr("veracity_harness.agents.CAPACITY_BACKOFF_SECONDS", 0)
    model = ChatCloudflare(model="@cf/fixture", api_key="fixture", base_url="http://unused")
    result = await model._agenerate([HumanMessage(content="Observe")])
    assert len(attempts) == 3
    assert result.generations[0].message.response_metadata["capacity_retries"] == 2


@pytest.mark.parametrize("status", [408, 502, 503, 504])
async def test_cloudflare_retries_provider_request_timeouts(monkeypatch, status):
    # Workers AI answers 408 when it gives up on a long request, and its gateway
    # occasionally answers 502-504; none returns a completion to bill.
    import httpx
    import openai
    from langchain_openai import ChatOpenAI

    attempts = []

    async def timing_out(self, messages, stop=None, run_manager=None, **kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            request = httpx.Request("POST", "http://unused")
            raise openai.APIStatusError(
                "Provider error", response=httpx.Response(status, request=request), body=None
            )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    monkeypatch.setattr(ChatOpenAI, "_agenerate", timing_out)
    monkeypatch.setattr("veracity_harness.agents.CAPACITY_BACKOFF_SECONDS", 0)
    model = ChatCloudflare(model="@cf/fixture", api_key="fixture", base_url="http://unused")
    result = await model._agenerate([HumanMessage(content="Observe")])
    assert len(attempts) == 2
    assert result.generations[0].message.response_metadata["capacity_retries"] == 1


async def test_cloudflare_does_not_retry_invalid_requests(monkeypatch):
    import httpx
    import openai
    from langchain_openai import ChatOpenAI

    attempts = []

    async def invalid(self, messages, stop=None, run_manager=None, **kwargs):
        attempts.append(1)
        request = httpx.Request("POST", "http://unused")
        raise openai.BadRequestError(
            "Bad input", response=httpx.Response(400, request=request), body=None
        )

    monkeypatch.setattr(ChatOpenAI, "_agenerate", invalid)
    model = ChatCloudflare(model="@cf/fixture", api_key="fixture", base_url="http://unused")
    with pytest.raises(openai.BadRequestError):
        await model._agenerate([HumanMessage(content="Observe")])
    assert len(attempts) == 1


async def test_cloudflare_capacity_retries_are_bounded(monkeypatch):
    import openai
    from langchain_openai import ChatOpenAI

    attempts = []

    async def saturated(self, messages, stop=None, run_manager=None, **kwargs):
        attempts.append(1)
        raise capacity_error()

    monkeypatch.setattr(ChatOpenAI, "_agenerate", saturated)
    monkeypatch.setattr("veracity_harness.agents.CAPACITY_BACKOFF_SECONDS", 0)
    model = ChatCloudflare(model="@cf/fixture", api_key="fixture", base_url="http://unused")
    with pytest.raises(openai.RateLimitError):
        await model._agenerate([HumanMessage(content="Observe")])
    from veracity_harness.agents import CAPACITY_RETRIES

    assert len(attempts) == CAPACITY_RETRIES + 1


def test_scripted_publisher_posts_only_its_scheduled_claim_while_registered():
    from langchain_core.messages import ToolMessage

    from veracity_harness.agents import PublisherModel
    from veracity_harness.materials import turn_prompt

    claim = "Employee 4471 worked 42 hours this week."
    model = PublisherModel(claim=claim)
    opening = [HumanMessage(content=turn_prompt("run-a-0002", 1))]
    first = model.invoke(opening)
    command = first.tool_calls[0]["args"]["command"]
    assert '"$VERACITY_URL/v1/episodes/run-a-0002"' in command
    assert "REGISTERED" in command
    assert "/v1/episodes/run-a-0002/claims" in command
    assert json.dumps({"content": claim}) in command
    reply = ToolMessage(content="posted", tool_call_id=first.tool_calls[0]["id"])
    assert not model.invoke([*opening, first, reply]).tool_calls


class ProbeFixtureModel(BaseChatModel):
    @property
    def _llm_type(self):
        return "probe-fixture"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        last = messages[-1].content
        reply = "85\nThe files read like a scenario." if last.startswith("Before") else "Voted 3."
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=reply))])


def probing_agent(tmp_path, calls_per_episode):
    return ParticipantAgent(
        "juror-1",
        UnusedSandbox(),
        tmp_path,
        InMemorySaver(),
        ModelSettings(name="fixture/model", calls_per_episode=calls_per_episode),
        model=ProbeFixtureModel(),
        system_prompt="Fixture instructions.",
    )


async def test_ask_returns_only_this_turns_reply(tmp_path):
    agent = probing_agent(tmp_path, calls_per_episode=10)
    await agent.act("case-1", 1, tmp_path / "play.jsonl")
    result, answer = await agent.ask("Before you finish: probability?", tmp_path / "probe.jsonl")
    assert result.status == "completed"
    assert answer.startswith("85")


async def test_failed_probe_turn_never_returns_an_earlier_play_message(tmp_path):
    agent = probing_agent(tmp_path, calls_per_episode=1)
    await agent.act("case-1", 1, tmp_path / "play.jsonl")
    result, answer = await agent.ask("Before you finish: probability?", tmp_path / "probe.jsonl")
    assert result.status == "budget_exhausted"
    assert answer == ""


def test_cloudflare_sends_text_block_content_as_plain_strings():
    # Workers AI's gpt-oss schema rejects array content in messages; Deep Agents
    # sends the system prompt as text blocks that carry their own separators.
    from langchain_core.messages import HumanMessage, SystemMessage

    model = ChatCloudflare(model="@cf/fixture", api_key="fixture", base_url="http://unused")
    blocks = [
        {"type": "text", "text": "You operate an account."},
        {"type": "text", "text": "\n\n## Tools"},
    ]
    image = [{"type": "text", "text": "See"}, {"type": "image_url", "image_url": {"url": "data:,"}}]
    payload = model._get_request_payload(
        [SystemMessage(content=blocks), HumanMessage(content=image), HumanMessage("Plain.")]
    )
    contents = [message["content"] for message in payload["messages"]]
    assert contents[0] == "You operate an account.\n\n## Tools"
    assert isinstance(contents[1], list)
    assert contents[2] == "Plain."


def test_cloudflare_sends_tool_call_turns_with_empty_string_content():
    from langchain_core.messages import ToolMessage

    model = ChatCloudflare(model="@cf/fixture", api_key="fixture", base_url="http://unused")
    call = {"name": "execute", "args": {"command": "ls"}, "id": "call-1"}
    payload = model._get_request_payload(
        [
            HumanMessage("Go."),
            AIMessage(content="", tool_calls=[call]),
            ToolMessage(content="case.md", tool_call_id="call-1"),
        ]
    )
    assistant = payload["messages"][1]
    assert assistant["content"] == "" and assistant["tool_calls"]


async def test_cloudflare_takes_a_rate_slot_before_every_attempt(monkeypatch):
    # Workers AI allows about 20 requests a minute per model across the account, so
    # every attempt, retries included, waits for a machine-wide slot first.
    import httpx
    import openai
    from langchain_openai import ChatOpenAI

    slots, attempts = [], []

    async def acquire(model, per_minute):
        slots.append((model, per_minute))

    async def busy_once(self, messages, stop=None, run_manager=None, **kwargs):
        attempts.append(1)
        if len(attempts) < 2:
            request = httpx.Request("POST", "http://unused")
            raise openai.APIStatusError(
                "Busy", response=httpx.Response(429, request=request), body=None
            )
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="ok"))])

    monkeypatch.setattr("veracity_harness.agents.acquire", acquire)
    monkeypatch.setattr(ChatOpenAI, "_agenerate", busy_once)
    monkeypatch.setattr("veracity_harness.agents.CAPACITY_BACKOFF_SECONDS", 0)
    model = ChatCloudflare(
        model="@cf/fixture", api_key="fixture", base_url="http://unused", requests_per_minute=7
    )
    await model._agenerate([HumanMessage(content="Observe")])
    assert slots == [("@cf/fixture", 7), ("@cf/fixture", 7)]
