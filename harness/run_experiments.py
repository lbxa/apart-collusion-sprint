#!/usr/bin/env python3
"""Run collusion experiments against the Rust game and local Anvil by default.

Examples:
  python run_experiments.py --treatment baseline --scripted --episodes 2
  OPENROUTER_API_KEY=... python run_experiments.py --all --live
  python run_experiments.py --compare-jury-sizes --scripted
  python run_experiments.py --compare-jury-sizes --mock --scripted

--scripted (also --dry-run) disables model calls, not the real game. Only --mock
selects the in-memory game. The external harness's treatment definitions remain
unchanged; unsupported real-protocol configurations fail before engine startup.
"""

import argparse
import asyncio
from dataclasses import replace
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))

from experiments.design import Cell, scenarios_for, treatment_for
from experiments.runner import ExperimentRunner
from experiments.treatments import (
    PREDEFINED_TREATMENTS,
    TreatmentConfig,
    make_incentive_treatment,
    make_jury_size_treatment,
)
from game_api.core_engine import CoreEngineAPI
from game_api.mock import MockGameAPI
from game_api.types import EpisodeConfig
from scenarios.examples import ALL_SCENARIOS, FALSE_CLAIMS_FOR_ATTACK

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def select_treatments(args) -> tuple[dict[str, TreatmentConfig], list]:
    """Choose the scientific comparison without changing its incentives or adversarial jurors."""
    if args.all:
        selected = {key: PREDEFINED_TREATMENTS[key] for key in (
            "baseline", "juror_objective", "bribe", "non_voter",
        )}
        scenarios, default_episodes = ALL_SCENARIOS, 5
    elif args.compare_jury_sizes:
        selected = {}
        sizes = [3, 5, 7, 11, 21] if args.mock else [3, 5, 7]
        for size in sizes:
            for with_adversaries in [False, True]:
                key = f"jury_{size}{'_adversarial' if with_adversaries else ''}"
                treatment = PREDEFINED_TREATMENTS.get(key)
                if treatment is None:
                    treatment = make_jury_size_treatment(size, with_adversaries)
                # These comparisons already use scripted party controls.
                selected[key] = replace(treatment, use_scripted_creator=True, use_scripted_challenger=True)
        scenarios, default_episodes = FALSE_CLAIMS_FOR_ATTACK, 10
    elif args.cell:
        cell = Cell.parse(args.cell)
        block = treatment_for(cell)
        selected = {f"{cell.id}_b{number}": block for number in range(1, args.blocks + 1)}
        scenarios, default_episodes = scenarios_for(cell), block.num_episodes
    elif args.compare_incentives:
        selected = {}
        for winner, juror, protocol, label in [
            (0.60, 0.30, 0.10, "default_60_30_10"),
            (0.80, 0.15, 0.05, "high_winner_80_15_5"),
            (0.40, 0.50, 0.10, "high_juror_40_50_10"),
            (0.50, 0.20, 0.30, "high_protocol_50_20_30"),
            (1 / 3, 1 / 3, 1 / 3, "equal_33_33_33"),
        ]:
            treatment = make_incentive_treatment(winner, juror, protocol, label)
            selected[label] = replace(treatment, use_scripted_creator=True, use_scripted_challenger=True)
        scenarios, default_episodes = FALSE_CLAIMS_FOR_ATTACK, 10
    else:
        treatment_id = args.treatment or "baseline"
        if treatment_id not in PREDEFINED_TREATMENTS:
            raise ValueError(f"Unknown treatment: {treatment_id}")
        selected = {treatment_id: PREDEFINED_TREATMENTS[treatment_id]}
        scenarios = ALL_SCENARIOS
        default_episodes = selected[treatment_id].num_episodes

    episodes = args.episodes if args.episodes is not None else (3 if args.scripted else default_episodes)
    prepared = {}
    for key, treatment in selected.items():
        treatment = replace(treatment, num_episodes=episodes, seed=args.seed)
        if args.scripted:
            treatment = replace(
                treatment, use_scripted_creator=True, use_scripted_challenger=True,
                scripted_juror_indices=list(range(treatment.jury_size)),
            )
        if not args.mock:
            CoreEngineAPI.validate_config(EpisodeConfig(
                episode_id="preflight", payout=treatment.payout,
                jury_size=treatment.jury_size, deliberation_rounds=treatment.deliberation_rounds,
            ))
        prepared[key] = treatment
    return prepared, scenarios


async def run_treatments(treatments, scenarios, *, output_dir, mock=False, core_engine_dir=None):
    """Own the game process for the complete experiment batch, including failures."""
    output_dir.mkdir(parents=True, exist_ok=True)
    game_api = MockGameAPI() if mock else CoreEngineAPI(core_engine_dir=core_engine_dir)
    logger.info("Using %s game backend", "mock" if mock else "core")
    try:
        if not mock:
            await game_api.start()
        runner = ExperimentRunner(game_api, output_dir=output_dir)
        results = {}
        for key, treatment in treatments.items():
            logger.info("Running treatment: %s", key)
            metrics = await runner.run_experiment(treatment, scenarios)
            results[key] = metrics.summary()
        print("\nEXPERIMENT RESULTS")
        print(json.dumps(results, indent=2, default=str, allow_nan=False))
        output_path = output_dir / "all_results.json"
        with output_path.open("w") as output:
            json.dump(results, output, indent=2, default=str, allow_nan=False)
        print(f"\nFull results saved to {output_path}")
        return results
    finally:
        if not mock:
            await game_api.stop()


async def main():
    parser = argparse.ArgumentParser(description="Run Veracity collusion experiments against Rust and Anvil")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--treatment", help="Treatment ID to run")
    selection.add_argument("--all", action="store_true", help="Run all core treatments")
    selection.add_argument("--compare-jury-sizes", action="store_true", help="Compare 3/5/7 jurors on core; --mock also includes 11/21")
    selection.add_argument("--cell", help="Experiment cell ID from docs/experiment-design.md, e.g. M1-C1-T1-R1-S1-E1")
    selection.add_argument("--compare-incentives", action="store_true", help="Compare original incentive structures; unsupported core configurations fail preflight")
    parser.add_argument("--blocks", type=int, default=2, help="Independent fresh-memory blocks per cell (with --cell)")
    parser.add_argument("--list", action="store_true", help="List available treatments")
    parser.add_argument("--episodes", type=int, help="Positive number of episodes per treatment")
    parser.add_argument("--output", default="results", help="Output directory")
    models = parser.add_mutually_exclusive_group()
    models.add_argument("--scripted", "--dry-run", dest="scripted", action="store_true", help="Use scripted models without API calls; still use the real game unless --mock")
    models.add_argument("--live", dest="scripted", action="store_false", help="Use each treatment's configured agents (default; scripted controls are preserved)")
    parser.set_defaults(scripted=False)
    backend = parser.add_mutually_exclusive_group()
    backend.add_argument("--core-engine", action="store_true", help="Use Rust and Anvil (default; retained for compatibility)")
    backend.add_argument("--mock", action="store_true", help="Explicitly use the in-memory game instead of Rust and Anvil")
    parser.add_argument("--core-engine-dir", help="Optional core engine repository root override")
    parser.add_argument("--seed", type=int, default=42, help="Random assignment seed")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable treatments:\n")
        for key, treatment in sorted(PREDEFINED_TREATMENTS.items()):
            print(f"  {key:30s}  {treatment.name}\n  {'':30s}  {treatment.description}\n")
        return 0
    if args.episodes is not None and args.episodes < 1:
        parser.error("--episodes must be positive")
    if args.blocks < 1:
        parser.error("--blocks must be positive")
    if args.mock and args.core_engine_dir:
        parser.error("--core-engine-dir cannot be used with --mock")
    if not (args.all or args.compare_jury_sizes or args.compare_incentives or args.treatment or args.cell or args.scripted):
        parser.print_help()
        return 0

    try:
        treatments, scenarios = select_treatments(args)
        results = await run_treatments(
            treatments, scenarios, output_dir=Path(args.output), mock=args.mock,
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
