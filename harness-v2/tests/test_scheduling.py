import asyncio
from types import SimpleNamespace

from veracity_harness.agents import TurnResult
from veracity_harness.config import Experiment
from veracity_harness.runner import play_episode


async def test_peers_can_act_in_the_same_round_before_the_clock_advances(tmp_path):
    state = SimpleNamespace(phase="REGISTERED")
    started = set()
    peers_active = asyncio.Event()

    class Agent:
        budget = SimpleNamespace(calls=0)

        def __init__(self, actor):
            self.actor = actor

        async def act(self, *args):
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
