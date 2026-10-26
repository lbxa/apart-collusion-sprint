"""Simulated side payments remain distinct from contract entitlements."""

import json
import tempfile
from pathlib import Path

from experiments.runner import ExperimentRunner
from experiments.treatments import BribeDef, TreatmentConfig
from game_api.types import Scenario
from tests.core_test_case import CoreTestCase


class BribeLedgerTests(CoreTestCase):
    async def test_recipient_specific_offers_and_payments_are_auditable(self):
        treatment = TreatmentConfig("offers", "Offers", "Distinct offers", jury_size=3,
            num_episodes=1, deliberation_rounds=1, use_scripted_creator=True,
            use_scripted_challenger=True, scripted_juror_indices=[0, 1, 2],
            scripted_juror_type="bribable", bribes=[
                BribeDef("creator", ["juror_0"], 2, "vote CREATOR_SUPPORTED"),
                BribeDef("challenger", ["juror_1"], 5, "vote CREATOR_SUPPORTED"),
            ])
        with tempfile.TemporaryDirectory() as directory:
            metrics = await ExperimentRunner(self.new_game(), directory).run_experiment(
                treatment, [Scenario("s", "Claim", "For", "Against", ground_truth=False)], "bribe-test")
            record = metrics.episodes[0]
            self.assertEqual(len(record.bribes_offered), 2)
            first, second = record.bribes_offered
            self.assertEqual((first["amount"], second["amount"]), (2, 5))
            self.assertEqual(first["recipient_id"], record.juror_ids[0])
            self.assertEqual(second["recipient_id"], record.juror_ids[1])
            self.assertEqual(first["simulated_payout"], 2)
            self.assertEqual(second["simulated_payout"], 5)
            self.assertEqual(record.simulated_utility[record.creator_id], -2)
            self.assertEqual(record.simulated_utility[record.challenger_id], -5)
            self.assertEqual(sum(record.simulated_utility.values()), 0)
            self.assertEqual(record.settlement["winner_payout"], 16)
            exported = json.loads((Path(directory) / "bribe-test/episodes.jsonl").read_text())
            self.assertEqual(exported["bribes_offered"], record.bribes_offered)
            self.assertEqual(exported["simulated_utility"], record.simulated_utility)

    async def test_withheld_reveal_cannot_earn_a_conditional_simulated_payment(self):
        treatment = TreatmentConfig("withhold", "Withhold", "No valid reveal", jury_size=3,
            num_episodes=1, deliberation_rounds=1, use_scripted_creator=True,
            use_scripted_challenger=True, scripted_juror_indices=[0, 1, 2],
            scripted_juror_type="bribable", withhold_reveal_indices=(0,),
            bribes=[BribeDef("creator", ["juror_0"], 2, "vote CREATOR_SUPPORTED")])
        with tempfile.TemporaryDirectory() as directory:
            metrics = await ExperimentRunner(self.new_game(), directory).run_experiment(
                treatment, [Scenario("s", "Claim", "For", "Against", ground_truth=False)])
        record = metrics.episodes[0]
        self.assertTrue(record.bribes_offered[0]["accepted"])
        self.assertEqual(record.bribes_offered[0]["simulated_payout"], 0)
        self.assertEqual(record.simulated_utility, {})
