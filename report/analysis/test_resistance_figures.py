"""Synthetic rendering checks; these fixtures are not experimental evidence."""

import json
import tempfile
import unittest
from pathlib import Path

from resistance_figures import SLOTS, read_points, render


def unplayed_export():
    return {
        "format_version": 1,
        "protocol_version": "collusion-resistance-v1",
        "primary_phase": "confirmation",
        "primary_endpoint": "resistance_to_executed_harmful_coordination",
        "primary_arms": ["paid-false-basic", "paid-rejection-basic"],
        "provisional": False,
        "models": [
            {
                "model_slot": slot,
                "review_gaps": [],
                "primary": {
                    "assigned_cases": 20,
                    "resolved_cases": 0,
                    "resistance_complete_case": None,
                    "resistance_ci95": None,
                    "ci_status": "unavailable",
                },
            }
            for slot in SLOTS
        ],
    }


class ResistanceFigureTests(unittest.TestCase):
    def test_unknown_and_measured_zero_remain_distinct(self):
        data = unplayed_export()
        known = data["models"][0]["primary"]
        known.update(
            resolved_cases=20, resistance_complete_case=0.0, ci_status="degenerate"
        )
        points = read_points(data)
        self.assertEqual(points[0].estimate, 0.0)
        self.assertIsNone(points[0].interval)
        self.assertTrue(all(point.estimate is None for point in points[1:]))

    def test_omitting_an_unavailable_model_is_rejected(self):
        data = unplayed_export()
        data["models"].pop()
        with self.assertRaisesRegex(ValueError, "all five"):
            read_points(data)

    def test_interval_without_resolved_cases_is_rejected(self):
        data = unplayed_export()
        data["models"][0]["primary"].update(
            resistance_complete_case=0.5, resistance_ci95=[0.2, 0.8], ci_status="ok"
        )
        with self.assertRaisesRegex(ValueError, "without resolved"):
            read_points(data)

    def test_unplayed_render_preserves_all_slots_and_input_hash(self):
        with tempfile.TemporaryDirectory(prefix="collusion-plot-test-") as directory:
            output = Path(directory)
            render(unplayed_export(), output, "a" * 64)
            self.assertGreater((output / "resistance-primary.pdf").stat().st_size, 0)
            self.assertGreater((output / "resistance-primary.png").stat().st_size, 0)
            provenance = json.loads(
                (output / "resistance-primary-provenance.json").read_text()
            )
            self.assertEqual(provenance["input_sha256"], "a" * 64)
            self.assertEqual(provenance["model_slots"], list(SLOTS))

    def test_collection_not_started_cannot_hide_a_started_job(self):
        data = unplayed_export()
        data["assignment_status_counts"] = {"pending": 4, "running": 1}
        with (
            tempfile.TemporaryDirectory(prefix="collusion-status-test-") as directory,
            self.assertRaisesRegex(ValueError, "five pending pilots"),
        ):
            render(data, Path(directory), "b" * 64, collection_not_started=True)


if __name__ == "__main__":
    unittest.main()
