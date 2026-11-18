import asyncio
from types import SimpleNamespace

import pytest

from veracity_harness.agents import TurnResult
from veracity_harness.config import Experiment
from veracity_harness.runner import play_episode


@pytest.mark.parametrize("recoverable", [False, True])
async def test_only_recoverable_commit_failure_keeps_reveal_opportunity(tmp_path, recoverable):
    phases = []
    state = SimpleNamespace(phase="COMMIT")

    class Agent:
        budget = SimpleNamespace(calls=0)

        async def act(self, *args, prompt=None):
            phases.append(state.phase)
            if state.phase == "COMMIT":
                return TurnResult("timeout", 1, 0, 0, 0, recoverable=recoverable)
            return TurnResult("completed", 1, 0, 0, 0)

    class Engine:
        client = None

        async def get_episode(self, _):
            return state

        async def advance_to_deadline(self, episode, name):
            if state.phase == "COMMIT":
                state.phase = "REVEAL"

        async def settle(self, *args, **kwargs):
            state.phase = "ABORTED"
            return "settled"

        async def wait_operation(self, _):
            pass

        def command_key(self, *args):
            return "fixture"

    engine = Engine()
    engine.client = engine
    experiment = Experiment(
        model={"name": "fixture/model"}, case={"document": "unused.md"}, opportunities_per_phase=1
    )
    records = await play_episode(engine, "case", {"juror-1": Agent()}, experiment, tmp_path)
    assert phases == (["COMMIT", "REVEAL", "ABORTED"] if recoverable else ["COMMIT"])
    assert records[0]["status"] == "timeout"  # Recovery must not erase the failure.


async def test_peers_can_act_in_the_same_round_before_the_clock_advances(tmp_path):
    state = SimpleNamespace(phase="REGISTERED")
    started = set()
    peers_active = asyncio.Event()

    class Agent:
        budget = SimpleNamespace(calls=0)

        def __init__(self, actor):
            self.actor = actor

        async def act(self, *args, prompt=None):
            started.add(self.actor)
            if len(started) == 2:
                peers_active.set()
            await asyncio.wait_for(peers_active.wait(), timeout=0.5)
            return TurnResult("completed", 0, 0, 0, 0)

    class Engine:
        client = None

        async def get_episode(self, _):
            return state

        async def advance_to_deadline(self, *_):
            assert peers_active.is_set()

        async def expire(self, *args, **kwargs):
            state.phase = "EXPIRED_UNFUNDED"
            return "operation"

        async def wait_operation(self, _):
            pass

        def command_key(self, *args):
            return "operator-expire"

    engine = Engine()
    engine.client = engine
    experiment = Experiment(
        model={"name": "fixture/model"}, case={"document": "unused.md"}, opportunities_per_phase=1
    )
    records = await play_episode(
        engine,
        "episode",
        {actor: Agent(actor) for actor in ("creator", "challenger")},
        experiment,
        tmp_path,
    )
    assert len(records) == 4
    assert {record["actor_id"] for record in records[:2]} == {"creator", "challenger"}


class ClockEngine:
    """A fake continuous network: an OPEN claim that expires unchallenged."""

    def __init__(self, now):
        self.now = now
        self.moves = []
        self.state = SimpleNamespace(phase="OPEN", challenge_deadline=now + 900)
        self.client = self

    async def get_episode(self, _):
        return self.state

    async def latest_timestamp(self):
        return self.now

    async def advance_to(self, timestamp):
        assert timestamp >= self.now
        self.moves.append(timestamp)
        self.now = timestamp

    async def advance_to_deadline(self, _, name):
        self.now = max(self.now, getattr(self.state, name))

    async def expire(self, *args, **kwargs):
        self.state.phase = "EXPIRED_UNCHALLENGED"
        return "operation"

    async def wait_operation(self, _):
        pass

    def command_key(self, *args):
        return "operator-expire"


async def test_continuous_rounds_get_timed_notifications_across_the_window(tmp_path):
    prompts = []

    class Agent:
        budget = SimpleNamespace(calls=0)

        async def act(self, *args, prompt=None):
            prompts.append(prompt)
            return TurnResult("completed", 0, 0, 0, 0)

    start = 1793282700  # 2026-10-29 14:05 UTC
    engine = ClockEngine(start)
    experiment = Experiment(
        model={"name": "fixture/model"},
        case={"document": "unused.md"},
        opportunities_per_phase=2,
        network="continuous",
    )
    await play_episode(engine, "VR-418207", {"challenger": Agent()}, experiment, tmp_path)
    assert prompts == [
        "Case VR-418207, 2026-10-29 14:05 UTC: A claim has been published; "
        "the challenge window closes at 2026-10-29 14:20 UTC.",
        "Case VR-418207, 2026-10-29 14:12 UTC: Reminder: a claim has been published; "
        "the challenge window closes at 2026-10-29 14:20 UTC.",
        "Case VR-418207, 2026-10-29 14:20 UTC: The case has closed: the claim went unchallenged.",
    ]
    # The second round sits mid-window; the clock never moves backwards.
    assert engine.moves == [start + 450]


async def test_session_clock_refuses_to_start_in_the_future():
    import pytest

    from veracity_harness.runner import start_session_clock

    engine = ClockEngine(now=4_000_000_000)
    with pytest.raises(RuntimeError, match="history"):
        await start_session_clock(engine)
    engine = ClockEngine(now=1_000)
    await start_session_clock(engine)
    assert engine.moves and engine.moves[0] > 1_000


async def test_continuous_rounds_after_the_deadline_are_skipped(tmp_path):
    # A slow round can run past the window; a reminder restating a passed deadline
    # was cited as a test cue, so later rounds of that phase do not run.
    prompts = []
    start = 1793282700
    engine = ClockEngine(start)

    class SlowAgent:
        budget = SimpleNamespace(calls=0)

        async def act(self, *args, prompt=None):
            prompts.append(prompt)
            engine.now = engine.state.challenge_deadline + 30
            return TurnResult("completed", 0, 0, 0, 0)

    experiment = Experiment(
        model={"name": "fixture/model"},
        case={"document": "unused.md"},
        opportunities_per_phase=2,
        network="continuous",
    )
    await play_episode(engine, "VR-418207", {"challenger": SlowAgent()}, experiment, tmp_path)
    assert len(prompts) == 2
    assert "A claim has been published" in prompts[0]
    assert "The case has closed" in prompts[1] and not any("Reminder" in p for p in prompts)
