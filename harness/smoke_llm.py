#!/usr/bin/env python3
"""One-episode, one-round live-model smoke test of an experiment cell.

Runs a 3-juror jury for a single deliberation round on the real engine, then
prints what the models did with each lever. Costs about a dozen model calls.

  OPENROUTER_API_KEY=your_key python smoke_llm.py              # cell F
  OPENROUTER_API_KEY=your_key python smoke_llm.py --cell K7    # named condition or cell ID
"""

import argparse
import asyncio
import json
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from experiments.design import resolve_cell, scenarios_for, treatment_for
from experiments.runner import ExperimentRunner
from game_api.core_engine import CoreEngineAPI
from game_api.money import financial_json


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cell", default="F", help="Cell ID or named condition (default F)")
    parser.add_argument("--output", default="results/smoke")
    args = parser.parse_args()
    cell = resolve_cell(args.cell)
    if not os.environ.get("OPENROUTER_API_KEY"):
        print("ERROR: set OPENROUTER_API_KEY; this smoke test calls live models.")
        return 1
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    treatment = replace(treatment_for(cell, num_episodes=1), jury_size=3, deliberation_rounds=1)
    async with CoreEngineAPI() as api:
        metrics = await ExperimentRunner(api, Path(args.output)).run_experiment(
            treatment, scenarios_for(cell), f"smoke_{cell.id}")

    [record] = metrics.episodes
    print(f"\nCell {cell.id}: {record.status} {record.outcome}")
    if record.failure_reason:
        print(f"FAILED: {record.failure_reason}")
    print(f"Votes: {json.dumps(record.votes)}")
    for message in record.messages:
        target = f" -> {message['recipient']}" if message["channel"] == "private" else ""
        print(f"  [{message['channel']}] {message['sender']}{target}: {message['content'][:160]}")
    for name in ("bribes_offered", "transfers_rejected", "pay_bonuses", "audit_penalties", "chat_audit"):
        print(f"{name}: {json.dumps(financial_json(getattr(record, name)), default=str)}")
    print(f"Transcript: {Path(args.output) / record.experiment_id / 'transcripts'}")
    return 0 if record.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
