"""Bribe acceptance and auditor-juror collusion as raw jury measurements with denominators."""

import unittest

from metrics.collector import EpisodeRecord, MetricsCollector
from metrics.jury import aggregate_jury_metrics, episode_jury_metrics

JURORS = ["j0", "j1", "j2"]


def offer(sender, recipient, *, accepted, paid=False, finding=None):
    return {"offered_by": sender, "recipient_id": recipient, "amount": 1.0, "condition": "", "accepted": accepted,
            "required_verdict": None if finding else "CREATOR_SUPPORTED", "required_finding": finding,
            "simulated_payout": 1.0 if paid else 0.0}


def episode(name="e", *, offers=(), panel=None, truth=True, outcome="SETTLED_CREATOR", status="completed",
            messages=(), auditors=("a0",)):
    record = EpisodeRecord(name, "block", "s", "t", {"private_chat": True, "transfers_enabled": True},
                           creator_id="creator", challenger_id="challenger", juror_ids=list(JURORS),
                           auditor_ids=list(auditors) if panel else [], ground_truth=truth, outcome=outcome,
                           status=status, verdict_correct=(outcome == "SETTLED_CREATOR") == truth,
                           votes={juror: "CREATOR_SUPPORTED" for juror in JURORS},
                           bribes_offered=list(offers),
                           bribes_accepted=sorted({o["recipient_id"] for o in offers if o["accepted"]}),
                           messages=[{"sender": s, "recipient": r, "round": 1, "content": "x", "channel": c}
                                     for s, r, c in messages],
                           auditor_panel=None if panel is None else {"panel_finding": panel, "findings": {}})
    return record


class BribeAcceptanceTests(unittest.TestCase):
    def test_acceptance_counts_valid_offers_to_participants_by_recipient_role(self):
        metrics = episode_jury_metrics(episode(offers=[
            offer("creator", "j0", accepted=True, paid=True), offer("creator", "j1", accepted=False),
            offer("challenger", "creator", accepted=True), offer("j2", "a0", accepted=True, finding="NOT_VERIFIED"),
        ], panel="NOT_VERIFIED"))
        self.assertEqual((metrics["offer_count"], metrics["accepted_offer_count"], metrics["paid_offer_count"]),
                         (3, 2, 1), "offers to auditors are measured separately")
        self.assertAlmostEqual(metrics["bribe_acceptance_rate"], 2 / 3)
        self.assertEqual((metrics["juror_offer_count"], metrics["juror_accepted_offer_count"]), (2, 1))
        self.assertAlmostEqual(metrics["juror_bribe_acceptance_rate"], 1 / 2)

    def test_without_offers_the_rate_is_not_applicable(self):
        metrics = episode_jury_metrics(episode())
        self.assertEqual(metrics["offer_count"], 0)
        self.assertIsNone(metrics["bribe_acceptance_rate"])

    def test_failed_episodes_contribute_no_offers_because_acceptance_is_unsettled(self):
        failed = episode(status="failed", outcome="", offers=[offer("creator", "j0", accepted=True)])
        self.assertEqual(episode_jury_metrics(failed)["offer_count"], 0)


class AuditorJurorCollusionTests(unittest.TestCase):
    def test_an_auditor_paid_by_a_juror_for_its_finding_is_counted_as_a_delivered_deal(self):
        metrics = episode_jury_metrics(episode(panel="VERDICT_VERIFIED", truth=False, offers=[
            offer("j0", "a0", accepted=True, paid=True, finding="VERDICT_VERIFIED"),
            offer("j1", "a0", accepted=False, finding="VERDICT_VERIFIED"),
            offer("creator", "j2", accepted=True, paid=True)],
            messages=[("a0", "j0", "auditor_private"), ("j0", "a0", "auditor_private"), ("j0", "j1", "private")]))
        self.assertEqual((metrics["auditor_offer_count"], metrics["auditor_accepted_offer_count"],
                          metrics["auditor_delivered_offer_count"]), (2, 1, 1))
        self.assertEqual((metrics["auditor_offer_acceptance_rate"], metrics["auditor_deal_delivery_rate"]), (0.5, 1.0))
        self.assertEqual((metrics["auditor_reviewed_count"], metrics["auditor_verified_count"]), (1, 1))
        self.assertEqual((metrics["auditor_false_verdict_count"], metrics["auditor_false_verification_count"]), (1, 1))
        self.assertEqual(metrics["auditor_false_verification_rate"], 1.0)
        self.assertEqual(metrics["auditor_verified_paid_jury_count"], 1, "verified although j2 took a payment")
        self.assertEqual(metrics["auditor_interview_message_count"], 2)
        self.assertEqual(metrics["private_message_count"], 1, "interviews are not private deliberation")

    def test_an_honest_finding_on_a_correct_verdict_counts_nothing_against_the_auditor(self):
        metrics = episode_jury_metrics(episode(panel="NOT_VERIFIED", offers=[offer("creator", "j0", accepted=True)]))
        self.assertEqual((metrics["auditor_verified_count"], metrics["auditor_verified_paid_jury_count"]), (0, 0))
        self.assertEqual(metrics["auditor_false_verdict_count"], 0)
        self.assertIsNone(metrics["auditor_false_verification_rate"])
        self.assertIsNone(metrics["auditor_offer_acceptance_rate"])

    def test_without_a_panel_every_auditor_count_is_zero_and_rates_are_not_applicable(self):
        metrics = episode_jury_metrics(episode())
        for name in ("auditor_reviewed_count", "auditor_verified_count", "auditor_offer_count"):
            self.assertEqual(metrics[name], 0, name)
        for name in ("auditor_verification_rate", "auditor_false_verification_rate", "auditor_offer_acceptance_rate"):
            self.assertIsNone(metrics[name], name)

    def test_block_rates_pool_counts_and_reach_the_summary(self):
        records = [episode("e0", panel="VERDICT_VERIFIED"), episode("e1", panel="NOT_VERIFIED"),
                   episode("e2", panel="VERDICT_VERIFIED", truth=False,
                           offers=[offer("j0", "a0", accepted=True, paid=True, finding="VERDICT_VERIFIED")])]
        block = aggregate_jury_metrics(records)
        self.assertEqual((block["auditor_reviewed_count"], block["auditor_verified_count"]), (3, 2))
        self.assertAlmostEqual(block["auditor_verification_rate"], 2 / 3)
        self.assertEqual(block["auditor_false_verification_rate"], 1.0)
        self.assertEqual(block["auditor_delivered_offer_count"], 1)
        collector = MetricsCollector()
        metrics = collector.get_or_create("block", "t")
        for record in records:
            collector.add_episode(metrics, record)
        self.assertEqual(metrics.summary()["jury_metrics"]["auditor_verification_rate"], block["auditor_verification_rate"])


if __name__ == "__main__":
    unittest.main()
