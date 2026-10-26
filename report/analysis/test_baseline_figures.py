"""The report treats episode spread and unavailable variation explicitly."""

import json
from pathlib import Path
import unittest

from baseline_figures import compute_statistics, sample_summary, validate_snapshot


DATA = Path(__file__).resolve().parents[1] / "data" / "baseline-smoke.json"


class BaselineFigureTests(unittest.TestCase):
    def test_sample_standard_deviation_uses_episode_sample(self):
        result = sample_summary([76.30706545792054, 79.0901371249929])
        self.assertEqual(result["n"], 2)
        self.assertAlmostEqual(result["mean"], 77.69860129145673)
        self.assertAlmostEqual(result["sample_sd"], 1.9679288483150175)

    def test_one_observation_has_no_estimable_sample_sd(self):
        result = sample_summary([1.0])
        self.assertEqual(result["mean"], 1.0)
        self.assertIsNone(result["sample_sd"])
        self.assertEqual(sample_summary([None]),
                         {"n": 0, "values": [], "mean": None, "sample_sd": None})

    def test_zero_observed_spread_is_not_inflated(self):
        self.assertEqual(sample_summary([1.0, 1.0])["sample_sd"], 0.0)

    def test_admitted_snapshot_preserves_sample_units_and_na(self):
        snapshot = json.loads(DATA.read_text())
        validate_snapshot(snapshot)
        result = compute_statistics(snapshot)
        self.assertEqual(result["rates"]["voting_alignment"]["n"], 2)
        self.assertEqual(result["rates"]["voting_alignment"]["values"], [1.0, 1.0])
        self.assertEqual(result["rates"]["voting_alignment"]["sample_sd"], 0.0)
        self.assertEqual(result["cross_episode"]["side_consistency"]["n"], 1)
        self.assertIsNone(result["cross_episode"]["side_consistency"]["sample_sd"])
        self.assertEqual(result["cross_episode"]["side_consistency"]["mean"], 0.0)
        self.assertEqual(result["cross_episode"]["truth_consistency"]["mean"], 1.0)
        self.assertIsNone(result["private_channel_abuse"]["mean"])

    def test_failed_episode_cannot_enter_behavioral_snapshot(self):
        snapshot = json.loads(DATA.read_text())
        snapshot["episodes"][0]["infrastructure_failure"] = True
        with self.assertRaisesRegex(ValueError, "completed, nonfailed"):
            validate_snapshot(snapshot)

    def test_channel_off_private_traffic_is_an_error_not_a_zero(self):
        snapshot = json.loads(DATA.read_text())
        snapshot["episodes"][0]["counts"]["private_messages"] = 1
        with self.assertRaisesRegex(ValueError, "private traffic"):
            validate_snapshot(snapshot)

    def test_saved_counts_must_match_revealed_vote_evidence(self):
        snapshot = json.loads(DATA.read_text())
        snapshot["episodes"][0]["counts"]["truth_aligned_votes"] = 6
        with self.assertRaisesRegex(ValueError, "counts disagree"):
            validate_snapshot(snapshot)

    def test_stale_verdict_accuracy_count_is_rejected_when_outcome_changes(self):
        snapshot = json.loads(DATA.read_text())
        snapshot["episodes"][0]["outcome"] = "SETTLED_CHALLENGER"
        with self.assertRaisesRegex(ValueError, "Verdict counts disagree"):
            validate_snapshot(snapshot)

    def test_consistent_incorrect_verdict_is_admissible_and_changes_accuracy(self):
        snapshot = json.loads(DATA.read_text())
        snapshot["episodes"][0]["outcome"] = "SETTLED_CHALLENGER"
        snapshot["episodes"][0]["counts"]["truth_aligned_verdicts"] = 0
        validate_snapshot(snapshot)
        result = compute_statistics(snapshot)["verdict_accuracy"]
        self.assertEqual(result["values"], [0.0, 1.0])
        self.assertEqual(result["mean"], 0.5)
        self.assertAlmostEqual(result["sample_sd"], 2 ** -0.5)

    def test_settled_known_truth_episode_has_one_verdict_denominator(self):
        snapshot = json.loads(DATA.read_text())
        snapshot["episodes"][0]["counts"]["truth_verdicts"] = 0
        with self.assertRaisesRegex(ValueError, "Verdict counts disagree"):
            validate_snapshot(snapshot)


if __name__ == "__main__":
    unittest.main()
