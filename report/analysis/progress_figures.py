"""Render frozen collection counts without estimating semantic resistance.

Run with the locked report environment, --data-dir pointing to the portable
verified snapshot, --output-dir for images, and --table-dir for TeX tables.
The original assigned frame and exploratory recovery remain separate cohorts.
"""

import argparse
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from resistance_figures import SLOTS

ARMS = (
    "honest-false",
    "honest-true",
    "paid-false-basic",
    "paid-rejection-basic",
    "paid-false-suppressed",
    "paid-false-principles",
)
ARM_LABELS = (
    "Honest\nfalse",
    "Honest\ntrue",
    "Paid\nfalse",
    "Paid\nreject",
    "Msg.\nsupp.",
    "Strong\nrules",
)
CASE_CATEGORIES = (
    "source_correct_settlement",
    "source_adverse_settlement",
    "aborted",
    "missing_case_evidence",
    "unsettled_other",
    "reference_not_applicable",
    "reference_unknown",
)
COHORTS = ("original_confirmation", "exploratory_recovery")
PRIMARY_ARMS = ("paid-false-basic", "paid-rejection-basic")
MODEL_LABELS = (
    "DeepSeek Pro",
    "GLM 5.3",
    "Kimi K2.6",
    "GPT OSS 120B",
    "Inkling 2 Small",
)
OUTCOME_LABELS = ("Source-correct", "Source-adverse", "Aborted", "Unresolved")
OUTCOME_COLORS = ("#0072B2", "#D55E00", "#CC79A7", "#E5E5E5")
OUTCOME_HATCHES = ("", "///", "...", "xx")


@dataclass(frozen=True)
class ModelProfile:
    """Validated, immutable case-count and session-count display boundary."""

    model_slot: str
    assigned_sessions: int
    complete_sessions: int
    assigned_cases: int
    categories: tuple[int, ...]

    @property
    def display_counts(self) -> tuple[int, int, int, int]:
        return (*self.categories[:3], sum(self.categories[3:]))


def read_profiles(
    data: dict, cohort_name: str, *, primary_paid: bool = False
) -> tuple[ModelProfile, ...]:
    if (
        data.get("format_version") != 1
        or data.get("semantic_label_status") != "not_reviewed"
        or cohort_name not in COHORTS
    ):
        raise ValueError("Expected the unreviewed version-1 collection snapshot")
    roster = data["roster"]
    if tuple(row["model_slot"] for row in roster) != SLOTS:
        raise ValueError(
            "The collection snapshot must retain the fixed five-model roster"
        )
    cohort = data["cohorts"][cohort_name]
    section = cohort["primary_paid"] if primary_paid else cohort
    if primary_paid and tuple(section["arms"]) != PRIMARY_ARMS:
        raise ValueError(
            "The primary display requires exactly the two registered paid arms"
        )
    rows = section["by_model"]
    if len(rows) != len(SLOTS) or {row["model_slot"] for row in rows} != set(SLOTS):
        raise ValueError("Every cohort must retain exactly five model rows")
    by_slot = {row["model_slot"]: row for row in rows}
    profiles = []
    for slot in SLOTS:
        row = by_slot[slot]
        keys = (
            "assigned_sessions",
            "orchestration_complete",
            "assigned_cases",
            *CASE_CATEGORIES,
        )
        if any(type(row[key]) is not int or row[key] < 0 for key in keys):
            raise ValueError("Collection counts must be nonnegative integers")
        counts = tuple(row[key] for key in CASE_CATEGORIES)
        expected_arm = "primary_paid" if primary_paid else "all"
        if row["arm"] != expected_arm or sum(counts) != row["assigned_cases"]:
            raise ValueError("Case categories must partition the assigned model frame")
        if not 0 <= row["orchestration_complete"] <= row["assigned_sessions"]:
            raise ValueError("Completed sessions cannot exceed assigned sessions")
        if row["assigned_cases"] != 2 * row["assigned_sessions"]:
            raise ValueError(
                "The collection frame requires two assigned cases per session"
            )
        if cohort_name == "original_confirmation" and row["assigned_sessions"] != (
            10 if primary_paid else 30
        ):
            raise ValueError(
                "Original confirmation changed its assigned per-model frame"
            )
        profiles.append(
            ModelProfile(
                slot,
                row["assigned_sessions"],
                row["orchestration_complete"],
                row["assigned_cases"],
                counts,
            )
        )
    expected_sessions = 150 if cohort_name == "original_confirmation" else 75
    if primary_paid:
        if cohort_name != "original_confirmation":
            raise ValueError(
                "The primary figure uses only original confirmation assignments"
            )
        expected_sessions = 50
    if sum(row.assigned_sessions for row in profiles) != expected_sessions or (
        not primary_paid
        and (
            cohort["assigned_sessions"] != expected_sessions
            or cohort["assigned_cases"] != 2 * expected_sessions
        )
    ):
        raise ValueError("Cohort assignment totals changed or were pooled")
    return tuple(profiles)


def read_coverage(
    data: dict, profiles: tuple[ModelProfile, ...]
) -> tuple[tuple[int, ...], ...]:
    rows = data["cohorts"]["original_confirmation"]["by_model_arm"]
    indexed = {(row["model_slot"], row["arm"]): row for row in rows}
    expected = {(slot, arm) for slot in SLOTS for arm in ARMS}
    if len(rows) != len(expected) or set(indexed) != expected:
        raise ValueError("Coverage must retain all five models and six original arms")
    matrix = []
    for profile in profiles:
        values = []
        arm_categories = [0] * len(CASE_CATEGORIES)
        for arm in ARMS:
            row = indexed[(profile.model_slot, arm)]
            counts = tuple(row[key] for key in CASE_CATEGORIES)
            if (
                any(type(count) is not int or count < 0 for count in counts)
                or row["assigned_sessions"] != 5
                or row["assigned_cases"] != 10
                or sum(counts) != 10
            ):
                raise ValueError(
                    "Each original model-arm must retain five two-case sessions"
                )
            terminal = sum(counts[:3])
            if row["source_applicable_terminal_cases"] != terminal:
                raise ValueError("Terminal coverage disagrees with the case categories")
            values.append(terminal)
            arm_categories = [
                a + b for a, b in zip(arm_categories, counts, strict=True)
            ]
        if tuple(arm_categories) != profile.categories:
            raise ValueError("Arm coverage categories disagree with the model totals")
        matrix.append(tuple(values))
    return tuple(matrix)


def render_table(profiles: tuple[ModelProfile, ...], labels: tuple[str, ...]) -> str:
    lines = [
        "% Generated by report/analysis/progress_figures.py; do not edit.",
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        (
            "Model & \\shortstack{Complete / assigned\\\\sessions} & "
            "\\shortstack{Assigned\\\\cases} & Correct & Adverse & Aborted & Unresolved \\\\"
        ),
        "\\midrule",
    ]
    for profile, label in zip(profiles, labels, strict=True):
        if any(symbol in label for symbol in "\\&%$#_{}~^"):
            raise ValueError("Model family labels must be safe literal TeX text")
        cells = (
            label,
            f"{profile.complete_sessions} / {profile.assigned_sessions}",
            str(profile.assigned_cases),
            *(str(value) for value in profile.display_counts),
        )
        lines.append(" & ".join(cells) + " \\\\")
    lines.extend(("\\bottomrule", "\\end{tabular}", ""))
    return "\n".join(lines)


def render(data: dict, output: Path, tables: Path, source_sha256: str) -> None:
    original = read_profiles(data, "original_confirmation")
    primary = read_profiles(data, "original_confirmation", primary_paid=True)
    recovery = read_profiles(data, "exploratory_recovery")
    coverage = read_coverage(data, original)
    arm_rows = data["cohorts"]["original_confirmation"]["by_model_arm"]
    for profile in primary:
        selected = [
            row
            for row in arm_rows
            if row["model_slot"] == profile.model_slot and row["arm"] in PRIMARY_ARMS
        ]
        if (
            tuple(sum(row[key] for row in selected) for key in CASE_CATEGORIES)
            != profile.categories
            or sum(row["orchestration_complete"] for row in selected)
            != profile.complete_sessions
        ):
            raise ValueError(
                "Primary paid counts disagree with their registered arm rows"
            )
    labels = MODEL_LABELS
    with plt.rc_context(
        {
            "font.family": "serif",
            "font.serif": ["cmr10"],
            "mathtext.fontset": "cm",
            "axes.formatter.use_mathtext": True,
            "axes.unicode_minus": False,
            "font.size": 9,
            "pdf.fonttype": 42,
            "hatch.linewidth": 0.4,
            "axes.linewidth": 0.6,
            "text.color": "#222222",
            "axes.labelcolor": "#222222",
        }
    ):
        figure, (outcomes, matrix) = plt.subplots(
            1, 2, figsize=(6.5, 3.1), gridspec_kw={"width_ratios": [1.12, 1.0]}
        )
        figure.subplots_adjust(left=0.16, right=0.99, top=0.76, bottom=0.27, wspace=0.2)
        outcomes.set_title("(a) Two primary paid arms", loc="left", fontsize=10, pad=12)
        left = [0] * len(primary)
        for index, (label, color, hatch) in enumerate(
            zip(OUTCOME_LABELS, OUTCOME_COLORS, OUTCOME_HATCHES, strict=True)
        ):
            values = [profile.display_counts[index] for profile in primary]
            outcomes.barh(
                range(len(primary)),
                values,
                left=left,
                height=0.68,
                color=color,
                edgecolor="#555555",
                linewidth=0.35,
                hatch=hatch,
                zorder=3,
            )
            for row, (offset, value) in enumerate(zip(left, values, strict=True)):
                if value >= 2:
                    outcomes.text(
                        offset + value / 2,
                        row,
                        str(value),
                        ha="center",
                        va="center",
                        color="white" if index < 2 else "#222222",
                        fontsize=8.5,
                        bbox={
                            "facecolor": color,
                            "edgecolor": "none",
                            "pad": 0.3,
                        },
                        zorder=4,
                    )
            left = [offset + value for offset, value in zip(left, values, strict=True)]
        outcomes.set_yticks(range(len(primary)), labels, fontsize=8.5)
        outcomes.set_ylim(4.5, -0.5)
        outcomes.set_xlim(0, 20)
        outcomes.set_xticks((0, 5, 10, 15, 20))
        outcomes.tick_params(axis="x", labelsize=8.5)
        outcomes.set_xlabel("Assigned cases (20 per model)", fontsize=8.5, labelpad=8)
        outcomes.tick_params(axis="y", length=0, pad=5)
        outcomes.spines[["top", "right", "left"]].set_visible(False)
        outcomes.grid(axis="x", color="#DDDDDD", linewidth=0.5, zorder=0)
        matrix.imshow(coverage, cmap="Blues", vmin=0, vmax=10, aspect="auto")
        matrix.set_title(
            "(b) Terminal outcomes / assigned", loc="left", fontsize=10, pad=12
        )
        matrix.set_xticks(range(len(ARMS)), ARM_LABELS, fontsize=8)
        matrix.set_yticks([])
        matrix.tick_params(length=0, pad=6)
        matrix.spines[:].set_visible(False)
        for row, values in enumerate(coverage):
            for column, value in enumerate(values):
                matrix.text(
                    column,
                    row,
                    f"{value}/10",
                    ha="center",
                    va="center",
                    fontsize=8.5,
                    color="white" if value >= 6 else "#222222",
                )
        matrix.set_xticks([index - 0.5 for index in range(7)], minor=True)
        matrix.set_yticks([index - 0.5 for index in range(6)], minor=True)
        matrix.grid(which="minor", color="white", linewidth=0.8)
        matrix.tick_params(which="minor", length=0)
        handles = [
            Patch(
                facecolor=color,
                edgecolor="#555555",
                linewidth=0.35,
                hatch=hatch,
                label=label,
            )
            for label, color, hatch in zip(
                OUTCOME_LABELS, OUTCOME_COLORS, OUTCOME_HATCHES, strict=True
            )
        ]
        figure.legend(
            handles=handles,
            loc="upper center",
            bbox_to_anchor=(0.55, 1.0),
            ncol=4,
            frameon=False,
            fontsize=8.5,
            handlelength=1.6,
            columnspacing=1.15,
        )
        figure.text(
            0.02,
            0.075,
            "Original frame: 150 sessions, 300 assigned cases. Exploratory recovery is separate.",
            fontsize=8.5,
        )
        figure.text(
            0.02,
            0.025,
            "Mechanical outcomes only; semantic coordination labels remain unreviewed. No confidence intervals.",
            fontsize=8,
        )
        output.mkdir(parents=True, exist_ok=True)
        figure.savefig(
            output / "collection-outcomes.pdf",
            metadata={
                "Title": "Original primary paid-arm outcomes and six-arm terminal coverage",
                "Subject": f"Frozen numeric input SHA256 {source_sha256}",
                "CreationDate": None,
                "ModDate": None,
            },
        )
        figure.savefig(output / "collection-outcomes.png", dpi=300)
        plt.close(figure)
    tables.mkdir(parents=True, exist_ok=True)
    for name, profiles in (
        ("models", primary),
        ("original", original),
        ("recovery", recovery),
    ):
        (tables / f"collection-{name}.tex").write_text(render_table(profiles, labels))
    provenance = {
        "snapshot_sha256": source_sha256,
        "selected_at_utc": data["selected_at_utc"],
        "cohort_pins": {
            name: {
                key: data["cohorts"][name][key]
                for key in (
                    "artifact",
                    "artifact_digest",
                    "capture_utc",
                    "verified_utc",
                    "manifest_sha256",
                )
            }
            for name in COHORTS
        },
        "model_slots": list(SLOTS),
        "model_labels": list(MODEL_LABELS),
        "figure_cohort": "original_confirmation",
        "bar_arms": list(PRIMARY_ARMS),
        "matrix_arms": list(ARMS),
        "table_cohorts": {
            "models": COHORTS[0],
            "original": COHORTS[0],
            "recovery": COHORTS[1],
        },
        "table_arms": {
            "models": list(PRIMARY_ARMS),
            "original": "all",
            "recovery": "all",
        },
        "case_category_order": list(CASE_CATEGORIES),
        "unresolved_categories": list(CASE_CATEGORIES[3:]),
        "coverage_numerator": "source_correct_settlement + source_adverse_settlement + aborted",
        "semantic_label_status": data["semantic_label_status"],
        "uncertainty": "none: descriptive counts from a frozen assigned frame",
        "width_inches": 6.5,
        "height_inches": 3.1,
        "matplotlib_version": matplotlib.__version__,
        "generator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "output_sha256": {
            path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in (
                output / "collection-outcomes.pdf",
                output / "collection-outcomes.png",
                tables / "collection-models.tex",
                tables / "collection-original.tex",
                tables / "collection-recovery.tex",
            )
        },
    }
    encoded = json.dumps(provenance, indent=2) + "\n"
    (output / "collection-outcomes-provenance.json").write_text(encoded)
    for name in ("models", "original", "recovery"):
        (tables / f"collection-{name}.provenance.json").write_text(encoded)


def main() -> None:
    from collection_snapshot import read_verified_snapshot

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--table-dir", type=Path, required=True)
    args = parser.parse_args()
    data = read_verified_snapshot(args.data_dir)
    raw = (args.data_dir / "snapshot.json").read_bytes()
    if json.loads(raw) != data:
        raise ValueError("The verified snapshot changed before figure generation")
    render(data, args.output_dir, args.table_dir, hashlib.sha256(raw).hexdigest())


if __name__ == "__main__":
    main()
