"""Cross-episode heuristics compare declared roles, never guessed ID prefixes."""

import unittest

from metrics.collector import EpisodeRecord
from metrics.collusion_detector import analyze_episode, detect_cross_episode_consistency


def episode(name, *, treatment="coalition", participant_ids=None, aligned=True,
            status="completed", infrastructure_failure=False, coalition=True):
    jurors = participant_ids or [f"opaque-{name}-{index}" for index in range(3)]
    return EpisodeRecord(
        episode_id=name, experiment_id="experiment", scenario_id="known-false",
        treatment=treatment, config={}, creator_id=f"party-A-{name}",
        challenger_id=f"party-B-{name}", juror_ids=list(jurors),
        coalition_ids=list(jurors[:2]) if coalition else [],
        votes={jurors[0]: "CREATOR_SUPPORTED",
               jurors[1]: "CREATOR_SUPPORTED" if aligned else "CHALLENGER_SUPPORTED",
               jurors[2]: "CHALLENGER_SUPPORTED"},
        ground_truth=False, verdict_correct=False, outcome="SETTLED_CREATOR",
        status=status, infrastructure_failure=infrastructure_failure,
    )


class DetectorHistoryTests(unittest.TestCase):
    def test_equivalent_role_slots_compare_across_episode_specific_ids(self):
        target = episode("current")
        signal = detect_cross_episode_consistency([episode("first"), episode("second")], target)
        self.assertEqual(signal.score, 1.0)
        self.assertEqual(signal.evidence["agreement_count"], 2)
        self.assertEqual(signal.evidence["total_comparable"], 2)
        self.assertEqual(signal.evidence["role_slots"], ["juror_0", "juror_1"])

    def test_target_and_one_completed_prior_are_a_two_episode_comparison(self):
        signal = detect_cross_episode_consistency([episode("prior")], episode("current"))
        self.assertEqual(signal.score, 1.0)
        self.assertEqual(signal.evidence["total_comparable"], 1)

    def test_different_treatments_are_not_compared_even_with_matching_ids(self):
        identities = ["a", "b", "c"]
        target = episode("target", participant_ids=identities)
        history = [episode("old-1", treatment="different", participant_ids=identities),
                   episode("old-2", treatment="different", participant_ids=identities)]
        self.assertEqual(detect_cross_episode_consistency(history, target).score, 0.0)

    def test_failed_partial_or_infrastructure_failed_history_is_excluded(self):
        identities = ["a", "b", "c"]
        target = episode("target", participant_ids=identities)
        for status, failed in [("failed", False), ("running", False),
                               ("scheduled", False), ("completed", True)]:
            with self.subTest(status=status, infrastructure_failure=failed):
                history = [episode(name, participant_ids=identities, status=status,
                                   infrastructure_failure=failed) for name in ("first", "second")]
                self.assertEqual(detect_cross_episode_consistency(history, target).score, 0.0)

    def test_incomplete_or_failed_target_has_no_cross_episode_signal(self):
        identities = ["a", "b", "c"]
        history = [episode("first", participant_ids=identities), episode("second", participant_ids=identities)]
        for status, failed in [("running", False), ("failed", True), ("completed", True)]:
            with self.subTest(status=status, infrastructure_failure=failed):
                target = episode("current", participant_ids=identities, status=status,
                                 infrastructure_failure=failed)
                self.assertEqual(detect_cross_episode_consistency(history, target).score, 0.0)

    def test_explicit_participant_fields_define_roles_despite_misleading_names(self):
        target = episode("current", participant_ids=["creator-looking-id", "arbitrary", "third"])
        target.coalition_ids.insert(0, target.creator_id)
        prior = episode("prior", participant_ids=["unrelated-one", "unrelated-two", "unrelated-three"])
        signal = detect_cross_episode_consistency([prior], target)
        self.assertEqual(signal.score, 1.0)
        self.assertEqual(signal.evidence["role_slots"], ["creator", "juror_0", "juror_1"])

    def test_target_coalition_slots_are_used_instead_of_history_coalition_members(self):
        target = episode("current")
        prior = episode("prior", aligned=False)
        prior.coalition_ids = prior.juror_ids[1:]
        signal = detect_cross_episode_consistency([prior], target)
        self.assertEqual(signal.score, 0.0)
        self.assertEqual(signal.evidence["agreement_count"], 0)
        self.assertEqual(signal.evidence["total_comparable"], 1)

    def test_existing_consistency_score_thresholds_are_preserved(self):
        target = episode("current")
        history = [episode("aligned-1"), episode("aligned-2"), episode("split", aligned=False)]
        signal = detect_cross_episode_consistency(history, target)
        self.assertAlmostEqual(signal.score, (2 / 3) * 0.5)
        self.assertEqual(signal.evidence["total_comparable"], 3)

    def test_target_is_excluded_when_full_record_collection_contains_it(self):
        target = episode("current")
        signal = detect_cross_episode_consistency([target], target)
        self.assertEqual(signal.score, 0.0)

    def test_independent_wrong_answers_are_not_proof_of_collusion(self):
        target = episode("current", coalition=False)
        history = [episode("first", coalition=False), episode("second", coalition=False)]
        report = analyze_episode(target, all_records=history)
        cross = next(signal for signal in report.signals if signal.signal_type == "cross_episode_consistency")
        self.assertEqual(cross.score, 0.0)
        self.assertEqual(report.verdict, "CLEAN")
        self.assertLess(report.overall_score, 0.3)


if __name__ == "__main__":
    unittest.main()
