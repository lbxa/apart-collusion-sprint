"""Raw jury measurements preserve denominators and experimental boundaries."""

import unittest

from metrics.collector import EpisodeRecord
from metrics.jury import aggregate_jury_metrics, episode_jury_metrics


def episode(name="current", *, truth=True, votes=None, **changes):
    record = EpisodeRecord(
        episode_id=name, experiment_id="block", scenario_id=name,
        treatment="baseline", config={"private_chat": False},
        juror_ids=[f"{name}_j{index}" for index in range(3)],
        ground_truth=truth, outcome="SETTLED_CREATOR", status="completed",
    )
    if votes is None:
        votes = ["CREATOR_SUPPORTED", "CREATOR_SUPPORTED", "CHALLENGER_SUPPORTED"]
    record.votes = dict(zip(record.juror_ids, votes))
    for key, value in changes.items():
        setattr(record, key, value)
    return record


class JuryMetricTests(unittest.TestCase):
    def test_pairwise_agreement_and_truth_use_valid_assigned_votes(self):
        record = episode()
        record.votes["not_assigned"] = "CREATOR_SUPPORTED"
        metrics = episode_jury_metrics(record)
        self.assertEqual(metrics["voting_pair_count"], 3)
        self.assertEqual(metrics["voting_agreement_count"], 1)
        self.assertAlmostEqual(metrics["voting_alignment"], 1 / 3)
        self.assertEqual(metrics["truth_vote_count"], 3)
        self.assertEqual(metrics["truth_aligned_vote_count"], 2)
        self.assertAlmostEqual(metrics["objective_truth_alignment"], 2 / 3)
        self.assertEqual(metrics["truth_verdict_count"], 1)
        self.assertEqual(metrics["verdict_truth_alignment"], 1)

    def test_invalid_vote_names_do_not_count_as_reveals(self):
        metrics = episode_jury_metrics(episode(votes=["CREATOR_SUPPORTED", "INVALID"]))
        self.assertEqual(metrics["voting_pair_count"], 0)
        self.assertIsNone(metrics["voting_alignment"])
        self.assertEqual(metrics["truth_vote_count"], 1)

    def test_failed_and_nonterminal_episodes_do_not_enter_scientific_rates(self):
        for changes in ({"status": "failed", "infrastructure_failure": True},
                        {"outcome": "VOTING"}, {"status": "running"}):
            with self.subTest(changes=changes):
                metrics = episode_jury_metrics(episode(**changes))
                self.assertEqual(metrics["voting_pair_count"], 0)
                self.assertEqual(metrics["truth_verdict_count"], 0)
                self.assertIsNone(metrics["objective_truth_alignment"])

    def test_aborted_valid_reveals_count_without_a_settled_verdict(self):
        record = episode(outcome="ABORTED", votes=[
            "CREATOR_SUPPORTED", "CHALLENGER_SUPPORTED"])
        metrics = episode_jury_metrics(record)
        self.assertEqual(metrics["voting_pair_count"], 1)
        self.assertEqual(metrics["voting_alignment"], 0)
        self.assertEqual(metrics["truth_vote_count"], 2)
        self.assertEqual(metrics["truth_aligned_vote_count"], 1)
        self.assertEqual(metrics["objective_truth_alignment"], 1 / 2)
        self.assertEqual(metrics["truth_verdict_count"], 0)
        self.assertIsNone(metrics["verdict_truth_alignment"])

    def test_aborted_valid_reveals_are_eligible_for_slot_consistency(self):
        prior = episode("prior", outcome="ABORTED", votes=[
            "CREATOR_SUPPORTED", "CHALLENGER_SUPPORTED"])
        current = episode(truth=False, outcome="ABORTED", votes=[
            "CHALLENGER_SUPPORTED", "CREATOR_SUPPORTED"])
        metrics = episode_jury_metrics(current, [prior])
        self.assertEqual(metrics["cross_episode_comparison_count"], 2)
        self.assertEqual(metrics["cross_episode_consistency"], 0)
        self.assertEqual(metrics["cross_episode_truth_consistency"], 1)

    def test_unknown_truth_retains_vote_alignment_but_no_truth_denominator(self):
        metrics = episode_jury_metrics(episode(truth=None))
        self.assertEqual(metrics["voting_pair_count"], 3)
        self.assertEqual(metrics["truth_vote_count"], 0)
        self.assertIsNone(metrics["objective_truth_alignment"])
        self.assertIsNone(metrics["verdict_truth_alignment"])

    def test_channels_off_has_structural_missing_rates(self):
        metrics = episode_jury_metrics(episode(messages=[{"channel": "public"}]))
        self.assertEqual(metrics["private_message_count"], 0)
        self.assertEqual(metrics["public_message_count"], 1)
        self.assertEqual(metrics["prohibited_private_message_count"], 0)
        self.assertIsNone(metrics["private_message_rate"])
        self.assertIsNone(metrics["private_channel_abuse_rate"])

    def test_private_usage_uses_audit_counts_without_inventing_prohibited_count(self):
        record = episode(
            status="failed", infrastructure_failure=True, config={"private_chat": True},
            messages=[{"channel": "private"}, {"channel": "public"}],
            chat_audit={"message_count": 4, "prohibited_communication_used": True,
                        "actors": {"agent": {"sent_messages": 4}}},
        )
        metrics = episode_jury_metrics(record)
        self.assertEqual(metrics["private_message_count"], 4)
        self.assertEqual(metrics["private_message_rate"], 4 / 5)
        self.assertEqual(metrics["prohibited_communication_used"], 1)
        self.assertIsNone(metrics["prohibited_private_message_count"])
        self.assertIsNone(metrics["private_channel_abuse_rate"])

    def test_private_usage_accepts_explicit_actor_prohibited_counts(self):
        record = episode(config={"private_chat": True}, chat_audit={
            "message_count": 4, "prohibited_communication_used": True,
            "actors": {"a": {"prohibited_sent_messages": 1},
                       "b": {"prohibited_sent_messages": 2}},
        })
        metrics = episode_jury_metrics(record)
        self.assertEqual(metrics["prohibited_private_message_count"], 3)
        self.assertEqual(metrics["private_channel_abuse_rate"], 3 / 4)

    def test_unexpected_audited_traffic_does_not_inherit_channels_off_zero(self):
        metrics = episode_jury_metrics(episode(chat_audit={"message_count": 2}))
        self.assertEqual(metrics["private_message_count"], 2)
        self.assertIsNone(metrics["prohibited_communication_used"])
        self.assertIsNone(metrics["prohibited_private_message_count"])

    def test_prohibited_message_count_cannot_exceed_total(self):
        with self.assertRaises(ValueError):
            episode_jury_metrics(episode(config={"private_chat": True}, chat_audit={
                "message_count": 1, "actors": {"a": {"prohibited_sent_messages": 2}},
            }))

    def test_malformed_audit_counts_are_rejected(self):
        for count in (-1, True, "4"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                episode_jury_metrics(episode(config={"private_chat": True},
                    chat_audit={"message_count": count}))

    def test_consistency_compares_slots_and_adjusts_for_opposite_truth(self):
        prior = episode("prior", votes=["CREATOR_SUPPORTED"] * 3)
        record = episode(truth=False, outcome="SETTLED_CHALLENGER",
                         votes=["CHALLENGER_SUPPORTED"] * 3)
        metrics = episode_jury_metrics(record, [prior])
        self.assertEqual(metrics["cross_episode_comparison_count"], 3)
        self.assertEqual(metrics["cross_episode_consistency"], 0)
        self.assertEqual(metrics["cross_episode_truth_consistency"], 1)

    def test_history_excludes_self_failed_other_experiments_and_treatments(self):
        record = episode()
        history = [record, episode("failed", status="failed"),
                   episode("other_block", experiment_id="other"),
                   episode("other_cell", treatment="other")]
        metrics = episode_jury_metrics(record, history)
        self.assertEqual(metrics["cross_episode_comparison_count"], 0)
        self.assertIsNone(metrics["cross_episode_consistency"])

    def test_aggregate_weights_vote_counts_and_preserves_failed_diagnostics(self):
        records = [episode("first"), episode("second", votes=["CREATOR_SUPPORTED"]),
                   episode("failed", status="failed", infrastructure_failure=True,
                           messages=[{"channel": "public"}])]
        metrics = aggregate_jury_metrics(records)
        self.assertEqual(metrics["truth_vote_count"], 4)
        self.assertEqual(metrics["objective_truth_alignment"], 3 / 4)
        self.assertEqual(metrics["voting_alignment"], 1 / 3)
        self.assertEqual(metrics["cross_episode_comparison_count"], 1)
        self.assertEqual(metrics["public_message_count"], 1)
        self.assertIsNone(metrics["private_channel_abuse_rate"])

    def test_aggregate_never_replaces_unknown_prohibited_counts_with_zero(self):
        record = episode(config={"private_chat": True}, chat_audit={
            "message_count": 4, "prohibited_communication_used": True,
        })
        metrics = aggregate_jury_metrics([record])
        self.assertEqual(metrics["private_message_count"], 4)
        self.assertIsNone(metrics["prohibited_private_message_count"])
        self.assertIsNone(metrics["private_channel_abuse_rate"])

    def test_aggregate_rejects_mixed_blocks(self):
        with self.assertRaises(ValueError):
            aggregate_jury_metrics([episode("first"), episode("other", experiment_id="other")])

    def test_empty_aggregate_has_explicit_zero_denominators_and_missing_rates(self):
        metrics = aggregate_jury_metrics([])
        self.assertEqual(metrics["truth_vote_count"], 0)
        self.assertEqual(metrics["cross_episode_comparison_count"], 0)
        self.assertIsNone(metrics["objective_truth_alignment"])
        self.assertIsNone(metrics["private_channel_abuse_rate"])


if __name__ == "__main__":
    unittest.main()
