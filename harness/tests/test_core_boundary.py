"""Fail-closed behavior at the Rust HTTP boundary, without a blockchain."""

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from game_api.core_engine import CoreEngineAPI
from game_api.types import EpisodeConfig, PayoutConfig


class Response:
    def __init__(self, data, status=200):
        self.data = data
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def json(self):
        return self.data

    async def text(self):
        import json
        return json.dumps(self.data)


class Session:
    def __init__(self, data, status=200):
        self.response = Response(data, status)

    def request(self, *args, **kwargs):
        return self.response


def operation(status, *, confirmed=False):
    return {
        "operation_id": "op-1", "episode_id": "ep-1", "actor_id": "creator",
        "kind": "post_claim", "status": status, "error": None,
        "transaction": {
            "transaction_hash": "0x123", "sender": "0x456", "nonce": 0,
            "receipt": {"transaction_hash": "0x123", "success": True,
                "block_number": 1, "block_hash": "0x789", "gas_used": "1",
                "effective_gas_price": "1", "confirmations": int(confirmed),
                "confirmed": confirmed},
        },
    }


class CoreBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_included_operation_is_reconciled_before_success(self):
        api = CoreEngineAPI(core_engine_dir=".")
        responses = iter([Response(operation("included")),
                          Response(operation("confirmed", confirmed=True))])
        api._session = Session({})
        api._session.request = request = unittest.mock.Mock(side_effect=lambda *a, **k: next(responses))
        result = await api._request("POST", "/v1/episodes/ep-1/claims")
        self.assertEqual(result["status"], "confirmed")
        self.assertEqual(request.call_count, 2)
        self.assertIn("/v1/operations/op-1/reconcile", request.call_args.args[1])
        self.assertEqual(request.call_args.kwargs["headers"]["Authorization"], "Bearer dev-operator")
        self.assertEqual(request.call_args.kwargs["headers"]["Idempotency-Key"],
                         api._idem_key("ep-1", "reconcile-op-1"))

    async def test_confirmed_label_without_confirmed_receipt_is_rejected(self):
        api = CoreEngineAPI(core_engine_dir=".")
        api._session = Session(operation("confirmed", confirmed=False))
        with self.assertRaises(RuntimeError):
            await api._request("POST", "/v1/episodes/ep-1/claims")

    async def test_http_200_failed_operation_is_not_a_success(self):
        api = CoreEngineAPI(core_engine_dir=".")
        api._session = Session({
            "operation_id": "op-1", "episode_id": "ep-1", "actor_id": "creator",
            "kind": "post_claim", "status": "failed", "transaction": None,
            "error": "rejected",
        })
        with self.assertRaises(RuntimeError):
            await api._request("POST", "/v1/episodes/ep-1/claims")

    async def test_malformed_success_json_is_not_a_valid_action(self):
        api = CoreEngineAPI(core_engine_dir=".")
        api._session = Session({"status": "confirmed"})
        with self.assertRaises(RuntimeError):
            await api._request("POST", "/v1/episodes/ep-1/claims")

    async def test_low_stakes_and_custom_shares_reach_registration(self):
        api = CoreEngineAPI(core_engine_dir=".")
        api._started = True
        api._request = AsyncMock(return_value={"status": "confirmed"})
        payout = PayoutConfig(creator_bet=1, challenger_bet=1, juror_bond=0.1,
                              winner_pct=0.4, juror_pool_pct=0.5, protocol_pct=0.1)
        await api.register_episode(EpisodeConfig("ep", payout, jury_size=3),
                                   "c", "x", ["a", "b", "d"], "t")
        parameters = api._request.call_args.kwargs["body"]["parameters"]
        self.assertEqual(parameters["beta_wei"], "100")
        self.assertEqual(parameters["gamma_bps"], 1000)
        self.assertEqual(parameters["winner_bps"], 4000)
        self.assertEqual(parameters["juror_bps"], 5000)
        self.assertEqual(parameters["protocol_bps"], 1000)

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

    async def test_startup_cancellation_runs_cleanup(self):
        api = CoreEngineAPI(core_engine_dir=".")
        cleanup = AsyncMock()
        with patch("pathlib.Path.is_file", return_value=True), \
             patch("asyncio.create_subprocess_exec", side_effect=asyncio.CancelledError), \
             patch.object(api, "stop", cleanup):
            with self.assertRaises(asyncio.CancelledError):
                await api.start()
        cleanup.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
