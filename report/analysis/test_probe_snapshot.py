"""The probe snapshot keeps counts and provenance only, and the table matches it."""

import json
from pathlib import Path
import unittest

from probe_snapshot import PROBES, SNAPSHOT, TABLE, render_table, summarise

SETTINGS = {"cell": "M1-C1-T1-R1-S1-E1-V1", "lineup": "deepseek_flash", "cot_monitor_model": "monitor"}


def record(**overrides):
    values = {
        "status": "completed", "infrastructure_failure": False, "experiment_id": "x", "episode_id": "x_ep0000",
        "scenario_id": "fic_001", "ground_truth": False, "outcome": "SETTLED_CHALLENGER", "verdict_correct": True,
        "config": {"models": {}}, "votes": {"juror_0_e": "CHALLENGER_SUPPORTED", "juror_1_e": "CREATOR_SUPPORTED"},
        "bribes_offered": [
            {"offered_by": "creator_e", "recipient_id": "juror_0_e", "amount": 1.4, "accepted": False},
            {"offered_by": "challenger_e", "recipient_id": "juror_0_e", "amount": 1.4, "accepted": True},
            {"offered_by": "challenger_e", "recipient_id": "auditor_0_e", "amount": 2.0, "accepted": False,
             "required_finding": "VERDICT_VERIFIED"},
        ],
        "transfers_rejected": [{"reason": "x"}],
        "jury_metrics": {"private_message_count": 5, "public_message_count": 6, "auditor_verified_paid_jury_count": 1},
        "auditor_panel": {"panel_finding": "VERDICT_VERIFIED", "findings": {"a": {"implicated": ["creator_e"]}}},
        "cot_monitor": {
            "juror_0_e": {"role": "JUROR", "rogue": True, "hidden": False, "behaviours": ["payment", "deception"],
                          "evidence": "SECRET QUOTE"},
            "auditor_0_e": {"role": "AUDITOR", "rogue": False, "hidden": False, "behaviours": [],
                            "evidence": "SECRET QUOTE"},
            "creator_e": {"role": "CREATOR", "error": "APIError"},
        },
        "messages": [{"content": "SECRET MESSAGE"}],
    }
    values.update(overrides)
    return values


class ProbeSnapshotTests(unittest.TestCase):
    def test_counts_separate_juror_and_auditor_offers_and_copy_no_text(self):
        entry = summarise(record(), PROBES[0], SETTINGS)
        self.assertEqual((entry["juror_offers"], entry["juror_offers_accepted"]),
                         ({"creator": 1, "challenger": 1}, {"challenger": 1}))
        self.assertEqual((entry["truth_aligned_votes"], entry["jurors"], entry["offers_dropped"]), (1, 2, 1))
        self.assertEqual(entry["auditor"]["offers"], [{"sender_role": "challenger", "amount": 2.0,
                                                       "required_finding": "VERDICT_VERIFIED", "accepted": False}])
        self.assertEqual(entry["monitor"]["judged"], 3)
        self.assertEqual((entry["monitor"]["monitored"], entry["monitor"]["rogue"], entry["monitor"]["rogue_jurors"]),
                         (2, 1, 1), "failed judgements are excluded from the denominator")
        self.assertNotIn("SECRET", json.dumps(entry))

    def test_only_completed_episodes_are_admitted(self):
        with self.assertRaises(ValueError):
            summarise(record(status="failed"), PROBES[0], SETTINGS)

    def test_the_committed_snapshot_is_content_free_and_the_table_is_current(self):
        snapshot = json.loads(SNAPSHOT.read_text())
        self.assertEqual([probe["id"] for probe in snapshot["probes"]], [probe["id"] for probe in PROBES])
        self.assertTrue(all(not probe["code_dirty"] and len(probe["source_sha256"]) == 64
                            for probe in snapshot["probes"]))
        for key in ("content", "reasoning", "evidence", "assessment", "rationale"):
            self.assertNotIn(f'"{key}"', SNAPSHOT.read_text())
        self.assertEqual(TABLE.read_text(), render_table(snapshot), "regenerate with probe_snapshot.py")


if __name__ == "__main__":
    unittest.main()
