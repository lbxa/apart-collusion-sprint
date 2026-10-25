"""The harness adapter retains exact chain amounts across its public boundary."""

from decimal import Decimal, localcontext
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from game_api.core_engine import CoreEngineAPI
from game_api.core_types import Balances, Deployment, Health, Settlement
from game_api.types import EpisodeConfig, PayoutConfig, Verdict


class CoreExactBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def test_uint256_balances_and_settlement_remain_exact_under_small_decimal_context(self):
        maximum = 2**256 - 1
        winner = maximum - 26
        deployment = Deployment(chain_id=31337, contract_address="0xcontract", code_hash="0xcode",
                                abi_version=1, confirmation_depth=1, finality_policy="confirmed")
        settlement = Settlement(
            episode_id="exact", outcome="SETTLED_CREATOR", winner_id="creator",
            winner_payout=str(winner), juror_payouts={"juror-1": "3"}, protocol_fee="5",
            forfeited_bonds={"juror-2": "7"}, refunds={"challenger": "11"},
            total_deposited=str(maximum), total_credited=str(maximum),
            final_votes={"juror-1": "CREATOR_SUPPORTED"}, deployment=deployment)
        balances = Balances(episode_id="exact", entitlements={"creator": str(maximum)},
                            withdrawal_credits={"creator": "0"})
        api = CoreEngineAPI()
        api.local.deployment = deployment
        api.local.client = SimpleNamespace(
            health=AsyncMock(return_value=Health(status="ok", api_version="v1", deployment=deployment)),
            register_episode=AsyncMock(), wait_operation=AsyncMock(),
            get_settlement=AsyncMock(return_value=settlement), get_balances=AsyncMock(return_value=balances))
        await api.start()
        await api.register_episode(EpisodeConfig("exact", jury_size=3),
                                   "alice", "bob", ["jane", "john", "jules"], "treasury")

        with patch.object(api.local, "finish_voting", AsyncMock()), localcontext() as context:
            context.prec = 6
            actual_balances = await api.get_balances("exact")
            result = await api.settle("exact")

        def token_text(units):
            digits = str(units).zfill(3)
            return digits[:-2] + "." + digits[-2:]

        self.assertIsInstance(actual_balances["alice"], Decimal)
        self.assertEqual(format(actual_balances["alice"], "f"), token_text(maximum))
        self.assertIsInstance(result.winner_payout, Decimal)
        self.assertEqual(format(result.winner_payout, "f"), token_text(winner))
        self.assertEqual(result.juror_payouts, {"jane": Decimal("0.03")})
        self.assertEqual(result.protocol_fee, Decimal("0.05"))
        self.assertEqual(result.forfeited_bonds, {"john": Decimal("0.07")})
        self.assertEqual(result.refunds, {"bob": Decimal("0.11")})
        amounts = [result.winner_payout, result.protocol_fee, *result.juror_payouts.values(),
                   *result.forfeited_bonds.values(), *result.refunds.values()]
        self.assertTrue(all(isinstance(amount, Decimal) for amount in amounts))
        self.assertEqual(result.final_votes, {"jane": Verdict.CREATOR_SUPPORTED})
        self.assertEqual(result.engine_evidence, settlement.model_dump())
        self.assertEqual(result.engine_evidence["total_credited"], str(maximum))

    def test_large_exact_configuration_reaches_wire_parameters_without_rounding(self):
        payout = PayoutConfig(
            creator_bet=Decimal("90071992547409931234567890123456789.10"),
            challenger_bet=Decimal("90071992547409931234567890123456789.10"),
            juror_bond=Decimal("9007199254740993123456789012345678.91"))
        with localcontext() as context:
            context.prec = 6
            parameters = CoreEngineAPI.validate_config(EpisodeConfig("exact", payout, jury_size=3))
        self.assertEqual(parameters["beta_wei"], "9007199254740993123456789012345678910")
        self.assertEqual(parameters["gamma_bps"], 1000)


if __name__ == "__main__":
    unittest.main()
