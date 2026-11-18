"""Command-line lifecycle and credential loading, outside participant sandboxes."""

import argparse
import asyncio
import json
import logging
import os
import shutil
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .config import load_experiment
from .ratelimit import RateLimitStoreError
from .runner import ROOT, run_experiment
from .sandbox import DockerArena
from .spending import CampaignSpending


def main():
    parser = argparse.ArgumentParser(description="Agentic Veracity experiments")
    parser.add_argument("command", choices=["validate", "build-sandbox", "run", "smoke"])
    parser.add_argument("--config", type=Path, default=ROOT / "harness/examples/discovery.toml")
    parser.add_argument("--output", type=Path, default=ROOT / "harness/results")
    parser.add_argument("--dotenv", type=Path, default=ROOT / ".env")
    parser.add_argument("--model", help="Provider model ID selected by the experiment")
    parser.add_argument(
        "--provider",
        choices=["openrouter", "cloudflare"],
        help="Model provider override; recorded with the experiment model settings",
    )
    parser.add_argument("--seed", type=int, help="Recorded participant-launch seed override")
    parser.add_argument(
        "--budget-ledger", type=Path, help="Shared SQLite ledger for all campaign runs"
    )
    parser.add_argument("--budget-usd", type=Decimal, help="Total authorized cap for this ledger")
    parser.add_argument("--credential", choices=["primary", "backup"], default="primary")
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Provider SDK logs can contain request bodies; private evidence has its own files.
    for name in ("httpx", "httpcore", "openrouter", "openai", "docker", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)
    if args.command == "build-sandbox":
        arena = DockerArena("veracity-image-build")
        try:
            arena.build_image()
        finally:
            arena.close()
        print("Sandbox image ready")
        return
    try:
        experiment = load_experiment(
            args.config, model_name=args.model, seed=args.seed, provider=args.provider
        )
    except ValidationError as error:
        missing_model = any(
            item["type"] == "missing" and item["loc"] in {("model",), ("model", "name")}
            for item in error.errors(include_input=False)
        )
        if missing_model:
            parser.error("Select an experiment model in [model].name or with --model")
        parser.error(f"Invalid configuration ({type(error).__name__}); check {args.config}")
    except (OSError, ValueError) as error:
        parser.error(f"Invalid configuration ({type(error).__name__}); check {args.config}")
    if args.command == "validate":
        print(json.dumps(experiment.model_dump(mode="json"), indent=2))
        return
    load_dotenv(args.dotenv, override=False)
    if experiment.model.provider == "cloudflare":
        if args.credential == "backup":
            parser.error("--credential backup selects an OpenRouter key")
        for name in ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN"):
            if not os.environ.get(name):
                parser.error(f"{name} is missing from the environment and {args.dotenv}")
    else:
        if args.credential == "backup":
            backup = os.environ.get("OPENROUTER_BACKUP_API_KEY")
            if not backup:
                parser.error("OPENROUTER_BACKUP_API_KEY is missing")
            os.environ["OPENROUTER_API_KEY"] = backup
        if not os.environ.get("OPENROUTER_API_KEY"):
            parser.error(f"OPENROUTER_API_KEY is missing from the environment and {args.dotenv}")
    if args.budget_ledger is None or args.budget_usd is None:
        parser.error("Live runs require --budget-ledger and --budget-usd")
    try:
        spending = CampaignSpending(args.budget_ledger.resolve(), args.budget_usd)
    except ValueError as error:
        parser.error(str(error))
    smoke = args.command == "smoke"
    if smoke:
        experiment = experiment.model_copy(
            update={
                "episodes": 1,
                "schedule": experiment.schedule[:1],
                "model": experiment.model.model_copy(
                    update={
                        "calls_per_turn": min(4, experiment.model.calls_per_turn),
                        "calls_per_episode": min(4, experiment.model.calls_per_episode),
                    }
                ),
            }
        )
    # Idle sleep pauses asyncio's monotonic clock, so turn timeouts stop counting and
    # provider connections drop on wake. Hold an assertion for this process's lifetime.
    if sys.platform == "darwin" and (caffeinate := shutil.which("caffeinate")):
        subprocess.Popen([caffeinate, "-i", "-w", str(os.getpid())])
    try:
        directory = asyncio.run(
            run_experiment(experiment, args.output, smoke=smoke, spending=spending)
        )
    except RateLimitStoreError:
        logging.error(
            "Rate-limit store unavailable; set VERACITY_RATE_DB to a writable shared SQLite path"
        )
        raise SystemExit(1) from None
    except Exception as error:
        logging.error(
            "run failed error_type=%s; inspect the run manifest in %s",
            type(error).__name__,
            args.output,
        )
        raise SystemExit(1) from None
    print(directory)
    if json.loads((directory / "run.json").read_text())["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
