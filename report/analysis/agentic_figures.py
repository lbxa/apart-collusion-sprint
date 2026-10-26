"""Render admitted agentic case-study payoffs and observed repeated-block outcomes."""

import argparse
import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap


def render(data: dict, output: Path):
    runs = {run["run_id"]: run for run in data["runs"]}
    case = runs["v2-7634412e56ed"]["episodes"][0]
    if case["review"]["classification"] != "harmful_coordination":
        raise ValueError(
            "The payoff illustration requires the admitted clear-case review"
        )
    actors = ["creator", "challenger", "juror-1", "juror-2", "juror-3"]
    values = [int(case["payoffs_wei"][actor]) / 1_000_000 for actor in actors]
    repeated = [
        runs["v2-682d20c83784"],
        runs["v2-18087e768b44"],
        runs["v2-cf7b913fb80b"],
    ]
    if any(
        run["status"] != "complete" or len(run["episodes"]) != 3 for run in repeated
    ):
        raise ValueError(
            "Repeated-block figure requires three complete three-episode blocks"
        )
    encodings = {
        "EXPIRED_UNFUNDED": 0,
        "EXPIRED_UNCHALLENGED": 1,
        "SETTLED_CHALLENGER": 2,
    }
    symbols = {
        "EXPIRED_UNFUNDED": "F",
        "EXPIRED_UNCHALLENGED": "U",
        "SETTLED_CHALLENGER": "C",
    }
    matrix = [
        [encodings[episode["outcome"]] for episode in run["episodes"]]
        for run in repeated
    ]
    plt.style.use(Path(__file__).with_name("baseline.mplstyle"))
    figure, axes = plt.subplots(
        1, 2, figsize=(6.5, 2.8), gridspec_kw={"width_ratios": [1.1, 1.2]}
    )
    figure.subplots_adjust(left=0.15, right=0.98, bottom=0.27, top=0.82, wspace=0.76)
    payoff, outcomes = axes
    colors = ["#D55E00", "#0072B2", "#0072B2", "#0072B2", "#0072B2"]
    bars = payoff.barh(range(5), values, color=colors, height=0.65, zorder=3)
    bars[0].set_hatch("///")
    payoff.axvline(0, color="#444444", linewidth=0.7)
    payoff.set_yticks(
        range(5),
        ["Creator", "Challenger", "Juror 1", "Juror 2", "Juror 3"],
        fontsize=8.5,
    )
    payoff.invert_yaxis()
    payoff.set_xlabel("Net payoff\n(million base units)")
    payoff.set_xlim(-1.35, 0.95)
    payoff.set_title("(a) Clear case, seed 43", loc="left", fontsize=10)
    for index, value in enumerate(values):
        payoff.text(
            value + (0.055 if value >= 0 else -0.055),
            index,
            f"{value:+.1f}",
            ha="left" if value >= 0 else "right",
            va="center",
            fontsize=8.5,
        )
    payoff.spines[["top", "right"]].set_visible(False)
    payoff.grid(axis="y", visible=False)
    outcomes.imshow(
        matrix,
        cmap=ListedColormap(["#E8E8E8", "#DCECF5", "#F6E1D5"]),
        vmin=-0.5,
        vmax=2.5,
        aspect="auto",
    )
    outcomes.set_xticks(range(3), ["Episode 1", "Episode 2", "Episode 3"], fontsize=8.5)
    outcomes.set_yticks(
        range(3),
        [
            "Memory on\nchannels on",
            "Memory on\nchannels off",
            "Context reset\nchannels on",
        ],
        fontsize=8.5,
    )
    outcomes.set_title("(b) Repeated blocks, seed 19", loc="left", fontsize=10)
    outcomes.tick_params(length=0)
    outcomes.grid(False)
    outcomes.spines[:].set_visible(False)
    for row, run in enumerate(repeated):
        for column, episode in enumerate(run["episodes"]):
            loss = int(episode["payoffs_wei"]["creator"]) / 1_000_000
            outcomes.text(
                column,
                row,
                f"{symbols[episode['outcome']]}\n{loss:+.1f}",
                ha="center",
                va="center",
                fontsize=9,
            )
    figure.text(
        0.10,
        0.025,
        "C: challenger settlement   U: unchallenged   F: unfunded; cell values: creator net payoff (million).",
        fontsize=8,
    )
    output.mkdir(parents=True, exist_ok=True)
    figure.savefig(
        output / "agentic-outcomes.pdf",
        metadata={
            "Title": "Agentic case-study payoffs and repeated-block outcomes",
            "Subject": "Observed outcomes; one block per repeated condition, no inferential intervals",
        },
    )
    figure.savefig(output / "agentic-outcomes.png", dpi=300)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    render(json.loads(args.data.read_text()), args.output_dir)


if __name__ == "__main__":
    main()
