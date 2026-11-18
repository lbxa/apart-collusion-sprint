"""Snapshot explicitly selected campaign evidence into a private W&B audit artifact.

No inference, campaign dispatch, database upload, or source-evidence mutation occurs.
Each snapshot records source and export hashes. Its receipt identifies the SDK
download-cache policy used with SDK-manifest and full SHA256 verification.
"""

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, model_validator

from veracity_harness import tracking

MANIFEST = "archive-manifest.json"
SCHEMA = "collusion-private-audit-v2"
JOB_STATUSES = ("pending", "running", "complete", "failed", "interrupted")
STOPPED_CONTROLLERS = frozenset({"complete", "failed", "interrupted", "budget_stopped"})
SOURCE_ROOTS = (
    "core/src",
    "contracts/src",
    "harness/src",
    "harness/docker",
    "harness/research/collusion-resistance-v1",
)
SOURCE_FILES = (
    "CONSTITUTION.md",
    "Cargo.toml",
    "Cargo.lock",
    "rust-toolchain.toml",
    ".foundry-version",
    "harness/pyproject.toml",
    "harness/uv.lock",
    "contracts/artifacts/Veracity.json",
    "core/Cargo.toml",
    "harness/README.md",
)
CAMPAIGN_FILES = (
    "progress.json",
    "local-run.json",
    "runtime-snapshot.json",
    "assignment-register.json",
    "pilot-first-plan.json",
    "pilot-rest-plan.json",
    "preflight-verification.json",
    "numeric.json",
    "numeric.csv",
    "case-observations.json",
    "review-schemas.json",
)
URL_FIELDS = {"base_url", "openai_api_base", "api_base", "url", "request_url", "endpoint"}
SEMANTIC_FIELDS = {
    "messages",
    "content",
    "text",
    "reasoning_content",
    "reasoning",
    "tool_calls",
    "function_call",
    "args",
    "arguments",
    "observation",
    "command",
    "stdout",
    "stderr",
}
FORBIDDEN_PARTS = {".git", "wandb", "__pycache__", ".venv", "gateway", "wallets"}


class AuditRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class Redaction(AuditRecord):
    field: str = Field(min_length=1)
    kind: Literal["cloudflare_account_id"]


class AuditFile(AuditRecord):
    path: str = Field(min_length=1)
    original_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    export_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    bytes: int = Field(ge=0)
    redactions: list[Redaction]


class AuditRun(AuditRecord):
    path: str
    run_id: str = Field(pattern=r"^run-[A-Za-z0-9_-]+$")
    status: Literal["running", "complete", "failed", "interrupted"]


class AuditAssignment(AuditRecord):
    phase: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    assignment_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    status: Literal["pending", "running", "complete", "failed", "interrupted", "unassigned"]
    run_paths: list[str]
    gaps: list[str]


class AuditManifest(AuditRecord):
    schema_version: Literal["collusion-private-audit-v2"] = Field(alias="schema")
    created_utc: str
    status: Literal["partial", "complete", "failed", "interrupted"]
    phase_statuses: dict[str, Literal["pending", "running", "complete", "failed", "incomplete"]]
    phase_gaps: dict[str, list[str]]
    source_gaps: list[str]
    assignments: list[AuditAssignment]
    runs: list[AuditRun]
    files: list[AuditFile]
    excluded: list[str]
    content_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_inventory(self):
        captured = datetime.fromisoformat(self.created_utc)
        if captured.tzinfo is None or captured.utcoffset() != timedelta(0):
            raise ValueError("Archive capture time must be UTC")
        file_paths = [row.path for row in self.files]
        run_paths = [row.path for row in self.runs]
        run_ids = [row.run_id for row in self.runs]
        assignment_keys = [(row.phase, row.assignment_id) for row in self.assignments]
        for entries in (file_paths, run_paths, run_ids, assignment_keys):
            if len(entries) != len(set(entries)):
                raise ValueError("Archive inventory requires unique paths and identities")
        for value in [*file_paths, *run_paths]:
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or str(path) != value:
                raise ValueError("Unsafe or noncanonical archive path")
        for row in self.runs:
            if Path(row.path).name != row.run_id or f"runs/{row.path}/run.json" not in file_paths:
                raise ValueError("Archive run identity is missing its matching manifest")
        for row in self.assignments:
            if len(row.run_paths) != len(set(row.run_paths)) or not set(row.run_paths) <= set(
                run_paths
            ):
                raise ValueError("Assignment run paths must be unique retained runs")
            if any(
                Path(path).parent != Path(row.phase) / "jobs" / row.assignment_id
                for path in row.run_paths
            ):
                raise ValueError("Assignment runs must belong to its canonical job directory")
            if row.status in {"failed", "interrupted"} and not row.run_paths and not row.gaps:
                raise ValueError("Missing terminal assignment runs require explicit evidence gaps")
            if row.status == "complete" and not row.gaps and len(row.run_paths) != 1:
                raise ValueError("A gap-free complete assignment requires exactly one run")
        phases = set(self.phase_statuses)
        if (
            any(not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", phase) for phase in phases)
            or not set(self.phase_gaps) <= phases
            or not {row.phase for row in self.assignments} <= phases
        ):
            raise ValueError("Archive phase inventory is inconsistent")
        for phase, status in self.phase_statuses.items():
            rows = [row for row in self.assignments if row.phase == phase]
            if status == "complete" and (
                not rows
                or self.phase_gaps.get(phase)
                or any(row.status != "complete" or row.gaps for row in rows)
            ):
                raise ValueError("A complete phase requires reconciled complete assignments")
        if self.status == "complete" and (
            not self.assignments
            or not self.phase_statuses
            or {row.phase for row in self.assignments} != phases
            or any(status != "complete" for status in self.phase_statuses.values())
            or any(self.phase_gaps.values())
            or self.source_gaps
            or any(row.status != "complete" for row in self.runs)
            or any(
                row.status != "complete" or row.gaps or len(row.run_paths) != 1
                for row in self.assignments
            )
        ):
            raise ValueError("A complete archive requires reconciled terminal assignments and runs")
        return self


def content_sha256(manifest: dict) -> str:
    """Canonical evidence/status identity; capture time does not create another version."""
    keys = (
        "schema",
        "status",
        "phase_statuses",
        "phase_gaps",
        "source_gaps",
        "assignments",
        "runs",
        "files",
    )
    return hashlib.sha256(
        json.dumps({key: manifest[key] for key in keys}, sort_keys=True).encode()
    ).hexdigest()


def complete_run_gaps(run: Path, *, require_complete: bool = True) -> list[str]:
    """Check terminal runner identity, expected episode count, and retained episode evidence."""
    gaps = []
    try:
        manifest = json.loads((run / "run.json").read_bytes())
        if manifest.get("run_id") != run.name:
            gaps.append("run_identity_mismatch")
        if require_complete and manifest.get("status") != "complete":
            gaps.append("run_not_complete")
            return gaps
        config, episodes = manifest.get("config"), manifest.get("episodes")
        expected = config.get("episodes") if isinstance(config, dict) else None
        if type(expected) is not int or expected < 1 or not isinstance(episodes, list):
            return [*gaps, "episode_inventory_invalid"]
        if len(episodes) != expected:
            gaps.append("episode_count_mismatch")
        seen = set()
        for row in episodes:
            episode_id = row.get("episode_id") if isinstance(row, dict) else None
            if not isinstance(episode_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", episode_id):
                gaps.append("episode_identity_invalid")
                continue
            if episode_id in seen:
                gaps.append("duplicate_episode_identity")
            seen.add(episode_id)
            evidence_path, summary_path = (
                run / episode_id / "evidence.json",
                run / episode_id / "summary.json",
            )
            if not safe_file(evidence_path, run) or not safe_file(summary_path, run):
                gaps.append("episode_evidence_missing")
                continue
            evidence, summary = (
                json.loads(evidence_path.read_bytes()),
                json.loads(summary_path.read_bytes()),
            )
            episode = evidence.get("episode")
            if not isinstance(episode, dict) or episode.get("episode_id") != episode_id:
                gaps.append("episode_evidence_identity_mismatch")
                continue
            outcome = row.get("outcome")
            if (
                summary != row
                or episode.get("phase") != outcome
                or outcome not in {"SETTLED_CREATOR", "SETTLED_CHALLENGER", "ABORTED"}
            ):
                gaps.append("episode_summary_identity_mismatch")
            if not {"settlement", "balances", "private_transcripts"} <= evidence.keys():
                gaps.append("episode_evidence_incomplete")
            for key in ("settlement", "balances"):
                if (
                    not isinstance(evidence.get(key), dict)
                    or evidence[key].get("episode_id") != episode_id
                ):
                    gaps.append(key + "_identity_mismatch")
            if config.get("treatment", {}).get("transfers") is True and not isinstance(
                evidence.get("credit_transfers"), list
            ):
                gaps.append("credit_transfers_missing")
            required = ["opportunities.jsonl", "gateway-audit/access.jsonl"]
            if config.get("scripted_setup_first") is True:
                required.append("scripted-setup.jsonl")
            models = manifest.get("models")
            if not isinstance(models, dict) or not models:
                gaps.append("actor_model_inventory_missing")
            else:
                for actor in models:
                    if not isinstance(actor, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", actor):
                        gaps.append("actor_identity_invalid")
                        continue
                    required.extend((f"{actor}.trace.jsonl", f"{actor}.trace.calls.jsonl"))
            for name in required:
                if not safe_file(run / episode_id / name, run):
                    gaps.append("execution_evidence_missing:" + name)
            for key in ("forum_transcript", "chat_audit", "forum_audit"):
                pages = evidence.get(key)
                if (
                    not isinstance(pages, list)
                    or not pages
                    or any(
                        not isinstance(page, dict)
                        or page.get("episode_id") != episode_id
                        or not isinstance(
                            page.get("messages" if key == "forum_transcript" else "events"), list
                        )
                        for page in pages
                    )
                    or pages[-1].get("has_more") is not False
                ):
                    gaps.append(key + "_incomplete")
            transcripts = evidence.get("private_transcripts")
            if not isinstance(transcripts, dict):
                gaps.append("private_transcripts_incomplete")
            else:
                for chat_id, transcript in transcripts.items():
                    chat = transcript.get("chat", {}) if isinstance(transcript, dict) else {}
                    pages = transcript.get("pages") if isinstance(transcript, dict) else None
                    if (
                        chat.get("chat_id") != chat_id
                        or chat.get("episode_id") != episode_id
                        or not isinstance(pages, list)
                        or not pages
                        or any(
                            not isinstance(page, dict)
                            or page.get("chat_id") != chat_id
                            or not isinstance(page.get("messages"), list)
                            for page in pages
                        )
                        or pages[-1].get("has_more") is not False
                    ):
                        gaps.append("private_transcripts_incomplete")
    except (OSError, ValueError, TypeError, AttributeError):
        gaps.append("run_or_episode_evidence_unreadable")
    return sorted(set(gaps))


def reconcile_phase(root: Path, progress: dict) -> tuple[str, list[dict], list[str]]:
    """Bind declared assignments to canonical job directories and terminal evidence."""
    phase_gaps, rows = [], []
    assignments, counts = progress.get("assignments"), progress.get("counts")
    if (
        not isinstance(counts, dict)
        or set(counts) != set(JOB_STATUSES)
        or any(type(value) is not int or value < 0 for value in counts.values())
    ):
        return "incomplete", [], ["assignment_counts_invalid"]
    if not isinstance(assignments, list) or not assignments:
        return "incomplete", [], ["assignment_rows_missing"]
    seen = set()
    observed = Counter()
    for assignment in assignments:
        if not isinstance(assignment, dict):
            phase_gaps.append("assignment_row_invalid")
            continue
        identity, status = assignment.get("id"), assignment.get("status")
        if (
            not isinstance(identity, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity)
            or status not in JOB_STATUSES
            or identity in seen
        ):
            phase_gaps.append("assignment_identity_or_status_invalid")
            continue
        seen.add(identity)
        observed[status] += 1
        job = root / "jobs" / identity
        directories = [path for path in sorted(job.glob("run-*")) if path.is_dir()]
        manifests = sorted(job.glob("run-*/run.json"))
        gaps = []
        supplied = assignment.get("run_directory")
        if status != "pending" and (not isinstance(supplied, str) or Path(supplied) != job):
            gaps.append("assignment_directory_mismatch")
        retained = [str(path.parent.relative_to(root.parent)) for path in manifests]
        run_id = assignment.get("run_id")
        if status == "pending" and manifests:
            gaps.append("pending_assignment_has_run")
        elif status == "complete":
            if len(directories) != 1 or len(manifests) != 1:
                gaps.append("complete_assignment_run_count_mismatch")
            elif run_id != manifests[0].parent.name:
                gaps.append("assignment_run_identity_mismatch")
            else:
                gaps.extend(complete_run_gaps(manifests[0].parent))
        elif status in {"failed", "interrupted"}:
            if not manifests:
                gaps.append("terminal_assignment_run_missing")
            elif len(manifests) != 1 or run_id != manifests[0].parent.name:
                gaps.append("terminal_assignment_run_identity_mismatch")
            else:
                run = json.loads(manifests[0].read_bytes())
                if run.get("run_id") != run_id or run.get("status") not in {
                    "failed",
                    "interrupted",
                }:
                    gaps.append("terminal_assignment_run_not_terminal")
                gaps.extend(complete_run_gaps(manifests[0].parent, require_complete=False))
        rows.append(
            {
                "phase": root.name,
                "assignment_id": identity,
                "status": status,
                "run_paths": retained,
                "gaps": sorted(set(gaps)),
            }
        )
    if dict.fromkeys(JOB_STATUSES, 0) | dict(observed) != counts:
        phase_gaps.append("assignment_counts_mismatch")
    for job in sorted((root / "jobs").glob("*")):
        if job.is_dir() and job.name not in seen and list(job.glob("run-*/run.json")):
            rows.append(
                {
                    "phase": root.name,
                    "assignment_id": job.name,
                    "status": "unassigned",
                    "run_paths": [
                        str(path.parent.relative_to(root.parent))
                        for path in sorted(job.glob("run-*/run.json"))
                    ],
                    "gaps": ["retained_run_has_no_assignment"],
                }
            )
    if phase_gaps or any(row["gaps"] for row in rows):
        state = "incomplete"
    elif counts["pending"] or counts["running"]:
        state = "running"
    else:
        state = "failed" if counts["failed"] or counts["interrupted"] else "complete"
    return state, rows, sorted(set(phase_gaps))


def safe_file(path: Path, root: Path) -> bool:
    """Exclude recovery/authentication state, and never traverse linked parents."""
    relative = path.relative_to(root)
    return (
        path.is_file()
        and not any((root / parent).is_symlink() for parent in (relative, *relative.parents))
        and not set(relative.parts) & FORBIDDEN_PARTS
        and not path.name.startswith(".env")
        and not path.name.endswith(
            (
                *tracking.LOCAL_ONLY[1:],
                ".sqlite3",
                ".sqlite3-wal",
                ".sqlite3-shm",
                ".key",
                ".pem",
                ".p12",
            )
        )
        and not any(word in path.name.casefold() for word in ("wallet", "private-key", "secret"))
        and path.name not in {tracking.MARKER, tracking.UPLOAD_INTENT, "policy.json"}
        and not path.name.endswith(".tmp")
    )


def export_bytes(data: bytes, suffix: str, needles: tuple[str, ...], account_ids: tuple[str, ...]):
    """Only redact noncredential account IDs inside named transport metadata fields."""
    redactions = []
    original = data
    accounts = tuple(account for account in account_ids if account and account.encode() in data)
    if accounts and suffix in {".json", ".jsonl"}:

        def redact(value, locator=""):
            if isinstance(value, dict):
                result = {}
                for key, child in value.items():
                    field = f"{locator}.{key}" if locator else key
                    if key in SEMANTIC_FIELDS:
                        result[key] = child
                        continue
                    if key in URL_FIELDS and isinstance(child, str):
                        for account in accounts:
                            if account in child:
                                child = child.replace(account, "[CLOUDFLARE_ACCOUNT_ID]")
                                redactions.append({"field": field, "kind": "cloudflare_account_id"})
                    result[key] = redact(child, field)
                return result
            if isinstance(value, list):
                return [redact(child, f"{locator}[{index}]") for index, child in enumerate(value)]
            return value

        try:
            if suffix == ".jsonl":
                values = [
                    redact(json.loads(line), f"line[{index}]")
                    for index, line in enumerate(data.splitlines())
                    if line.strip()
                ]
                exported = b"".join(
                    (json.dumps(row, ensure_ascii=False) + "\n").encode() for row in values
                )
            else:
                value = redact(json.loads(data))
                exported = (json.dumps(value, ensure_ascii=False) + "\n").encode()
        except (UnicodeDecodeError, json.JSONDecodeError):
            exported = original
        if redactions:
            data = exported
    if any(needle.encode() in data for needle in needles if needle):
        raise ValueError("Credential or unredacted account material in selected evidence")
    return data, redactions


def stage_snapshot(
    runtime: Path,
    campaign: Path,
    runs: list[Path],
    destination: Path,
    *,
    needles: tuple[str, ...],
    account_ids: tuple[str, ...] = (),
    campaign_files: tuple[Path, ...] = (),
    benchmark_files: tuple[Path, ...] = (),
    status: str = "partial",
    previous_content_sha256: str | None = None,
    phase_statuses: dict[str, str] | None = None,
    phase_gaps: dict[str, list[str]] | None = None,
    assignments: list[dict] | None = None,
) -> dict:
    """Freeze current bytes once, preserving originals and recording partial-run status."""
    runtime, campaign = runtime.resolve(strict=True), campaign.resolve(strict=True)
    selected = [(Path(__file__), Path("operator/archive.py"))]
    source_gaps = []
    for name in SOURCE_FILES:
        path = runtime / name
        if safe_file(path, runtime):
            selected.append((path, Path("source") / name))
        else:
            source_gaps.append("missing_or_unsafe_source_file:" + name)
    for name in SOURCE_ROOTS:
        source_root = runtime / name
        if not source_root.is_dir() or any(
            parent.is_symlink()
            for parent in (source_root, *source_root.parents)
            if parent != runtime.parent
        ):
            source_gaps.append("missing_or_unsafe_source_root:" + name)
            continue
        retained = 0
        for path in sorted((runtime / name).rglob("*")):
            if path.is_symlink():
                source_gaps.append("unsafe_source_entry:" + str(path.relative_to(runtime)))
                continue
            if safe_file(path, runtime) and (
                path.suffix
                in {
                    ".py",
                    ".md",
                    ".rs",
                    ".sol",
                    ".sql",
                    ".json",
                    ".toml",
                }
                or path.name == "Dockerfile"
            ):
                selected.append((path, Path("source") / path.relative_to(runtime)))
                retained += 1
        if not retained:
            source_gaps.append("empty_source_root:" + name)
    campaign_paths = {campaign / name for name in CAMPAIGN_FILES} | set(campaign_files)
    for path in sorted(campaign_paths):
        if not path.is_relative_to(campaign):
            raise ValueError("Selected campaign file is outside this campaign")
        if safe_file(path, campaign):
            selected.append((path, Path("campaign") / path.relative_to(campaign)))
    run_status = []
    for run in runs:
        # Validate the supplied path before resolve() so symlink aliases are rejected.
        if not run.is_relative_to(campaign) or any(
            parent.is_symlink() for parent in (run, *run.parents) if parent != campaign.parent
        ):
            raise ValueError("Selected run must be an unlinked directory inside this campaign")
        run = run.resolve(strict=True)
        manifest = json.loads((run / "run.json").read_bytes())
        if manifest.get("status") not in {"running", "complete", "failed", "interrupted"}:
            raise ValueError("Selected run has an unknown status")
        run_status.append(
            {
                "path": str(run.relative_to(campaign)),
                "run_id": manifest["run_id"],
                "status": manifest["status"],
            }
        )
        for path in tracking.uploadable(
            run,
            include_private_evidence=True,
            include_model_calls=True,
        ):
            if safe_file(path, run):
                selected.append((path, Path("runs") / path.relative_to(campaign)))
    for index, path in enumerate(benchmark_files):
        if not safe_file(path, path.parent):
            raise ValueError("Selected benchmark file is not a regular safe file")
        selected.append((path, Path("benchmark") / f"{index:02}-{path.name}"))
    files = []
    payloads = []
    for path, relative in sorted(set(selected), key=lambda pair: str(pair[1])):
        original = path.read_bytes()
        exported, redactions = export_bytes(original, path.suffix, needles, account_ids)
        payloads.append((relative, exported))
        files.append(
            {
                "path": str(relative),
                "original_sha256": hashlib.sha256(original).hexdigest(),
                "export_sha256": hashlib.sha256(exported).hexdigest(),
                "bytes": len(exported),
                "redactions": redactions,
            }
        )
    manifest = {
        "schema": SCHEMA,
        "created_utc": datetime.now(UTC).isoformat(),
        "status": "partial" if status == "complete" and source_gaps else status,
        "phase_statuses": phase_statuses or {},
        "phase_gaps": phase_gaps or {},
        "source_gaps": sorted(set(source_gaps)),
        "assignments": assignments or [],
        "runs": run_status,
        "files": files,
        "excluded": [
            "recovery databases and journals",
            "spending databases",
            "environment files",
            "wallet keys",
            "gateway authentication",
            "symlinks",
        ],
    }
    manifest["content_sha256"] = content_sha256(manifest)
    AuditManifest.model_validate(manifest)
    if manifest["content_sha256"] == previous_content_sha256:
        return manifest
    if destination.exists():
        raise ValueError("Archive stage must be a new directory")
    destination.mkdir(parents=True, mode=0o700)
    for relative, exported in payloads:
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_bytes(exported)
        target.chmod(0o600)
    tracking.persist_metadata(destination / MANIFEST, manifest)
    return manifest


def verify_snapshot(directory: Path) -> dict:
    """Reject changed, missing, extra or linked files against the embedded SHA256 manifest."""
    if not safe_file(directory / MANIFEST, directory):
        raise ValueError("Archive manifest must be an unlinked regular file")
    manifest_bytes = (directory / MANIFEST).read_bytes()
    manifest = json.loads(manifest_bytes)
    AuditManifest.model_validate(manifest)
    if content_sha256(manifest) != manifest["content_sha256"]:
        raise ValueError("Archive canonical content hash differs from manifest")
    expected = {row["path"] for row in manifest["files"]} | {MANIFEST}
    actual = {str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()}
    if actual != expected:
        raise ValueError("Archive file inventory differs from manifest")
    for row in manifest["files"]:
        relative = Path(row["path"])
        path = directory / relative
        if relative.is_absolute() or ".." in relative.parts or not safe_file(path, directory):
            raise ValueError("Unsafe archive manifest path")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["export_sha256"] or len(data) != row["bytes"]:
            raise ValueError("Archive file hash differs from manifest")
    run_files = {
        row["path"]
        for row in manifest["files"]
        if row["path"].startswith("runs/") and row["path"].endswith("/run.json")
    }
    if run_files != {"runs/" + row["path"] + "/run.json" for row in manifest["runs"]}:
        raise ValueError("Retained run manifests differ from run inventory")
    proved_runs = {
        path
        for assignment in manifest["assignments"]
        if assignment["status"] == "complete" and not assignment["gaps"]
        for path in assignment["run_paths"]
    }
    for row in manifest["runs"]:
        run = directory / "runs" / row["path"]
        data = json.loads((run / "run.json").read_bytes())
        if data.get("run_id") != row["run_id"] or data.get("status") != row["status"]:
            raise ValueError("Retained run identity/status differs from run inventory")
        if row["path"] in proved_runs and complete_run_gaps(run):
            raise ValueError("Complete archive has missing or inconsistent episode evidence")
    if manifest["status"] == "complete":
        file_paths = {row["path"] for row in manifest["files"]}
        if any("source/" + name not in file_paths for name in SOURCE_FILES) or any(
            not any(path.startswith("source/" + name + "/") for path in file_paths)
            for name in SOURCE_ROOTS
        ):
            raise ValueError("Complete archive is missing mandatory frozen source evidence")
        for phase in manifest["phase_statuses"]:
            progress_file = directory / "campaign" / phase / "progress.json"
            if not safe_file(progress_file, directory):
                raise ValueError("Complete archive is missing phase assignment evidence")
            progress = json.loads(progress_file.read_bytes())
            declared = [row for row in manifest["assignments"] if row["phase"] == phase]
            progress_rows = progress.get("assignments")
            expected_counts = dict.fromkeys(JOB_STATUSES, 0)
            expected_counts["complete"] = len(declared)
            if (
                progress.get("counts") != expected_counts
                or not isinstance(progress_rows, list)
                or len(progress_rows) != len(declared)
            ):
                raise ValueError("Complete archive assignment evidence is not terminal")
            expected = {
                (row["assignment_id"], "complete", Path(row["run_paths"][0]).name)
                for row in declared
            }
            observed = {
                (row.get("id"), row.get("status"), row.get("run_id"))
                for row in progress_rows
                if isinstance(row, dict)
            }
            if observed != expected:
                raise ValueError("Complete archive assignment identities differ from evidence")
    return {
        "files": len(manifest["files"]),
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "content_sha256": manifest["content_sha256"],
        "validation_schema": SCHEMA,
    }


def publish_snapshot(
    stage: Path,
    scope: tracking.TrackingScope,
    campaign_id: str,
    *,
    use_sdk_cache_for_verification: bool = False,
) -> dict:
    """The W&B adapter checks destination privacy before any retained content leaves disk."""
    import wandb

    if not scope.api_key or scope.public() != {
        "entity": "lbxa-corp",
        "project": "apart-collusion-sprint",
        "base_url": "https://api.wandb.ai",
    }:
        raise ValueError("Audit upload requires the explicitly authorized W&B destination")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", campaign_id):
        raise ValueError("Invalid campaign audit identity")
    verified = verify_snapshot(stage)
    for path in stage.rglob("*"):
        if path.is_file() and any(needle.encode() in path.read_bytes() for needle in scope.needles):
            raise ValueError("Credential material in staged archive")
    api = wandb.Api(api_key=scope.api_key, overrides=scope.public(), timeout=30)
    # The SDK's ProjectFragment omits access; ask its GraphQL transport for that scalar.
    result = api._service_api.execute_graphql(
        "query AuditPrivacy($name: String!, $entity: String!) { "
        "project(name: $name, entityName: $entity) { access } }",
        variables={"name": scope.project, "entity": scope.entity},
        parse=json.loads,
    )
    if not isinstance(result, dict) or (result.get("project") or {}).get("access") != "PRIVATE":
        raise ValueError("Audit destination is missing, inaccessible, or not PRIVATE")
    identity = "audit-" + hashlib.sha256(campaign_id.encode()).hexdigest()[:24]
    run = wandb.init(
        id=identity,
        resume="allow",
        entity=scope.entity,
        project=scope.project,
        name=campaign_id + "-audit",
        job_type="campaign-audit",
        reinit="create_new",
        settings=wandb.Settings(
            base_url=scope.base_url, api_key=scope.api_key, **tracking.SDK_PRIVACY_SETTINGS
        ),
        config={"campaign_id": campaign_id, "audit_schema": SCHEMA},
    )
    success = False
    try:
        artifact = wandb.Artifact(campaign_id + "-audit", type="campaign-audit", metadata=verified)
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                artifact.add_file(str(path), name=str(path.relative_to(stage)))
        logged = run.log_artifact(artifact).wait(timeout=180)
        # Always resolve the exact remote version anew. Cache use is explicit in its receipt.
        remote = api.artifact(logged.qualified_name)
        with tempfile.TemporaryDirectory(prefix="collusion-audit-download-") as temporary:
            downloaded = Path(
                remote.download(
                    root=temporary,
                    skip_cache=not use_sdk_cache_for_verification,
                )
            )
            remote.verify(root=str(downloaded))
            downloaded_verified = verify_snapshot(downloaded)
        if downloaded_verified != verified or remote.digest != logged.digest:
            raise ValueError("Downloaded artifact differs from staged snapshot")
        receipt = {
            "verified_utc": datetime.now(UTC).isoformat(),
            "scope": scope.public(),
            "run_id": identity,
            "run_url": run.url,
            "artifact": remote.qualified_name,
            "version": remote.version,
            "digest": remote.digest,
            "download_verified": True,
            "verification_download_mode": (
                "sdk_cache_enabled" if use_sdk_cache_for_verification else "fresh_skip_cache"
            ),
            "fresh_remote_version_lookup": True,
            "sdk_manifest_verified": True,
            "all_payloads_sha256_verified": True,
            **verified,
        }
        run.summary.update(
            {
                "audit/status": json.loads((stage / MANIFEST).read_bytes())["status"],
                "audit/verified_artifact": remote.qualified_name,
                "audit/manifest_sha256": verified["manifest_sha256"],
                "audit/files": verified["files"],
                "audit/validation_schema": SCHEMA,
            }
        )
        success = True
        return receipt
    finally:
        run.finish(exit_code=0 if success else 1)


def prune_verified_payloads(stage: Path, receipt_path: Path) -> int:
    """Remove only owned snapshot payload copies after checking a persisted verified receipt."""
    if (
        not re.fullmatch(r"snapshot-[0-9]{8}T[0-9]{12}Z", stage.name)
        or stage.is_symlink()
        or stage.parent != receipt_path.parent
        or not safe_file(receipt_path, stage.parent)
    ):
        raise ValueError("Pruning requires an owned watcher snapshot and sibling receipt")
    verified = verify_snapshot(stage)
    receipt = json.loads(receipt_path.read_bytes())
    if receipt.get("download_verified") is not True or any(
        receipt.get(key) != value for key, value in verified.items()
    ):
        raise ValueError("Persisted receipt does not verify this staging snapshot")
    manifest = json.loads((stage / MANIFEST).read_bytes())
    for row in manifest["files"]:
        # verify_snapshot has checked every path, hash and symlink before deletion begins.
        (stage / row["path"]).unlink()
    return len(manifest["files"])


def observe_controllers(campaign: Path, phases: list[str]) -> dict[str, str]:
    """Read explicit controller lifecycle records; absence never establishes a stopped phase."""
    controllers = {}
    for phase in phases:
        path = campaign / phase / "progress.json"
        controllers[phase] = "missing" if not path.exists() else "unknown"
        if safe_file(path, campaign):
            try:
                status = json.loads(path.read_bytes()).get("controller_status")
                if isinstance(status, str) and (
                    status in STOPPED_CONTROLLERS or status == "running"
                ):
                    controllers[phase] = status
            except (OSError, ValueError, AttributeError):
                pass
    return controllers


def watch_once(
    args, scope: tracking.TrackingScope, accounts: tuple[str, ...], now: datetime
) -> dict:
    """Archive one allowlisted cohort; missing phases remain pending and never count as complete."""
    binding = {
        "campaign_id": args.campaign_id,
        "scope": scope.public(),
        "runtime": str(args.runtime_root.resolve()),
        "campaign": str(args.campaign_root.resolve()),
        "phases": sorted(args.phase),
        "deadline_utc": None if args.no_deadline else args.deadline.isoformat(),
        "no_deadline": args.no_deadline,
    }
    state_path = args.stage / "watch-state.json"
    state = json.loads(state_path.read_bytes()) if state_path.exists() else {"binding": binding}
    if state.get("binding") != binding:
        raise ValueError("Watcher identity, phase allowlist, runtime, or deadline changed")
    controllers = observe_controllers(args.campaign_root, args.phase)
    runs, files, phases, assignments, phase_gaps = [], list(args.campaign_file), {}, [], {}
    for phase in sorted(args.phase):
        root = args.campaign_root / phase
        progress = root / "progress.json"
        phases[phase] = "pending"
        if progress.is_file():
            phases[phase], rows, gaps = reconcile_phase(root, json.loads(progress.read_bytes()))
            if (
                args.no_deadline
                and controllers[phase] in STOPPED_CONTROLLERS
                and phases[phase] == "running"
            ):
                # A stopped controller with pending assignments has unfinished evidence.
                phases[phase] = "incomplete"
            assignments.extend(rows)
            phase_gaps[phase] = gaps
        files.extend(
            root / name for name in ("progress.json", "local-run.json", "campaign-tracking.json")
        )
        runs.extend(path.parent for path in sorted(root.glob("jobs/*/run-*/run.json")))
        # Preserve partial outputs even when a failed attempt never wrote its run manifest.
        for attempt in sorted(root.glob("jobs/*/run-*")):
            if attempt.is_dir() and not (attempt / "run.json").exists():
                files.extend(
                    path for path in attempt.rglob("*") if safe_file(path, args.campaign_root)
                )
    terminal = all(status in {"complete", "failed"} for status in phases.values())
    status = ("failed" if "failed" in phases.values() else "complete") if terminal else "partial"
    if not args.no_deadline and now >= args.deadline and not terminal:
        status = "interrupted"
    stage = args.stage / ("snapshot-" + now.strftime("%Y%m%dT%H%M%S%fZ"))
    manifest = stage_snapshot(
        args.runtime_root,
        args.campaign_root,
        runs,
        stage,
        needles=scope.needles,
        account_ids=accounts,
        campaign_files=tuple(files),
        benchmark_files=tuple(args.benchmark_file),
        status=status,
        previous_content_sha256=state.get("content_sha256"),
        phase_statuses=phases,
        phase_gaps=phase_gaps,
        assignments=assignments,
    )
    state.update(
        last_checked_utc=now.isoformat(),
        phases=phases,
        last_observed_content_sha256=manifest["content_sha256"],
        final_verified=False,
        controllers=controllers,
        all_controllers_stopped=bool(controllers)
        and all(status in STOPPED_CONTROLLERS for status in controllers.values()),
    )
    args.stage.mkdir(parents=True, exist_ok=True, mode=0o700)
    tracking.persist_metadata(state_path, state)
    if stage.is_dir():
        receipt = publish_snapshot(
            stage,
            scope,
            args.campaign_id,
            use_sdk_cache_for_verification=args.use_sdk_cache_for_verification,
        )
        receipt_path = args.stage / (
            "receipt-" + receipt["version"] + "-" + receipt["manifest_sha256"][:12] + ".json"
        )
        tracking.persist_metadata(receipt_path, receipt)
        state.update(
            content_sha256=manifest["content_sha256"],
            last_receipt=str(receipt_path),
            artifact=receipt["artifact"],
            last_verified_utc=receipt["verified_utc"],
        )
        print(json.dumps({"event": "audit_verified", **receipt}), flush=True)
    # Completion concerns the latest observed bytes, rather than any earlier successful upload.
    receipt_path = state.get("last_receipt")
    if receipt_path and Path(receipt_path).is_file():
        receipt = json.loads(Path(receipt_path).read_bytes())
        state["final_verified"] = (
            receipt.get("download_verified") is True
            and receipt.get("validation_schema") == SCHEMA
            and receipt.get("content_sha256") == state["last_observed_content_sha256"]
            and state.get("content_sha256") == state["last_observed_content_sha256"]
        )
    tracking.persist_metadata(state_path, state)
    if args.prune_verified_payloads and stage.is_dir() and state["final_verified"]:
        try:
            removed = prune_verified_payloads(stage, Path(state["last_receipt"]))
            state.update(last_pruned_snapshot=str(stage), last_pruned_payload_files=removed)
            tracking.persist_metadata(state_path, state)
            print(
                json.dumps(
                    {
                        "event": "audit_staging_payload_pruned",
                        "files": removed,
                        "manifest": str(stage / MANIFEST),
                    }
                ),
                flush=True,
            )
        except Exception as error:
            print(
                json.dumps(
                    {"event": "audit_staging_prune_failed", "error_type": type(error).__name__}
                ),
                flush=True,
            )
    if args.log_finished_runs:
        for run in runs:
            if tracking.eligible(run, force=False):
                try:
                    url = tracking.log_run(
                        run, scope, include_private_evidence=True, include_model_calls=True
                    )
                    print(
                        json.dumps({"event": "session_logged", "run": run.name, "url": url}),
                        flush=True,
                    )
                except Exception as error:
                    print(
                        json.dumps(
                            {
                                "event": "session_upload_failed",
                                "run": run.name,
                                "error_type": type(error).__name__,
                            }
                        ),
                        flush=True,
                    )
    tracking.persist_metadata(state_path, state)
    return state


def watch(args, scope: tracking.TrackingScope, accounts: tuple[str, ...]) -> int:
    """Observe through the explicit deadline, or until all declared controllers stop."""
    terminal_content = None
    while True:
        now = datetime.now(UTC)
        final_verified = False
        state = None
        try:
            state = watch_once(args, scope, accounts, now)
            final_verified = state.get("final_verified") is True
        except Exception as error:
            print(
                json.dumps(
                    {
                        "event": "audit_snapshot_failed",
                        "error_type": type(error).__name__,
                        "checked_utc": now.isoformat(),
                        **(
                            {"errno": error.errno}
                            if isinstance(error, OSError) and type(error.errno) is int
                            else {}
                        ),
                    }
                ),
                flush=True,
            )
        if args.no_deadline:
            stopped = bool(state and state.get("all_controllers_stopped"))
            if state is None:
                controllers = observe_controllers(args.campaign_root, args.phase)
                stopped = bool(controllers) and all(
                    status in STOPPED_CONTROLLERS for status in controllers.values()
                )
            if stopped:
                content = state.get("last_observed_content_sha256") if state else None
                if not final_verified or content == terminal_content:
                    print(
                        json.dumps(
                            {
                                "event": "audit_watcher_finished",
                                "reason": "controllers_stopped",
                                "final_verified": final_verified,
                            }
                        ),
                        flush=True,
                    )
                    return 0 if final_verified else 1
                # Re-observe after publication, retaining any bytes written during finalization.
                terminal_content = content
                continue
            terminal_content = None
            time.sleep(args.interval)
            continue
        end = args.deadline + timedelta(seconds=args.finalization_grace_seconds)
        if now >= end:
            print(
                json.dumps({"event": "audit_watcher_finished", "final_verified": final_verified}),
                flush=True,
            )
            return 0 if final_verified else 1
        # Ten-second observation captures late terminal writes during the bounded drain.
        boundary = end if now >= args.deadline else args.deadline
        delay = min(
            10 if now >= args.deadline else args.interval,
            max(0, (boundary - datetime.now(UTC)).total_seconds()),
        )
        time.sleep(delay)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runtime-root", "campaign-root", "stage", "dotenv"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--run", type=Path, action="append", default=[])
    parser.add_argument("--campaign-file", type=Path, action="append", default=[])
    parser.add_argument("--benchmark-file", type=Path, action="append", default=[])
    parser.add_argument("--scan-env", type=Path, action="append", default=[])
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument(
        "--status", choices=("partial", "complete", "failed", "interrupted"), default="partial"
    )
    parser.add_argument("--upload", action="store_true")
    parser.add_argument(
        "--publish-staged",
        action="store_true",
        help="Upload an existing finite snapshot after revalidating its manifest and secret scan",
    )
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--phase", action="append", default=[])
    parser.add_argument("--interval", type=int, default=90)
    lifetime = parser.add_mutually_exclusive_group()
    lifetime.add_argument("--deadline", type=datetime.fromisoformat)
    lifetime.add_argument(
        "--no-deadline",
        action="store_true",
        help="Watch until every declared phase controller stops and final content is verified",
    )
    parser.add_argument("--finalization-grace-seconds", type=int, default=60)
    parser.add_argument("--log-finished-runs", action="store_true")
    parser.add_argument(
        "--use-sdk-cache-for-verification",
        action="store_true",
        help="Use W&B's artifact cache for watch downloads; still verify every file hash",
    )
    parser.add_argument(
        "--prune-verified-payloads",
        action="store_true",
        help="After a persisted verified receipt, remove only owned staging payload copies",
    )
    args = parser.parse_args(argv)
    if args.publish_staged and not args.upload:
        parser.error("--publish-staged requires --upload")
    if args.prune_verified_payloads and not (args.watch and args.upload):
        parser.error("--prune-verified-payloads requires --watch --upload")
    if args.use_sdk_cache_for_verification and not (args.watch and args.upload):
        parser.error("--use-sdk-cache-for-verification requires --watch --upload")
    if args.no_deadline and not (args.watch and args.upload):
        parser.error("--no-deadline requires --watch --upload")
    if args.watch:
        if not args.upload or args.publish_staged or args.run or not args.phase:
            parser.error("--watch requires --upload and explicit --phase values, without --run")
        if len(set(args.phase)) != len(args.phase) or any(
            not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", phase) for phase in args.phase
        ):
            parser.error("Watcher phases must be unique single path components")
        if not 60 <= args.interval <= 120 or not 0 <= args.finalization_grace_seconds <= 60:
            parser.error(
                "Watcher interval must be 60–120 seconds and finalization grace 0–60 seconds"
            )
        if not args.no_deadline and (
            args.deadline is None
            or args.deadline.tzinfo is None
            or args.deadline.utcoffset() != timedelta(0)
        ):
            parser.error("--watch requires an absolute UTC --deadline or explicit --no-deadline")
    os.umask(0o077)
    scope = tracking.resolve_scope(args.dotenv)
    sources = [
        os.environ,
        dotenv_values(args.dotenv, interpolate=False),
        *(dotenv_values(path, interpolate=False) for path in args.scan_env),
    ]
    needles = tuple(
        sorted(
            set(scope.needles)
            | {
                value
                for source in sources
                for name in tracking.SECRET_NAMES
                if (value := source.get(name))
            }
        )
    )
    accounts = tuple(
        sorted(
            {
                source["CLOUDFLARE_ACCOUNT_ID"]
                for source in sources
                if source.get("CLOUDFLARE_ACCOUNT_ID")
            }
        )
    )
    try:
        if args.watch:
            scan_scope = tracking.TrackingScope(
                scope.project, scope.entity, scope.base_url, scope.api_key, needles
            )
            return watch(args, scan_scope, accounts)
        if not args.publish_staged:
            stage_snapshot(
                args.runtime_root,
                args.campaign_root,
                args.run,
                args.stage,
                needles=needles,
                account_ids=accounts,
                campaign_files=tuple(args.campaign_file),
                benchmark_files=tuple(args.benchmark_file),
                status=args.status,
            )
        verification = verify_snapshot(args.stage)
        if args.upload:
            if args.receipt is None:
                raise ValueError("--upload requires --receipt")
            scan_scope = tracking.TrackingScope(
                scope.project, scope.entity, scope.base_url, scope.api_key, needles
            )
            receipt = publish_snapshot(args.stage, scan_scope, args.campaign_id)
            tracking.persist_metadata(args.receipt, receipt)
            print(json.dumps(receipt))
        else:
            print(json.dumps({"scope": scope.public(), "status": "staged", **verification}))
    except Exception as error:
        # Provider/SDK exception strings can include credentials or content.
        print(json.dumps({"status": "archive_failed", "error_type": type(error).__name__}))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
