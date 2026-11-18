"""Synthetic count-boundary checks; these fixtures are not research evidence."""

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from progress_figures import (
    ARMS,
    CASE_CATEGORIES,
    PRIMARY_ARMS,
    SLOTS,
    read_coverage,
    read_profiles,
    render,
)


def snapshot_fixture():
    def row(slot, arm, sessions):
        return {
            "model_slot": slot,
            "arm": arm,
            "assigned_sessions": sessions,
            "orchestration_complete": 0,
            "assigned_cases": 2 * sessions,
            **{key: 0 for key in CASE_CATEGORIES},
            "missing_case_evidence": 2 * sessions,
            "source_applicable_terminal_cases": 0,
        }

    original = {
        "assigned_sessions": 150,
        "assigned_cases": 300,
        "by_model": [row(slot, "all", 30) for slot in SLOTS],
        "by_model_arm": [row(slot, arm, 5) for slot in SLOTS for arm in ARMS],
        "primary_paid": {
            "arms": list(PRIMARY_ARMS),
            "by_model": [row(slot, "primary_paid", 10) for slot in SLOTS],
        },
    }
    recovery = {
        "assigned_sessions": 75,
        "assigned_cases": 150,
        "by_model": [
            row(slot, "all", count)
            for slot, count in zip(SLOTS, (19, 16, 16, 11, 13), strict=True)
        ],
    }
    for cohort in (original, recovery):
        cohort.update(
            artifact="synthetic-fixture:v1",
            artifact_digest="0" * 32,
            capture_utc="2026-11-17T00:00:00+00:00",
            verified_utc="2026-11-17T00:00:01+00:00",
            manifest_sha256="0" * 64,
        )
    return {
        "format_version": 1,
        "selected_at_utc": "2026-11-17T00:00:00+00:00",
        "semantic_label_status": "not_reviewed",
        "roster": [{"model_slot": slot, "family": slot.title()} for slot in SLOTS],
        "cohorts": {
            "original_confirmation": original,
            "exploratory_recovery": recovery,
        },
    }


class ProgressFigureTests(unittest.TestCase):
    def test_unplayed_cases_remain_unresolved_on_full_assigned_frame(self):
        data = snapshot_fixture()
        original = read_profiles(data, "original_confirmation")
        primary = read_profiles(data, "original_confirmation", primary_paid=True)
        self.assertEqual([row.display_counts for row in original], [(0, 0, 0, 60)] * 5)
        self.assertEqual([row.display_counts for row in primary], [(0, 0, 0, 20)] * 5)
        self.assertEqual(read_coverage(data, original), ((0,) * 6,) * 5)

    def test_recovery_unequal_denominators_are_preserved(self):
        profiles = read_profiles(snapshot_fixture(), "exploratory_recovery")
        self.assertEqual([row.assigned_cases for row in profiles], [38, 32, 32, 22, 26])

    def test_omitted_model_or_changed_original_frame_is_rejected(self):
        for mutate in (
            lambda rows: rows.pop(),
            lambda rows: rows[0].update(assigned_sessions=29, assigned_cases=58),
        ):
            data = snapshot_fixture()
            mutate(data["cohorts"]["original_confirmation"]["by_model"])
            with self.assertRaises(ValueError):
                read_profiles(data, "original_confirmation")

    def test_terminal_coverage_cannot_use_physical_file_count(self):
        data = snapshot_fixture()
        arm = data["cohorts"]["original_confirmation"]["by_model_arm"][0]
        arm["retained_case_evidence"] = 10
        self.assertEqual(
            read_coverage(data, read_profiles(data, "original_confirmation"))[0][0], 0
        )
        arm["source_applicable_terminal_cases"] = 10
        with self.assertRaisesRegex(ValueError, "Terminal coverage"):
            read_coverage(data, read_profiles(data, "original_confirmation"))

    def test_arm_and_model_category_totals_must_agree(self):
        data = snapshot_fixture()
        arm = data["cohorts"]["original_confirmation"]["by_model_arm"][0]
        arm.update(
            missing_case_evidence=9, aborted=1, source_applicable_terminal_cases=1
        )
        with self.assertRaisesRegex(ValueError, "model totals"):
            read_coverage(data, read_profiles(data, "original_confirmation"))

    def test_primary_panel_cannot_substitute_other_arm_outcomes(self):
        data = snapshot_fixture()
        primary = data["cohorts"]["original_confirmation"]["primary_paid"]["by_model"][
            0
        ]
        primary.update(source_correct_settlement=1, missing_case_evidence=19)
        with (
            tempfile.TemporaryDirectory(prefix="collusion-primary-check-") as directory,
            self.assertRaisesRegex(ValueError, "registered arm rows"),
        ):
            render(data, Path(directory), Path(directory), "a" * 64)

    def test_render_keeps_primary_and_recovery_outputs_separate_and_does_not_mutate(
        self,
    ):
        data = snapshot_fixture()
        before = deepcopy(data)
        with tempfile.TemporaryDirectory(
            prefix="collusion-collection-plot-"
        ) as directory:
            output = Path(directory)
            render(data, output / "images", output / "tables", "a" * 64)
            provenance = json.loads(
                (output / "images/collection-outcomes-provenance.json").read_text()
            )
            self.assertEqual(provenance["snapshot_sha256"], "a" * 64)
            self.assertEqual(provenance["bar_arms"], list(PRIMARY_ARMS))
            self.assertEqual(provenance["figure_cohort"], "original_confirmation")
            self.assertIn(
                "0 / 10 & 20", (output / "tables/collection-models.tex").read_text()
            )
            self.assertIn(
                "0 / 19 & 38", (output / "tables/collection-recovery.tex").read_text()
            )
            self.assertGreater(
                (output / "images/collection-outcomes.pdf").stat().st_size, 0
            )
            self.assertGreater(
                (output / "images/collection-outcomes.png").stat().st_size, 0
            )
        self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
