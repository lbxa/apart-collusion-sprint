import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from veracity_harness import tracking


def test_scope_defaults_ignore_another_studys_process_scope(tmp_path):
    scope = tracking.resolve_scope(
        tmp_path / ".env",
        environ={
            "WANDB_PROJECT": "apart-epistemics-sprint",
            "WANDB_ENTITY": "another-team",
            "WANDB_BASE_URL": "https://unrelated.example",
            "WANDB_API_KEY": "process-key",
        },
    )
    assert (scope.entity, scope.project, scope.base_url) == (
        "lbxa-corp",
        "apart-collusion-sprint",
        "https://api.wandb.ai",
    )
    assert scope.api_key == "process-key"
    assert "process-key" not in repr(scope)


def test_scope_uses_selected_dotenv_and_explicit_overrides(tmp_path):
    dotenv = tmp_path / "collusion.env"
    dotenv.write_text(
        "WANDB_PROJECT=collusion-replication\n"
        "WANDB_ENTITY=collusion-team\n"
        "WANDB_BASE_URL=https://wandb.example/\n"
        "WANDB_API_KEY=file-key\n"
    )
    scope = tracking.resolve_scope(dotenv, environ={"WANDB_API_KEY": "process-key"})
    assert (scope.entity, scope.project, scope.base_url) == (
        "collusion-team",
        "collusion-replication",
        "https://wandb.example",
    )
    assert scope.api_key == "process-key"
    assert {"file-key", "process-key"} <= set(scope.needles)
    explicit = tracking.resolve_scope(
        dotenv,
        project="collusion-confirmation",
        entity="explicit-team",
        base_url="https://explicit.example",
        environ={},
    )
    assert (explicit.entity, explicit.project, explicit.base_url) == (
        "explicit-team",
        "collusion-confirmation",
        "https://explicit.example",
    )
    assert explicit.api_key == "file-key"


@pytest.mark.parametrize("source", ["argument", "dotenv"])
def test_scope_rejects_epistemics_destination(tmp_path, source):
    dotenv = tmp_path / ".env"
    kwargs = {}
    if source == "dotenv":
        dotenv.write_text("WANDB_PROJECT=apart-epistemics-sprint\n")
    else:
        kwargs["project"] = "apart-epistemics-sprint"
    with pytest.raises(ValueError, match="Epistemics"):
        tracking.resolve_scope(dotenv, environ={}, **kwargs)


@pytest.mark.parametrize(
    "host",
    ["http://remote.example", "https://user:password@remote.example", "https://x.test/?key=bad"],
)
def test_scope_refuses_unsafe_api_hosts(tmp_path, host):
    with pytest.raises(ValueError, match="base URL"):
        tracking.resolve_scope(tmp_path / ".env", base_url=host, environ={})


def test_dry_run_prints_only_safe_scope_without_importing_wandb(tmp_path, monkeypatch, capsys):
    run = tmp_path / "run-safe"
    run.mkdir()
    (run / "run.json").write_text(
        json.dumps(
            {
                "run_id": "run-safe",
                "status": "complete",
                "config": {"name": "safe", "seed": 1},
                "episodes": [],
            }
        )
    )
    dotenv = tmp_path / ".env"
    dotenv.write_text("WANDB_API_KEY=fixture-private-key\n")
    monkeypatch.delenv("WANDB_API_KEY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "veracity-harness-wandb",
            "--dry-run",
            "--results",
            str(run),
            "--dotenv",
            str(dotenv),
        ],
    )
    monkeypatch.setattr(
        tracking, "log_run", lambda *args, **kwargs: pytest.fail("dry run attempted upload")
    )
    tracking.main()
    output = capsys.readouterr().out
    record = json.loads(output)
    assert record["scope"]["project"] == "apart-collusion-sprint"
    assert record["runs"] == [{"run": "run-safe", "eligible": True, "files": 1}]
    assert "fixture-private-key" not in output


def test_secrets_from_both_env_sources_are_checked(tmp_path):
    dotenv = tmp_path / ".env"
    dotenv.write_text("CLOUDFLARE_API_TOKEN=file-token\n")
    scope = tracking.resolve_scope(dotenv, environ={"CLOUDFLARE_API_TOKEN": "process-token"})
    run = tmp_path / "run"
    run.mkdir()
    (run / "log.json").write_text('{"credential": "file-token"}')
    with pytest.raises(ValueError, match="Credential"):
        tracking.check_secrets(run, scope.needles, include_private_evidence=True)


def test_upload_never_exports_recovery_sqlite_or_ledgers(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    for name in ("spending.sqlite", "recovery.sqlite-wal", "agents.sqlite-shm", "engine.db"):
        (run / name).write_bytes(b"private")
    (run / "evidence.json").write_text("{}")
    assert [
        path.name
        for path in tracking.uploadable(
            run, include_private_evidence=True, include_model_calls=True
        )
    ] == ["evidence.json"]


def test_upload_excludes_environment_files_and_symlinks(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    outside = tmp_path / "private.txt"
    outside.write_text("not run evidence")
    (run / "outside.txt").symlink_to(outside)
    (run / ".env").write_text("PRIVATE=value")
    (run / ".env.backup").write_text("PRIVATE=value")
    (run / "evidence.json").write_text("{}")
    assert [path.name for path in tracking.uploadable(run, include_private_evidence=True)] == [
        "evidence.json"
    ]


def test_access_check_uses_explicit_scope_and_never_initializes_a_run(tmp_path, monkeypatch):
    calls = []

    def create_api(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(project=lambda project, *, entity: (project, entity))

    monkeypatch.setitem(
        sys.modules,
        "wandb",
        SimpleNamespace(
            Api=create_api,
            init=lambda **kwargs: pytest.fail("access check created a run"),
        ),
    )
    scope = tracking.resolve_scope(tmp_path / ".env", environ={"WANDB_API_KEY": "fixture-key"})
    tracking.verify_access(scope)
    assert calls == [{"api_key": "fixture-key", "overrides": scope.public(), "timeout": 30}]


def test_access_errors_do_not_disclose_provider_text(tmp_path, monkeypatch):
    def fail_api(**kwargs):
        raise ConnectionError("request contained fixture-key")

    monkeypatch.setitem(sys.modules, "wandb", SimpleNamespace(Api=fail_api))
    scope = tracking.resolve_scope(tmp_path / ".env", environ={"WANDB_API_KEY": "fixture-key"})
    with pytest.raises(RuntimeError, match="ConnectionError") as error:
        tracking.verify_access(scope)
    assert "fixture-key" not in str(error.value)


def test_upload_passes_explicit_host_credentials_and_destination(tmp_path, monkeypatch):
    calls = []
    run = tmp_path / "run"
    run.mkdir()
    (run / "evidence.json").write_text("{}")
    (run / "run.json").write_text("{}")
    monkeypatch.setattr(
        tracking,
        "run_metrics",
        lambda directory: ({"name": "case", "seed": 1, "run_id": "run"}, {}, [], []),
    )
    remote = SimpleNamespace(
        summary={},
        url=None,
        log_artifact=lambda artifact: None,
        finish=lambda: None,
    )

    def start_run(**kwargs):
        calls.append(kwargs)
        return remote

    monkeypatch.setitem(
        sys.modules,
        "wandb",
        SimpleNamespace(
            init=start_run,
            Settings=lambda **kwargs: kwargs,
            Artifact=lambda *args, **kwargs: SimpleNamespace(add_file=lambda *a, **kw: None),
        ),
    )
    scope = tracking.resolve_scope(tmp_path / ".env", environ={"WANDB_API_KEY": "fixture-key"})
    tracking.log_run(run, scope)
    assert calls[0]["settings"] == {
        "base_url": "https://api.wandb.ai",
        "api_key": "fixture-key",
        **tracking.SDK_PRIVACY_SETTINGS,
    }
    assert (calls[0]["entity"], calls[0]["project"]) == (scope.entity, scope.project)
    assert not (run / tracking.MARKER).exists()


def test_live_campaign_preserves_id_and_exports_only_safe_progress(tmp_path, monkeypatch):
    starts, artifacts, metrics, finishes = [], [], [], []

    class Artifact:
        def __init__(self, *args, **kwargs):
            self.files = []

        def add_file(self, path, *, name):
            self.files.append((name, json.loads(Path(path).read_text())))

    def start_run(**kwargs):
        starts.append(kwargs)
        return SimpleNamespace(
            summary={},
            log=metrics.append,
            log_artifact=lambda artifact: artifacts.append(artifact),
            finish=lambda **options: finishes.append(options),
        )

    monkeypatch.setattr(tracking, "verify_access", lambda scope: None)
    monkeypatch.setitem(
        sys.modules,
        "wandb",
        SimpleNamespace(init=start_run, Settings=lambda **kwargs: kwargs, Artifact=Artifact),
    )
    scope = tracking.resolve_scope(tmp_path / ".env", environ={"WANDB_API_KEY": "fixture-key"})
    snapshot = {
        "campaign_id": "campaign-abc",
        "fingerprint": "a" * 64,
        "runner": "cloud-worker-1",
        "counts": {"pending": 1, "running": 0, "complete": 1, "failed": 0, "interrupted": 0},
        "spending": {"limit_usd": "10", "accounted_usd": "0.25", "charged_usd": "0.20"},
        "assignments": [
            {"id": "job-1", "status": "complete", "run_id": "run-1", "prompt": "fixture-key"}
        ],
        "secret": "fixture-key",
    }
    for _ in range(2):
        with tracking.LiveCampaignTracking(scope, "campaign-abc", tmp_path) as observer:
            observer.publish(snapshot)
            observer.close("complete")
    assert starts[0]["id"] == starts[1]["id"]
    assert starts[0]["resume"] == "allow"
    assert starts[0]["project"] == "apart-collusion-sprint"
    assert metrics[0]["counts/complete"] == 1
    assert metrics[0]["spending/charged_usd"] == 0.2
    assert finishes == [{"exit_code": 0}, {"exit_code": 0}]
    progress = artifacts[0].files[0]
    assert progress[0] == "progress.json"
    assert "fixture-key" not in json.dumps(progress)
    marker = json.loads((tmp_path / "campaign-tracking.json").read_text())
    assert marker["status"] == "complete"
    assert "fixture-key" not in json.dumps(marker)


def test_live_campaign_rejects_cross_project_resume_before_sdk_use(tmp_path, monkeypatch):
    (tmp_path / "campaign-tracking.json").write_text(
        json.dumps({"campaign_id": "campaign-abc", "scope": {"project": "apart-epistemics-sprint"}})
    )
    monkeypatch.setattr(
        tracking, "verify_access", lambda scope: pytest.fail("scope mismatch reached W&B")
    )
    scope = tracking.resolve_scope(tmp_path / ".env", environ={})
    with pytest.raises(ValueError, match="scope"):
        with tracking.LiveCampaignTracking(scope, "campaign-abc", tmp_path):
            pass


@pytest.fixture
def upload_sdk(monkeypatch):
    observed = {"starts": [], "artifacts": [], "tables": [], "fail_finish": False}

    class Artifact:
        def __init__(self, *args, **kwargs):
            self.files = {}

        def add_file(self, path, *, name):
            self.files[name] = Path(path).read_text()

    def start(**kwargs):
        observed["starts"].append(kwargs)

        def finish():
            if observed["fail_finish"]:
                observed["fail_finish"] = False
                raise ConnectionError("interrupted after remote initialization")

        return SimpleNamespace(
            summary={},
            log=lambda table: observed["tables"].append(table),
            log_artifact=lambda artifact: observed["artifacts"].append(artifact),
            url="https://wandb.ai/lbxa-corp/apart-collusion-sprint/runs/fixture",
            finish=finish,
        )

    monkeypatch.setitem(
        sys.modules,
        "wandb",
        SimpleNamespace(
            init=start,
            Settings=lambda **kwargs: kwargs,
            Artifact=Artifact,
            Table=lambda **kwargs: kwargs,
        ),
    )
    return observed


def private_run(root):
    run = root / "run-private"
    (run / "case-1").mkdir(parents=True)
    manifest = {
        "run_id": "run-private",
        "status": "complete",
        "config": {"name": "private-study", "seed": 1, "reference_claim": "private reference"},
        "episodes": [
            {
                "episode_id": "case-1",
                "outcome": "SETTLED_CREATOR",
                "verdict_correct": True,
            }
        ],
        "models": {"creator": "@cf/example/model"},
    }
    (run / "run.json").write_text(json.dumps(manifest))
    (run / "case-1/evidence.json").write_text(
        json.dumps(
            {
                "forum_transcript": [
                    {"messages": [{"content": "private public-forum discussion"}]}
                ],
                "private_transcripts": [{"messages": [{"body": "private pairwise discussion"}]}],
            }
        )
    )
    (run / "probe.jsonl").write_text(
        json.dumps(
            {
                "actor_id": "creator",
                "probability": 50,
                "answer": "private probe explanation",
            }
        )
    )
    return run


def test_default_upload_releases_only_numeric_and_provenance_projection(tmp_path, upload_sdk):
    run = private_run(tmp_path)
    original = (run / "case-1/evidence.json").read_bytes()
    scope = tracking.resolve_scope(tmp_path / ".env", environ={"WANDB_API_KEY": "fixture-key"})
    tracking.log_run(run, scope)
    files = upload_sdk["artifacts"][0].files
    assert set(files) == {tracking.PUBLIC_EXPORT}
    remote_data = json.dumps([upload_sdk["starts"][0]["config"], files, upload_sdk["tables"]])
    assert "private reference" not in remote_data
    assert "private public-forum discussion" not in remote_data
    assert "private pairwise discussion" not in remote_data
    assert "private probe explanation" not in remote_data
    assert (run / "case-1/evidence.json").read_bytes() == original
    assert tracking.UPLOAD_INTENT not in files


@pytest.mark.parametrize("window", ["during_finish", "after_finish_before_marker"])
def test_upload_crash_resumes_the_same_scoped_remote_id(tmp_path, monkeypatch, upload_sdk, window):
    run = private_run(tmp_path)
    scope = tracking.resolve_scope(tmp_path / ".env", environ={"WANDB_API_KEY": "fixture-key"})
    if window == "during_finish":
        upload_sdk["fail_finish"] = True
    else:
        persist = tracking.persist_metadata
        attempted = []

        def interrupt_marker(path, payload):
            if path.name == tracking.MARKER and not attempted:
                attempted.append(True)
                raise OSError("interrupted before local success marker")
            persist(path, payload)

        monkeypatch.setattr(tracking, "persist_metadata", interrupt_marker)
    with pytest.raises((ConnectionError, OSError)):
        tracking.log_run(run, scope)
    assert not (run / tracking.MARKER).exists()
    intent = json.loads((run / tracking.UPLOAD_INTENT).read_text())
    tracking.log_run(run, scope)
    assert len(upload_sdk["starts"]) == 2
    assert upload_sdk["starts"][0]["id"] == upload_sdk["starts"][1]["id"] == intent["id"]
    assert all(start["resume"] == "allow" for start in upload_sdk["starts"])
    assert (run / tracking.MARKER).exists()


def test_upload_intent_refuses_scope_and_immutable_input_changes(tmp_path, upload_sdk):
    run = private_run(tmp_path)
    scope = tracking.resolve_scope(tmp_path / ".env", environ={"WANDB_API_KEY": "fixture-key"})
    tracking.log_run(run, scope)
    other = tracking.resolve_scope(
        tmp_path / ".env", project="collusion-other", environ={"WANDB_API_KEY": "fixture-key"}
    )
    with pytest.raises(ValueError, match="intent"):
        tracking.log_run(run, other)
    manifest = json.loads((run / "run.json").read_text())
    manifest["config"]["seed"] = 2
    (run / "run.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="intent"):
        tracking.log_run(run, scope)
    assert len(upload_sdk["starts"]) == 1


def test_raw_model_calls_require_separate_private_evidence_release(tmp_path):
    run = private_run(tmp_path)
    with pytest.raises(ValueError, match="private-evidence"):
        tracking.uploadable(run, include_model_calls=True)
