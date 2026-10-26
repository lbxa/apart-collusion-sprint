import hashlib
import json
from zipfile import ZipFile

import pytest

from veracity_harness.config import Experiment
from veracity_harness.export import export_raw


@pytest.fixture
def recorded_run(tmp_path):
    campaign = tmp_path / "campaign"
    run = campaign / "fixture-run"
    run.mkdir(parents=True)
    manifest = {
        "run_id": "fixture-run",
        "kind": "experiment",
        "status": "failed",
        "config": Experiment(
            model={"name": "fixture/model"}, case={"document": "unused.md"}
        ).model_dump(mode="json"),
        "episodes": [],
    }
    (run / "run.json").write_text(json.dumps(manifest))
    (run / "trace.jsonl").write_text(
        '{"event":"first","value":"private fixture"}\n{"event":"second"}\n'
    )
    (run / "case.md").write_text("Public fixture evidence")
    (run / "checkpoint.sqlite").write_bytes(b"binary-fixture")
    return campaign, run


def test_raw_export_preserves_every_record_and_original_bytes(recorded_run, tmp_path):
    campaign, run = recorded_run
    output = tmp_path / "export"
    archive = export_raw(campaign, output)
    data = json.loads((output / "experiments/fixture-run.json").read_text())
    assert data["recorded_json"]["trace.jsonl"] == [
        {"event": "first", "value": "private fixture"},
        {"event": "second"},
    ]
    assert data["recorded_text"]["case.md"] == "Public fixture evidence"
    assert (
        data["source_sha256"]["checkpoint.sqlite"] == hashlib.sha256(b"binary-fixture").hexdigest()
    )
    with ZipFile(archive) as bundle:
        for path in run.iterdir():
            assert bundle.read(f"originals/fixture-run/{path.name}") == path.read_bytes()
    assert (
        json.loads((output / "campaign-index.json").read_text())["experiments"][0]["status"]
        == "failed"
    )


def test_raw_export_refuses_credentials_in_json_or_checkpoint_bytes(recorded_run, tmp_path):
    campaign, run = recorded_run
    secret = "fixture-key-that-must-never-be-exported"
    (run / "checkpoint.sqlite").write_bytes(b"prefix" + secret.encode() + b"suffix")
    with pytest.raises(ValueError, match="Credential material"):
        export_raw(campaign, tmp_path / "export", secret_values=(secret,))
    assert not (tmp_path / "export/raw-data.zip").exists()
