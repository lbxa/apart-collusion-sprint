from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from deepagents.backends.sandbox import BaseSandbox
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import Field

from veracity_harness.agents import SYSTEM_PROMPT, BudgetExceeded, ModelBudget, ParticipantAgent
from veracity_harness.config import ModelSettings


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


def test_starting_instruction_supplies_objective_without_strategy_or_api_actions():
    prompt = SYSTEM_PROMPT.lower()
    assert "maximize your final payoff" in prompt
    assert "explore" in prompt
    for cue in ("collu", "brib", "recipro", "commit", "reveal", "vote", "/v1/"):
        assert cue not in prompt


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
        if isinstance(last, HumanMessage) and last.content.startswith("Episode "):
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
    ParticipantAgent("juror-1", UnusedSandbox(), tmp_path, InMemorySaver(), settings)
    assert received["model"] == settings.name
    assert received["max_tokens"] == 65536
    assert received["reasoning"] == {"effort": "high", "exclude": False}
