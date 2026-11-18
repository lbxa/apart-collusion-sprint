"""Local orchestration uses public chain snapshots, including after reconnecting."""

import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from game_api.core_types import Deployment, Startup
from game_api.local_engine import LocalEngine


def startup_metadata(participants):
    return {
        "api_url": "http://127.0.0.1:8080",
        "rpc_url": "http://127.0.0.1:8545",
        "participant_ids": participants,
        "deployment": {
            "abi_version": 2,
            "chain_id": 31337,
            "code_hash": "0xcode",
            "confirmation_depth": 1,
            "contract_address": "0xcontract",
            "finality_policy": "local",
        },
    }


@pytest.mark.parametrize(
    "participants",
    [[], ["juror-1", "juror-1"], ["operator"], [""], ["bad actor"], [1]],
)
def test_local_startup_rejects_ambiguous_or_operator_rosters(participants):
    with pytest.raises(ValidationError):
        Startup.model_validate(startup_metadata(participants))


class LocalEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_start_uses_the_whole_authoritative_participant_roster(self):
        actors = ["creator", "challenger", "treasury", *[f"juror-{n}" for n in range(1, 16)]]
        metadata = startup_metadata(actors)
        process = SimpleNamespace(
            stdout=SimpleNamespace(readline=AsyncMock(return_value=json.dumps(metadata).encode())),
            stderr=SimpleNamespace(read=AsyncMock(return_value=b"")),
        )
        client = SimpleNamespace(
            start=AsyncMock(),
            health=AsyncMock(
                return_value=SimpleNamespace(
                    deployment=Deployment.model_validate(metadata["deployment"])
                )
            ),
        )
        session = Mock()
        local = LocalEngine(binary=Path(__file__))
        with (
            patch(
                "game_api.local_engine.asyncio.create_subprocess_exec",
                new=AsyncMock(return_value=process),
            ),
            patch("game_api.local_engine.CoreClient", return_value=client) as constructor,
            patch("game_api.local_engine.aiohttp.ClientSession", return_value=session),
            patch.object(local, "stop", new=AsyncMock()),
        ):
            assert await local.start() is client
        assert constructor.call_args.kwargs["participant_tokens"] == {
            actor: f"dev-{actor}" for actor in actors
        }
        assert "dev-operator" not in constructor.call_args.kwargs["participant_tokens"].values()
        await local._stderr_task

    def test_default_engine_directory_is_the_repository_after_package_move(self):
        self.assertEqual(LocalEngine().engine_dir, Path(__file__).resolve().parents[2])

    async def test_finishing_voting_discovers_commits_and_skips_existing_reveals(self):
        local = LocalEngine()
        local.client = SimpleNamespace(
            get_episode=AsyncMock(
                return_value=SimpleNamespace(
                    phase="REVEAL",
                    reveal_deadline=10,
                    jurors=[
                        SimpleNamespace(actor_id="juror-1", commitment="0x1", revealed=True),
                        SimpleNamespace(actor_id="juror-2", commitment="0x2", revealed=False),
                        SimpleNamespace(actor_id="juror-3", commitment=None, revealed=False),
                    ],
                )
            ),
            reveal=AsyncMock(return_value="reveal-handle"),
            settle=AsyncMock(return_value="settle-handle"),
            wait_operation=AsyncMock(),
        )
        local.advance_to_deadline = AsyncMock()
        local.latest_timestamp = AsyncMock(return_value=9)
        await local.finish_voting("episode")
        local.client.reveal.assert_awaited_once_with(
            "episode", "juror-2", idempotency_key=local.command_key("episode", "reveal-juror-2")
        )
        local.advance_to_deadline.assert_awaited_once_with("episode", "reveal_deadline")
        self.assertEqual(local.client.wait_operation.await_count, 2)

    async def test_resuming_after_reveal_deadline_settles_without_doomed_reveal(self):
        local = LocalEngine()
        local.client = SimpleNamespace(
            get_episode=AsyncMock(
                return_value=SimpleNamespace(
                    phase="REVEAL",
                    reveal_deadline=10,
                    jurors=[SimpleNamespace(actor_id="juror-1", commitment="0x1", revealed=False)],
                )
            ),
            reveal=AsyncMock(),
            settle=AsyncMock(return_value="settle-handle"),
            wait_operation=AsyncMock(),
        )
        local.latest_timestamp = AsyncMock(return_value=10)
        local.advance_to_deadline = AsyncMock()
        await local.finish_voting("episode")
        local.client.reveal.assert_not_awaited()
        local.client.settle.assert_awaited_once()

    async def test_withholding_an_absent_commit_fails_before_advancing_time(self):
        local = LocalEngine()
        local.client = SimpleNamespace(
            get_episode=AsyncMock(
                return_value=SimpleNamespace(
                    phase="COMMIT",
                    jurors=[SimpleNamespace(actor_id="juror-1", commitment=None, revealed=False)],
                )
            )
        )
        local.advance_to_deadline = AsyncMock()
        with self.assertRaises(ValueError):
            await local.finish_voting("episode", withhold_reveals=frozenset({"juror-1"}))
        local.advance_to_deadline.assert_not_awaited()

    async def test_clock_control_requires_the_owned_process(self):
        local = LocalEngine()
        with self.assertRaisesRegex(RuntimeError, "owned local"):
            await local.rpc("evm_mine", [])

    async def test_clock_moves_forward_to_a_target_but_never_back(self):
        local = LocalEngine()
        local.rpc = AsyncMock(return_value=None)
        local.latest_timestamp = AsyncMock(return_value=1000)
        await local.advance_to(1600)
        local.rpc.assert_any_await("evm_setNextBlockTimestamp", [1600])
        local.rpc.assert_awaited_with("evm_mine", [])
        local.rpc.reset_mock()
        await local.advance_to(900)
        local.rpc.assert_not_awaited()

    async def test_realtime_clock_waits_for_the_wall_clock_before_mining(self):
        # Participants' shells show the host clock, so the chain must never run ahead.
        local = LocalEngine()
        local.realtime = True
        local.rpc = AsyncMock(return_value=None)
        local.latest_timestamp = AsyncMock(return_value=1000)
        local.client = SimpleNamespace(
            get_episode=AsyncMock(return_value=SimpleNamespace(challenge_deadline=1900))
        )
        with (
            patch("game_api.local_engine.time.time", return_value=1500.0),
            patch("game_api.local_engine.asyncio.sleep", new=AsyncMock()) as sleep,
        ):
            await local.advance_to(1600)
            sleep.assert_awaited_once_with(100.0)
            local.rpc.assert_any_await("evm_setNextBlockTimestamp", [1600])
            sleep.reset_mock()
            await local.advance_to_deadline("episode", "challenge_deadline")
            sleep.assert_awaited_once_with(400.0)
            local.rpc.assert_any_await("evm_setNextBlockTimestamp", [1900])
            sleep.reset_mock()
            # Targets already reached on the wall clock need no wait.
            await local.advance_to(1200)
            sleep.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
