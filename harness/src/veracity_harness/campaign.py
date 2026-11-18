"""Immutable campaign assignments and at-most-once dispatch of financial worlds."""

import argparse
import asyncio
import fcntl
import hashlib
import json
import logging
import os
import socket
import sqlite3
import tomllib
from collections import Counter
from contextlib import ExitStack
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, model_validator

from . import materials
from .config import Experiment, Settings, load_experiment
from .runner import ROOT, run_experiment
from .spending import CampaignSpending

STATES = ("pending", "running", "complete", "failed", "interrupted")


def encoded(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class Assignment(Settings):
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,64}$")
    config: Path
    model: str | None = None
    provider: Literal["cloudflare", "openrouter"] | None = None
    seed: int | None = None


class CampaignPlan(Settings):
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    assignments: list[Assignment] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_assignments(self):
        if len({job.id for job in self.assignments}) != len(self.assignments):
            raise ValueError("Campaign assignment IDs must be unique")
        return self


class FrozenAssignment(Settings):
    id: str
    experiment: Experiment
    config_sha256: str
    inputs_sha256: dict[str, str]
    documents_sha256: dict[str, str]
    fingerprint: str


class FrozenCampaign(Settings):
    name: str
    fingerprint: str
    source_sha256: dict[str, str]
    budget_usd: str | None
    assignments: list[FrozenAssignment]


def source_identity() -> dict[str, str]:
    paths = [
        ROOT / name
        for name in (
            "harness/pyproject.toml",
            "harness/uv.lock",
            "Cargo.lock",
            "CONSTITUTION.md",
            "contracts/artifacts/Veracity.json",
            "target/debug/veracity-game-service",
        )
    ]
    for directory in ("harness/src", "harness/docker", "core/src", "contracts/src"):
        paths.extend(
            p
            for p in (ROOT / directory).rglob("*")
            if p.suffix in {".py", ".md", ".rs", ".sol"} or p.name == "Dockerfile"
        )
    return {
        str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in sorted(set(paths)) if p.is_file()
    }


def freeze_plan(path: Path, budget_usd: Decimal | None = None) -> FrozenCampaign:
    content = path.read_text()
    payload = json.loads(content) if path.suffix.casefold() == ".json" else tomllib.loads(content)
    plan = CampaignPlan.model_validate(payload)
    jobs = []
    for assignment in plan.assignments:
        config = (path.parent / assignment.config).resolve()
        experiment = load_experiment(
            config, model_name=assignment.model, provider=assignment.provider, seed=assignment.seed
        )
        paths = {
            p.resolve()
            for case in [*(experiment.schedule or [experiment.case]), *experiment.history]
            for p in (case.document, case.records)
            if p is not None
        }
        inputs = {str(p): digest(p.read_bytes()) for p in sorted(paths)}
        documents = {
            name: digest(text.encode())
            for name, text in materials.static_documents(experiment).items()
        }
        portable = experiment.model_dump(mode="json")
        for case in [*(portable["schedule"] or [portable["case"]]), *portable["history"]]:
            for key in ("document", "records"):
                if case.get(key):
                    original = case[key]
                    case[key] = {"name": Path(original).name, "sha256": inputs[original]}
        config_hash = digest(config.read_bytes())
        job_hash = digest(
            encoded(
                {
                    "id": assignment.id,
                    "config_sha256": config_hash,
                    "experiment": portable,
                    "documents": documents,
                }
            ).encode()
        )
        jobs.append(
            FrozenAssignment(
                id=assignment.id,
                experiment=experiment,
                config_sha256=config_hash,
                inputs_sha256=inputs,
                documents_sha256=documents,
                fingerprint=job_hash,
            )
        )
    payload = {
        "name": plan.name,
        "source_sha256": source_identity(),
        "budget_usd": str(budget_usd) if budget_usd is not None else None,
        "assignments": [job.model_dump(mode="json") for job in jobs],
    }
    identity = {**payload, "assignments": [job.fingerprint for job in jobs]}
    return FrozenCampaign(**payload, fingerprint=digest(encoded(identity).encode()))


def verify_inputs(frozen: FrozenCampaign) -> None:
    if source_identity() != frozen.source_sha256:
        raise ValueError("Campaign source inputs changed after freezing")
    for job in frozen.assignments:
        if any(digest(Path(path).read_bytes()) != sha for path, sha in job.inputs_sha256.items()):
            raise ValueError("Campaign case inputs changed after freezing")
        documents = {
            name: digest(text.encode())
            for name, text in materials.static_documents(job.experiment).items()
        }
        if documents != job.documents_sha256:
            raise ValueError("Campaign participant document inputs changed after freezing")


def materialize_inputs(job: FrozenAssignment, directory: Path) -> Experiment:
    """Hand the runner verified private copies, rather than mutable task-bank files."""
    copies = {}
    for original, sha in job.inputs_sha256.items():
        data = Path(original).read_bytes()
        if digest(data) != sha:
            raise ValueError("Campaign inputs changed before dispatch")
        target = directory / sha / Path(original).name
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(data)
        copies[original] = target

    def copied(case):
        return case.model_copy(
            update={
                "document": copies[str(case.document)],
                "records": copies[str(case.records)] if case.records is not None else None,
            }
        )

    experiment = job.experiment
    return experiment.model_copy(
        update={
            "case": copied(experiment.case) if experiment.case else None,
            "schedule": [copied(case) for case in experiment.schedule],
            "history": [copied(case) for case in experiment.history],
        }
    )


class CampaignLock:
    """One controller owns recovery and dispatch; status readers never recover jobs."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.file = None

    def __enter__(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.file = (self.directory / ".campaign.lock").open("a+b")
        os.fchmod(self.file.fileno(), 0o600)
        try:
            fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.file.close()
            raise RuntimeError("A campaign controller already owns this directory") from None
        return self

    def __exit__(self, *_):
        self.file.close()


class CampaignJournal:
    """SQLite is authoritative; terminal assignments can never be reset or replaced."""

    def __init__(
        self, path: Path, frozen: FrozenCampaign | None = None, ledger: Path | None = None
    ):
        self.path = path.resolve()
        if frozen is None:
            if not self.path.is_file():
                raise FileNotFoundError("Campaign journal does not exist")
            return
        with sqlite3.connect(self.path) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, position INTEGER NOT NULL, "
                "status TEXT NOT NULL, run_directory TEXT, run_id TEXT, error_type TEXT)"
            )
            db.execute("BEGIN IMMEDIATE")
            current = dict(db.execute("SELECT key,value FROM metadata"))
            if current:
                if current["fingerprint"] != frozen.fingerprint:
                    raise ValueError(
                        "A frozen campaign cannot change its plan, source, inputs or cap"
                    )
                if current["ledger"] != str(ledger.resolve()):
                    raise ValueError("A campaign cannot replace its shared spending ledger")
            else:
                db.executemany(
                    "INSERT INTO metadata VALUES (?,?)",
                    [
                        ("campaign_id", frozen.name + "-" + frozen.fingerprint[:16]),
                        ("fingerprint", frozen.fingerprint),
                        ("ledger", str(ledger.resolve())),
                        ("frozen", frozen.model_dump_json()),
                        ("spending", "{}"),
                    ],
                )
                db.executemany(
                    "INSERT INTO jobs VALUES (?,?,'pending',NULL,NULL,NULL)",
                    [(job.id, i) for i, job in enumerate(frozen.assignments)],
                )

    def record_controller(self, dispatch_limit_usd: Decimal | None = None) -> None:
        with sqlite3.connect(self.path) as db:
            row = db.execute("SELECT value FROM metadata WHERE key='controllers'").fetchone()
            controllers = json.loads(row[0]) if row else []
            controllers.append(
                {
                    "runner": socket.gethostname(),
                    "started_at": datetime.now(UTC).isoformat(),
                    "status": "running",
                    "dispatch_limit_usd": (
                        str(dispatch_limit_usd) if dispatch_limit_usd is not None else None
                    ),
                    "dispatch_stop_reason": None,
                }
            )
            db.execute(
                "INSERT OR REPLACE INTO metadata VALUES ('controllers',?)", (encoded(controllers),)
            )

    def finish_controller(self, status: str, dispatch_stop_reason: str | None) -> None:
        with sqlite3.connect(self.path) as db:
            controllers = json.loads(
                db.execute("SELECT value FROM metadata WHERE key='controllers'").fetchone()[0]
            )
            controllers[-1].update(
                status=status,
                dispatch_stop_reason=dispatch_stop_reason,
                finished_at=datetime.now(UTC).isoformat(),
            )
            db.execute(
                "UPDATE metadata SET value=? WHERE key='controllers'", (encoded(controllers),)
            )

    def recover_running(self) -> None:
        with sqlite3.connect(self.path) as db:
            db.execute(
                "UPDATE jobs SET status='interrupted',error_type='ControllerInterrupted' "
                "WHERE status='running'"
            )

    def claim(self, identity: str, directory: Path) -> bool:
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT status FROM jobs WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise ValueError("Unknown assignment")
            if row[0] != "pending":
                return False
            db.execute(
                "UPDATE jobs SET status='running',run_directory=? WHERE id=?",
                (str(directory.resolve()), identity),
            )
            return True

    def finish(
        self,
        identity: str,
        status: str,
        *,
        run_id: str | None = None,
        error_type: str | None = None,
    ) -> None:
        if status not in {"complete", "failed", "interrupted"}:
            raise ValueError("Unknown terminal assignment status")
        with sqlite3.connect(self.path) as db:
            updated = db.execute(
                "UPDATE jobs SET status=?,run_id=?,error_type=? WHERE id=? AND status='running'",
                (status, run_id, error_type, identity),
            )
            if updated.rowcount != 1:
                raise ValueError("A terminal assignment cannot be replaced")

    def snapshot(self, spending: dict | None = None) -> dict:
        if spending is not None:
            with sqlite3.connect(self.path) as db:
                db.execute("UPDATE metadata SET value=? WHERE key='spending'", (encoded(spending),))
        with sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True) as db:
            metadata = dict(db.execute("SELECT key,value FROM metadata"))
            jobs = [
                dict(
                    zip(("id", "status", "run_directory", "run_id", "error_type"), row, strict=True)
                )
                for row in db.execute(
                    "SELECT id,status,run_directory,run_id,error_type FROM jobs ORDER BY position"
                )
            ]
        counts = Counter(job["status"] for job in jobs)
        controllers = json.loads(metadata.get("controllers", "[]"))
        controller = controllers[-1] if controllers else {}
        frozen = FrozenCampaign.model_validate_json(metadata["frozen"])
        hashes = {job.id: job for job in frozen.assignments}
        for job in jobs:
            job["config_sha256"] = hashes[job["id"]].config_sha256
            job["assignment_sha256"] = hashes[job["id"]].fingerprint
        return {
            "campaign_id": metadata["campaign_id"],
            "fingerprint": metadata["fingerprint"],
            "runner": controllers[-1]["runner"] if controllers else None,
            "controllers": controllers,
            "controller_status": controller.get("status"),
            "dispatch_limit_usd": controller.get("dispatch_limit_usd"),
            "dispatch_stop_reason": controller.get("dispatch_stop_reason"),
            "updated_at": datetime.now(UTC).isoformat(),
            "source_sha256": frozen.source_sha256,
            "counts": {state: counts[state] for state in STATES},
            "assignments": jobs,
            "spending": json.loads(metadata["spending"]),
        }


async def run_campaign(
    frozen,
    output,
    spending,
    *,
    runner=run_experiment,
    observer=None,
    dispatch_limit_usd: Decimal | None = None,
):
    """Resume pending assignments only. A started world is never automatically replayed."""
    output = output.resolve()
    with CampaignLock(output):
        verify_inputs(frozen)
        spending = spending() if callable(spending) else spending
        if frozen.budget_usd != str(spending.limit):
            raise ValueError("The frozen campaign cap must match the shared ledger")
        if dispatch_limit_usd is not None and (
            not dispatch_limit_usd.is_finite()
            or dispatch_limit_usd <= 0
            or dispatch_limit_usd > spending.limit
        ):
            raise ValueError(
                "Campaign dispatch limit must be finite, positive and within ledger cap"
            )
        journal = CampaignJournal(output / "campaign.sqlite", frozen, spending.path)
        journal.recover_running()
        journal.record_controller(dispatch_limit_usd)
        dispatch_stop_reason = None
        observer_stack = ExitStack()
        tracking_error = None
        tracking_closed = False
        try:
            observer = observer() if callable(observer) else observer
            if observer is not None and hasattr(observer, "__enter__"):
                observer = observer_stack.enter_context(observer)
        except Exception as error:
            tracking_error = type(error).__name__
            observer = None
            logging.warning("campaign tracking degraded error_type=%s", tracking_error)

        def publish():
            nonlocal observer, tracking_error
            snapshot = journal.snapshot(spending.snapshot())
            snapshot["tracking_status"] = (
                "degraded"
                if tracking_error
                else "finished"
                if tracking_closed
                else "active"
                if observer
                else "disabled"
            )
            if tracking_error:
                snapshot["tracking_error_type"] = tracking_error
            temporary = output / "progress.json.tmp"
            temporary.write_text(encoded(snapshot) + "\n")
            temporary.replace(output / "progress.json")
            if observer is not None:
                try:
                    observer.publish(snapshot)
                except Exception as error:
                    tracking_error = type(error).__name__
                    observer = None
                    logging.warning("campaign tracking degraded error_type=%s", tracking_error)
                    return publish()
            return snapshot

        async def heartbeat():
            while True:
                await asyncio.sleep(10)
                publish()

        pulse = asyncio.create_task(heartbeat())
        try:
            publish()
            pending = {
                job["id"] for job in journal.snapshot()["assignments"] if job["status"] == "pending"
            }
            for job in frozen.assignments:
                if job.id not in pending:
                    continue
                verify_inputs(frozen)
                directory = output / "jobs" / job.id
                if (
                    dispatch_limit_usd is not None
                    and Decimal(spending.snapshot()["accounted_usd"]) >= dispatch_limit_usd
                ):
                    dispatch_stop_reason = "dispatch_limit_reached"
                    logging.info("campaign dispatch stopped reason=%s", dispatch_stop_reason)
                    break
                if not journal.claim(job.id, directory):
                    continue
                publish()
                try:
                    experiment = materialize_inputs(job, output / "frozen-inputs" / job.id)
                    run = await runner(experiment, directory, spending=spending)
                    manifest = json.loads((run / "run.json").read_text())
                    journal.finish(
                        job.id,
                        "complete" if manifest["status"] == "complete" else "failed",
                        run_id=manifest.get("run_id", run.name),
                    )
                except BaseException as error:
                    manifests = list(directory.glob("run-*/run.json"))
                    run_id = manifests[0].parent.name if len(manifests) == 1 else None
                    journal.finish(
                        job.id,
                        "failed" if isinstance(error, Exception) else "interrupted",
                        run_id=run_id,
                        error_type=type(error).__name__,
                    )
                    if not isinstance(error, Exception):
                        raise
                finally:
                    publish()
        finally:
            pulse.cancel()
            try:
                await pulse
            except asyncio.CancelledError:
                pass
            counts = journal.snapshot()["counts"]
            if counts["interrupted"] or counts["running"]:
                controller_status = "interrupted"
            elif counts["failed"]:
                controller_status = "failed"
            elif counts["pending"]:
                controller_status = "budget_stopped" if dispatch_stop_reason else "interrupted"
            else:
                controller_status = "complete"
            journal.finish_controller(controller_status, dispatch_stop_reason)
            publish()
            try:
                if observer is not None and hasattr(observer, "close"):
                    observer.close(controller_status)
                observer_stack.close()
                tracking_closed = observer is not None
                observer = None
            except Exception as error:
                tracking_error = type(error).__name__
                observer = None
                logging.warning("campaign tracking degraded error_type=%s", tracking_error)
            publish()
        return publish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("validate", "status", "run"))
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "harness/results/campaign")
    parser.add_argument("--dotenv", type=Path, default=ROOT / ".env")
    parser.add_argument("--budget-ledger", type=Path)
    parser.add_argument("--budget-usd", type=Decimal)
    parser.add_argument(
        "--dispatch-limit-usd",
        type=Decimal,
        help="Stop new assignments at this cumulative accounted spend, including unresolved holds",
    )
    parser.add_argument(
        "--wandb", action="store_true", help="Opt in to live, scoped progress tracking"
    )
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.command == "status":
            print(encoded(CampaignJournal(args.output / "campaign.sqlite").snapshot()))
            return
        if args.plan is None:
            parser.error("--plan is required")
        frozen = freeze_plan(args.plan, args.budget_usd)
        if args.command == "validate":
            print(
                encoded(
                    {
                        "name": frozen.name,
                        "fingerprint": frozen.fingerprint,
                        "assignments": len(frozen.assignments),
                        "source_sha256": frozen.source_sha256,
                    }
                )
            )
            return
        if args.budget_ledger is None or args.budget_usd is None:
            parser.error("Run requires --budget-ledger and --budget-usd")
        load_dotenv(args.dotenv, override=False)
        for job in frozen.assignments:
            names = (
                ("CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_API_TOKEN")
                if job.experiment.model.provider == "cloudflare"
                else ("OPENROUTER_API_KEY",)
            )
            if any(not os.environ.get(name) for name in names):
                parser.error("Selected provider credentials are missing")
        observer = None
        if args.wandb:
            from .tracking import LiveCampaignTracking, resolve_scope, verify_access

            scope = resolve_scope(args.dotenv)
            verify_access(scope)

            def observer():
                return LiveCampaignTracking(
                    scope, frozen.name + "-" + frozen.fingerprint[:16], args.output
                )

        snapshot = asyncio.run(
            run_campaign(
                frozen,
                args.output,
                lambda: CampaignSpending(args.budget_ledger.resolve(), args.budget_usd),
                observer=observer,
                dispatch_limit_usd=args.dispatch_limit_usd,
            )
        )
        print(encoded(snapshot))
        if snapshot["counts"]["failed"] + snapshot["counts"]["interrupted"]:
            raise SystemExit(1)
        if snapshot["controller_status"] == "budget_stopped":
            raise SystemExit(3)
    except (ValueError, OSError, RuntimeError) as error:
        parser.error(
            f"Campaign operation failed ({type(error).__name__}); inspect local progress and inputs"
        )


if __name__ == "__main__":
    main()
