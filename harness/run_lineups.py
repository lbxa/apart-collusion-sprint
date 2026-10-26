#!/usr/bin/env python3
"""Run cells once per model lineup, in parallel, as separate run_experiments.py processes.

Each (cell, lineup) pair is its own process with its own engine, output directory
and log. Lineups of one cell are queued together, so they run side by side and
share provider drift over time instead of confounding it with model. Every run
joins one W&B group, named after the output directory. Options after `--` pass
through to run_experiments.py.

Examples:
  python run_lineups.py M0-C0-T0-R0-S0-E0 V --jobs 8 -- --wandb --run-purpose first-pass
  python run_lineups.py V --lineup opus gpt_luna -- --blocks 1 --episodes 1 --run-purpose smoke
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).parent))

from experiments.design import LINEUPS, resolve_cell

RUN_EXPERIMENTS = Path(__file__).with_name("run_experiments.py")
DEFAULT_OUTPUT_ROOT = Path(__file__).resolve().parents[1] / ".harness" / "experiments"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    own, passthrough = (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, [])
    parser = argparse.ArgumentParser(description="Run cells once per model lineup, in parallel")
    parser.add_argument("cells", nargs="+", help="Cell IDs or named conditions, e.g. M0-C0-T0-R0-S0-E0 V")
    parser.add_argument("--lineup", nargs="+", choices=list(LINEUPS), default=list(LINEUPS),
                        help="Lineups to run (default: every lineup)")
    parser.add_argument("--jobs", type=int, default=8, help="Runs at once (default 8)")
    parser.add_argument("--output", type=Path, help="Output directory (default: .harness/experiments/lineups-<UTC time>)")
    args = parser.parse_args(own)
    if args.jobs < 1:
        parser.error("--jobs must be positive")
    try:
        cells = [resolve_cell(cell).id for cell in args.cells]
    except ValueError as error:
        parser.error(str(error))

    output = args.output or DEFAULT_OUTPUT_ROOT / time.strftime("lineups-%Y%m%dT%H%M%SZ", time.gmtime())
    output.mkdir(parents=True, exist_ok=True)
    runs = [(cell, lineup) for cell in cells for lineup in args.lineup]
    print(f"{len(runs)} runs, {args.jobs} at a time; logs in {output}", flush=True)

    def run(cell: str, lineup: str) -> int:
        name = f"{cell}_{lineup}"
        command = [sys.executable, str(RUN_EXPERIMENTS), "--cell", cell, "--lineup", lineup,
                   "--output", str(output / name), "--wandb-group", output.name, *passthrough]
        with (output / f"{name}.log").open("w") as log:
            code = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT).returncode
        print(f"{'done' if code == 0 else 'FAILED'}  {name}", flush=True)
        return code

    with ThreadPoolExecutor(args.jobs) as pool:
        codes = list(pool.map(run, *zip(*runs)))
    failed = sum(code != 0 for code in codes)
    print(f"{len(runs) - failed}/{len(runs)} runs succeeded; logs in {output}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
