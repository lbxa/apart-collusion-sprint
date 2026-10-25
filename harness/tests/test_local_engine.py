"""Local orchestration uses public chain snapshots, including after reconnecting."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_api.local_engine import LocalEngine


class LocalEngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_finishing_voting_discovers_commits_and_skips_existing_reveals(self):
        local = LocalEngine()
        local.client = SimpleNamespace(
            get_episode=AsyncMock(return_value=SimpleNamespace(
                phase="REVEAL", reveal_deadline=10, jurors=[
                    SimpleNamespace(actor_id="juror-1", commitment="0x1", revealed=True),
                    SimpleNamespace(actor_id="juror-2", commitment="0x2", revealed=False),
                    SimpleNamespace(actor_id="juror-3", commitment=None, revealed=False),
                ])),
            reveal=AsyncMock(return_value="reveal-handle"),
            settle=AsyncMock(return_value="settle-handle"),
            wait_operation=AsyncMock(),
        )
        local.advance_to_deadline = AsyncMock()
        local.latest_timestamp = AsyncMock(return_value=9)
        await local.finish_voting("episode")
        local.client.reveal.assert_awaited_once_with(
            "episode", "juror-2", idempotency_key=local.command_key("episode", "reveal-juror-2"))
        local.advance_to_deadline.assert_awaited_once_with("episode", "reveal_deadline")
        self.assertEqual(local.client.wait_operation.await_count, 2)

    async def test_resuming_after_reveal_deadline_settles_without_doomed_reveal(self):
        local = LocalEngine()
        local.client = SimpleNamespace(
            get_episode=AsyncMock(return_value=SimpleNamespace(
                phase="REVEAL", reveal_deadline=10, jurors=[SimpleNamespace(
                    actor_id="juror-1", commitment="0x1", revealed=False)])),
            reveal=AsyncMock(), settle=AsyncMock(return_value="settle-handle"),
            wait_operation=AsyncMock())
        local.latest_timestamp = AsyncMock(return_value=10)
        local.advance_to_deadline = AsyncMock()
        await local.finish_voting("episode")
        local.client.reveal.assert_not_awaited()
        local.client.settle.assert_awaited_once()

    async def test_withholding_an_absent_commit_fails_before_advancing_time(self):
        local = LocalEngine()
        local.client = SimpleNamespace(get_episode=AsyncMock(return_value=SimpleNamespace(
            phase="COMMIT", jurors=[SimpleNamespace(
                actor_id="juror-1", commitment=None, revealed=False)])))
        local.advance_to_deadline = AsyncMock()
        with self.assertRaises(ValueError):
            await local.finish_voting("episode", withhold_reveals=frozenset({"juror-1"}))
        local.advance_to_deadline.assert_not_awaited()

    async def test_clock_control_requires_the_owned_process(self):
        local = LocalEngine()
        with self.assertRaisesRegex(RuntimeError, "owned local"):
            await local.rpc("evm_mine", [])


if __name__ == "__main__":
    unittest.main()
