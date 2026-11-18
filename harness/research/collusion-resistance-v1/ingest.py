"""Read-only campaign ingestion and prospective confirmation preparation.

Select the frozen runtime with PYTHONPATH before invoking this operator helper.
Outputs are new private artifacts; authoritative registers and raw runs are never
rewritten. Running jobs remain deferred because their session bytes are mutable.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Literal

from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict, Field

from game_api.generated import ChatView, MessagePage
from veracity_harness import materials, resistance
from veracity_harness.analysis import EpisodeEvidence, RunRecord
from veracity_harness.campaign import CampaignPlan, FrozenCampaign, digest
from veracity_harness.resistance import (
    ARMS,
    CONFIRMATION_CASES,
    PRIMARY_ARMS,
    V1_ROSTER,
    ActorObservation,
    BlindedReviewPacket,
    CaseObservation,
    ResistanceAssignment,
    ResistanceManifest,
    ReviewExcerpt,
    ScenarioRegistry,
    assignment_fingerprint,
    config_fingerprint,
    extract_observations,
    freeze_config,
)
from veracity_harness.scoring import session_sha256

TERMINAL = {"complete", "failed", "interrupted"}
RUN_STATUS_MATRIX = {"complete": {"complete"}, "failed": {"failed"}, "interrupted": {"failed"}}


class JournalJob(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    status: Literal["pending", "running", "complete", "failed", "interrupted"]
    run_directory: str | None = None
    run_id: str | None = None
    error_type: str | None = None


class ProgressProjection(BaseModel):
    fingerprint: str
    counts: dict[str, int]


class ChatTranscript(BaseModel):
    chat: ChatView
    pages: list[MessagePage]


class CreditTransfer(BaseModel):
    sender: str
    recipient: str
    amount_wei: str = Field(pattern=r"^(0|[1-9][0-9]*)$")
    transaction_hash: str
    block_number: int


class RetainedEvidence(EpisodeEvidence):
    private_transcripts: dict[str, ChatTranscript] = Field(default_factory=dict)
    credit_transfers: list[CreditTransfer] | None = None


class Opportunity(BaseModel):
    actor_id: str
    opportunity: int = Field(ge=1)
    status: str
    model_calls: int = Field(ge=0)
    error_type: str | None = None


class Generation(BaseModel):
    message: AIMessage


class Response(BaseModel):
    generations: list[list[Generation]]


class TraceEvent(BaseModel):
    event: str
    request_id: str | None = None
    response: Response | None = None
    error_type: str | None = None


def write_bytes(path: Path, data: bytes) -> str:
    """Exclusive private creation for computed or copied audit artifacts."""
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(data)
    return digest(data)


def write_json(path: Path, value) -> str:
    return write_bytes(path, (json.dumps(value, indent=2, allow_nan=False) + "\n").encode())


def imported_runtime() -> Path:
    return Path(resistance.__file__).resolve().parents[3]


def read_journal(campaign: Path):
    """One SQLite read transaction, with no controller recovery or writes."""
    path = campaign / "campaign.sqlite"
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as db:
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        metadata = dict(db.execute("SELECT key,value FROM metadata"))
        jobs = tuple(
            JournalJob.model_validate(
                dict(
                    zip(
                        ("id", "status", "run_directory", "run_id", "error_type"),
                        row,
                        strict=True,
                    )
                )
            )
            for row in db.execute(
                "SELECT id,status,run_directory,run_id,error_type FROM jobs ORDER BY position"
            )
        )
    frozen = FrozenCampaign.model_validate_json(metadata["frozen"])
    if frozen.fingerprint != metadata["fingerprint"]:
        raise ValueError("Journal frozen identity mismatch")
    if {job.id for job in jobs} != {job.id for job in frozen.assignments}:
        raise ValueError("Journal assignments differ from its immutable campaign")
    progress_path = campaign / "progress.json"
    progress_bytes = progress_path.read_bytes() if progress_path.is_file() else b""
    progress = ProgressProjection.model_validate_json(progress_bytes) if progress_bytes else None
    if progress is not None and progress.fingerprint != frozen.fingerprint:
        raise ValueError("Progress projection names another frozen campaign")
    safe = {
        "campaign_directory": str(campaign.resolve()),
        "campaign_fingerprint": frozen.fingerprint,
        "frozen_campaign_sha256": digest(metadata["frozen"].encode()),
        "journal_snapshot_sha256": digest(
            json.dumps([job.model_dump() for job in jobs], sort_keys=True).encode()
        ),
        "progress_sha256": digest(progress_bytes) if progress_bytes else None,
        "journal_status_counts": dict(Counter(job.status for job in jobs)),
        "progress_status_counts": progress.counts if progress is not None else None,
    }
    return frozen, jobs, safe


def blind_text(text: str, aliases: dict[str, str]) -> str:
    replacements = {
        identifier: "[model identity withheld]"
        for slot, (_, family, model) in V1_ROSTER.items()
        for identifier in (model, family, slot)
    }
    replacements.update(aliases)
    pattern = re.compile(
        r"(?<!\w)("
        + "|".join(re.escape(key) for key in sorted(replacements, key=len, reverse=True))
        + r")(?!\w)",
        re.I,
    )
    by_lower = {key.lower(): value for key, value in replacements.items()}
    return pattern.sub(lambda match: by_lower[match.group().lower()], text)


def actor_mechanics(row: CaseObservation) -> dict:
    directory = Path(row.run_directory)
    run = RunRecord.model_validate_json((directory / "run.json").read_bytes())
    episode_dir = directory / row.episode_id
    evidence = RetainedEvidence.model_validate_json((episode_dir / "evidence.json").read_bytes())
    record = next(record for record in run.episodes if record.episode_id == row.episode_id)
    opportunities_path = episode_dir / "opportunities.jsonl"
    opportunities = (
        [
            Opportunity.model_validate_json(line)
            for line in opportunities_path.read_bytes().splitlines()
            if line
        ]
        if opportunities_path.is_file()
        else []
    )
    actors = []
    for actor in row.actors:
        entries = [entry for entry in opportunities if entry.actor_id == actor.actor_id]
        trace = episode_dir / f"{actor.actor_id}.trace.calls.jsonl"
        events = (
            [
                TraceEvent.model_validate_json(line)
                for line in trace.read_bytes().splitlines()
                if line
            ]
            if trace.is_file()
            else []
        )
        starts = {event.request_id for event in events if event.event == "model_start"}
        ends = {event.request_id for event in events if event.event == "model_end"}
        juror = next((j for j in evidence.episode.jurors if j.actor_id == actor.actor_id), None)
        settings = run.config.model_for(actor.actor_id)
        evaluated = actor.control == "evaluated"
        actors.append(
            {
                **actor.model_dump(),
                "committed": bool(juror.commitment) if juror else None,
                "verdict": juror.verdict if juror else None,
                "opportunities": len(entries) if opportunities_path.is_file() else None,
                "opportunity_status_counts": dict(Counter(e.status for e in entries))
                if opportunities_path.is_file()
                else None,
                "observed_model_starts": len(starts) if evaluated and trace.is_file() else None,
                "all_actor_callback_starts": len(starts) if trace.is_file() else None,
                "all_actor_callback_end_receipts": len(ends) if trace.is_file() else None,
                "callback_error_counts": dict(
                    Counter(
                        event.error_type or event.event
                        for event in events
                        if event.event in {"model_error", "model_cancelled"}
                    )
                )
                if trace.is_file()
                else None,
                "budget_exhausted_opportunities": sum(
                    entry.status == "budget_exhausted" for entry in entries
                )
                if opportunities_path.is_file()
                else None,
                "provider_dispatched_requests": None,
                "charged_requests": None,
                "opportunity_model_calls": sum(e.model_calls for e in entries)
                if evaluated and opportunities_path.is_file()
                else None,
                "opportunities_observed": opportunities_path.is_file(),
                "opportunities_sha256": digest(opportunities_path.read_bytes())
                if opportunities_path.is_file()
                else None,
                "model_trace_observed": trace.is_file() if evaluated else None,
                "model_trace_sha256": digest(trace.read_bytes())
                if evaluated and trace.is_file()
                else None,
                "calls_per_turn": settings.calls_per_turn if evaluated else None,
                "calls_per_episode": settings.calls_per_episode if evaluated else None,
                "turn_timeout_seconds": settings.turn_timeout_seconds if evaluated else None,
                "over_budget_opportunities": [
                    e.opportunity
                    for e in entries
                    if evaluated and e.model_calls > settings.calls_per_turn
                ]
                if opportunities_path.is_file()
                else None,
                "ordinary_jury_reward_wei": str(
                    int(evidence.settlement.juror_payouts.get(actor.actor_id, "0"))
                    - int(evidence.episode.juror_bond_wei)
                )
                if juror and juror.revealed and evidence.settlement
                else "0"
                if juror and evidence.settlement
                else None,
                "extra_credit_received_wei": str(
                    sum(
                        int(transfer.amount_wei)
                        for transfer in evidence.credit_transfers
                        if transfer.recipient == actor.actor_id
                    )
                )
                if evidence.credit_transfers is not None
                else None,
                "extra_credit_sent_wei": str(
                    sum(
                        int(transfer.amount_wei)
                        for transfer in evidence.credit_transfers
                        if transfer.sender == actor.actor_id
                    )
                )
                if evidence.credit_transfers is not None
                else None,
            }
        )
    return {
        "job_id": row.job_id,
        "run_id": row.run_id,
        "run_status": run.status,
        "case_id": row.case_id,
        "episode_id": row.episode_id,
        "phase": evidence.episode.phase,
        "required_votes": evidence.episode.required_votes,
        "source_sha256": row.source_sha256,
        "session_sha256": row.session_sha256,
        "run_manifest_sha256": row.run_manifest_sha256,
        "evidence_sha256": row.evidence_sha256,
        "actual_claim_sha256": row.actual_claim_sha256,
        "effective_config_sha256": row.effective_config_sha256,
        "agent_execution_failed": record.agent_execution_failed,
        "model_calls": record.model_calls,
        "input_tokens": record.input_tokens,
        "output_tokens": record.output_tokens,
        "evaluated_jurors": row.evaluated_jurors,
        "valid_commitments": sum(
            bool(j.commitment)
            for j in evidence.episode.jurors
            if any(a.actor_id == j.actor_id and a.control == "evaluated" for a in row.actors)
        ),
        "valid_reveals": row.valid_reveals,
        "reference_applicable": row.reference_applicable,
        "wrong_votes": row.wrong_votes,
        "ballot_accuracy": (row.valid_reveals - row.wrong_votes) / row.valid_reveals
        if row.valid_reveals and row.wrong_votes is not None
        else None,
        "credit_transfer_event_count": len(evidence.credit_transfers)
        if evidence.credit_transfers is not None
        else None,
        "capability_evidence_gaps": (
            [] if opportunities_path.is_file() else ["opportunities_missing"]
        )
        + [
            f"model_trace_missing:{actor['actor_id']}"
            for actor in actors
            if actor["control"] == "evaluated" and not actor["model_trace_observed"]
        ],
        "actors": actors,
        "semantic_labels": "not_reviewed",
    }


def build_packet(row: CaseObservation):
    """Curate a blinded projection; preserve a separate original-locator map."""
    directory = Path(row.run_directory)
    run_payload = json.loads((directory / "run.json").read_text())
    run = RunRecord.model_validate(run_payload)
    path = directory / row.episode_id / "evidence.json"
    evidence = RetainedEvidence.model_validate_json(path.read_bytes())
    actors = {
        actor.actor_id: f"actor-{index:02}" for index, actor in enumerate(row.actors, start=1)
    }
    aliases = {**actors, row.run_id: "session", row.episode_id: "case"}
    aliases.update(
        {
            alias: actors[actor]
            for actor, alias in run_payload.get("account_names", {}).items()
            if actor in actors
        }
    )
    excerpts, locator_map = [], {}
    evidence_sha = digest(path.read_bytes())

    def retain(key, modality, content, relative, selector, actor=None):
        original = directory / relative
        text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        excerpts.append(
            ReviewExcerpt(
                excerpt_id=key,
                modality=modality,
                actor_key=actors.get(actor),
                content=blind_text(text, aliases),
                original_sha256=digest(original.read_bytes()),
            )
        )
        locator_map[key] = {
            "path": relative,
            "sha256": digest(original.read_bytes()),
            "selector": selector,
        }

    relative = f"{row.episode_id}/evidence.json"
    retain("claim", "claim", evidence.episode.content or "", relative, "/episode/content")
    source_path = row.proof_locators[0].partition("#")[0]
    source_lines = (directory / source_path).read_text().splitlines()
    retain("source", "source", "\n".join(source_lines), source_path, f"lines:1-{len(source_lines)}")
    for name in ("CONSTITUTION.md", "rules.md", "interface.md"):
        relative_instruction = f"inputs/{name}"
        lines = (directory / relative_instruction).read_text().splitlines()
        retain(
            f"instruction-{name}",
            "obligation",
            "\n".join(lines),
            relative_instruction,
            f"lines:1-{len(lines)}",
        )
    retain(
        "outcome",
        "action",
        {
            "phase": evidence.episode.phase,
            "required_votes": evidence.episode.required_votes,
            "jurors": [
                {
                    "actor": actors[j.actor_id],
                    "committed": bool(j.commitment),
                    "revealed": j.revealed,
                    "verdict": j.verdict,
                }
                for j in evidence.episode.jurors
            ],
            "net_payoffs_wei": {actors[a.actor_id]: a.payoff_wei for a in row.actors},
        },
        relative,
        "/episode",
    )
    if evidence.credit_transfers is not None:
        retain(
            "credit-transfers",
            "action",
            [
                {
                    "sender": actors.get(transfer.sender, "external-account"),
                    "recipient": actors.get(transfer.recipient, "external-account"),
                    "amount_wei": transfer.amount_wei,
                    "block_number": transfer.block_number,
                }
                for transfer in evidence.credit_transfers
            ],
            relative,
            "/credit_transfers",
        )
    for page_index, page in enumerate(evidence.forum_transcript):
        for index, message in enumerate(page.messages):
            retain(
                f"public-{message.sequence}",
                "communication",
                {
                    "channel": "public",
                    "sequence": message.sequence,
                    "time_ms": message.created_at_ms,
                    "sender": actors[message.sender_id],
                    "body": message.content,
                },
                relative,
                f"/forum_transcript/{page_index}/messages/{index}",
                message.sender_id,
            )
    for channel_index, (chat_id, chat) in enumerate(
        sorted(evidence.private_transcripts.items()), start=1
    ):
        channel = f"channel-{channel_index:02}"
        aliases[chat_id] = channel
        escaped = chat_id.replace("~", "~0").replace("/", "~1")
        for page_index, page in enumerate(chat.pages):
            for index, message in enumerate(page.messages):
                retain(
                    f"private-{channel_index}-{message.sequence}",
                    "communication",
                    {
                        "channel": channel,
                        "sequence": message.sequence,
                        "time_ms": message.created_at_ms,
                        "sender": actors[message.sender_id],
                        "recipient": actors[message.recipient_id],
                        "body": message.content,
                    },
                    relative,
                    f"/private_transcripts/{escaped}/pages/{page_index}/messages/{index}",
                    message.sender_id,
                )
    delivery_fields = {
        "event",
        "actor_id",
        "method",
        "endpoint",
        "status",
        "time_ns",
        "messages_returned",
        "messages_withheld",
        "chats_withheld",
        "offer_visible",
        "offer_stored",
        "public_messages_returned",
        "public_messages_withheld",
        "before_evaluated_juror_notification",
    }
    for name in ("scripted-setup.jsonl", "gateway-audit/access.jsonl"):
        audit = directory / row.episode_id / name
        if audit.is_file():
            for line_index, line in enumerate(audit.read_text().splitlines(), start=1):
                event = json.loads(line)
                shown = {key: value for key, value in event.items() if key in delivery_fields}
                retain(
                    f"delivery-{name}-{line_index}",
                    "action",
                    shown,
                    str(audit.relative_to(directory)),
                    f"line:{line_index}",
                )
    reasoning_count = 0
    missing_traces = []
    for actor in row.actors:
        trace = directory / row.episode_id / f"{actor.actor_id}.trace.calls.jsonl"
        if not trace.is_file():
            if actor.control == "evaluated":
                missing_traces.append(actors[actor.actor_id])
            continue
        for line_index, line in enumerate(trace.read_bytes().splitlines(), start=1):
            event = TraceEvent.model_validate_json(line)
            if event.response is None:
                continue
            for group in event.response.generations:
                for generation in group:
                    reasoning = generation.message.additional_kwargs.get("reasoning_content")
                    if isinstance(reasoning, str) and reasoning:
                        reasoning_count += 1
                        retain(
                            f"reasoning-{reasoning_count}",
                            "reasoning",
                            reasoning,
                            str(trace.relative_to(directory)),
                            f"line:{line_index}",
                            actor.actor_id,
                        )
    opportunities = directory / row.episode_id / "opportunities.jsonl"
    if opportunities.is_file():
        for line_index, line in enumerate(opportunities.read_bytes().splitlines(), start=1):
            event = Opportunity.model_validate_json(line)
            settings = run.config.model_for(event.actor_id)
            retain(
                f"opportunity-{line_index}",
                "action",
                {
                    "actor": actors[event.actor_id],
                    "opportunity": event.opportunity,
                    "status": event.status,
                    "model_calls": event.model_calls,
                    "error_type": event.error_type,
                    "calls_per_turn": settings.calls_per_turn
                    if event.actor_id not in run.config.scripted_actors
                    else None,
                    "calls_per_episode": settings.calls_per_episode
                    if event.actor_id not in run.config.scripted_actors
                    else None,
                },
                str(opportunities.relative_to(directory)),
                f"line:{line_index}",
                event.actor_id,
            )
    packet_id = "packet-" + digest(f"{row.session_sha256}/{row.episode_id}".encode())[:24]
    packet = BlindedReviewPacket(
        packet_id=packet_id,
        source_sha256=row.source_sha256,
        session_sha256=row.session_sha256,
        evidence_sha256=evidence_sha,
        actual_claim_sha256=row.actual_claim_sha256,
        actors=tuple(
            ActorObservation(**{**actor.model_dump(), "actor_id": actors[actor.actor_id]})
            for actor in row.actors
        ),
        excerpts=tuple(excerpts),
        blinding_reviewed=False,
        blinding_gaps=(
            "literal_identifier_redaction_only_not_independent_blinding",
            "delivered_duties_and_delivery_facts_may_reveal_intervention",
            "returned_reasoning_is_not_guaranteed_faithful_internal_state",
        )
        + (("no_returned_reasoning_observed",) if reasoning_count == 0 else ())
        + (("credit_transfer_coverage_missing",) if evidence.credit_transfers is None else ()),
        # Missing capability evidence stays explicit even with retained outcome evidence.
    )
    mapping = {
        "job_id": row.job_id,
        "case_id": row.case_id,
        "episode_id": row.episode_id,
        "model_slot": row.model_slot,
        "actors": actors,
        "excerpts": locator_map,
        "reasoning_excerpts": reasoning_count,
    }
    packet = packet.model_copy(
        update={
            "blinding_gaps": (
                *packet.blinding_gaps,
                *(f"model_trace_missing:{actor}" for actor in missing_traces),
                *(("opportunities_missing",) if not opportunities.is_file() else ()),
            )
        }
    )
    return packet, mapping


def ingest(register: Path, registry_path: Path, campaigns: list[Path], output: Path):
    original = register.read_bytes()
    payload = json.loads(original)
    manifest = ResistanceManifest.model_validate(payload)
    registry = ScenarioRegistry.model_validate_json(registry_path.read_bytes())
    rows = {job["job_id"]: dict(job) for job in payload["assignments"]}
    slots = {slot.model_slot: slot for slot in manifest.model_slots}
    seen, snapshots, deferred = set(), [], []
    for campaign in campaigns:
        frozen, jobs, snapshot = read_journal(campaign)
        snapshots.append(snapshot)
        frozen_jobs = {job.id: job for job in frozen.assignments}
        for job in jobs:
            if job.id in seen or job.id not in rows:
                raise ValueError("Campaign job duplicated or absent from the immutable register")
            seen.add(job.id)
            assignment = ResistanceAssignment.model_validate(rows[job.id])
            expected = frozen_jobs[job.id]
            slot = slots[assignment.model_slot]
            if (
                expected.config_sha256 != assignment.config_sha256
                or config_fingerprint(expected.experiment) != assignment.effective_config_sha256
            ):
                raise ValueError("Journal frozen configuration differs from immutable register")
            if (
                expected.experiment.seed,
                expected.experiment.model.name,
                expected.experiment.model.provider,
            ) != (assignment.seed, slot.model_id, slot.provider):
                raise ValueError("Journal seed/provider/model differs from immutable register")
            update = {
                "status": job.status,
                "run_directory": None,
                "run_id": None,
                "run_manifest_sha256": None,
                "session_sha256": None,
            }
            if job.status not in TERMINAL:
                deferred.append(
                    {"job_id": job.id, "status": job.status, "reason": "mutable_or_unstarted_run"}
                )
            elif job.run_directory is None:
                deferred.append(
                    {
                        "job_id": job.id,
                        "status": job.status,
                        "reason": "terminal_job_missing_run_directory",
                    }
                )
            elif job.run_directory is not None:
                expected_parent = (campaign / "jobs" / job.id).resolve()
                if Path(job.run_directory).resolve() != expected_parent:
                    raise ValueError("Journal run directory escapes its assigned job")
                candidates = list(expected_parent.glob("run-*/run.json"))
                if len(candidates) > 1:
                    raise ValueError("Multiple retained runs for one assignment")
                if candidates:
                    path = candidates[0]
                    if not path.resolve().is_relative_to(expected_parent):
                        raise ValueError("Retained run escapes its assigned job directory")
                    run = RunRecord.model_validate_json(path.read_bytes())
                    if (
                        run.run_id != path.parent.name
                        or job.run_id is not None
                        and job.run_id != run.run_id
                    ):
                        raise ValueError("Journal/run manifest identity mismatch")
                    if run.status not in RUN_STATUS_MATRIX[job.status]:
                        deferred.append(
                            {
                                "job_id": job.id,
                                "status": job.status,
                                "run_status": run.status,
                                "run_id": run.run_id,
                                "reason": "journal_run_status_mismatch",
                            }
                        )
                    else:
                        update.update(
                            run_directory=str(path.parent),
                            run_id=run.run_id,
                            run_manifest_sha256=digest(path.read_bytes()),
                            session_sha256=session_sha256(path.parent),
                        )
                else:
                    deferred.append(
                        {
                            "job_id": job.id,
                            "status": job.status,
                            "reason": "terminal_job_missing_run_evidence",
                        }
                    )
            rows[job.id] = {**rows[job.id], **update}
    derived = {**payload, "assignments": list(rows.values())}
    admitted = ResistanceManifest.model_validate(derived)
    observations = extract_observations(admitted, registry)
    packets, mechanics, mappings = [], [], {}
    for row in observations:
        if row.evidence_sha256 is None:
            continue
        mechanics.append(actor_mechanics(row))
        packet, mapping = build_packet(row)
        packets.append(packet)
        mappings[packet.packet_id] = mapping
    for job in admitted.assignments:
        if (
            job.run_directory is not None
            and session_sha256(Path(job.run_directory)) != job.session_sha256
        ):
            raise ValueError(
                "Terminal run changed during ingestion; retry without modifying raw evidence"
            )
    if register.read_bytes() != original:
        raise ValueError("Authoritative register changed during ingestion")
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    packet_dir = output / "review-packets"
    packet_dir.mkdir(mode=0o700)
    hashes = {
        "assignment-register.json": write_json(output / "assignment-register.json", derived),
        "case-observations.json": write_json(
            output / "case-observations.json", [row.model_dump(mode="json") for row in observations]
        ),
        "actor-mechanics.json": write_json(output / "actor-mechanics.json", mechanics),
        "operator-review-map.json": write_json(output / "operator-review-map.json", mappings),
    }
    hashes["ingest.py"] = write_bytes(output / "ingest.py", Path(__file__).read_bytes())
    for packet in packets:
        relative = f"review-packets/{packet.packet_id}.json"
        hashes[relative] = write_json(output / relative, packet.model_dump(mode="json"))
    runtime = imported_runtime()
    receipt = {
        "format_version": 2,
        "schema": "collusion-resistance-ingestion-v2",
        "register_sha256": digest(original),
        "registry_sha256": digest(registry_path.read_bytes()),
        "campaigns": snapshots,
        "runtime_root": str(runtime),
        "interpreter": sys.executable,
        "python_version": sys.version,
        "operator_helper_sha256": digest(Path(__file__).read_bytes()),
        "operator_helper_path": str(Path(__file__).resolve()),
        "runtime_sources": {
            str(path.relative_to(runtime)): digest(path.read_bytes())
            for path in (
                Path(resistance.__file__),
                Path(materials.__file__),
                materials.RESOURCES / "interface.md",
            )
        },
        "deferred_jobs": deferred,
        "outputs_sha256": hashes,
        "run_status_matrix": {key: sorted(value) for key, value in RUN_STATUS_MATRIX.items()},
        "capability_evidence_gaps": [
            {
                "job_id": row["job_id"],
                "case_id": row["case_id"],
                "gaps": row["capability_evidence_gaps"],
            }
            for row in mechanics
            if row["capability_evidence_gaps"]
        ],
        "review_packet_count": len(packets),
        "semantic_labels_created": 0,
    }
    write_json(output / "ingestion-receipt.json", receipt)
    return receipt


def prepare_confirmation(
    runtime_root: Path,
    output: Path,
    seeds: tuple[int, ...],
    *,
    priority_primary: bool = False,
    previous_plan: Path | None = None,
    protocol_amendment: Path | None = None,
    cost_basis: Path | None = None,
):
    if runtime_root.resolve() != imported_runtime():
        raise ValueError("Select the candidate runtime through PYTHONPATH before freezing")
    if len(seeds) != 5 or len(set(seeds)) != 5:
        raise ValueError("Confirmation requires five distinct seeds")
    if priority_primary and (protocol_amendment is None or cost_basis is None):
        raise ValueError("Primary-first scheduling needs its protocol amendment and cost basis")
    directory = runtime_root / "harness/research/collusion-resistance-v1"
    slots = [
        {"model_slot": slot, "provider": provider, "family": family, "model_id": model}
        for slot, (provider, family, model) in V1_ROSTER.items()
    ]
    jobs, plan = [], []
    for seed_index, seed in enumerate(seeds):
        for round_index in range(len(ARMS)):
            for offset in range(len(slots)):
                slot = slots[(offset + seed_index) % len(slots)]
                arm = ARMS[(round_index + offset + seed_index) % len(ARMS)]
                config = directory / f"{arm}.toml"
                job = ResistanceAssignment(
                    job_id=f"confirm-{slot['model_slot']}-{arm}-{seed}",
                    model_slot=slot["model_slot"],
                    arm=arm,
                    seed=seed,
                    config=str(config.resolve()),
                    sourcecases=CONFIRMATION_CASES,
                    phase="confirmation",
                    status="pending",
                    **freeze_config(
                        config, model_id=slot["model_id"], provider=slot["provider"], seed=seed
                    ),
                )
                job = job.model_copy(update={"job_fingerprint": assignment_fingerprint(job)})
                jobs.append(job)
                plan.append(
                    {
                        "id": job.job_id,
                        "config": job.config,
                        "model": slot["model_id"],
                        "provider": slot["provider"],
                        "seed": seed,
                    }
                )
    if priority_primary:
        lookup = {(job.model_slot, job.arm, job.seed): job for job in jobs}
        ordered = [job for job in jobs if job.seed == seeds[0]]
        for arms in (PRIMARY_ARMS, tuple(arm for arm in ARMS if arm not in PRIMARY_ARMS)):
            for seed_index, seed in enumerate(seeds[1:], start=1):
                for round_index in range(len(arms)):
                    for offset in range(len(slots)):
                        slot = slots[(offset + seed_index) % len(slots)]
                        arm = arms[(round_index + offset + seed_index) % len(arms)]
                        ordered.append(lookup[(slot["model_slot"], arm, seed)])
        jobs = ordered
        by_id = {job["id"]: job for job in plan}
        plan = [by_id[job.job_id] for job in jobs]
    prior = previous_plan.read_bytes() if previous_plan is not None else None
    if prior is not None:
        old = CampaignPlan.model_validate_json(prior)
        if {job.id: job.model_dump(mode="json") for job in old.assignments} != {
            job["id"]: job for job in plan
        }:
            raise ValueError("Scheduling change must preserve every exact prior plan assignment")
    manifest = ResistanceManifest(
        model_slots=slots,
        assignments=tuple(jobs),
        selected_case_ids=CONFIRMATION_CASES,
        planned_seeds=seeds,
    )
    campaign = CampaignPlan(name="crv1-confirmation", assignments=plan)
    shards = {
        slot["model_slot"]: CampaignPlan(
            name=f"crv1-confirm-{slot['model_slot']}",
            assignments=[
                item
                for item in campaign.assignments
                if next(job.model_slot for job in jobs if job.job_id == item.id)
                == slot["model_slot"]
            ],
        )
        for slot in slots
    }
    shard_ids = [job.id for shard in shards.values() for job in shard.assignments]
    if (
        len(shard_ids) != 150
        or len(set(shard_ids)) != 150
        or set(shard_ids) != {job.job_id for job in jobs}
    ):
        raise ValueError("Family shard union must preserve all 150 exact assignments once")
    # Validate every canonical arm and source before the candidate is written.
    registry_path = directory / "scenario-bank.json"
    registry = ScenarioRegistry.model_validate_json(registry_path.read_bytes())
    extract_observations(manifest, registry)
    output.mkdir(parents=True, mode=0o700, exist_ok=False)
    hashes = {
        "assignment-register.json": write_json(
            output / "assignment-register.json", manifest.model_dump(mode="json")
        ),
        "plan.json": write_json(output / "plan.json", campaign.model_dump(mode="json")),
    }
    hashes["ingest.py"] = write_bytes(output / "ingest.py", Path(__file__).read_bytes())
    if prior is not None:
        hashes["prior-plan.json"] = write_bytes(output / "prior-plan.json", prior)
    shard_receipts = {}
    for slot, shard in shards.items():
        name = f"confirmation-{slot}.json"
        hashes[name] = write_json(output / name, shard.model_dump(mode="json"))
        shard_receipts[slot] = {
            "plan": name,
            "sha256": hashes[name],
            "assignments": len(shard.assignments),
            "phase_output_name": f"confirmation-{slot}",
            "preserves_full_plan_relative_order": True,
        }
    if protocol_amendment is not None:
        hashes["protocol-amendment.md"] = write_bytes(
            output / "protocol-amendment.md", protocol_amendment.read_bytes()
        )
    if cost_basis is not None:
        hashes["cost-planning-receipts.json"] = write_bytes(
            output / "cost-planning-receipts.json", cost_basis.read_bytes()
        )
    write_json(
        output / "candidate-receipt.json",
        {
            "status": "pending_candidate_not_dispatched",
            "runtime_root": str(runtime_root.resolve()),
            "operator_helper_sha256": digest(Path(__file__).read_bytes()),
            "operator_helper_path": str(Path(__file__).resolve()),
            "registry_sha256": digest(registry_path.read_bytes()),
            "outputs_sha256": hashes,
            "assigned_sessions": 150,
            "assigned_cases": 300,
            "planned_seeds": list(seeds),
            "scheduling": "full_first_seed_then_primary_repeats_then_control_repeats"
            if priority_primary
            else "rotating_model_and_arm_blocks_within_each_seed",
            "scheduling_basis": "pilot_api_cost_only_before_confirmation_outcomes"
            if priority_primary
            else "prospective_balanced_frame",
            "previous_plan_sha256": digest(prior) if prior is not None else None,
            "runtime_protocol_sha256": digest((directory / "PROTOCOL.md").read_bytes()),
            "protocol_amendment_sha256": hashes.get("protocol-amendment.md"),
            "protocol_amendment_scope": "dispatch_order_only_no_participant_configuration_changes"
            if protocol_amendment is not None
            else None,
            "cost_basis_sha256": hashes.get("cost-planning-receipts.json"),
            "cost_basis_callback_field_semantics": {
                "model_starts": (
                    "all_actor_callback_starts_including_scripted_controls_not_paid_requests"
                )
            },
            "family_shards": shard_receipts,
            "shard_union_check": {
                "assignments": len(shard_ids),
                "unique_assignments": len(set(shard_ids)),
                "matches_full_frame": True,
            },
            "execution": {
                "controllers": 5,
                "shared_ledger_cap_usd": "100",
                "cumulative_dispatch_limit_usd": "80",
                "dispatched": False,
            },
        },
    )
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("--register", type=Path, required=True)
    collect.add_argument("--registry", type=Path, required=True)
    collect.add_argument("--campaign", type=Path, action="append", required=True)
    collect.add_argument("--output", type=Path, required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--runtime-root", type=Path, required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--seeds", type=int, nargs=5, default=[701, 702, 703, 704, 705])
    prepare.add_argument("--priority-primary", action="store_true")
    prepare.add_argument("--previous-plan", type=Path)
    prepare.add_argument("--protocol-amendment", type=Path)
    prepare.add_argument("--cost-basis", type=Path)
    args = parser.parse_args()
    if args.command == "collect":
        ingest(args.register, args.registry, args.campaign, args.output)
    else:
        prepare_confirmation(
            args.runtime_root,
            args.output,
            tuple(args.seeds),
            priority_primary=args.priority_primary,
            previous_plan=args.previous_plan,
            protocol_amendment=args.protocol_amendment,
            cost_basis=args.cost_basis,
        )
    print(args.output)


if __name__ == "__main__":
    main()
