"""Run one frozen local campaign with an explicitly selected operator time policy.

Supply the target harness virtualenv Python when invoking this operator script.
It never restarts work; campaign.py owns assignments, recovery and spending holds.
"""

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from dotenv import dotenv_values

PROVIDER_KEYS = ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN")
TRACKING_KEYS = ("WANDB_API_KEY", "WANDB_ENTITY", "WANDB_PROJECT", "WANDB_BASE_URL")


def campaign_environment(provider_file: Path, tracking_file: Path, runtime: Path):
    """Keep provider process overrides, but take tracking identity only from its file."""
    provider = dotenv_values(provider_file, interpolate=False)
    tracking = dotenv_values(tracking_file, interpolate=False)
    environment = {key: value for key, value in os.environ.items() if not key.startswith("WANDB_")}
    for key in PROVIDER_KEYS:
        environment[key] = os.environ.get(key) or provider.get(key) or ""
    for key in TRACKING_KEYS:
        if tracking.get(key):
            environment[key] = tracking[key]
    if any(not environment[key] for key in PROVIDER_KEYS):
        raise ValueError("Selected provider credentials are missing")
    environment["PYTHONPATH"] = str(runtime / "harness/src")
    environment["PYTHONUNBUFFERED"] = "1"
    return environment


def stop_campaign(child):
    """Interrupt only the new session we own; leave campaign recovery records intact."""
    if child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGINT)
        except ProcessLookupError:
            pass
    try:
        return child.wait(timeout=60)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return child.wait(timeout=5)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in (
        "runtime-root",
        "python",
        "provider-env",
        "tracking-env",
        "plan",
        "output",
        "budget-ledger",
    ):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--budget-usd", type=Decimal, default=Decimal(100))
    parser.add_argument("--dispatch-limit-usd", type=Decimal, required=True)
    time_policy = parser.add_mutually_exclusive_group(required=True)
    time_policy.add_argument(
        "--deadline",
        type=datetime.fromisoformat,
        help="Absolute UTC time; at most eight hours ahead",
    )
    time_policy.add_argument(
        "--no-deadline", action="store_true", help="Wait until assigned work or budget ends"
    )
    parser.add_argument("--wandb", action="store_true")
    parser.add_argument(
        "--caffeinate", action="store_true", help="Prevent idle sleep while the child runs"
    )
    args = parser.parse_args(argv)
    os.umask(0o077)
    now = datetime.now(UTC)
    if args.deadline is not None:
        if args.deadline.tzinfo is None or args.deadline.utcoffset() != timedelta(0):
            parser.error("--deadline must include UTC timezone information")
        if args.deadline > now + timedelta(hours=8):
            parser.error("--deadline cannot exceed eight hours from launch")
    budget, limit = args.budget_usd, args.dispatch_limit_usd
    if not budget.is_finite() or budget <= 0:
        parser.error("--budget-usd must be positive and finite")
    if not limit.is_finite() or not Decimal(0) < limit <= budget:
        parser.error("--dispatch-limit-usd must be positive and at most --budget-usd")
    if args.deadline is not None and args.deadline <= now:
        print('{"outcome":"deadline_expired","child_started":false}', flush=True)
        return 124
    child = caffeine = None
    metadata = None
    outcome = "failed"
    returncode = 1
    try:
        runtime = args.runtime_root.resolve(strict=True)
        if not (runtime / "harness/src/veracity_harness/campaign.py").is_file():
            raise ValueError("Frozen runtime is missing the campaign module")
        if not args.python.is_file() or not args.plan.is_file():
            raise ValueError("Python executable or plan is missing")
        if not args.provider_env.is_file() or not args.tracking_env.is_file():
            raise ValueError("Selected operator environment file is missing")
        environment = campaign_environment(args.provider_env, args.tracking_env, runtime)
        if args.wandb and not environment.get("WANDB_API_KEY"):
            raise ValueError("Selected tracking file has no W&B key")
        args.output.mkdir(parents=True, exist_ok=True, mode=0o700)
        metadata_path = args.output / "local-run.json"
        metadata = {
            "child_pid": None,
            "plan_sha256": hashlib.sha256(args.plan.read_bytes()).hexdigest(),
            "launcher_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "deadline_utc": args.deadline.isoformat() if args.deadline is not None else None,
            "time_policy": "none" if args.no_deadline else "deadline",
            "started_utc": now.isoformat(),
            "outcome": "starting",
        }
        metadata_path.write_text(json.dumps(metadata, sort_keys=True) + "\n")
        command = [
            str(args.python.absolute()),
            "-m",
            "veracity_harness.campaign",
            "run",
            "--plan",
            str(args.plan.resolve()),
            "--output",
            str(args.output.resolve()),
            "--budget-ledger",
            str(args.budget_ledger.resolve()),
            "--budget-usd",
            str(budget),
            "--dispatch-limit-usd",
            str(limit),
            "--dotenv",
            str(args.tracking_env.resolve()),
        ]
        if args.wandb:
            command.append("--wandb")
        child = subprocess.Popen(
            command,
            cwd=runtime,
            env=environment,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        metadata.update(child_pid=child.pid, outcome="running")
        metadata_path.write_text(json.dumps(metadata, sort_keys=True) + "\n")
        print(json.dumps({"outcome": "running", "child_pid": child.pid}), flush=True)
        if args.caffeinate and (executable := shutil.which("caffeinate")):
            caffeine = subprocess.Popen(
                [executable, "-i", "-w", str(child.pid)], stdin=subprocess.DEVNULL
            )
        try:
            if args.no_deadline:
                returncode = child.wait()
            else:
                remaining = max(0, (args.deadline - datetime.now(UTC)).total_seconds())
                returncode = child.wait(timeout=remaining)
            outcome = {0: "complete", 3: "budget_stopped"}.get(returncode, "child_failed")
        except subprocess.TimeoutExpired:
            stop_campaign(child)
            outcome, returncode = "deadline", 124
        except KeyboardInterrupt:
            stop_campaign(child)
            outcome, returncode = "interrupted", 130
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"outcome": "failed", "error_type": type(error).__name__}), flush=True)
    finally:
        if child is not None and child.poll() is None:
            stop_campaign(child)
        if caffeine is not None and caffeine.poll() is None:
            caffeine.terminate()
            try:
                caffeine.wait(timeout=5)
            except subprocess.TimeoutExpired:
                caffeine.kill()
                caffeine.wait(timeout=5)
        if metadata is not None:
            metadata.update(
                outcome=outcome,
                returncode=returncode,
                finished_utc=datetime.now(UTC).isoformat(),
            )
            metadata_path.write_text(json.dumps(metadata, sort_keys=True) + "\n")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())
