"""Generate an original teaching figure from FICTIONAL counts, not project data.

From the repository root:
  python docs/reporting/templates/figure-example.py --output-dir /tmp/report-preview

Requires Matplotlib. The output directory receives a vector PDF and a provenance
JSON record. Use actual admitted data and its analysis method for real reports.
"""

from __future__ import annotations

import argparse
import json
import math
import platform
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def wilson_interval(successes: int, trials: int) -> tuple[float, float]:
    """Two-sided 95% Wilson score interval for this illustrative binomial model."""
    z = 1.959963984540054
    rate = successes / trials
    scale = 1.0 + z * z / trials
    center = (rate + z * z / (2 * trials)) / scale
    half_width = z * math.sqrt(rate * (1 - rate) / trials + z * z / (4 * trials**2)) / scale
    return center - half_width, center + half_width


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    # These counts match the explicitly fictional table and caption in the TeX.
    trials = [40, 40]
    successes = [12, 18]
    failures = [2, 1]
    labels = ["Treatment A", "Treatment B"]
    colors = ["#0072B2", "#D55E00"]
    markers = ["o", "s"]
    width_inches, height_inches = 3.35, 2.35
    style_path = Path(__file__).with_name("figure.mplstyle")

    with plt.style.context(style_path):
        fig, ax = plt.subplots(figsize=(width_inches, height_inches))
        # Explicit margins preserve the exact physical dimensions when saving.
        fig.subplots_adjust(left=0.21, right=0.97, bottom=0.22, top=0.88)
        intervals = []
        for position, (count, total, color, marker) in enumerate(zip(successes, trials, colors, markers)):
            low, high = wilson_interval(count, total)
            rate = count / total
            intervals.append([low, high])
            ax.errorbar(
                position, 100 * rate,
                yerr=[[100 * (rate - low)], [100 * (high - rate)]],
                fmt=marker, color=color, capsize=3, linestyle="none",
            )
            ax.annotate(f"{count}/{total}", (position, 100 * high), xytext=(0, 6),
                        textcoords="offset points", ha="center", fontsize=8)
        ax.set_xticks([0, 1], labels)
        ax.set_xlim(-0.5, 1.5)
        ax.set_ylim(0, 100)
        ax.set_yticks([0, 25, 50, 75, 100])
        ax.set_ylabel("Target-verdict rate (%)")
        ax.set_title("Fictional example", loc="left")
        output = args.output_dir / "figure-example.pdf"
        fig.savefig(output, metadata={"Title": "Fictional teaching example"})
        plt.close(fig)

    record = {
        "status": "fictional teaching example; not project evidence",
        "source_script": str(Path(__file__).resolve()),
        "style_file": str(style_path.resolve()),
        "python_version": platform.python_version(),
        "matplotlib_version": matplotlib.__version__,
        "width_inches": width_inches,
        "height_inches": height_inches,
        "denominator": "all assigned trials; infrastructure failures are unsuccessful",
        "independence_assumption": "independently initialized trials with no shared memory",
        "uncertainty": "95% Wilson score intervals under an illustrative binomial model",
        "trials": trials,
        "target_verdicts": successes,
        "infrastructure_failures": failures,
        "intervals": intervals,
        "output": str(output.resolve()),
    }
    (args.output_dir / "figure-example.json").write_text(json.dumps(record, indent=2) + "\n")
    print(output.resolve())


if __name__ == "__main__":
    main()
