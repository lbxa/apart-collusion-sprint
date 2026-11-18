"""Enforce a UTC deadline for captured Collusion controllers without starting work.

Capture verifies operator launch receipts. Watch checks wall time after every
short sleep, including laptop wake, and signals only unchanged process identities.
It never edits campaign journals, releases holds, or restarts assignments.
"""

import argparse
import json
import os
import shlex
import signal
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

MODULE = "veracity_harness.campaign"
PHASES = {f"confirmation-{name}" for name in ("deepseek", "glm", "kimi", "gptoss", "inkling")}


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    process_group: int
    started: str
    module: str
    output: str


def utc_now():
    return datetime.now(UTC)


def read_process(pid: int) -> ProcessIdentity | None:
    result = subprocess.run(
        ["/bin/ps", "-ww", "-p", str(pid), "-o", "pid=,pgid=,lstart=,command="],
        capture_output=True,
        text=True,
        timeout=1,
        env={**os.environ, "LC_ALL": "C"},
    )
    if result.returncode == 1 and not result.stdout.strip():
        return None
    fields = result.stdout.strip().split(None, 7)
    if result.returncode != 0 or len(fields) != 8:
        raise ValueError("Process identity could not be read")
    arguments = shlex.split(fields[7])
    module, output = "", ""
    if arguments.count("-m") == 1:
        index = arguments.index("-m")
        if len(arguments) > index + 2 and arguments[index + 2] == "run":
            module = arguments[index + 1]
    if arguments.count("--output") == 1:
        index = arguments.index("--output")
        if len(arguments) > index + 1:
            output = arguments[index + 1]
    return ProcessIdentity(int(fields[0]), int(fields[1]), " ".join(fields[2:7]), module, output)


def validate_target(target: ProcessIdentity, study_root: Path):
    output = Path(target.output)
    if (
        type(target.pid) is not int
        or target.pid <= 1
        or type(target.process_group) is not int
        or target.process_group != target.pid
        or not target.started
        or target.module != MODULE
        or not output.is_absolute()
        or output.parent != study_root
        or output.name not in PHASES
    ):
        raise ValueError("Target is not a captured study controller")


def watch(targets: list[ProcessIdentity], deadline: datetime, record) -> int:
    pending = list(targets)

    def retain_owned():
        owned = []
        for target in pending:
            observed = read_process(target.pid)
            if observed == target:
                owned.append(target)
            else:
                record(
                    {
                        "event": "process_exited" if observed is None else "identity_changed",
                        "expected": asdict(target),
                        "observed": asdict(observed) if observed is not None else None,
                    }
                )
        return owned

    def send(target, signum):
        observed = read_process(target.pid)
        if observed != target:
            record(
                {
                    "event": "process_exited" if observed is None else "identity_changed",
                    "expected": asdict(target),
                    "observed": asdict(observed) if observed is not None else None,
                }
            )
            return False
        try:
            os.killpg(target.process_group, signum)
        except ProcessLookupError:
            record({"event": "process_exited", "expected": asdict(target), "observed": None})
            return False
        record(
            {
                "event": "sigterm_sent" if signum == signal.SIGTERM else "sigkill_sent",
                "signal": signum.name,
                "observed": asdict(observed),
            }
        )
        return True

    while pending and utc_now() < deadline:
        pending = retain_owned()
        remaining = (deadline - utc_now()).total_seconds()
        if pending and remaining > 0:
            time.sleep(min(1, remaining))
    if not pending:
        return 0
    pending = [target for target in pending if send(target, signal.SIGTERM)]
    if not pending:
        return 0
    cleanup_deadline = utc_now() + timedelta(seconds=5)
    while pending and utc_now() < cleanup_deadline:
        pending = retain_owned()
        remaining = (cleanup_deadline - utc_now()).total_seconds()
        if pending and remaining > 0:
            time.sleep(min(1, remaining))
    for target in pending:
        send(target, signal.SIGKILL)
    return 124


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="Read identities of already owned controllers")
    capture.add_argument("--study-root", type=Path, required=True)
    capture.add_argument("--suspension", type=Path, required=True)
    capture.add_argument("--targets", type=Path, required=True)
    run = commands.add_parser("watch", help="Wait for UTC deadline; never start or replay work")
    run.add_argument("--targets", type=Path, required=True)
    run.add_argument("--deadline", type=datetime.fromisoformat, required=True)
    run.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args(argv)
    os.umask(0o077)
    if args.command == "watch" and (
        args.deadline.tzinfo is None or args.deadline.utcoffset() != timedelta(0)
    ):
        parser.error("--deadline must be an absolute UTC timestamp")
    try:
        if args.command == "capture":
            root = args.study_root.resolve(strict=True)
            targets, exited = [], []
            for entry in json.loads(args.suspension.read_text()):
                pid, group, phase = entry["controller_pid"], entry["process_group"], entry["phase"]
                if type(pid) is not int or pid <= 1 or group != pid or phase not in PHASES:
                    raise ValueError("Invalid controller launch receipt")
                target = read_process(pid)
                if target is None:
                    exited.append(pid)
                    continue
                validate_target(target, root)
                if target.pid != pid or target.output != str(root / phase):
                    raise ValueError("Controller differs from launch receipt")
                targets.append(asdict(target))
            if len({target["pid"] for target in targets}) != len(targets):
                raise ValueError("Duplicate controller PID")
            with args.targets.open("x") as file:
                file.write(
                    json.dumps(
                        {
                            "format_version": 1,
                            "study_root": str(root),
                            "captured_utc": utc_now().isoformat(),
                            "targets": targets,
                            "exited_pids": exited,
                        },
                        sort_keys=True,
                    )
                    + "\n"
                )
            print(json.dumps({"event": "identities_captured", "count": len(targets)}), flush=True)
            return 0
        payload = json.loads(args.targets.read_text())
        if payload["format_version"] != 1:
            raise ValueError("Unsupported target manifest")
        root = Path(payload["study_root"])
        targets = [ProcessIdentity(**target) for target in payload["targets"]]
        for target in targets:
            validate_target(target, root)
        if len({target.pid for target in targets}) != len(targets):
            raise ValueError("Duplicate controller PID")

        def record(event):
            event = {"time_utc": utc_now().isoformat(), **event}
            serialized = json.dumps(event, sort_keys=True) + "\n"
            with args.receipt.open("a") as file:
                file.write(serialized)
            print(serialized, end="", flush=True)

        record(
            {
                "event": "guard_started",
                "deadline_utc": args.deadline.isoformat(),
                "targets": [asdict(target) for target in targets],
            }
        )
        result = watch(targets, args.deadline, record)
        record({"event": "guard_finished", "returncode": result})
        return result
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"event": "guard_failed", "error_type": type(error).__name__}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
