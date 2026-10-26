"""The heuristic detector scores identical jury behaviour identically with or without auditors."""

import unittest

from metrics.collector import EpisodeRecord, MetricsCollector
from metrics.collusion_detector import SIGNAL_WEIGHTS, analyze_episode, detect_bribe_acceptance, detect_private_channel_abuse

JURORS = [f"juror_{index}" for index in range(5)]


def episode(*, auditors=(), finding=None, extra_messages=()):
    messages = [("juror_0", "juror_1", "private"), ("juror_0", "", "public"), ("juror_1", "", "public"),
                *extra_messages]
    return EpisodeRecord(
        "episode", "experiment", "scenario", "treatment", {}, creator_id="creator", challenger_id="challenger",
        juror_ids=list(JURORS), auditor_ids=list(auditors), ground_truth=False, outcome="SETTLED_CREATOR",
        verdict_correct=False, status="completed", votes={juror: "CREATOR_SUPPORTED" for juror in JURORS},
        bribes_accepted=["juror_0", "juror_1", *auditors],
        messages=[{"sender": s, "recipient": r, "round": 1, "content": "x", "channel": c} for s, r, c in messages],
        auditor_panel=None if finding is None else {"panel_finding": finding, "findings": {}},
    )


def with_auditor(finding):
    return episode(auditors=["auditor_0"], finding=finding, extra_messages=[
        ("auditor_0", "juror_0", "auditor_private"), ("juror_0", "auditor_0", "auditor_private"),
        ("auditor_0", "", "auditor_hearing")])


class DetectorAlignmentTests(unittest.TestCase):
    def test_the_detector_keeps_its_original_signal_set_and_weights(self):
        self.assertEqual(SIGNAL_WEIGHTS, {"verdict_evidence_mismatch": 0.25, "straw_poll_herding": 0.10,
                                          "private_channel_abuse": 0.10, "bribe_acceptance": 0.20,
                                          "cross_episode_consistency": 0.10})

    def test_identical_jury_behaviour_scores_identically_with_or_without_auditors(self):
        without = analyze_episode(episode())
        for finding in ("NOT_VERIFIED", "VERDICT_VERIFIED"):
            with self.subTest(finding=finding):
                audited = analyze_episode(with_auditor(finding))
                self.assertEqual([s.signal_type for s in without.signals], [s.signal_type for s in audited.signals])
                self.assertAlmostEqual(without.overall_score, audited.overall_score)
                self.assertEqual(without.verdict, audited.verdict)

    def test_auditor_acceptances_and_interviews_are_not_jury_behaviour(self):
        self.assertEqual(detect_bribe_acceptance(with_auditor("VERDICT_VERIFIED")).evidence["accepted_by"],
                         ["juror_0", "juror_1"])
        self.assertEqual(detect_private_channel_abuse(episode()).score,
                         detect_private_channel_abuse(with_auditor("NOT_VERIFIED")).score)
        collector = MetricsCollector()
        plain, audited = collector.get_or_create("a", "t"), collector.get_or_create("b", "t")
        collector.add_episode(plain, episode())
        collector.add_episode(audited, with_auditor("NOT_VERIFIED"))
        self.assertEqual(plain.avg_messages_per_episode, audited.avg_messages_per_episode)


if __name__ == "__main__":
    unittest.main()
