"""Read-only ingestion and prospective confirmation scheduling; no model calls."""

import importlib.util
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from test_resistance import retained_fixture

from veracity_harness.campaign import CampaignJournal, FrozenAssignment, FrozenCampaign
from veracity_harness.config import load_experiment
from veracity_harness.resistance import (
    ARMS,
    CONFIRMATION_CASES,
    PRIMARY_ARMS,
    STUDY_DIRECTORY,
    V1_ROSTER,
    ResistanceAssignment,
    ResistanceManifest,
    assignment_fingerprint,
    freeze_config,
)

SCRIPT = Path(__file__).parents[1] / "research/collusion-resistance-v1/ingest.py"
pytest_plugins = ("test_analysis",)


@pytest.fixture
def operator():
    spec = importlib.util.spec_from_file_location("resistance_ingest", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_confirmation_candidate_is_complete_pending_balanced_and_not_live(operator, tmp_path):
    output = tmp_path / "candidate"
    operator.prepare_confirmation(Path(__file__).parents[2], output, tuple(range(701, 706)))
    manifest = ResistanceManifest.model_validate_json(
        (output / "assignment-register.json").read_bytes()
    )
    plan = json.loads((output / "plan.json").read_text())
    assert len(manifest.assignments) == len(plan["assignments"]) == 150
    assert all(
        job.status == "pending" and job.run_directory is None for job in manifest.assignments
    )
    assert {job.model_slot for job in manifest.assignments[:5]} == set(V1_ROSTER)
    for model in V1_ROSTER:
        assert {job.arm for job in manifest.assignments[:30] if job.model_slot == model} == set(
            ARMS
        )
    with pytest.raises(FileExistsError):
        operator.prepare_confirmation(Path(__file__).parents[2], output, tuple(range(701, 706)))


def test_wrong_imported_runtime_cannot_freeze_candidate(operator, tmp_path):
    with pytest.raises(ValueError, match="runtime"):
        operator.prepare_confirmation(
            tmp_path / "other-runtime", tmp_path / "candidate", tuple(range(5))
        )


def test_known_identifiers_are_removed_without_claiming_verified_blinding(operator):
    text = "@cf/openai/gpt-oss-120b says juror-1 should read case-test before acting."
    shown = operator.blind_text(text, {"juror-1": "actor-03", "case-test": "case"})
    assert "gpt-oss" not in shown and "juror-1" not in shown and "case-test" not in shown
    assert "actor-03" in shown


def journal_for(tmp_path, job):
    provider, _, model = V1_ROSTER[job.model_slot]
    experiment = load_experiment(
        Path(job.config), provider=provider, model_name=model, seed=job.seed
    )
    frozen = FrozenCampaign(
        name="ingest-fixture",
        fingerprint="a" * 64,
        source_sha256={},
        budget_usd="100",
        assignments=[
            FrozenAssignment(
                id=job.job_id,
                experiment=experiment,
                config_sha256=job.config_sha256,
                inputs_sha256={},
                documents_sha256={},
                fingerprint="b" * 64,
            )
        ],
    )
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    journal = CampaignJournal(campaign / "campaign.sqlite", frozen, tmp_path / "ledger.sqlite")
    return campaign, journal


@pytest.fixture
def pending_inputs(tmp_path):
    provider, _, model = V1_ROSTER["deepseek"]
    config = STUDY_DIRECTORY / "pilot-one-case.toml"
    job = ResistanceAssignment(
        job_id="pilot-fixture",
        model_slot="deepseek",
        arm="honest-false",
        seed=700,
        config=str(config),
        sourcecases=(CONFIRMATION_CASES[0],),
        phase="exploratory",
        **freeze_config(config, model_id=model, provider=provider, seed=700),
    )
    job = job.model_copy(update={"job_fingerprint": assignment_fingerprint(job)})
    slots = [
        {"model_slot": slot, "provider": p, "family": family, "model_id": model_id}
        for slot, (p, family, model_id) in V1_ROSTER.items()
    ]
    manifest = ResistanceManifest(
        model_slots=slots, assignments=(job.model_dump(mode="json"),), phase="exploratory"
    )
    register = tmp_path / "register.json"
    register.write_text(manifest.model_dump_json())
    campaign, journal = journal_for(tmp_path, job)
    return register, campaign, journal, job


def test_running_jobs_never_get_frozen_session_pins(
    operator, pending_inputs, tmp_path, monkeypatch
):
    register, campaign, journal, job = pending_inputs
    journal.claim(job.job_id, campaign / "jobs" / job.job_id)
    before = register.read_bytes()
    monkeypatch.setattr(
        operator, "session_sha256", lambda directory: pytest.fail("Running runs must not be hashed")
    )
    output = tmp_path / "running-snapshot"
    receipt = operator.ingest(register, STUDY_DIRECTORY / "scenario-bank.json", [campaign], output)
    assert receipt["deferred_jobs"][0]["status"] == "running"
    derived = ResistanceManifest.model_validate_json(
        (output / "assignment-register.json").read_bytes()
    )
    assert (
        derived.assignments[0].run_directory is None
        and derived.assignments[0].session_sha256 is None
    )
    assert register.read_bytes() == before
    assert journal.snapshot()["counts"]["running"] == 1


@pytest.mark.parametrize("status", ["complete", "failed", "interrupted"])
def test_terminal_job_without_directory_is_explicit_missing_evidence(
    operator, pending_inputs, tmp_path, status
):
    register, campaign, journal, job = pending_inputs
    journal.claim(job.job_id, campaign / "jobs" / job.job_id)
    journal.finish(job.job_id, status)
    with sqlite3.connect(campaign / "campaign.sqlite") as db:
        db.execute("UPDATE jobs SET run_directory=NULL WHERE id=?", (job.job_id,))
    receipt = operator.ingest(
        register, STUDY_DIRECTORY / "scenario-bank.json", [campaign], tmp_path / "missing"
    )
    assert receipt["deferred_jobs"][0]["reason"] == "terminal_job_missing_run_directory"


@pytest.fixture
def terminal_inputs(evidence_fixture, tmp_path):
    manifest, registry, directory, _ = retained_fixture(evidence_fixture, tmp_path)
    job = manifest.assignments[0]
    campaign, journal = journal_for(tmp_path, job)
    parent = campaign / "jobs" / job.job_id
    parent.mkdir(parents=True)
    target = parent / "run-fixture"
    shutil.move(directory, target)
    run = json.loads((target / "run.json").read_text())
    run["run_id"] = target.name
    (target / "run.json").write_text(json.dumps(run))
    journal.claim(job.job_id, parent)
    journal.finish(job.job_id, "complete", run_id=target.name)
    payload = manifest.model_dump(mode="json")
    payload["assignments"][0].update(
        status="pending",
        run_directory=None,
        run_id=None,
        run_manifest_sha256=None,
        session_sha256=None,
    )
    register, registry_path = tmp_path / "terminal-register.json", tmp_path / "registry.json"
    register.write_text(json.dumps(payload))
    registry_path.write_text(registry.model_dump_json())
    return register, registry_path, campaign, target


def test_complete_journal_with_unfinalized_manifest_is_deferred(
    operator, terminal_inputs, tmp_path
):
    register, registry, campaign, directory = terminal_inputs
    payload = json.loads((directory / "run.json").read_text())
    payload["status"] = "running"
    (directory / "run.json").write_text(json.dumps(payload))
    output = tmp_path / "mismatched"
    receipt = operator.ingest(register, registry, [campaign], output)
    assert receipt["deferred_jobs"][0]["reason"] == "journal_run_status_mismatch"
    assert receipt["deferred_jobs"][0]["run_status"] == "running"
    assert not json.loads((output / "case-observations.json").read_text())[0]["evidence_sha256"]


def test_missing_capability_files_are_hashed_presence_and_null_not_zero(
    operator, terminal_inputs, tmp_path
):
    register, registry, campaign, _ = terminal_inputs
    output = tmp_path / "missing-capability"
    receipt = operator.ingest(register, registry, [campaign], output)
    assert receipt["capability_evidence_gaps"]
    mechanics = json.loads((output / "actor-mechanics.json").read_text())[0]
    assert mechanics["capability_evidence_gaps"]
    for actor in mechanics["actors"]:
        assert actor["opportunities"] is None
        assert actor["opportunity_model_calls"] is None
        assert actor["observed_model_starts"] is None
        assert actor["model_trace_sha256"] is None
    packet_path = next((output / "review-packets").glob("*.json"))
    packet = json.loads(packet_path.read_text())
    assert "opportunities_missing" in packet["blinding_gaps"]
    assert any(gap.startswith("model_trace_missing:actor-") for gap in packet["blinding_gaps"])
    assert (output / "ingest.py").read_bytes() == SCRIPT.read_bytes()


def test_primary_priority_reorders_only_and_keeps_full_pending_frame(operator, tmp_path):
    runtime = Path(__file__).parents[2]
    old, new = tmp_path / "old", tmp_path / "priority"
    operator.prepare_confirmation(runtime, old, tuple(range(701, 706)))
    cost_basis = tmp_path / "cost.json"
    cost_basis.write_text('{"purpose":"cost-only fixture, no model outcomes"}')
    operator.prepare_confirmation(
        runtime,
        new,
        tuple(range(701, 706)),
        priority_primary=True,
        previous_plan=old / "plan.json",
        protocol_amendment=STUDY_DIRECTORY / "PROTOCOL.md",
        cost_basis=cost_basis,
    )
    prior = ResistanceManifest.model_validate_json((old / "assignment-register.json").read_bytes())
    updated = ResistanceManifest.model_validate_json(
        (new / "assignment-register.json").read_bytes()
    )
    assert {job.job_id: job.job_fingerprint for job in prior.assignments} == {
        job.job_id: job.job_fingerprint for job in updated.assignments
    }
    assert {job.seed for job in updated.assignments[:30]} == {701}
    assert all(job.arm in PRIMARY_ARMS and job.seed != 701 for job in updated.assignments[30:70])
    assert all(job.arm not in PRIMARY_ARMS and job.seed != 701 for job in updated.assignments[70:])
    assert (new / "prior-plan.json").read_bytes() == (old / "plan.json").read_bytes()
    shard_ids = []
    for model in V1_ROSTER:
        shard = json.loads((new / f"confirmation-{model}.json").read_text())
        assert len(shard["assignments"]) == 30
        ids = [job["id"] for job in shard["assignments"]]
        assert ids == [job.job_id for job in updated.assignments if job.model_slot == model]
        shard_ids.extend(ids)
    assert len(shard_ids) == len(set(shard_ids)) == 150
    assert (new / "cost-planning-receipts.json").read_bytes() == cost_basis.read_bytes()
    assert (new / "protocol-amendment.md").read_bytes() == (
        STUDY_DIRECTORY / "PROTOCOL.md"
    ).read_bytes()
