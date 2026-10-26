"""Scripted model fixtures validate mechanics, never emergent model behavior."""

import json
import shlex

import pytest
from game_api.generated import RegisterEpisode
from game_api.local_engine import LocalEngine
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from veracity_harness.config import load_experiment
from veracity_harness.runner import ROOT, retain_evidence, run_experiment


class ProtocolFixtureModel(BaseChatModel):
    histories: dict[str, list[str]] = Field(default_factory=dict, exclude=True)

    @property
    def _llm_type(self):
        return "protocol-test-fixture"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        actor = run_manager.metadata["lc_agent_name"]
        self.histories[actor] = [
            message.content for message in messages if isinstance(message, HumanMessage)
        ]
        human = next(message for message in reversed(messages) if isinstance(message, HumanMessage))
        episode = human.content.split("Episode ", 1)[1].split(".", 1)[0]
        command = None
        if isinstance(messages[-1], HumanMessage):
            command = (
                f"curl -fsS $GAME_URL/v1/episodes/{episode} | "
                "python -c 'import json,sys; print(json.load(sys.stdin)[\"phase\"])'"
            )
        elif isinstance(messages[-1], ToolMessage):
            phase = messages[-1].content
            action, body = None, {}
            if "REGISTERED" in phase and actor == "creator":
                action, body = (
                    "claims",
                    {"content": "The warehouse received more units than it dispatched."},
                )
            elif "OPEN" in phase and actor == "challenger":
                action, body = (
                    "challenges",
                    {"evidence": "The ledger records 17 received, 23 dispatched."},
                )
            elif "COMMIT" in phase and actor.startswith("juror-"):
                action, body = (
                    "commitments",
                    {"verdict": "CHALLENGER_SUPPORTED", "assessment": "17 is less than 23."},
                )
            elif "REVEAL" in phase and actor.startswith("juror-"):
                action = "reveals"
            if action:
                command = (
                    f"curl -fsS -X POST $GAME_URL/v1/episodes/{episode}/{action} "
                    "-H 'Content-Type: application/json' "
                    f"-H 'Idempotency-Key: {episode}-{actor}-{action}' "
                    f"--data {shlex.quote(json.dumps(body))}"
                )
        message = (
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "execute", "args": {"command": command}, "id": "fixture-call"}
                ],
            )
            if command
            else AIMessage(content="Opportunity finished.")
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class PassiveModel(BaseChatModel):
    fail: bool = False
    replace_case: str | None = None

    @property
    def _llm_type(self):
        return "nonparticipation-fixture"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        if self.replace_case is not None:
            from pathlib import Path

            Path(self.replace_case).write_text("Changed external fixture after the run started.")
        if self.fail:
            raise RuntimeError("Private provider failure detail")
        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content="I take no action."))]
        )


@pytest.mark.integration
async def test_public_inputs_are_frozen_before_any_agent_runs(tmp_path):
    case = tmp_path / "case.md"
    case.write_text("Original public fixture.")
    experiment = load_experiment(
        ROOT / "harness-v2/examples/discovery.toml", model_name="fixture/protocol"
    ).model_copy(update={"episodes": 2, "opportunities_per_phase": 1})
    experiment = experiment.model_copy(
        update={"case": experiment.case.model_copy(update={"document": case})}
    )
    directory = await run_experiment(
        experiment, tmp_path / "results", model=PassiveModel(replace_case=str(case))
    )
    manifest = json.loads((directory / "run.json").read_text())
    assert manifest["agent_backend"] == "injected_test_model"
    assert case.read_text().startswith("Changed external fixture")
    for episode in manifest["episodes"]:
        for document in (directory / episode["episode_id"] / "documents").glob("*/case.md"):
            assert document.read_text() == "Original public fixture."


@pytest.mark.integration
async def test_active_episode_keeps_evidence_when_no_settlement_exists_yet(tmp_path):
    experiment = load_experiment(
        ROOT / "harness-v2/examples/discovery.toml", model_name="fixture/protocol"
    )
    async with LocalEngine(ROOT) as engine:
        client = engine.client
        operation = await client.register_episode(
            RegisterEpisode(
                episode_id="active-evidence",
                creator_id="creator",
                challenger_id="challenger",
                juror_ids=list(experiment.actor_ids[2:]),
                treasury_id="treasury",
                parameters=experiment.parameters,
            ),
            idempotency_key="register-active",
        )
        await client.wait_operation(operation)
        evidence = await retain_evidence(client, "active-evidence", tmp_path)
    assert evidence["episode"]["phase"] == "REGISTERED"
    assert evidence["settlement"] is None
    assert evidence["settlement_unavailable_http_status"] == 409
    assert "forum_transcript" in evidence
    assert "private_transcripts" in evidence
    assert json.loads((tmp_path / "evidence.json").read_text()) == evidence


@pytest.mark.integration
@pytest.mark.parametrize("fail", [False, True])
async def test_harness_never_submits_actions_to_rescue_nonparticipation(tmp_path, fail, caplog):
    experiment = load_experiment(
        ROOT / "harness-v2/examples/discovery.toml", model_name="fixture/protocol"
    )
    experiment = experiment.model_copy(update={"opportunities_per_phase": 1})
    directory = await run_experiment(experiment, tmp_path, model=PassiveModel(fail=fail))
    manifest = json.loads((directory / "run.json").read_text())
    summary = manifest["episodes"][0]
    evidence = json.loads((directory / summary["episode_id"] / "evidence.json").read_text())
    assert summary["outcome"] == "EXPIRED_UNFUNDED"
    assert evidence["episode"]["total_deposited_wei"] == "0"
    assert summary["agent_execution_failed"] == fail
    assert manifest["status"] == ("failed" if fail else "complete")
    assert "Private provider failure detail" not in caplog.text


@pytest.mark.integration
@pytest.mark.parametrize("memory", [False, True])
async def test_deep_agents_play_actual_protocol_through_isolated_shells(tmp_path, memory):
    experiment = load_experiment(
        ROOT / "harness-v2/examples/discovery.toml", model_name="fixture/protocol"
    )
    experiment = experiment.model_copy(
        update={
            "opportunities_per_phase": 1,
            "episodes": 2,
            "treatment": experiment.treatment.model_copy(update={"memory": memory}),
        }
    )
    model = ProtocolFixtureModel()
    directory = await run_experiment(experiment, tmp_path, model=model)
    manifest = json.loads((directory / "run.json").read_text())
    assert manifest["status"] == "complete"
    summary = manifest["episodes"][0]
    assert summary["outcome"] == "SETTLED_CHALLENGER"
    assert summary["verdict_correct"] is True
    assert summary["payoffs_wei"]["creator"] == "-1000000"
    assert summary["payoffs_wei"]["challenger"] == "600000"
    evidence = json.loads((directory / summary["episode_id"] / "evidence.json").read_text())
    assert len(evidence["settlement"]["final_votes"]) == 3
    assert not summary["agent_execution_failed"]
    assert any(summary["episode_id"] in text for text in model.histories["creator"]) == memory
    second_id = manifest["episodes"][1]["episode_id"]
    second_evidence = json.loads((directory / second_id / "evidence.json").read_text())
    assert (
        second_evidence["balances"]["withdrawal_credits"]
        == evidence["balances"]["withdrawal_credits"]
    )
    for actor in experiment.actor_ids:
        trace = directory / summary["episode_id"] / f"{actor}.trace.jsonl"
        assert trace.stat().st_size > 0
        assert not (directory / summary["episode_id"] / "documents" / actor / ".env").exists()
