import asyncio
from types import SimpleNamespace

import pytest

from veracity_harness.agents import TurnResult
from veracity_harness.config import Experiment
from veracity_harness.runner import play_episode


@pytest.mark.asyncio
async def test_challenger_cannot_outrun_its_required_client_filing(monkeypatch, tmp_path):
    published = asyncio.Event()
    state = SimpleNamespace(phase="REGISTERED", evidence=None)
    prefiled = False
    challenger_phases = []

    class Agent:
        budget = SimpleNamespace(calls=0)

        def __init__(self, actor):
            self.actor = actor

        async def act(self, *args, prompt=None):
            if self.actor == "creator" and state.phase == "REGISTERED":
                state.phase = "OPEN"
                published.set()
            elif self.actor == "challenger":
                await published.wait()
                assert prefiled, "Agent acted before the client filing"
                challenger_phases.append(state.phase)
                if state.phase == "COMMIT":
                    state.phase = "SETTLED_CHALLENGER"
            return TurnResult("completed", 0, 0, 0, 0)

    class Engine:
        client = None

        async def get_episode(self, _):
            return state

    async def prefile(agent, client, case_id, phase, case):
        nonlocal prefiled
        assert phase == "OPEN"
        prefiled = True
        state.evidence = case.evidence
        state.phase = "COMMIT"

    monkeypatch.setattr("veracity_harness.runner.file_for_client", prefile)
    engine = Engine()
    engine.client = engine
    experiment = Experiment(
        model={"name": "fixture/model"},
        creator="scripted",
        mandate="challenger",
        opportunities_per_phase=1,
        case={
            "document": "unused.md",
            "reference_claim": "The world is round.",
            "evidence": "Client filing",
        },
    )
    await play_episode(
        engine,
        "case",
        {a: Agent(a) for a in ("creator", "challenger")},
        experiment,
        tmp_path,
        case=experiment.case,
    )
    assert state.evidence == "Client filing"
    assert challenger_phases == ["COMMIT", "SETTLED_CHALLENGER"]
