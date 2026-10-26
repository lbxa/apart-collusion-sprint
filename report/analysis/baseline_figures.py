"""Regenerate the admitted two-episode baseline figures without model calls.

Normal use reads the committed, content-free measurement snapshot:
  python report/analysis/baseline_figures.py

To audit and refresh that genuine computed snapshot, additionally supply the
original episodes JSONL and W&B config YAML through --source and --config.
Only final revealed votes, counters, public deployment identity, and safe run
metadata cross that boundary. No message bodies, prompts, or assessments do.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
from statistics import mean, stdev


REPORT = Path(__file__).resolve().parents[1]
REPO = REPORT.parent
RUN_ID = "m073at4i"
EXPERIMENT_ID = "exp_exp_m0c0t0r0s0e0_78819ce7"
CELL = "M0-C0-T0-R0-S0-E0"
BLUE = "#0072B2"
PALE_BLUE = "#DCECF5"
ORANGE = "#D55E00"
CHARCOAL = "#26343E"
GRAY = "#687680"
LIGHT_GRAY = "#DDE3E7"

RATE_COUNTS = {
    "voting_alignment": ("agreeing_pairs", "voting_pairs"),
    "truth_alignment": ("truth_aligned_votes", "truth_votes"),
    "valid_reveals": ("valid_reveals", "assigned_jurors"),
    "completion": ("completed_episodes", "assigned_episodes"),
}


def sample_summary(values: list[float | None]) -> dict:
    """Episode-level descriptive spread; one observation cannot estimate SD."""
    observed = [value for value in values if value is not None]
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in observed):
        raise ValueError("Plot observations must be finite numbers or null")
    return {
        "n": len(observed),
        "values": observed,
        "mean": mean(observed) if observed else None,
        "sample_sd": stdev(observed) if len(observed) > 1 else None,
    }


def validate_snapshot(snapshot: dict) -> None:
    """Enforce this figure's admitted population and count/rate contract."""
    if snapshot["schema_version"] != 1 or snapshot["provenance"]["run_id"] != RUN_ID:
        raise ValueError("This report admits only baseline smoke run m073at4i")
    provenance = snapshot["provenance"]
    if provenance["cell"] != CELL or provenance["backend"] != "core":
        raise ValueError("Baseline figures require the all-off cell on the core backend")
    if len(snapshot["episodes"]) != 2:
        raise ValueError("The admitted smoke population contains exactly two episodes")
    for record in snapshot["episodes"]:
        if record["status"] != "completed" or record["infrastructure_failure"]:
            raise ValueError("Behavioral figures require completed, nonfailed episodes")
        if record["outcome"] not in ("SETTLED_CREATOR", "SETTLED_CHALLENGER"):
            raise ValueError("The admitted baseline episodes must have settled")
        if type(record["ground_truth"]) is not bool:
            raise ValueError("A truth-alignment figure requires known evaluator truth")
        if type(record["duration_secs"]) not in (int, float) or not math.isfinite(record["duration_secs"]):
            raise ValueError("Episode duration must be finite")
        if record["duration_secs"] < 0:
            raise ValueError("Episode duration must be nonnegative")
        if len(record["revealed_votes"]) != 7 or any(
            vote not in ("CREATOR_SUPPORTED", "CHALLENGER_SUPPORTED")
            for vote in record["revealed_votes"]
        ):
            raise ValueError("The admitted baseline has seven valid revealed votes per episode")
        counts = record["counts"]
        if any(type(value) is not int or value < 0 for value in counts.values()):
            raise ValueError("Measurement counts must be nonnegative integers")
        if counts["private_messages"] or counts["prohibited_private_messages"]:
            raise ValueError("Channel-off baseline cannot contain delivered private traffic")
        if counts["assigned_jurors"] != 7 or counts["valid_reveals"] != len(record["revealed_votes"]):
            raise ValueError("Reveal counts disagree with the assigned jury")
        votes = record["revealed_votes"]
        expected_vote = "CREATOR_SUPPORTED" if record["ground_truth"] else "CHALLENGER_SUPPORTED"
        if (counts["truth_aligned_votes"] != sum(vote == expected_vote for vote in votes)
                or counts["truth_votes"] != len(votes)
                or counts["voting_pairs"] != len(votes) * (len(votes) - 1) // 2
                or counts["agreeing_pairs"] != sum(left == right
                    for index, left in enumerate(votes) for right in votes[index + 1:])):
            raise ValueError("Saved jury counts disagree with revealed vote evidence")
        expected_outcome = "SETTLED_CREATOR" if record["ground_truth"] else "SETTLED_CHALLENGER"
        if (counts["truth_verdicts"] != 1
                or counts["truth_aligned_verdicts"] != int(record["outcome"] == expected_outcome)):
            raise ValueError("Verdict counts disagree with settled outcome and evaluator truth")
        for numerator, denominator in RATE_COUNTS.values():
            if counts[numerator] > counts[denominator]:
                raise ValueError("Rate numerator exceeds its denominator")
        if [poll["round"] for poll in record["straw_polls"]] != [1, 2, 3]:
            raise ValueError("The admitted run has three ordered deliberation rounds")
        for poll in record["straw_polls"]:
            if any(type(poll[name]) is not int or poll[name] < 0
                   for name in ("creator_votes", "challenger_votes")):
                raise ValueError("Straw-poll counts must be nonnegative integers")
            if poll["creator_votes"] + poll["challenger_votes"] != 7:
                raise ValueError("The admitted polls contain seven declared votes")


def compute_statistics(snapshot: dict) -> dict:
    """Use episodes, not jurors or juror pairs, as the descriptive SD unit."""
    validate_snapshot(snapshot)
    records = snapshot["episodes"]
    rates = {}
    for name, (numerator, denominator) in RATE_COUNTS.items():
        values = [record["counts"][numerator] / record["counts"][denominator]
                  if record["counts"][denominator] else None for record in records]
        rates[name] = sample_summary(values)
    polls = []
    for index in range(3):
        values = []
        for record in records:
            poll = record["straw_polls"][index]
            correct = poll["creator_votes"] if record["ground_truth"] else poll["challenger_votes"]
            values.append(correct / (poll["creator_votes"] + poll["challenger_votes"]))
        polls.append({"round": index + 1, **sample_summary(values)})
    cross_episode = {}
    for name, numerator, denominator in (
        ("side_consistency", "same_side_comparisons", "slot_comparisons"),
        ("truth_consistency", "same_correctness_comparisons", "truth_slot_comparisons"),
    ):
        cross_episode[name] = sample_summary([
            record["counts"][numerator] / record["counts"][denominator]
            if record["counts"][denominator] else None for record in records
        ])
    return {
        "observation_unit": "episode; cross-episode measures have one eligible episode pair",
        "uncertainty": "descriptive sample SD with ddof=1; not SE or a confidence interval",
        "rates": rates,
        "verdict_accuracy": sample_summary([
            record["counts"]["truth_aligned_verdicts"] / record["counts"]["truth_verdicts"]
            for record in records
        ]),
        "straw_polls": polls,
        "duration_secs": sample_summary([record["duration_secs"] for record in records]),
        "cross_episode": cross_episode,
        "private_channel_abuse": sample_summary([None for _ in records]),
    }


def extract_snapshot(source: Path, config_path: Path) -> dict:
    """Allowlist genuine runtime measurements into the portable report input."""
    import yaml

    config_bytes = config_path.read_bytes()
    config = {key: value["value"] for key, value in yaml.safe_load(config_bytes).items()
              if key != "_wandb"}
    if config["cell"] != CELL or config["juror_model"] != "nvidia/nemotron-3-ultra-550b-a55b":
        raise ValueError("Source configuration does not match the admitted paid-route baseline")
    if any(config[name] for name in ("scripted_creator", "scripted_challenger", "scripted_jurors",
                                     "private_chat", "transfers_enabled", "memory_enabled")):
        raise ValueError("Admitted baseline must use live agents with all opportunity levers off")
    if config["pay_multiplier"] != 1 or config["audit_probability"] != 0:
        raise ValueError("Admitted baseline must use flat pay and no simulated audit")
    source_bytes = source.read_bytes()
    records = [json.loads(line) for line in source_bytes.decode().splitlines() if line.strip()]
    episodes = []
    for record in records:
        if record["experiment_id"] != EXPERIMENT_ID or record["config"]["game_backend"] != "core":
            raise ValueError("Episode evidence does not belong to the admitted core experiment")
        episode_id = record["episode_id"]
        jury = record["jury_metrics"]
        assigned_ids = [f"juror_{slot}_{episode_id}" for slot in range(config["jury_size"])]
        if set(record["votes"]) != set(assigned_ids):
            raise ValueError("Revealed vote identities do not match the runner's assigned roster")
        episodes.append({
            "episode_id": episode_id,
            "scenario_id": record["scenario_id"],
            "ground_truth": record["ground_truth"],
            "status": record["status"],
            "outcome": record["outcome"],
            "infrastructure_failure": record["infrastructure_failure"],
            "duration_secs": record["duration_secs"],
            "revealed_votes": [record["votes"][identity] for identity in assigned_ids],
            "counts": {
                "assigned_episodes": 1,
                "completed_episodes": int(record["status"] == "completed"
                    and not record["infrastructure_failure"]),
                "assigned_jurors": record["config"]["jury_size"],
                "valid_reveals": len(record["votes"]),
                "voting_pairs": jury["voting_pair_count"],
                "agreeing_pairs": jury["voting_agreement_count"],
                "truth_votes": jury["truth_vote_count"],
                "truth_aligned_votes": jury["truth_aligned_vote_count"],
                "truth_verdicts": jury["truth_verdict_count"],
                "truth_aligned_verdicts": jury["truth_aligned_verdict_count"],
                "public_messages": jury["public_message_count"],
                "private_messages": jury["private_message_count"],
                "prohibited_private_messages": jury["prohibited_private_message_count"],
                "slot_comparisons": jury["cross_episode_comparison_count"],
                "same_side_comparisons": jury["cross_episode_agreement_count"],
                "truth_slot_comparisons": jury["cross_episode_truth_comparison_count"],
                "same_correctness_comparisons": jury["cross_episode_truth_agreement_count"],
            },
            "straw_polls": [{key: poll[key] for key in ("round", "creator_votes", "challenger_votes")}
                            for poll in record["straw_polls"]],
        })
    deployment = records[0]["settlement"]["engine_evidence"]["deployment"]
    provenance = {
        "run_id": RUN_ID,
        "experiment_id": EXPERIMENT_ID,
        "wandb_url": f"https://forge.coreweave.com/wandb/lbxa-corp/apart-collusion-sprint/runs/{RUN_ID}",
        "excluded_free_route_run_id": "2vu0jc3u",
        "exclusion_reason": "daily free-model quota exhausted; not pooled with the completed paid-route run",
        "episodes_source": {"path": str(source.relative_to(REPO)) if source.is_relative_to(REPO) else str(source),
                            "sha256": hashlib.sha256(source_bytes).hexdigest()},
        "config_source": {"path": str(config_path.relative_to(REPO)) if config_path.is_relative_to(REPO) else str(config_path),
                          "sha256": hashlib.sha256(config_bytes).hexdigest()},
        "prompt_source_at_analysis": {
            "path": "harness/agents/prompts.py",
            "sha256": hashlib.sha256((REPO / "harness/agents/prompts.py").read_bytes()).hexdigest(),
        },
        "deployment": {key: deployment[key] for key in (
            "abi_version", "chain_id", "code_hash", "contract_address", "confirmation_depth")},
    }
    for key in ("cell", "backend", "purpose", "code_revision", "code_dirty", "seed",
                "temperature", "max_tokens", "creator_model", "challenger_model", "juror_model",
                "creator_provider", "challenger_provider", "juror_provider", "blocks", "block_index",
                "jury_size", "deliberation_rounds", "scenario_order", "memory_enabled", "memory_window",
                "private_chat", "public_messaging", "transfers_enabled", "pay_multiplier",
                "audit_probability", "creator_bet", "challenger_bet", "juror_bond"):
        provenance[key] = config[key]
    snapshot = {"schema_version": 1, "provenance": provenance, "episodes": episodes}
    snapshot["statistics"] = compute_statistics(snapshot)
    return snapshot


def plot_outcomes(snapshot: dict, statistics: dict, output_dir: Path) -> None:
    """Rates show episode replication; the matrix exposes the truth-side switch."""
    import matplotlib.pyplot as plt
    from matplotlib.colors import ListedColormap
    from matplotlib.ticker import PercentFormatter

    fig = plt.figure(figsize=(6.5, 3.05))
    grid = fig.add_gridspec(1, 2, left=0.20, right=0.98, bottom=0.35, top=0.82,
                           width_ratios=(1.48, 1), wspace=0.63)
    ax = fig.add_subplot(grid[0])
    names = list(RATE_COUNTS)
    labels = ["Voting alignment", "Truth alignment", "Valid reveals", "Completed episodes"]
    for row, name in enumerate(names):
        result = statistics["rates"][name]
        for value, offset, marker in zip(result["values"], (-0.095, 0.095), ("o", "s")):
            ax.plot(value, row + offset, marker=marker, color=GRAY, markerfacecolor="white",
                    markeredgewidth=0.85, markersize=4.2, zorder=3)
        ax.errorbar(result["mean"], row, xerr=result["sample_sd"], fmt="D", color=BLUE,
                    ecolor=PALE_BLUE, elinewidth=7, markersize=4.5, capsize=0, zorder=4)
        ax.text(1.055, row, f"{100 * result['mean']:.0f} ± {100 * result['sample_sd']:.0f}",
                va="center", ha="left", fontsize=8.5, color=CHARCOAL)
    ax.set_yticks(range(4), labels)
    ax.set_ylim(3.5, -0.5)
    ax.set_xlim(0, 1.30)
    ax.set_xticks([0, 0.5, 1])
    ax.xaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel("Episode rate")
    ax.grid(axis="x", color=LIGHT_GRAY, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0, pad=7)
    ax.spines["left"].set_visible(False)
    ax.spines["bottom"].set_bounds(0, 1)
    ax.set_title("(a) Alignment and execution", loc="left", pad=12, fontweight="bold")

    matrix = [[int(record["revealed_votes"][slot] == "CHALLENGER_SUPPORTED")
               for record in snapshot["episodes"]] for slot in range(7)]
    ax = fig.add_subplot(grid[1])
    ax.imshow(matrix, cmap=ListedColormap([BLUE, ORANGE]), vmin=0, vmax=1, aspect="auto")
    for slot in range(7):
        for episode in range(2):
            ax.text(episode, slot, "Cr" if matrix[slot][episode] == 0 else "Ch",
                    ha="center", va="center", color="white", fontsize=8.5)
    ax.set_xticks([0, 1], ["E1 · true", "E2 · false"])
    ax.set_yticks(range(7), [f"J{index + 1}" for index in range(7)])
    ax.set_xticks([-0.5, 0.5, 1.5], minor=True)
    ax.set_yticks([index - 0.5 for index in range(8)], minor=True)
    ax.grid(which="minor", color="white", linewidth=1.2)
    ax.tick_params(which="both", length=0)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_title("(b) Revealed votes", loc="left", pad=12, fontweight="bold")
    ax.set_xlabel("Cr: creator   Ch: challenger", labelpad=8, fontsize=8.5)
    fig.text(0.04, 0.15,
             "n = 2 episodes. Circles / squares: observations. Diamonds: mean ± sample SD (SD = 0).",
             fontsize=8.5, color=CHARCOAL)
    private_count = sum(record["counts"]["private_messages"] for record in snapshot["episodes"])
    side_repeats = sum(record["counts"]["same_side_comparisons"] for record in snapshot["episodes"])
    side_comparisons = sum(record["counts"]["slot_comparisons"] for record in snapshot["episodes"])
    fig.text(0.04, 0.085,
             f"Private channel disabled: {private_count} messages; abuse rate N/A. "
             f"Cross-episode side repeat: {side_repeats}/{side_comparisons}.",
             fontsize=8.5, color=CHARCOAL)
    for suffix in ("pdf", "png"):
        metadata = {"Title": "All-off jury baseline: alignment and revealed votes"}
        if suffix == "pdf":
            metadata.update(CreationDate=None, ModDate=None)
        fig.savefig(output_dir / f"baseline-outcomes.{suffix}", metadata=metadata)
    plt.close(fig)


def plot_process(snapshot: dict, statistics: dict, output_dir: Path) -> None:
    """Separate public deliberation dynamics from observed execution latency."""
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    from matplotlib.ticker import PercentFormatter

    fig = plt.figure(figsize=(6.5, 2.75))
    grid = fig.add_gridspec(1, 2, left=0.105, right=0.98, bottom=0.28, top=0.79,
                           width_ratios=(1.1, 1), wspace=0.65)
    ax = fig.add_subplot(grid[0])
    rounds = [poll["round"] for poll in statistics["straw_polls"]]
    means = [poll["mean"] for poll in statistics["straw_polls"]]
    deviations = [poll["sample_sd"] for poll in statistics["straw_polls"]]
    ax.fill_between(rounds, [value - sd for value, sd in zip(means, deviations)],
                    [value + sd for value, sd in zip(means, deviations)],
                    color=PALE_BLUE, alpha=1, zorder=1)
    ax.plot(rounds, means, color=BLUE, marker="D", markersize=4.5, zorder=4)
    for episode_index, (offset, marker) in enumerate(((-0.055, "o"), (0.055, "s"))):
        ax.plot([value + offset for value in rounds],
                [poll["values"][episode_index] for poll in statistics["straw_polls"]],
                linestyle="none", marker=marker, markersize=4, color=GRAY,
                markerfacecolor="white", markeredgewidth=0.85, zorder=3)
    ax.set_xlim(0.7, 3.3)
    ax.set_ylim(0, 1.13)
    ax.set_xticks(rounds)
    ax.set_yticks([0, 0.5, 1])
    ax.yaxis.set_major_formatter(PercentFormatter(1, decimals=0))
    ax.set_xlabel("Public deliberation round")
    ax.set_ylabel("Truth-aligned straw votes")
    ax.grid(axis="y", color=LIGHT_GRAY, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.set_title("(a) Deliberation trajectory", loc="left", pad=12, fontweight="bold")
    if len(set(zip(means, deviations))) == 1:
        ax.text(0.5, 0.16, f"{100 * means[0]:.0f}% ± {100 * deviations[0]:.0f} pp in every round",
                transform=ax.transAxes, ha="center", color=BLUE, fontsize=9)

    duration = statistics["duration_secs"]
    ax = fig.add_subplot(grid[1])
    for index, (value, marker) in enumerate(zip(duration["values"], ("o", "s"))):
        position = 2 - index
        ax.plot(value, position, marker=marker, color=GRAY, markerfacecolor="white",
                markersize=5.5, markeredgewidth=1, zorder=3)
        ax.annotate(f"{value:.1f}", (value, position), xytext=(0, 8),
                    textcoords="offset points", ha="center", color=GRAY, fontsize=8.5)
    center, sd = duration["mean"], duration["sample_sd"]
    ax.add_patch(Rectangle((center - sd, -0.23), 2 * sd, 0.46,
                           facecolor=PALE_BLUE, edgecolor="none", alpha=1, zorder=1))
    ax.hlines(0, center - sd, center + sd, color=BLUE, linewidth=1.1, zorder=2)
    ax.vlines([center - sd, center + sd], -0.1, 0.1, color=BLUE, linewidth=1.1, zorder=2)
    ax.plot(center, 0, marker="D", color=BLUE, markersize=5, zorder=3)
    ax.annotate(f"{center:.1f} ± {sd:.1f} s", (center, 0), xytext=(0, 10),
                textcoords="offset points", ha="center", color=BLUE, fontsize=9)
    ax.set_yticks([2, 1, 0], ["Episode 1", "Episode 2", "Mean ± SD"])
    ax.set_ylim(-0.6, 2.7)
    ax.set_xlim(72, 84)
    ax.set_xticks([72, 76, 80, 84])
    ax.set_xlabel("Episode duration (s)")
    ax.tick_params(axis="y", length=0, pad=5)
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x", color=LIGHT_GRAY, linewidth=0.5)
    ax.set_axisbelow(True)
    ax.set_title("(b) Observed execution time", loc="left", pad=12, fontweight="bold")
    fig.text(0.04, 0.10,
             "Pale blue: mean ± sample SD across two episodes; not a confidence interval.",
             fontsize=8.5, color=CHARCOAL)
    fig.text(0.04, 0.035,
             "Straw-poll bands collapse at SD = 0. Duration includes model, forum, and local-chain work.",
             fontsize=8.5, color=CHARCOAL)
    for suffix in ("pdf", "png"):
        metadata = {"Title": "All-off jury baseline: deliberation and execution time"}
        if suffix == "pdf":
            metadata.update(CreationDate=None, ModDate=None)
        fig.savefig(output_dir / f"baseline-process.{suffix}", metadata=metadata)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=REPORT / "data/baseline-smoke.json")
    parser.add_argument("--source", type=Path, help="Original admitted episodes JSONL; refresh safe snapshot")
    parser.add_argument("--config", type=Path, help="Original W&B config YAML; required with --source")
    parser.add_argument("--output-dir", type=Path, default=REPORT / "figures")
    parser.add_argument("--snapshot-only", action="store_true", help="Refresh measurement input without plotting")
    args = parser.parse_args()
    if bool(args.source) != bool(args.config):
        parser.error("--source and --config must be supplied together")
    if args.source:
        snapshot = extract_snapshot(args.source.resolve(), args.config.resolve())
        args.data.parent.mkdir(parents=True, exist_ok=True)
        with args.data.open("w") as output:
            json.dump(snapshot, output, indent=2, allow_nan=False)
            output.write("\n")
    else:
        snapshot = json.loads(args.data.read_text())
    statistics = compute_statistics(snapshot)
    if snapshot["statistics"] != statistics:
        raise ValueError("Saved measurement statistics differ from recomputation")
    if args.snapshot_only:
        print(args.data.resolve())
        return
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    args.output_dir.mkdir(parents=True, exist_ok=True)
    with plt.style.context(Path(__file__).with_name("baseline.mplstyle")):
        plot_outcomes(snapshot, statistics, args.output_dir)
        plot_process(snapshot, statistics, args.output_dir)
    print(json.dumps({"python": platform.python_version(), "matplotlib": matplotlib.__version__,
                      "data": str(args.data.resolve()), "output": str(args.output_dir.resolve()),
                      "duration_secs": statistics["duration_secs"]}, indent=2))


if __name__ == "__main__":
    main()
