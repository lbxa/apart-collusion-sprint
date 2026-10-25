"""Experiment adapter validation and delegation without a blockchain."""

import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from game_api.core_engine import CoreEngineAPI
from game_api.local_engine import LocalEngine
from game_api.types import EpisodeConfig, PayoutConfig


class CoreBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_low_stakes_and_custom_shares_reach_registration(self):
        api = CoreEngineAPI(core_engine_dir=".")
        api.local.client = SimpleNamespace(
            register_episode=AsyncMock(), wait_operation=AsyncMock())
        payout = PayoutConfig(creator_bet=1, challenger_bet=1, juror_bond=0.1,
                              winner_pct=0.4, juror_pool_pct=0.5, protocol_pct=0.1)
        await api.register_episode(EpisodeConfig("ep", payout, jury_size=3),
                                   "c", "x", ["a", "b", "d"], "t")
        parameters = api.client.register_episode.call_args.args[0].parameters
        self.assertEqual(parameters.beta_wei, "100")
        self.assertEqual(parameters.gamma_bps, 1000)
        self.assertEqual(parameters.winner_bps, 4000)
        self.assertEqual(parameters.juror_bps, 5000)
        self.assertEqual(parameters.protocol_bps, 1000)
        api.client.wait_operation.assert_awaited_once()

    def test_unknown_phase_cannot_become_setup(self):
        with self.assertRaises(RuntimeError):
            CoreEngineAPI._map_phase("UNRECOGNIZED")

    def test_config_rejects_lossy_or_asymmetric_economics_before_startup(self):
        for payout in (
            PayoutConfig(creator_bet=10, challenger_bet=1),
            PayoutConfig(juror_bond=0.001),
            PayoutConfig(winner_pct=1 / 3, juror_pool_pct=1 / 3, protocol_pct=1 / 3),
        ):
            with self.subTest(payout=payout), self.assertRaises(ValueError):
                CoreEngineAPI.validate_config(EpisodeConfig("ep", payout))

    async def test_startup_cancellation_runs_owned_process_cleanup(self):
        local = LocalEngine(core_engine_dir=".")
        cleanup = AsyncMock()
        with patch("pathlib.Path.is_file", return_value=True), \
             patch("asyncio.create_subprocess_exec", side_effect=asyncio.CancelledError), \
             patch.object(local, "stop", cleanup):
            with self.assertRaises(asyncio.CancelledError):
                await local.start()
        cleanup.assert_awaited_once()

    def test_local_metadata_rejects_nonlocal_and_invalid_listeners(self):
        for endpoint in ("https://127.0.0.1:1", "http://example.com:1", "http://127.0.0.1:1/path",
                         "http://127.0.0.1:1/?token=x", "http://user:token@127.0.0.1:1", "http://127.0.0.1"):
            with self.subTest(endpoint=endpoint), self.assertRaises(RuntimeError):
                LocalEngine._validate_listener(endpoint)


if __name__ == "__main__":
    unittest.main()
