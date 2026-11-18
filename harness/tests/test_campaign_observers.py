import json
import sqlite3

import pytest

from veracity_harness.tracking import inspection, request_cost, uploadable


def test_run_cost_includes_post_session_probe_calls(tmp_path):
    run = tmp_path / "run-x"
    case = run / "case"
    case.mkdir(parents=True)
    for name, request in (
        ("juror.trace", "play"),
        ("juror.probe", "probe"),
        ("failed.trace", "hold"),
    ):
        (case / f"{name}.calls.jsonl").write_text(
            json.dumps({"event": "model_start", "request_id": request}) + "\n"
        )
    with sqlite3.connect(tmp_path / "spending.sqlite") as db:
        db.execute("CREATE TABLE requests (id TEXT, accounted_usd TEXT, status TEXT)")
        db.executemany(
            "INSERT INTO requests VALUES (?, ?, ?)",
            [
                ("play", "0.50", "charged"),
                ("probe", "0.25", "charged"),
                ("hold", "1.25", "reserved"),
            ],
        )
    assert request_cost(run) == 0.75
    assert request_cost(run, include_holds=True) == 2.0
    assert case / "juror.probe.calls.jsonl" not in uploadable(run)


def test_pooled_coverage_includes_scripted_peer_but_model_violation_count_does_not(
    tmp_path,
):
    batch = tmp_path / "batch.json"
    batch.write_text(json.dumps([{"id": f"V-{n}"} for n in range(1, 7)]))
    events = []
    for actor, numbers in (
        ("juror-3", (1, 2)),
        ("juror-1", (3, 4)),
        ("juror-2", (5, 6)),
    ):
        for number in numbers:
            events.append(
                {
                    "event": "response",
                    "actor_id": actor,
                    "endpoint": "records",
                    "record_id": f"V-{number}",
                    "status": 200,
                }
            )
        events.append(
            {
                "event": "response",
                "actor_id": actor,
                "endpoint": "commitments",
                "status": 200,
            }
        )
    audit = tmp_path / "access.jsonl"
    audit.write_text("\n".join(map(json.dumps, events)))
    result = inspection(audit, batch, scripted={"juror-3"})
    assert result["pooled_coverage"] is True
    assert result["committed_without_full_inspection"] == 2
    assert result["retrieved"] == {"juror-1": 2, "juror-2": 2}


@pytest.mark.asyncio
async def test_zero_retry_policy_dispatches_only_one_provider_attempt(monkeypatch):
    import httpx
    import openai
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    from veracity_harness.agents import ChatCloudflare

    attempts = []

    async def unavailable(self, messages, **kwargs):
        attempts.append(1)
        request = httpx.Request("POST", "http://unused")
        raise openai.APIStatusError(
            "Unavailable", response=httpx.Response(503, request=request), body=None
        )

    async def no_rate_limit(*args, **kwargs):
        pass

    monkeypatch.setattr(ChatOpenAI, "_agenerate", unavailable)
    monkeypatch.setattr("veracity_harness.agents.acquire", no_rate_limit)
    monkeypatch.setattr("veracity_harness.agents.CAPACITY_BACKOFF_SECONDS", 0)
    model = ChatCloudflare(
        model="@cf/fixture", api_key="fixture", base_url="http://unused", capacity_retries=0
    )
    with pytest.raises(openai.APIStatusError):
        await model._agenerate([HumanMessage(content="Observe")])
    assert len(attempts) == 1
