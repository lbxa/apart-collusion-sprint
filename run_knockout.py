#!/usr/bin/env python3
"""Run the knockout experimental design for the Apart Collusion Sprint.

This is the main entry point. It runs the 8-condition knockout design
from the Inducing Collusion PDF using Qwen via OpenRouter.

Usage:
  # Pilot: run just the full condition (2-3 blocks) to check if collusion emerges
  OPENROUTER_API_KEY=your_key python run_knockout.py --pilot

  # Minimum viable: full + honest + 3 key knockouts (5 conditions)
  OPENROUTER_API_KEY=your_key python run_knockout.py --minimum

  # Full knockout: all 8 conditions
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
from metrics.collector import MetricsCollector
from scenarios.examples import FACTUAL_SCENARIOS, FALSE_CLAIMS_FOR_ATTACK

try:
    from game_api.core_engine import CoreEngineAPI
except ImportError:
    CoreEngineAPI = None

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
    return TreatmentConfig(
        **{
            **{k: getattr(treatment, k) for k in treatment.__dataclass_fields__},
            "use_scripted_creator": True,
            "use_scripted_challenger": True,
            "scripted_juror_indices": list(range(treatment.jury_size)),
            "scripted_juror_type": "honest",
            "num_episodes": 3,
        }
    )


async def run_conditions(
    conditions: dict[str, TreatmentConfig],
    output_dir: Path,
    episodes_per_condition: int | None = None,
    dry_run: bool = False,
    use_core_engine: bool = False,
    core_engine_dir: str | None = None,
):
    """Run a set of conditions and produce comparative results."""
    if use_core_engine:
        if CoreEngineAPI is None:
            print("ERROR: CoreEngineAPI not available. Install aiohttp: pip install aiohttp")
            sys.exit(1)
        game_api = CoreEngineAPI(core_engine_dir=core_engine_dir)
        logger.info("Using CORE ENGINE (Rust + Anvil on-chain settlement)")
    else:
        game_api = MockGameAPI()
        logger.info("Using MockGameAPI (in-memory)")
    runner = ExperimentRunner(game_api, output_dir=output_dir)

    all_results = {}
    total_start = time.monotonic()

    for cid, treatment in conditions.items():
        logger.info("=" * 70)
        logger.info("CONDITION: %s — %s", cid, treatment.name)
        logger.info("  %s", treatment.description)
        logger.info("=" * 70)

        if dry_run:
            treatment = make_dry_run_treatment(treatment)
        elif episodes_per_condition:
            treatment = TreatmentConfig(
                **{
                    **{k: getattr(treatment, k) for k in treatment.__dataclass_fields__},
                    "num_episodes": episodes_per_condition,
                }
            )

        scenarios = get_scenarios_for_condition(cid)
        metrics = await runner.run_experiment(treatment, scenarios)

        summary = metrics.summary()
        all_results[cid] = {
            "name": treatment.name,
            "description": treatment.description,
            "hypothesis": treatment.hypothesis,
            "levers": _describe_levers(cid),
            **summary,
        }

        logger.info("  Result: %s", json.dumps(summary, indent=2, default=str))
        logger.info("")

    elapsed = time.monotonic() - total_start

    # Print comparative summary
    print("\n" + "=" * 70)
    print("KNOCKOUT EXPERIMENT RESULTS")
    print("=" * 70)
    print(f"Total time: {elapsed:.1f}s")
    print(f"Conditions: {len(all_results)}")
    print()

    # Collusion comparison table
    print(f"{'Condition':<30} {'Episodes':>8} {'False Verdicts':>14} {'Accuracy':>10} {'Hung':>6}")
    print("-" * 70)
    for cid, result in all_results.items():
        name = result["name"][:28]
        episodes = result.get("total_episodes", 0)
        fvr = result.get("false_verdict_rate", 0)
        acc = result.get("verdict_accuracy", 0)
        hung = result.get("hung_jury_rate", 0)
        print(f"{name:<30} {episodes:>8} {fvr:>13.1%} {acc:>9.1%} {hung:>5.1%}")

    print()

    # Shutdown core engine if used
    if use_core_engine and hasattr(game_api, "stop"):
        await game_api.stop()

    # Save results
    results_file = output_dir / "knockout_results.json"
    with open(results_file, "w") as f:
        json.dump(all_results, f, indent=2, default=str)
    print(f"Full results: {results_file}")

    return all_results


def _describe_levers(condition_id: str) -> dict[str, bool]:
    """Describe which levers are active in a condition."""
    if condition_id == "knockout_full":
        return {
            "private_channel": True, "side_payments": True,
            "repeated_play": True, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": True,
        }
    elif condition_id == "knockout_honest":
        return {
            "private_channel": False, "side_payments": False,
            "repeated_play": False, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": False,
        }
    elif condition_id == "knockout_no_channel":
        return {
            "private_channel": False, "side_payments": True,
            "repeated_play": True, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": True,
        }
    elif condition_id == "knockout_no_transfers":
        return {
            "private_channel": True, "side_payments": False,
            "repeated_play": True, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": True,
        }
    elif condition_id == "knockout_no_repeat":
        return {
            "private_channel": True, "side_payments": True,
            "repeated_play": False, "high_stakes": True,
            "ambiguous_evidence": True, "no_detection_risk": True,
        }
    elif condition_id == "knockout_low_stakes":
        return {
            "private_channel": True, "side_payments": True,
            "repeated_play": True, "high_stakes": False,
            "ambiguous_evidence": True, "no_detection_risk": True,
        }
    elif condition_id == "knockout_clear_evidence":
        return {
            "private_channel": True, "side_payments": True,
            "repeated_play": True, "high_stakes": True,
            "ambiguous_evidence": False, "no_detection_risk": True,
        }
    elif condition_id == "knockout_detection":
        return {
            "private_channel": True, "side_payments": True,
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
  python run_knockout.py --minimum          # 5 key conditions
  python run_knockout.py --full             # All 8 conditions
  python run_knockout.py --condition knockout_full --episodes 20
        """,
    )
    parser.add_argument("--pilot", action="store_true",
                        help="Pilot run: full condition only (2 blocks = 20 episodes)")
    parser.add_argument("--minimum", action="store_true",
                        help="Minimum viable: 5 key conditions")
    parser.add_argument("--full", action="store_true",
                        help="Full knockout: all 8 conditions")
    parser.add_argument("--condition", type=str,
                        help="Run a single condition by ID")
    parser.add_argument("--dry-run", action="store_true",
                        help="Use scripted agents (no API key needed)")
    parser.add_argument("--list", action="store_true",
                        help="List all conditions")
    parser.add_argument("--episodes", type=int, default=None,
                        help="Episodes per condition (overrides default)")
    parser.add_argument("--output", type=str, default="results/knockout",
                        help="Output directory")
    parser.add_argument("--core-engine", action="store_true",
                        help="Use the real Rust core engine with on-chain settlement (requires compiled binary)")
    parser.add_argument("--core-engine-dir", type=str, default=None,
                        help="Path to core engine repo (default: auto-detect)")

    args = parser.parse_args()

    if args.list:
        print("\nKnockout conditions:\n")
        for cid, c in KNOCKOUT_CONDITIONS.items():
            levers = _describe_levers(cid)
            active = sum(1 for v in levers.values() if v)
            print(f"  {cid:<30} {c.name}")
            print(f"  {'':30} {c.description}")
            print(f"  {'':30} Levers active: {active}/6")
            print()
        return

    if not args.dry_run and not os.environ.get("OPENROUTER_API_KEY"):
        print("ERROR: Set OPENROUTER_API_KEY environment variable.")
        print("  Get one at https://openrouter.ai/keys")
        print("  Or use --dry-run to test with scripted agents.")
        sys.exit(1)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    engine_kwargs = {
        "use_core_engine": args.core_engine,
        "core_engine_dir": args.core_engine_dir,
    }

    if args.pilot:
        conditions = {"knockout_full": KNOCKOUT_CONDITIONS["knockout_full"]}
        await run_conditions(
            conditions, output_dir,
            episodes_per_condition=args.episodes or 20,
            dry_run=args.dry_run,
            **engine_kwargs,
        )
    elif args.minimum:
        await run_conditions(
            KNOCKOUT_MINIMUM, output_dir,
            episodes_per_condition=args.episodes,
            dry_run=args.dry_run,
            **engine_kwargs,
        )
    elif args.full:
        await run_conditions(
            KNOCKOUT_CONDITIONS, output_dir,
            episodes_per_condition=args.episodes,
            dry_run=args.dry_run,
            **engine_kwargs,
        )
    elif args.condition:
        if args.condition not in KNOCKOUT_CONDITIONS:
            print(f"Unknown condition: {args.condition}")
            print(f"Available: {', '.join(KNOCKOUT_CONDITIONS.keys())}")
            sys.exit(1)
        conditions = {args.condition: KNOCKOUT_CONDITIONS[args.condition]}
        await run_conditions(
            conditions, output_dir,
            episodes_per_condition=args.episodes,
            dry_run=args.dry_run,
            **engine_kwargs,
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())