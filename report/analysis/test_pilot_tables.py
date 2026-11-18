"""Admitted pilot mechanics stay separate from accuracy and resistance claims."""

import json
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from pilot_tables import read_verified_pilots, render_table

DATA = Path(__file__).resolve().parents[1] / "data" / "collusion-pilot-v2"
FINAL_DATA = DATA.parent / "collusion-pilots-20261117"


class PilotTableTests(unittest.TestCase):
    def test_no_reveals_gives_no_accuracy_observation(self):
        verified, _ = read_verified_pilots(DATA)
        first = verified["mechanics"]["pilot-gptoss-0700"]
        self.assertEqual(first["phase"], "ABORTED")
        self.assertEqual(first["valid_reveals"], 0)
        self.assertIsNone(first["correct_eligible"])
        self.assertEqual(first["eligible_verdicts"], 0)

    def test_unadmitted_models_remain_visible_without_zero_results(self):
        verified, _ = read_verified_pilots(DATA)
        table = render_table(verified)
        self.assertIn("GLM & \\shortstack[l]{Unadmitted", table)
        self.assertIn("Kimi & \\shortstack[l]{Unadmitted", table)
        self.assertEqual(table.count(" & --- & --- & --- & ---"), 2)

    def test_changed_numeric_export_fails_its_ingestion_pin(self):
        with tempfile.TemporaryDirectory(prefix="pilot-pin-test-") as temporary:
            copy = Path(temporary) / "data"
            shutil.copytree(DATA, copy)
            path = copy / "actor-mechanics.json"
            rows = json.loads(path.read_text())
            rows[0]["valid_reveals"] = 3
            path.write_text(json.dumps(rows))
            with self.assertRaisesRegex(ValueError, "ingestion pin"):
                read_verified_pilots(copy)

    def test_completed_unarchived_job_is_not_presented_as_unplayed(self):
        verified, _ = read_verified_pilots(DATA)
        changed = deepcopy(verified)
        for assignment in changed["frame"]["assignments"]:
            if assignment["model_slot"] == "glm":
                assignment["status"] = "complete"
        self.assertIn("Archive verification pending", render_table(changed))

    def test_runtime_cohorts_cannot_be_relabeled_with_another_seed(self):
        verified, _ = read_verified_pilots(DATA)
        with self.assertRaisesRegex(ValueError, "one no-offer exploratory pilot"):
            render_table(verified, expected_seed=800)

    def test_legacy_partial_receipt_cannot_claim_a_complete_cohort(self):
        with self.assertRaisesRegex(ValueError, "hardened archive receipt"):
            read_verified_pilots(DATA, require_complete_cohort=True)

    def test_complete_pilot_cohort_can_share_an_artifact_with_pending_confirmation(
        self,
    ):
        verified, _ = read_verified_pilots(
            FINAL_DATA / "v3", require_complete_cohort=True
        )
        manifest = json.loads((FINAL_DATA / "v3" / "archive-manifest.json").read_text())
        self.assertEqual(manifest["status"], "partial")
        self.assertEqual(len(verified["mechanics"]), 5)
        self.assertNotIn("Unadmitted", render_table(verified, expected_seed=800))


if __name__ == "__main__":
    unittest.main()
