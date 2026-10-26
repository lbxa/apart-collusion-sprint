"""Financial values remain exact through records, summaries, and exports."""

from decimal import Decimal, localcontext
import json
from pathlib import Path
import tempfile
import unittest

from game_api.state_file import state_to_settlement
from metrics.collector import EpisodeRecord, ExperimentMetrics, MetricsCollector
from metrics.episode_logger import EpisodeLogger


class ExactMoneyTests(unittest.TestCase):
    def test_participant_profit_preserves_small_difference_between_large_amounts(self):
        deposited = Decimal("900719925474099312345678901234567890.10")
        paid_out = Decimal("900719925474099312345678901234567890.11")
        record = EpisodeRecord("episode", "experiment", "scenario", "treatment", {},
                               status="completed",
                               bonds_deposited={"juror": deposited}, payouts={"juror": paid_out},
                               forfeited={"withholder": Decimal("0.01")})
        metrics = ExperimentMetrics("experiment", "treatment", [record])
        logger = EpisodeLogger("episode", Path("unused"))
        logger.log("COMMIT", "juror", "JUROR", "deposit", "", money_in=deposited)
        logger.log("SETTLE", "juror", "JUROR", "payout", "", money_out=paid_out)
        with localcontext() as context:
            context.prec = 6
            self.assertIn("+$0.01", logger.export_markdown())
            self.assertEqual(metrics.participation_loss, Decimal("0.01"))
        summary = json.loads(json.dumps(metrics.summary()))
        self.assertEqual(summary["participation_loss"], "0.01")
        self.assertFalse(any("coalition" in name for name in summary))

    def test_mixed_legacy_deposits_and_exact_payouts_can_be_logged_and_aggregated(self):
        logger = EpisodeLogger("episode", Path("unused"))
        logger.log("COMMIT", "juror", "JUROR", "deposit", "", money_in=0.1)
        logger.log("SETTLE", "juror", "JUROR", "payout", "", money_out=Decimal("0.11"))
        self.assertIn("+$0.01", logger.export_markdown())
        exported = json.loads(json.dumps(logger.export_json()))
        self.assertEqual(exported["entries"][1]["money_out"], "0.11")

    def test_aggregated_financial_totals_preserve_low_digits_above_decimal_precision(self):
        amount = Decimal("900719925474099312345678901234567890.11")
        records = [EpisodeRecord(str(index), "experiment", "scenario", "treatment", {},
                                 status="completed",
                                 payouts={"juror": amount}, forfeited={"other": amount})
                   for index in range(2)]
        metrics = ExperimentMetrics("experiment", "treatment", records)
        with localcontext() as context:
            context.prec = 6
            expected = Decimal("1801439850948198624691357802469135780.22")
            self.assertEqual(metrics.participation_loss, expected)

    def test_base_units_are_scaled_without_decimal_context_rounding(self):
        from game_api.money import base_units_to_tokens

        units = str(2**256 - 1)
        with localcontext() as context:
            context.prec = 6
            amount = base_units_to_tokens(units)
        self.assertEqual(format(amount, "f"), units[:-2] + "." + units[-2:])
        self.assertEqual(base_units_to_tokens("9007199254740993"), Decimal("90071992547409.93"))

    def test_exact_inputs_and_prompt_parameters_do_not_round_large_amounts(self):
        from game_api.money import integer_units
        from game_api.types import PayoutConfig

        amount = Decimal("90071992547409931234567890123456789.10")
        with localcontext() as context:
            context.prec = 6
            self.assertEqual(integer_units(amount, 100, "bet"), 9007199254740993123456789012345678910)
            payout = PayoutConfig(creator_bet=amount, challenger_bet=amount)
            self.assertIn("90071992547409931234567890123456789.10", payout.describe())
            self.assertIn("Winner share of losing bet: 60.00%", payout.describe())
        for value in (Decimal("0.001"), Decimal("-0.01"), Decimal("NaN"), float("inf")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                integer_units(value, 100, "bet")

    def test_payout_prompt_states_parameters_without_simulating_settlement(self):
        from game_api.types import PayoutConfig

        description = PayoutConfig().describe()
        self.assertIn("Winner share of losing bet: 60.00%", description)
        self.assertIn("Juror pool share of losing bet: 30.00%", description)
        self.assertIn("Protocol share of losing bet: 10.00%", description)
        self.assertIn("deposited with commitment", description)
        self.assertNotIn("Total pot:", description)
        self.assertNotIn("$6.00", description)
        self.assertNotIn("$3.00", description)

    def test_exported_financial_strings_restore_as_exact_decimals(self):
        amount = Decimal("900719925474099312345678901234567890.11")
        record = EpisodeRecord("episode", "experiment", "scenario", "treatment", {},
                               status="completed", outcome="SETTLED_CREATOR",
                               settlement={"outcome": "SETTLED_CREATOR", "winner_id": "creator",
                                           "winner_payout": amount, "juror_payouts": {"juror": Decimal("0.01")},
                                           "engine_evidence": {"winner_payout": "90071992547409931234567890123456789011"}})
        metrics = ExperimentMetrics("experiment", "treatment", [record])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "episodes.jsonl"
            MetricsCollector().export_jsonl(path, metrics)
            exported = json.loads(path.read_text())
        self.assertEqual(exported["settlement"]["winner_payout"], str(amount))
        restored = state_to_settlement(exported)
        self.assertEqual(restored.winner_payout, amount)
        self.assertEqual(restored.juror_payouts, {"juror": Decimal("0.01")})
        self.assertEqual(restored.engine_evidence, record.settlement["engine_evidence"])


if __name__ == "__main__":
    unittest.main()
