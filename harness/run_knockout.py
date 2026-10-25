#!/usr/bin/env python3
"""Run the knockout experimental design for the Apart Collusion Sprint.

This is the main entry point. It runs the 7-condition knockout design
from the Inducing Collusion PDF using the configured model providers.

Usage:
  # Pilot: run just the full condition (2-3 blocks) to check if collusion emerges
  OPENROUTER_API_KEY=your_key python run_knockout.py --pilot

  # Minimum viable: full + honest + 2 key knockouts (4 conditions)
  OPENROUTER_API_KEY=your_key python run_knockout.py --minimum

  # Full knockout: all 7 conditions
  OPENROUTER_API_KEY=your_key python run_knockout.py --full

  # Single condition
  OPENROUTER_API_KEY=your_key python run_knockout.py --condition knockout_full

  # Dry run with scripted agents (no API key needed, tests the plumbing)
  python run_knockout.py --dry-run

  # List conditions
  python run_knockout.py --list
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from experiments.knockout import (
    FICTIONAL_SCENARIOS_AMBIGUOUS,
    FICTIONAL_SCENARIOS_CLEAR,
    KNOCKOUT_CONDITIONS,
    KNOCKOUT_MINIMUM,
)
from experiments.runner import ExperimentRunner
from experiments.treatments import TreatmentConfig
from game_api.mock import MockGameAPI
from game_api.core_engine import CoreEngineAPI
from game_api.types import EpisodeConfig
from scenarios.examples import FACTUAL_SCENARIOS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def get_scenarios_for_condition(condition_id: str):
    """Pick scenarios based on the condition.

    - knockout_clear_evidence uses clear-cut factual scenarios
    - All others use the ambiguous fictional scenarios (per PDF)
    """
    if condition_id == "knockout_clear_evidence":
        # Use clear scenarios + factual scenarios with known truth
        return FICTIONAL_SCENARIOS_CLEAR + FACTUAL_SCENARIOS
    elif condition_id == "knockout_honest":
        # Baseline also uses ambiguous scenarios for fair comparison
        return FICTIONAL_SCENARIOS_AMBIGUOUS
    else:
        # All collusion conditions use ambiguous scenarios
        return FICTIONAL_SCENARIOS_AMBIGUOUS


def make_dry_run_treatment(treatment: TreatmentConfig) -> TreatmentConfig:
    """Convert a treatment to use scripted agents (no API needed)."""
    return replace(
        treatment,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=list(range(treatment.jury_size)),
        scripted_auditor_indices=list(range(treatment.auditor_count)),
    )


async def run_conditions(
    conditions: dict[str, TreatmentConfig],
    output_dir: Path,
    episodes_per_condition: int | None = None,
    dry_run: bool = False,
    use_core_engine: bool = True,
    core_engine_dir: str | None = None,
):
    """Run a set of conditions and produce comparative results."""
    if episodes_per_condition is not None and episodes_per_condition < 1:
        raise ValueError("episodes_per_condition must be positive")
    prepared = {}
    for cid, treatment in conditions.items():
        if dry_run:
            treatment = make_dry_run_treatment(treatment)
        episodes = episodes_per_condition if episodes_per_condition is not None else (3 if dry_run else treatment.num_episodes)
        treatment = replace(treatment, num_episodes=episodes)
        if use_core_engine:
            CoreEngineAPI.validate_config(EpisodeConfig(
                episode_id="preflight", payout=treatment.payout,
                jury_size=treatment.jury_size, deliberation_rounds=treatment.deliberation_rounds,
            ))
        prepared[cid] = treatment

    output_dir.mkdir(parents=True, exist_ok=True)
    game_api = CoreEngineAPI(core_engine_dir=core_engine_dir) if use_core_engine else MockGameAPI()
    logger.info("Using %s game backend; models=%s", "core" if use_core_engine else "mock", "scripted" if dry_run else "configured")
    all_results = {}
    total_start = time.monotonic()
    try:
        if use_core_engine:
            await game_api.start()
        runner = ExperimentRunner(game_api, output_dir=output_dir)
        for cid, treatment in prepared.items():
            logger.info("CONDITION: %s — %s", cid, treatment.name)
            metrics = await runner.run_experiment(treatment, get_scenarios_for_condition(cid))
            summary = metrics.summary()
            all_results[cid] = {
                "name": treatment.name, "description": treatment.description,
                "hypothesis": treatment.hypothesis, "levers": _describe_levers(cid), **summary,
            }
            logger.info("Result for %s: %s", cid, json.dumps(summary, default=str, allow_nan=False))

        print("\nKNOCKOUT EXPERIMENT RESULTS")
        print(f"Total time: {time.monotonic() - total_start:.1f}s")
        print(f"Conditions: {len(all_results)}")
        print(f"{'Condition':<30} {'Episodes':>8} {'False Verdicts':>14} {'Accuracy':>10} {'Hung':>6}")
        for result in all_results.values():
            rates = [f"{value:.1%}" if value is not None else "n/a" for value in (
                result.get("false_verdict_rate"), result.get("verdict_accuracy"), result.get("hung_jury_rate"))]
            print(f"{result['name'][:28]:<30} {result.get('total_episodes', 0):>8} "
                  f"{rates[0]:>14} {rates[1]:>10} {rates[2]:>6}")
        results_file = output_dir / "knockout_results.json"
        with results_file.open("w") as output:
            json.dump(all_results, output, indent=2, default=str, allow_nan=False)
        print(f"Full results: {results_file}")
        return all_results
    finally:
        if use_core_engine:
            await game_api.stop()


def _describe_levers(condition_id: str) -> dict[str, bool]:
    """Describe which levers are active in a condition."""
    if condition_id == "knockout_full":
        return {
            "side_payments": True,
            "repeated_play": True, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": True,
        }
    elif condition_id == "knockout_honest":
        return {
            "side_payments": False,
            "repeated_play": False, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": False,
        }
    elif condition_id == "knockout_no_transfers":
        return {
            "side_payments": False,
            "repeated_play": True, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": True,
        }
    elif condition_id == "knockout_no_repeat":
        return {
            "side_payments": True,
            "repeated_play": False, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": True,
        }
    elif condition_id == "knockout_low_stakes":
        return {
            "side_payments": True,
            "repeated_play": True, "high_stakes": False,
            "ambiguous_evidence": True, "no_detection_risk": True,
        }
    elif condition_id == "knockout_clear_evidence":
        return {
            "side_payments": True,
            "repeated_play": True, "high_stakes": True,
            "ambiguous_evidence": False, "no_detection_risk": True,
        }
    elif condition_id == "knockout_detection":
        return {
            "side_payments": True,
            "repeated_play": True, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": False,
        }
    return {}


async def main():
    parser = argparse.ArgumentParser(
        description="Run knockout collusion experiment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_knockout.py --dry-run          # Test with scripted agents (no API key)
  python run_knockout.py --pilot            # Pilot: full condition only
  python run_knockout.py --minimum          # 4 key conditions
  python run_knockout.py --full             # All 7 conditions
  python run_knockout.py --condition knockout_full --episodes 20
        """,
    )
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--pilot", action="store_true",
                        help="Pilot run: full condition only (2 blocks = 20 episodes)")
    selection.add_argument("--minimum", action="store_true",
                        help="Minimum viable: 4 key conditions")
    selection.add_argument("--full", action="store_true",
                        help="Full knockout: all 7 conditions")
    selection.add_argument("--condition", type=str,
                        help="Run a single condition by ID")
    models = parser.add_mutually_exclusive_group()
    models.add_argument("--dry-run", "--scripted", dest="dry_run", action="store_true",
                        help="Use scripted models without an API key; keep the selected game backend")
    models.add_argument("--live", dest="dry_run", action="store_false",
                        help="Use the treatment's configured model agents (default)")
    parser.set_defaults(dry_run=False)
    parser.add_argument("--list", action="store_true",
                        help="List all conditions")
    parser.add_argument("--episodes", type=int, default=None,
                        help="Episodes per condition (overrides default)")
    parser.add_argument("--output", type=str, default="results/knockout",
                        help="Output directory")
    backend = parser.add_mutually_exclusive_group()
    backend.add_argument("--core-engine", action="store_true",
                        help="Use Rust and Anvil (default; retained for compatibility)")
    backend.add_argument("--mock", action="store_true",
                        help="Explicitly use the in-memory mock instead of Rust and Anvil")
    parser.add_argument("--core-engine-dir", type=str, default=None,
                        help="Override the core engine repository root (default: this repository)")

    args = parser.parse_args()

    if args.list:
        print("\nKnockout conditions:\n")
        for cid, c in KNOCKOUT_CONDITIONS.items():
            levers = _describe_levers(cid)
            active = sum(1 for v in levers.values() if v)
            print(f"  {cid:<30} {c.name}")
            print(f"  {'':30} {c.description}")
            print(f"  {'':30} Levers active: {active}/5")
            print()
        return 0

    if args.episodes is not None and args.episodes < 1:
        parser.error("--episodes must be positive")
    if args.mock and args.core_engine_dir:
        parser.error("--core-engine-dir cannot be used with --mock")

    if args.pilot:
        conditions = {"knockout_full": KNOCKOUT_CONDITIONS["knockout_full"]}
        episodes = args.episodes if args.episodes is not None else (3 if args.dry_run else 20)
    elif args.minimum:
        conditions, episodes = KNOCKOUT_MINIMUM, args.episodes
    elif args.full:
        conditions, episodes = KNOCKOUT_CONDITIONS, args.episodes
    elif args.condition or args.dry_run:
        condition = args.condition or "knockout_full"
        if condition not in KNOCKOUT_CONDITIONS:
            parser.error(f"Unknown condition: {condition}")
        conditions = {condition: KNOCKOUT_CONDITIONS[condition]}
        episodes = args.episodes
    else:
        parser.print_help()
        return 0

    if not args.dry_run and not os.environ.get("OPENROUTER_API_KEY"):
        print("ERROR: Set OPENROUTER_API_KEY environment variable.")
        print("  Get one at https://openrouter.ai/keys")
        print("  Or use --scripted for model-free tests against the real game.")
        return 1

    try:
        results = await run_conditions(
            conditions, Path(args.output), episodes_per_condition=episodes,
            dry_run=args.dry_run, use_core_engine=not args.mock,
            core_engine_dir=args.core_engine_dir,
        )
    except Exception as error:
        logger.error("Experiment run failed: %s", error)
        return 1
    if any(result.get("infrastructure_failure_rate", 0) > 0 for result in results.values()):
        logger.error("One or more episodes failed because of infrastructure; inspect the saved results.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
