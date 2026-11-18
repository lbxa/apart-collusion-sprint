"""Exercise the operator amendment with real SQLite and no model or tracking calls."""

import hashlib
import importlib.util
import json
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

from veracity_harness import campaign
from veracity_harness.spending import CampaignSpending

SCRIPT = Path(__file__).parents[1] / "research/collusion-resistance-v1/amend_budget.py"
SPEC = importlib.util.spec_from_file_location("study_budget_amendment", SCRIPT)
amendment = importlib.util.module_from_spec(SPEC)
AUTHORIZATION = "Lucas authorized total API cap 300 while preserving this ledger"


@pytest.fixture
def study(tmp_path, monkeypatch):
    SPEC.loader.exec_module(amendment)
    monkeypatch.setattr(campaign, "source_identity", lambda: {"fixture.py": "frozen"})
    (tmp_path / "case.md").write_text("Public fixture evidence")
    (tmp_path / "experiment.toml").write_text(
        '[case]\ndocument="case.md"\n[model]\nname="@cf/fixture"\nprovider="cloudflare"\n'
    )
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps(
            {
                "name": "study",
                "assignments": [
                    {"id": "complete", "config": "experiment.toml", "seed": 701},
                    {"id": "pending", "config": "experiment.toml", "seed": 702},
                    {"id": "failed", "config": "experiment.toml", "seed": 703},
                    {"id": "interrupted", "config": "experiment.toml", "seed": 704},
                ],
            }
        )
    )
    frozen = campaign.freeze_plan(plan, Decimal(100))
    output = tmp_path / "campaign"
    output.mkdir()
    ledger = tmp_path / "same-ledger.sqlite"
    spending = CampaignSpending(ledger, Decimal(100))
    with sqlite3.connect(ledger) as db:
        db.executemany(
            "INSERT INTO requests VALUES (?,?,?,?,?)",
            [
                ("charged", "@cf/fixture", "1", "0.5", "charged"),
                ("unknown", "@cf/fixture", "2", "2", "reserved"),
            ],
        )
    spending.increase_limit(Decimal(300), authorization=AUTHORIZATION)
    journal = campaign.CampaignJournal(output / "campaign.sqlite", frozen, ledger)
    journal.record_controller(Decimal(80))
    journal.claim("complete", output / "jobs/complete")
    journal.finish("complete", "complete", run_id="run-complete")
    journal.claim("failed", output / "jobs/failed")
    journal.finish("failed", "failed", run_id="run-failed", error_type="ProviderError")
    journal.claim("interrupted", output / "jobs/interrupted")
    journal.finish("interrupted", "interrupted", run_id="run-interrupted", error_type="Shutdown")
    journal.finish_controller("budget_stopped", "dispatch_limit_reached")
    progress = journal.snapshot()
    (output / "progress.json").write_text(json.dumps(progress))
    (output / "tracking").mkdir()
    (output / "tracking/progress.json").write_text(json.dumps(progress))
    campaign_id = progress["campaign_id"]
    (output / "campaign-tracking.json").write_text(
        json.dumps(
            {
                "campaign_id": campaign_id,
                "fingerprint": frozen.fingerprint,
                "id": "collusion-" + hashlib.sha256(campaign_id.encode()).hexdigest()[:24],
            }
        )
    )
    return output, plan, ledger, tmp_path / "recovery", frozen


def rows(path):
    with sqlite3.connect(path) as db:
        return (
            dict(db.execute("SELECT key,value FROM metadata")),
            db.execute("SELECT * FROM jobs ORDER BY position").fetchall(),
        )


def invoke(study):
    output, plan, _, backup, _ = study
    return amendment.amend(output, plan, Decimal(100), Decimal(300), AUTHORIZATION, backup)


def test_preserves_terminal_jobs_ledger_controllers_and_tracking_backup(study):
    output, plan, ledger, backup, old_frozen = study
    before_metadata, before_jobs = rows(output / "campaign.sqlite")
    with sqlite3.connect(ledger) as db:
        before_requests = db.execute("SELECT * FROM requests ORDER BY id").fetchall()
    old_progress = (output / "progress.json").read_bytes()
    old_tracking = (output / "campaign-tracking.json").read_bytes()
    result = invoke(study)
    after_metadata, after_jobs = rows(output / "campaign.sqlite")
    new_frozen = campaign.freeze_plan(plan, Decimal(300))
    assert before_jobs == after_jobs
    assert {key for key in before_metadata if before_metadata[key] != after_metadata[key]} == {
        "fingerprint",
        "frozen",
        "campaign_id",
    }
    assert after_metadata["controllers"] == before_metadata["controllers"]
    assert after_metadata["ledger"] == before_metadata["ledger"]
    assert after_metadata["fingerprint"] == new_frozen.fingerprint
    assert json.loads(after_metadata["frozen"]) == new_frozen.model_dump(mode="json")
    assert after_metadata["campaign_id"] == new_frozen.name + "-" + new_frozen.fingerprint[:16]
    with sqlite3.connect(ledger) as db:
        assert db.execute("SELECT * FROM requests ORDER BY id").fetchall() == before_requests
        assert db.execute("SELECT limit_usd,halted FROM campaign").fetchone() == ("300", 0)
    backup_metadata, backup_jobs = rows(backup / "campaign.sqlite")
    assert backup_metadata == before_metadata and backup_jobs == before_jobs
    assert (backup / "progress.json").read_bytes() == old_progress
    assert (backup / "campaign-tracking.json").read_bytes() == old_tracking
    assert (backup / "tracking/progress.json").is_file()
    assert not (output / "campaign-tracking.json").exists()
    progress = json.loads((output / "progress.json").read_text())
    assert progress["fingerprint"] == new_frozen.fingerprint
    assert progress["campaign_id"] == after_metadata["campaign_id"]
    assert progress["spending"]["limit_usd"] == "300"
    assert progress["spending"]["unresolved_requests"] == 1
    with sqlite3.connect(output / "campaign.sqlite") as db:
        audit = db.execute(
            "SELECT previous_frozen,new_frozen,previous_campaign_id,new_campaign_id,authorization "
            "FROM operator_cap_amendments"
        ).fetchall()
    assert len(audit) == 1
    assert json.loads(audit[0][0]) == old_frozen.model_dump(mode="json")
    assert json.loads(audit[0][1]) == new_frozen.model_dump(mode="json")
    assert audit[0][2:] == (
        before_metadata["campaign_id"],
        after_metadata["campaign_id"],
        AUTHORIZATION,
    )
    assert result["new_fingerprint"] == new_frozen.fingerprint


def test_changed_source_is_rejected_before_backup_or_mutation(study, monkeypatch):
    output, _, _, backup, _ = study
    before = rows(output / "campaign.sqlite")
    monkeypatch.setattr(campaign, "source_identity", lambda: {"fixture.py": "changed"})
    with pytest.raises(ValueError, match="frozen"):
        invoke(study)
    assert rows(output / "campaign.sqlite") == before
    assert not backup.exists()


def test_running_job_is_rejected_without_recovery_or_mutation(study):
    output, _, _, backup, _ = study
    campaign.CampaignJournal(output / "campaign.sqlite").claim("pending", output / "jobs/pending")
    before = rows(output / "campaign.sqlite")
    with pytest.raises(ValueError, match="running"):
        invoke(study)
    assert rows(output / "campaign.sqlite") == before
    assert not backup.exists()


def test_absent_ledger_authorization_is_rejected(study):
    output, _, ledger, backup, _ = study
    with sqlite3.connect(ledger) as db:
        db.execute("DELETE FROM cap_amendments")
    before = rows(output / "campaign.sqlite")
    with pytest.raises(ValueError, match="authorization"):
        invoke(study)
    assert rows(output / "campaign.sqlite") == before
    assert not backup.exists()


def test_halted_ledger_is_rejected(study):
    output, _, ledger, backup, _ = study
    with sqlite3.connect(ledger) as db:
        db.execute("UPDATE campaign SET halted=1")
    with pytest.raises(ValueError, match="halted"):
        invoke(study)
    assert not backup.exists()


def test_new_frozen_assignments_must_remain_identical(study, monkeypatch):
    _, _, _, backup, _ = study
    real_freeze = amendment.freeze_plan

    def changed(plan, cap):
        frozen = real_freeze(plan, cap)
        if cap == 300:
            return frozen.model_copy(update={"source_sha256": {"changed": "source"}})
        return frozen

    monkeypatch.setattr(amendment, "freeze_plan", changed)
    with pytest.raises(ValueError, match="only"):
        invoke(study)
    assert not backup.exists()
