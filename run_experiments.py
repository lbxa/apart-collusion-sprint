#!/usr/bin/env python3
"""Main entry point for running collusion experiments.

Usage:
  # Run all predefined treatments with mock API
  python run_experiments.py --all

  # Run a specific treatment
  python run_experiments.py --treatment baseline

  # Run with real LLM agents (requires API keys)
  OPENAI_API_KEY=... python run_experiments.py --treatment baseline --live

  # Run with custom jury size and coalition
  python run_experiments.py --treatment jury_11_coalition --episodes 20

  # Run a comparative study across jury sizes
  python run_experiments.py --compare-jury-sizes

  # Run a comparative study across incentive structures
  python run_experiments.py --compare-incentives

  # List available treatments
  python run_experiments.py --list
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

# Add harness to path
sys.path.insert(0, str(Path(__file__).parent))

from experiments.runner import ExperimentRunner
from experiments.treatments import PREDEFINED_TREATMENTS, TreatmentConfig, make_jury_size_treatment, make_incentive_treatment
from game_api.mock import MockGameAPI
from metrics.collector import MetricsCollector
from scenarios.examples import ALL_SCENARIOS, FACTUAL_SCENARIOS, FALSE_CLAIMS_FOR_ATTACK

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_single_treatment(
    runner: ExperimentRunner,
    treatment_id: str,
    num_episodes: int | None = None,
    scenarios=None,
):
    """Run a single treatment."""
    treatment = PREDEFINED_TREATMENTS.get(treatment_id)
    if treatment is None:
        logger.error("Unknown treatment: %s", treatment_id)
        logger.info("Available: %s", ", ".join(PREDEFINED_TREATMENTS.keys()))
        return None

    if num_episodes is not None:
        # Create a modified copy
        treatment = TreatmentConfig(
            **{
                **{k: getattr(treatment, k) for k in treatment.__dataclass_fields__},
                "num_episodes": num_episodes,
            }
        )

    if scenarios is None:
        scenarios = ALL_SCENARIOS

    return await runner.run_experiment(treatment, scenarios)


async def run_all_treatments(runner: ExperimentRunner, num_episodes: int = 5):
    """Run all predefined treatments."""
    results = {}
    core_treatments = [
        "baseline",
        "coalition_no_msg",
        "coalition_with_msg",
        "creator_juror",
        "bribe",
        "non_voter",
    ]

    for tid in core_treatments:
        logger.info("=" * 60)
        logger.info("Running treatment: %s", tid)
        logger.info("=" * 60)
        metrics = await run_single_treatment(runner, tid, num_episodes)
        if metrics:
            results[tid] = metrics.summary()

    return results


async def compare_jury_sizes(runner: ExperimentRunner, num_episodes: int = 10):
    """Compare collusion resistance across jury sizes."""
    results = {}
    for size in [3, 5, 7, 11, 21]:
        for with_coalition in [False, True]:
            tid = f"jury_{size}{'_coalition' if with_coalition else ''}"
            treatment = PREDEFINED_TREATMENTS.get(tid)
            if treatment is None:
                treatment = make_jury_size_treatment(size, with_coalition)

            treatment = TreatmentConfig(
                **{
                    **{k: getattr(treatment, k) for k in treatment.__dataclass_fields__},
                    "num_episodes": num_episodes,
                    "use_scripted_creator": True,
                    "use_scripted_challenger": True,
                }
            )

            logger.info("Running jury size %d %s", size, "with coalition" if with_coalition else "baseline")
            metrics = await runner.run_experiment(treatment, FALSE_CLAIMS_FOR_ATTACK)
            results[tid] = metrics.summary()

    return results


async def compare_incentives(runner: ExperimentRunner, num_episodes: int = 10):
    """Compare collusion under different incentive structures."""
    results = {}
    configs = [
        (0.60, 0.30, 0.10, "default_60_30_10"),
        (0.80, 0.15, 0.05, "high_winner_80_15_5"),
        (0.40, 0.50, 0.10, "high_juror_40_50_10"),
        (0.50, 0.20, 0.30, "high_protocol_50_20_30"),
        (1/3, 1/3, 1/3, "equal_33_33_33"),
    ]

    for winner, juror, protocol, label in configs:
        treatment = make_incentive_treatment(winner, juror, protocol, label)
        treatment = TreatmentConfig(
            **{
                **{k: getattr(treatment, k) for k in treatment.__dataclass_fields__},
                "num_episodes": num_episodes,
                "use_scripted_creator": True,
                "use_scripted_challenger": True,
            }
        )

        logger.info("Running incentive structure: %s", label)
        metrics = await runner.run_experiment(treatment, FALSE_CLAIMS_FOR_ATTACK)
        results[label] = metrics.summary()

    return results


async def main():
    parser = argparse.ArgumentParser(description="Run Veracity collusion experiments")
    parser.add_argument("--treatment", type=str, help="Treatment ID to run")
    parser.add_argument("--all", action="store_true", help="Run all core treatments")
    parser.add_argument("--compare-jury-sizes", action="store_true", help="Compare across jury sizes")
    parser.add_argument("--compare-incentives", action="store_true", help="Compare across incentive structures")
    parser.add_argument("--list", action="store_true", help="List available treatments")
    parser.add_argument("--episodes", type=int, default=None, help="Number of episodes per treatment")
    parser.add_argument("--output", type=str, default="results", help="Output directory")
    parser.add_argument("--live", action="store_true", help="Use real LLM APIs (requires API keys)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")

    args = parser.parse_args()

    if args.list:
        print("\nAvailable treatments:\n")
        for tid, t in sorted(PREDEFINED_TREATMENTS.items()):
            print(f"  {tid:30s}  {t.name}")
            if t.description:
                print(f"  {'':30s}  {t.description}")
            print()
        return

    # Create game API (mock for now; swap for real API when game is built)
    game_api = MockGameAPI()
    runner = ExperimentRunner(game_api, output_dir=Path(args.output))

    if args.all:
        results = await run_all_treatments(runner, args.episodes or 5)
    elif args.compare_jury_sizes:
        results = await compare_jury_sizes(runner, args.episodes or 10)
    elif args.compare_incentives:
        results = await compare_incentives(runner, args.episodes or 10)
    elif args.treatment:
        metrics = await run_single_treatment(runner, args.treatment, args.episodes)
        results = {args.treatment: metrics.summary()} if metrics else {}
    else:
        parser.print_help()
        return

    # Print results
    print("\n" + "=" * 60)
    print("EXPERIMENT RESULTS")
    print("=" * 60)
    print(json.dumps(results, indent=2, default=str))

    # Save full results
    output_path = Path(args.output) / "all_results.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results saved to {output_path}")


if __name__ == "__main__":
    asyncio.run(main())
