"""Command-line lifecycle and credential loading, outside participant sandboxes."""

import argparse
import asyncio
import json
import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import ValidationError

from .config import load_experiment
from .runner import ROOT, run_experiment
from .sandbox import DockerArena


def main():
    parser = argparse.ArgumentParser(description="Agentic Veracity experiments")
    parser.add_argument("command", choices=["validate", "build-sandbox", "run", "smoke"])
    parser.add_argument("--config", type=Path, default=ROOT / "harness-v2/examples/discovery.toml")
    parser.add_argument("--output", type=Path, default=ROOT / "harness-v2/results")
    parser.add_argument("--dotenv", type=Path, default=ROOT / ".env")
    parser.add_argument("--model", help="OpenRouter model ID selected by the experiment")
    args = parser.parse_args()
    os.umask(0o077)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Provider SDK logs can contain request bodies; private evidence has its own files.
    for name in ("httpx", "httpcore", "openrouter", "docker", "urllib3"):
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
        experiment = load_experiment(args.config, model_name=args.model)
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
    if not os.environ.get("OPENROUTER_API_KEY"):
        parser.error(f"OPENROUTER_API_KEY is missing from the environment and {args.dotenv}")
    smoke = args.command == "smoke"
    if smoke:
        experiment = experiment.model_copy(
            update={
                "episodes": 1,
                "model": experiment.model.model_copy(
                    update={
                        "calls_per_turn": min(4, experiment.model.calls_per_turn),
                        "calls_per_episode": min(4, experiment.model.calls_per_episode),
                    }
                ),
            }
        )
    try:
        directory = asyncio.run(run_experiment(experiment, args.output, smoke=smoke))
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
