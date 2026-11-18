"""Plot the five-slot confirmation export without turning unknowns into zeros."""

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

SLOTS = ("deepseek", "glm", "kimi", "gptoss", "inkling")
FAMILIES = ("DeepSeek Pro", "GLM", "Kimi", "GPT OSS", "Inkling")


@dataclass(frozen=True)
class ResistancePoint:
    """Validated plotting boundary for the numeric admission export."""

    assigned: int
    resolved: int
    estimate: float | None
    interval: tuple[float, float] | None
    ci_status: str


def read_points(data: dict) -> tuple[ResistancePoint, ...]:
    if (
        data.get("format_version") != 1
        or data.get("protocol_version") != "collusion-resistance-v1"
        or data.get("primary_phase") != "confirmation"
        or data.get("primary_endpoint") != "resistance_to_executed_harmful_coordination"
        or data.get("primary_arms") != ["paid-false-basic", "paid-rejection-basic"]
    ):
        raise ValueError(
            "Expected the version-1 harmful-coordination confirmation export"
        )
    models = data.get("models")
    if not isinstance(models, list) or len(models) != len(SLOTS):
        raise ValueError("The numeric export must retain all five model slots")
    by_slot = {model["model_slot"]: model for model in models}
    if set(by_slot) != set(SLOTS):
        raise ValueError(
            "The numeric export changed or duplicated a requested model slot"
        )
    points = []
    for slot in SLOTS:
        primary = by_slot[slot]["primary"]
        assigned, resolved = primary["assigned_cases"], primary["resolved_cases"]
        if (
            type(assigned) is not int
            or type(resolved) is not int
            or not 0 <= resolved <= assigned
        ):
            raise ValueError(f"Invalid assigned/resolved denominator for {slot}")
        estimate = primary["resistance_complete_case"]
        interval = primary["resistance_ci95"]
        if interval is not None and (
            not isinstance(interval, list) or len(interval) != 2
        ):
            raise ValueError(f"Invalid confidence-interval shape for {slot}")
        numbers = ([] if estimate is None else [estimate]) + (
            [] if interval is None else interval
        )
        if any(
            type(value) not in (int, float)
            or not math.isfinite(value)
            or not 0 <= value <= 1
            for value in numbers
        ):
            raise ValueError(f"Invalid resistance value for {slot}")
        if estimate is not None and resolved == 0:
            raise ValueError(
                f"An estimate without resolved cases cannot be plotted for {slot}"
            )
        if interval is not None and (interval[0] > interval[1] or estimate is None):
            raise ValueError(f"Invalid confidence interval for {slot}")
        status = primary["ci_status"]
        if (interval is not None) != (status == "ok"):
            raise ValueError(
                f"Confidence-interval status disagrees with its value for {slot}"
            )
        points.append(
            ResistancePoint(
                assigned,
                resolved,
                estimate,
                tuple(interval) if interval else None,
                status,
            )
        )
    return tuple(points)


def render(
    data: dict,
    output: Path,
    source_sha256: str,
    *,
    collection_not_started: bool = False,
) -> None:
    points = read_points(data)
    if collection_not_started and (
        data.get("assignment_status_counts") != {"pending": 5}
        or any(
            point.assigned or point.resolved or point.estimate is not None
            for point in points
        )
        or any(
            row["run_id"] is not None or row["evidence_sha256"] is not None
            for row in data.get("case_observations", [])
        )
    ):
        raise ValueError(
            "Collection-not-started status requires five pending pilots and no confirmation observations"
        )
    provisional = bool(data.get("provisional")) or any(
        "independent_human_review_missing" in model["review_gaps"]
        for model in data["models"]
    )
    with plt.rc_context(
        {
            "font.family": "serif",
            "font.serif": ["cmr10"],
            "mathtext.fontset": "cm",
            "axes.formatter.use_mathtext": True,
            "axes.unicode_minus": False,
            "font.size": 9,
            "pdf.fonttype": 42,
            "axes.linewidth": 0.6,
            "text.color": "#222222",
            "axes.labelcolor": "#222222",
        }
    ):
        figure, axis = plt.subplots(figsize=(6.5, 3.5))
        figure.subplots_adjust(left=0.19, right=0.76, top=0.82, bottom=0.27)
        title = (
            "Collection not started: confirmation"
            if collection_not_started
            else "Resistance to executed harmful coordination"
        )
        axis.set_title(title, loc="left", fontsize=10, pad=24)
        axis.set_yticks(range(len(points)), FAMILIES, fontsize=9)
        axis.set_ylim(len(points) - 0.5, -0.5)
        axis.set_xlim(0, 100)
        axis.tick_params(axis="y", length=0, pad=8)
        axis.spines[["top", "right", "left"]].set_visible(False)
        axis.text(
            1.04, 1.09, "Resolved / assigned", transform=axis.transAxes, fontsize=8.5
        )
        for row, point in enumerate(points):
            axis.text(
                1.04,
                row,
                f"{point.resolved} / {point.assigned}",
                transform=axis.get_yaxis_transform(),
                va="center",
                fontsize=9,
            )
            if point.estimate is None:
                axis.text(
                    0.5,
                    row,
                    "Unavailable",
                    transform=axis.get_yaxis_transform(),
                    ha="center",
                    va="center",
                    color="#555555",
                )
                continue
            if point.interval is not None:
                low, high = (100 * value for value in point.interval)
                axis.hlines(row, low, high, colors="#0072B2", linewidth=1.4, zorder=2)
                axis.vlines(
                    [low, high],
                    row - 0.08,
                    row + 0.08,
                    colors="#0072B2",
                    linewidth=1.0,
                    zorder=2,
                )
            axis.plot(
                100 * point.estimate,
                row,
                marker="D",
                markersize=5,
                color="#222222",
                clip_on=False,
                zorder=3,
            )
            if point.interval is None:
                axis.text(
                    1.04,
                    row + 0.25,
                    f"CI {point.ci_status.replace('_', ' ')}",
                    transform=axis.get_yaxis_transform(),
                    va="center",
                    fontsize=8,
                    color="#555555",
                )
        if any(point.estimate is not None for point in points):
            axis.set_xticks(range(0, 101, 20))
            axis.set_xlabel("Complete-case competent resistance (%)", labelpad=8)
            axis.grid(axis="x", color="#DDDDDD", linewidth=0.5, zorder=0)
        else:
            axis.set_xticks([])
            axis.spines["bottom"].set_visible(False)
            label = (
                "Five exploratory pilot jobs pending; confirmation unassigned"
                if collection_not_started
                else "Awaiting admitted reviewed evidence"
            )
            axis.set_xlabel(label, labelpad=8)
        status = (
            "Provisional labels; independent review remains open."
            if provisional
            else "No estimates are supplied for unresolved or unplayed cells."
        )
        legend = (
            "Status display only. No resistance estimates or confidence intervals."
            if collection_not_started
            else "Diamonds: complete-case estimate. Whiskers: source/session-clustered 95% interval."
        )
        figure.text(0.02, 0.09, legend, fontsize=8)
        figure.text(0.02, 0.045, status + " Unknown values are not zero.", fontsize=8)
        output.mkdir(parents=True, exist_ok=True)
        figure.savefig(
            output / "resistance-primary.pdf",
            metadata={
                "Title": title,
                "Subject": f"Numeric input SHA256 {source_sha256}",
            },
        )
        figure.savefig(output / "resistance-primary.png", dpi=300)
        plt.close(figure)
    (output / "resistance-primary-provenance.json").write_text(
        json.dumps(
            {
                "input_sha256": source_sha256,
                "numeric_input_hashes": data.get("input_sha256", {}),
                "primary_phase": "confirmation",
                "model_slots": list(SLOTS),
                "provisional": provisional,
                "matplotlib_version": matplotlib.__version__,
                "collection_not_started": collection_not_started,
                "width_inches": 6.5,
                "height_inches": 3.5,
            },
            indent=2,
        )
        + "\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--collection-not-started",
        action="store_true",
        help="Validate and label the five-pending-pilot, unassigned-confirmation status",
    )
    args = parser.parse_args()
    raw = args.data.read_bytes()
    render(
        json.loads(raw),
        args.output_dir,
        hashlib.sha256(raw).hexdigest(),
        collection_not_started=args.collection_not_started,
    )


if __name__ == "__main__":
    main()
