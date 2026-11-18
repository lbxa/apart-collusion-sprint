"""Private audit exports preserve original evidence and verify downloaded bytes."""

import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).parents[1] / "research/collusion-resistance-v1/archive.py"


@pytest.fixture
def archive():
    spec = importlib.util.spec_from_file_location("audit_archive", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def inputs(tmp_path, archive):
    runtime, campaign = tmp_path / "runtime", tmp_path / "campaign"
    source = runtime / "harness/src/veracity_harness"
    source.mkdir(parents=True)
    (source / "runner.py").write_text("# frozen source\n")
    research = runtime / "harness/research/collusion-resistance-v1/cases"
    research.mkdir(parents=True)
    (research / "source.md").write_text("Benchmark document\n")
    (runtime / "CONSTITUTION.md").write_text("Participant constitution\n")
    for name in archive.SOURCE_FILES:
        path = runtime / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("{}\n" if path.suffix == ".json" else "# frozen fixture\n")
    for name in archive.SOURCE_ROOTS:
        path = runtime / name
        path.mkdir(parents=True, exist_ok=True)
        if not any(path.rglob("*")):
            (path / "fixture.md").write_text("Frozen source fixture\n")
    run = campaign / "pilot-first/jobs/job/run-one"
    case = run / "case"
    case.mkdir(parents=True)
    (run / "run.json").write_text(
        json.dumps(
            {
                "run_id": "run-one",
                "status": "running",
                "config": {"episodes": 1},
                "episodes": [],
            }
        )
    )
    (case / "juror.trace.calls.jsonl").write_text(
        '{"event":"model_start","messages":["Exact prompt"]}\n'
    )
    (case / "evidence.json").write_text('{"forum":["Exact forum message"]}\n')
    (case / "recovery.sqlite").write_bytes(b"private recovery")
    (run / "wallet.key").write_bytes(b"private wallet")
    (run / ".env").write_text("PRIVATE=fixture\n")
    (campaign / "progress.json").write_text('{"counts":{"running":1}}\n')
    unrelated = campaign / "unrelated/run-two"
    unrelated.mkdir(parents=True)
    (unrelated / "run.json").write_text("{}")
    return runtime, campaign, run


def test_snapshot_contains_raw_evidence_frozen_inputs_and_only_selected_run(
    archive,
    inputs,
    tmp_path,
):
    runtime, campaign, run = inputs
    stage = tmp_path / "stage"
    manifest = archive.stage_snapshot(runtime, campaign, [run], stage, needles=())
    paths = {entry["path"] for entry in manifest["files"]}
    assert "runs/pilot-first/jobs/job/run-one/case/juror.trace.calls.jsonl" in paths
    assert "source/harness/src/veracity_harness/runner.py" in paths
    assert "source/harness/research/collusion-resistance-v1/cases/source.md" in paths
    assert "campaign/progress.json" in paths
    assert not any("unrelated" in path or "sqlite" in path for path in paths)
    assert not any(path.endswith(("wallet.key", ".env")) for path in paths)
    assert archive.verify_snapshot(stage)["files"] == len(paths)


def test_credentials_block_export_without_mutating_originals(archive, inputs, tmp_path):
    runtime, campaign, run = inputs
    trace = run / "case/juror.trace.calls.jsonl"
    trace.write_text('{"content":"known-secret-token"}\n')
    before = trace.read_bytes()
    with pytest.raises(ValueError, match="Credential"):
        archive.stage_snapshot(
            runtime, campaign, [run], tmp_path / "stage", needles=("known-secret-token",)
        )
    assert trace.read_bytes() == before


def test_account_metadata_redaction_records_original_and_export_hash(archive, inputs, tmp_path):
    runtime, campaign, run = inputs
    trace = run / "case/juror.trace.calls.jsonl"
    original = (
        b'{"base_url":"https://api.cloudflare.com/accounts/account-id/ai",'
        b'"content":"Exact answer"}\n'
    )
    trace.write_bytes(original)
    manifest = archive.stage_snapshot(
        runtime,
        campaign,
        [run],
        tmp_path / "stage",
        needles=("account-id",),
        account_ids=("account-id",),
    )
    entry = next(row for row in manifest["files"] if row["path"].endswith("calls.jsonl"))
    exported = (tmp_path / "stage" / entry["path"]).read_bytes()
    assert b"account-id" not in exported
    assert json.loads(exported)["content"] == "Exact answer"
    assert trace.read_bytes() == original
    assert entry["original_sha256"] == hashlib.sha256(original).hexdigest()
    assert entry["export_sha256"] == hashlib.sha256(exported).hexdigest()
    assert entry["redactions"] == [{"field": "line[0].base_url", "kind": "cloudflare_account_id"}]


def test_account_id_in_semantic_text_is_never_silently_redacted(archive, inputs, tmp_path):
    runtime, campaign, run = inputs
    (run / "case/juror.trace.calls.jsonl").write_text('{"content":"account-id"}\n')
    with pytest.raises(ValueError, match="Credential"):
        archive.stage_snapshot(
            runtime,
            campaign,
            [run],
            tmp_path / "stage",
            needles=("account-id",),
            account_ids=("account-id",),
        )


def test_transport_shaped_model_input_is_preserved(archive):
    original = b'{"messages":[{"base_url":"account-id"}]}\n'
    with pytest.raises(ValueError, match="Credential"):
        archive.export_bytes(original, ".jsonl", ("account-id",), ("account-id",))


def test_tampered_or_extra_download_file_fails_verification(archive, inputs, tmp_path):
    runtime, campaign, run = inputs
    stage = tmp_path / "stage"
    archive.stage_snapshot(runtime, campaign, [run], stage, needles=())
    (stage / "campaign/progress.json").write_text("tampered")
    with pytest.raises(ValueError, match="hash"):
        archive.verify_snapshot(stage)


def test_run_outside_campaign_and_symlink_inputs_are_rejected(archive, inputs, tmp_path):
    runtime, campaign, run = inputs
    outside = tmp_path / "outside"
    outside.mkdir()
    with pytest.raises(ValueError, match="campaign"):
        archive.stage_snapshot(runtime, campaign, [outside], tmp_path / "stage", needles=())
    (run / "escaped").symlink_to(outside, target_is_directory=True)
    (outside / "secret.json").write_text('{"secret":"outside"}')
    manifest = archive.stage_snapshot(runtime, campaign, [run], tmp_path / "safe", needles=())
    assert not any("escaped" in row["path"] for row in manifest["files"])


@pytest.fixture
def fake_wandb(monkeypatch):
    state = SimpleNamespace(
        access="PRIVATE",
        initialized=[],
        downloaded=[],
        finished=[],
        corrupt=False,
        api_lookups=[],
        sdk_verified=[],
        sdk_verify_fails=False,
    )

    class Artifact:
        qualified_name = "lbxa-corp/apart-collusion-sprint/test-audit:v3"
        version = "v3"
        digest = "fixture-digest"

        def __init__(self, *args, **kwargs):
            self.files = []
            state.artifact = self

        def add_file(self, path, *, name):
            self.files.append((Path(path), name))

        def wait(self, *, timeout):
            assert timeout > 0
            return self

        def download(self, *, root, skip_cache):
            state.downloaded.append(skip_cache)
            for source, name in self.files:
                target = Path(root) / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
            if state.corrupt:
                (Path(root) / "campaign/progress.json").write_text("corrupted download")
            return root

        def verify(self, *, root):
            state.sdk_verified.append(root)
            if state.sdk_verify_fails:
                raise ValueError("fixture SDK verification failed")
            assert Path(root).is_dir()

    class Api:
        def __init__(self, **kwargs):
            self._service_api = SimpleNamespace(
                execute_graphql=lambda *args, **kwargs: {
                    "project": {"access": state.access},
                }
            )

        def artifact(self, name):
            state.api_lookups.append(name)
            assert name == state.artifact.qualified_name
            return state.artifact

    def init(**kwargs):
        state.initialized.append(kwargs)
        return SimpleNamespace(
            url="https://wandb.ai/lbxa-corp/apart-collusion-sprint/runs/audit",
            summary={},
            log_artifact=lambda artifact: artifact,
            finish=lambda **kwargs: state.finished.append(kwargs),
        )

    monkeypatch.setitem(
        sys.modules,
        "wandb",
        SimpleNamespace(
            Api=Api,
            Artifact=Artifact,
            init=init,
            Settings=lambda **kwargs: kwargs,
        ),
    )
    return state


@pytest.mark.parametrize("access", ["PUBLIC", "RESTRICTED", None])
def test_publish_requires_private_project_before_initializing(
    archive,
    inputs,
    tmp_path,
    fake_wandb,
    access,
):
    runtime, campaign, run = inputs
    stage = tmp_path / "stage"
    archive.stage_snapshot(runtime, campaign, [run], stage, needles=())
    fake_wandb.access = access
    scope = archive.tracking.TrackingScope(
        "apart-collusion-sprint",
        "lbxa-corp",
        "https://api.wandb.ai",
        "fixture-key",
        (),
    )
    with pytest.raises(ValueError, match="PRIVATE"):
        archive.publish_snapshot(stage, scope, "test")
    assert fake_wandb.initialized == []


@pytest.mark.parametrize("use_cache", [False, True])
def test_published_receipt_records_verified_version_digest_and_download_hash(
    archive,
    inputs,
    tmp_path,
    fake_wandb,
    use_cache,
):
    runtime, campaign, run = inputs
    stage = tmp_path / "stage"
    archive.stage_snapshot(runtime, campaign, [run], stage, needles=())
    scope = archive.tracking.TrackingScope(
        "apart-collusion-sprint",
        "lbxa-corp",
        "https://api.wandb.ai",
        "fixture-key",
        (),
    )
    receipt = archive.publish_snapshot(
        stage, scope, "test", use_sdk_cache_for_verification=use_cache
    )
    assert receipt["version"] == "v3"
    assert receipt["digest"] == "fixture-digest"
    assert receipt["download_verified"] is True
    assert receipt["manifest_sha256"] == archive.verify_snapshot(stage)["manifest_sha256"]
    assert fake_wandb.downloaded == [not use_cache]
    assert fake_wandb.api_lookups == [fake_wandb.artifact.qualified_name]
    assert len(fake_wandb.sdk_verified) == 1
    assert receipt["verification_download_mode"] == (
        "sdk_cache_enabled" if use_cache else "fresh_skip_cache"
    )
    assert receipt["all_payloads_sha256_verified"] is True
    assert receipt["sdk_manifest_verified"] is True
    assert fake_wandb.finished == [{"exit_code": 0}]


@pytest.mark.parametrize("use_cache", [False, True])
def test_corrupt_download_does_not_create_verified_receipt(
    archive,
    inputs,
    tmp_path,
    fake_wandb,
    use_cache,
):
    runtime, campaign, run = inputs
    stage = tmp_path / "stage"
    archive.stage_snapshot(runtime, campaign, [run], stage, needles=())
    fake_wandb.corrupt = True
    scope = archive.tracking.TrackingScope(
        "apart-collusion-sprint",
        "lbxa-corp",
        "https://api.wandb.ai",
        "fixture-key",
        (),
    )
    with pytest.raises(ValueError, match="hash"):
        archive.publish_snapshot(stage, scope, "test", use_sdk_cache_for_verification=use_cache)
    assert fake_wandb.finished == [{"exit_code": 1}]


def test_unchanged_snapshot_does_not_create_another_stage(archive, inputs, tmp_path):
    runtime, campaign, run = inputs
    first = archive.stage_snapshot(runtime, campaign, [run], tmp_path / "first", needles=())
    second = archive.stage_snapshot(
        runtime,
        campaign,
        [run],
        tmp_path / "second",
        needles=(),
        previous_content_sha256=first["content_sha256"],
    )
    assert second["content_sha256"] == first["content_sha256"]
    assert not (tmp_path / "second").exists()


@pytest.fixture
def watcher(archive, inputs, tmp_path):
    runtime, campaign, run = inputs
    now = datetime(2026, 11, 17, 17, tzinfo=UTC)
    args = SimpleNamespace(
        runtime_root=runtime,
        campaign_root=campaign,
        phase=["pilot-first", "pilot-rest"],
        stage=tmp_path / "watcher",
        campaign_id="test",
        campaign_file=[],
        benchmark_file=[],
        deadline=now + timedelta(hours=1),
        no_deadline=False,
        log_finished_runs=False,
        prune_verified_payloads=False,
        use_sdk_cache_for_verification=False,
        interval=90,
        finalization_grace_seconds=60,
    )
    scope = archive.tracking.TrackingScope(
        "apart-collusion-sprint",
        "lbxa-corp",
        "https://api.wandb.ai",
        "fixture-key",
        (),
    )
    return args, scope, now, run


def finish_run(run):
    episode = {"episode_id": "case", "outcome": "ABORTED"}
    (run / "run.json").write_text(
        json.dumps(
            {
                "run_id": run.name,
                "status": "complete",
                "config": {
                    "episodes": 1,
                    "scripted_setup_first": True,
                    "treatment": {"transfers": True},
                },
                "models": {"juror-1": "fixture"},
                "episodes": [episode],
            }
        )
    )
    (run / "case").mkdir(exist_ok=True)
    (run / "case/summary.json").write_text(json.dumps(episode))
    page = {"episode_id": "case", "has_more": False, "messages": [], "events": []}
    (run / "case/evidence.json").write_text(
        json.dumps(
            {
                "episode": {"episode_id": "case", "phase": "ABORTED"},
                "settlement": {"episode_id": "case"},
                "balances": {"episode_id": "case", "entitlements": {}, "withdrawal_credits": {}},
                "private_transcripts": {},
                "forum_transcript": [page],
                "chat_audit": [page],
                "forum_audit": [page],
                "credit_transfers": [],
            }
        )
    )

    for name in (
        "scripted-setup.jsonl",
        "opportunities.jsonl",
        "juror-1.trace.jsonl",
        "juror-1.trace.calls.jsonl",
        "gateway-audit/access.jsonl",
    ):
        path = run / "case" / name
        path.parent.mkdir(exist_ok=True)
        path.write_text('{"event":"fixture"}\n')


def write_progress(root, **statuses):
    root.mkdir(parents=True, exist_ok=True)
    counts = dict.fromkeys(("pending", "running", "complete", "failed", "interrupted"), 0)
    counts.update(statuses)
    assignments = []
    existing = list(root.glob("jobs/*/run-*/run.json"))
    for status, count in counts.items():
        for index in range(count):
            job = root / "jobs" / (existing[0].parent.parent.name if existing else f"job-{index}")
            run = existing[0].parent if existing else job / f"run-{root.name}-{index}"
            if status != "pending":
                run.mkdir(parents=True, exist_ok=True)
                if status == "complete":
                    finish_run(run)
                else:
                    (run / "run.json").write_text(
                        json.dumps(
                            {
                                "run_id": run.name,
                                "status": status,
                                "config": {"episodes": 1},
                                "episodes": [],
                            }
                        )
                    )
            assignments.append(
                {
                    "id": job.name,
                    "status": status,
                    "run_id": run.name if status != "pending" else None,
                    "run_directory": str(job) if status != "pending" else None,
                }
            )
    (root / "progress.json").write_text(json.dumps({"counts": counts, "assignments": assignments}))


def test_watcher_keeps_missing_phases_pending_and_skips_unchanged_upload(
    archive,
    watcher,
    fake_wandb,
):
    args, scope, now, run = watcher
    write_progress(args.campaign_root / "pilot-first", complete=1)
    state = archive.watch_once(args, scope, (), now)
    assert state["phases"] == {"pilot-first": "complete", "pilot-rest": "pending"}
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    assert manifest["status"] == "partial"
    assert manifest["phase_statuses"]["pilot-rest"] == "pending"
    archive.watch_once(args, scope, (), now + timedelta(seconds=90))
    assert len(fake_wandb.initialized) == 1
    assert len(list(args.stage.glob("snapshot-*"))) == 1


def test_watcher_archives_terminal_changes_and_late_evidence(archive, watcher, fake_wandb):
    args, scope, now, run = watcher
    for phase in args.phase:
        write_progress(args.campaign_root / phase, running=1)
    archive.watch_once(args, scope, (), now)
    for phase in args.phase:
        write_progress(args.campaign_root / phase, complete=1)
    archive.watch_once(args, scope, (), now + timedelta(seconds=90))
    evidence = json.loads((run / "case/evidence.json").read_bytes())
    evidence["late_retained_transcript"] = "late retained transcript"
    (run / "case/evidence.json").write_text(json.dumps(evidence))
    archive.watch_once(args, scope, (), now + timedelta(seconds=180))
    assert len(fake_wandb.initialized) == 3
    manifests = sorted(args.stage.glob("snapshot-*/archive-manifest.json"))
    assert [json.loads(path.read_bytes())["status"] for path in manifests] == [
        "partial",
        "complete",
        "complete",
    ]


def test_watcher_cannot_broaden_retained_phase_binding(archive, watcher, fake_wandb):
    args, scope, now, run = watcher
    archive.watch_once(args, scope, (), now)
    args.phase.append("unrelated")
    with pytest.raises(ValueError, match="allowlist"):
        archive.watch_once(args, scope, (), now + timedelta(seconds=90))
    assert len(fake_wandb.initialized) == 1


def test_watcher_marks_unfinished_deadline_snapshot_interrupted(archive, watcher, fake_wandb):
    args, scope, now, run = watcher
    write_progress(args.campaign_root / "pilot-first", running=1)
    archive.watch_once(args, scope, (), args.deadline)
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    assert manifest["status"] == "interrupted"
    assert manifest["runs"][0]["status"] == "running"


def test_watcher_finalization_drain_observes_late_terminal_writes(
    archive,
    watcher,
    monkeypatch,
):
    args, scope, now, run = watcher
    clock = SimpleNamespace(now=args.deadline - timedelta(seconds=5))
    calls = []

    class Clock:
        @staticmethod
        def now(zone):
            return clock.now

    monkeypatch.setattr(archive, "datetime", Clock)
    monkeypatch.setattr(
        archive,
        "watch_once",
        lambda args, scope, accounts, now: calls.append(now) or {"final_verified": True},
    )
    monkeypatch.setattr(
        archive.time,
        "sleep",
        lambda seconds: setattr(
            clock,
            "now",
            clock.now + timedelta(seconds=seconds),
        ),
    )
    assert archive.watch(args, scope, ()) == 0
    assert calls[-1] == args.deadline + timedelta(seconds=60)
    assert any(args.deadline < instant < calls[-1] for instant in calls)


def test_manifest_status_tampering_is_detected(archive, inputs, tmp_path):
    runtime, campaign, run = inputs
    stage = tmp_path / "stage"
    archive.stage_snapshot(runtime, campaign, [run], stage, needles=())
    path = stage / archive.MANIFEST
    manifest = json.loads(path.read_bytes())
    manifest["status"] = "complete"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="hash|complete"):
        archive.verify_snapshot(stage)


@pytest.mark.parametrize("field", ["files", "runs"])
def test_duplicate_manifest_entries_are_rejected(archive, inputs, tmp_path, field):
    runtime, campaign, run = inputs
    stage = tmp_path / "stage"
    archive.stage_snapshot(runtime, campaign, [run], stage, needles=())
    path = stage / archive.MANIFEST
    manifest = json.loads(path.read_bytes())
    manifest[field].append(manifest[field][0])
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="duplicate|unique|hash"):
        archive.verify_snapshot(stage)


def test_complete_progress_with_running_run_stays_incomplete(archive, watcher, fake_wandb):
    args, scope, now, run = watcher
    args.phase = ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", complete=1)
    run_manifest = json.loads((run / "run.json").read_bytes())
    run_manifest["status"] = "running"
    (run / "run.json").write_text(json.dumps(run_manifest))
    progress = args.campaign_root / "pilot-first/progress.json"
    payload = json.loads(progress.read_bytes())
    payload["assignments"] = [
        {"id": "job", "status": "complete", "run_id": run.name, "run_directory": str(run.parent)}
    ]
    progress.write_text(json.dumps(payload))
    state = archive.watch_once(args, scope, (), now)
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    assert manifest["status"] != "complete"
    assert state["phases"]["pilot-first"] == "incomplete"
    assert manifest["assignments"][0]["gaps"]


def test_watcher_boundary_fails_when_every_publish_fails(archive, watcher, monkeypatch):
    args, scope, now, run = watcher
    args.finalization_grace_seconds = 0

    class Clock:
        fromisoformat = staticmethod(datetime.fromisoformat)

        @staticmethod
        def now(zone):
            return args.deadline

    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture upload unavailable")

    monkeypatch.setattr(archive, "datetime", Clock)
    monkeypatch.setattr(archive, "publish_snapshot", unavailable)
    assert archive.watch(args, scope, ()) != 0


@pytest.mark.parametrize(
    "damage", ["missing_run", "duplicate_run", "missing_evidence", "wrong_episode"]
)
def test_terminal_assignment_evidence_gaps_are_explicit(
    archive,
    watcher,
    fake_wandb,
    damage,
):
    args, scope, now, run = watcher
    args.phase = ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", complete=1)
    if damage == "missing_run":
        (run / "run.json").unlink()
    elif damage == "duplicate_run":
        other = run.parent / "run-other"
        other.mkdir()
        finish_run(other)
    elif damage == "missing_evidence":
        (run / "case/evidence.json").unlink()
    else:
        evidence = json.loads((run / "case/evidence.json").read_bytes())
        evidence["episode"]["episode_id"] = "another-case"
        (run / "case/evidence.json").write_text(json.dumps(evidence))
    state = archive.watch_once(args, scope, (), now)
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    assert state["phases"]["pilot-first"] == "incomplete"
    assert manifest["status"] == "partial"
    assert manifest["assignments"][0]["gaps"]


@pytest.mark.parametrize("status", ["failed", "interrupted"])
def test_missing_failed_or_interrupted_run_is_an_explicit_gap(
    archive,
    watcher,
    fake_wandb,
    status,
):
    args, scope, now, run = watcher
    args.phase = ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", **{status: 1})
    (run / "run.json").unlink()
    archive.watch_once(args, scope, (), now)
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    row = manifest["assignments"][0]
    assert row["status"] == status
    assert "terminal_assignment_run_missing" in row["gaps"]
    assert row["run_paths"] == []


def test_aggregate_counts_must_match_assignment_rows(archive, watcher, fake_wandb):
    args, scope, now, run = watcher
    args.phase = ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", complete=1)
    progress_path = args.campaign_root / "pilot-first/progress.json"
    progress = json.loads(progress_path.read_bytes())
    progress["counts"]["complete"] = 2
    progress_path.write_text(json.dumps(progress))
    archive.watch_once(args, scope, (), now)
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    assert "assignment_counts_mismatch" in manifest["phase_gaps"]["pilot-first"]
    assert manifest["status"] != "complete"


@pytest.mark.parametrize("key,value", [("schema", "unknown"), ("status", "unknown")])
def test_unknown_manifest_schema_and_status_are_rejected(archive, inputs, tmp_path, key, value):
    runtime, campaign, run = inputs
    stage = tmp_path / "stage"
    archive.stage_snapshot(runtime, campaign, [run], stage, needles=())
    path = stage / archive.MANIFEST
    manifest = json.loads(path.read_bytes())
    manifest[key] = value
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        archive.verify_snapshot(stage)


def test_rehashed_manifest_cannot_claim_incomplete_source_evidence_is_complete(
    archive,
    watcher,
    fake_wandb,
):
    args, scope, now, run = watcher
    args.phase = ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", complete=1)
    archive.watch_once(args, scope, (), now)
    stage = next(args.stage.glob("snapshot-*"))
    path = stage / archive.MANIFEST
    manifest = json.loads(path.read_bytes())
    evidence_row = next(row for row in manifest["files"] if row["path"].endswith("/evidence.json"))
    (stage / evidence_row["path"]).unlink()
    manifest["files"].remove(evidence_row)
    manifest["content_sha256"] = archive.content_sha256(manifest)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="episode evidence"):
        archive.verify_snapshot(stage)


def test_completed_assignment_bytes_are_required_inside_a_partial_cohort(
    archive,
    watcher,
    fake_wandb,
):
    args, scope, now, run = watcher
    write_progress(args.campaign_root / "pilot-first", complete=1)
    archive.watch_once(args, scope, (), now)
    stage = next(args.stage.glob("snapshot-*"))
    path = stage / archive.MANIFEST
    manifest = json.loads(path.read_bytes())
    assert manifest["status"] == "partial"
    row = next(row for row in manifest["files"] if row["path"].endswith("/opportunities.jsonl"))
    (stage / row["path"]).unlink()
    manifest["files"].remove(row)
    manifest["content_sha256"] = archive.content_sha256(manifest)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="episode evidence"):
        archive.verify_snapshot(stage)


def test_earlier_success_does_not_cover_later_failed_upload(
    archive, watcher, fake_wandb, monkeypatch
):
    args, scope, now, run = watcher
    initial = archive.watch_once(args, scope, (), now)
    assert initial["final_verified"] is True
    (run / "case/evidence.json").write_text('{"late":"new evidence"}')

    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture upload unavailable")

    monkeypatch.setattr(archive, "publish_snapshot", unavailable)
    with pytest.raises(RuntimeError):
        archive.watch_once(args, scope, (), now + timedelta(seconds=90))
    state = json.loads((args.stage / "watch-state.json").read_bytes())
    assert state["last_observed_content_sha256"] != state["content_sha256"]
    assert state["final_verified"] is False


@pytest.mark.parametrize(
    "name",
    [
        "scripted-setup.jsonl",
        "opportunities.jsonl",
        "gateway-audit/access.jsonl",
        "juror-1.trace.jsonl",
        "juror-1.trace.calls.jsonl",
    ],
)
def test_complete_assignment_requires_configured_execution_evidence(
    archive,
    watcher,
    fake_wandb,
    name,
):
    args, scope, now, run = watcher
    args.phase = ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", complete=1)
    (run / "case" / name).unlink()
    archive.watch_once(args, scope, (), now)
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    assert manifest["status"] == "partial"
    assert manifest["assignments"][0]["gaps"]


@pytest.mark.parametrize("damage", ["credit_transfers", "balances", "settlement", "messages"])
def test_complete_assignment_requires_financial_identity_and_transcript_payload(
    archive,
    watcher,
    fake_wandb,
    damage,
):
    args, scope, now, run = watcher
    args.phase = ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", complete=1)
    path = run / "case/evidence.json"
    evidence = json.loads(path.read_bytes())
    if damage == "credit_transfers":
        del evidence[damage]
    elif damage == "messages":
        del evidence["forum_transcript"][0]["messages"]
    else:
        evidence[damage]["episode_id"] = "another-case"
    path.write_text(json.dumps(evidence))
    archive.watch_once(args, scope, (), now)
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    assert manifest["status"] == "partial"
    assert manifest["assignments"][0]["gaps"]


@pytest.mark.parametrize("damage", ["missing_file", "missing_root", "unsafe_file"])
def test_mandatory_source_gaps_prevent_complete_archive(archive, watcher, fake_wandb, damage):
    args, scope, now, run = watcher
    args.phase = ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", complete=1)
    if damage == "missing_root":
        shutil.rmtree(args.runtime_root / "harness/docker")
    else:
        path = args.runtime_root / "CONSTITUTION.md"
        content = path.read_bytes()
        path.unlink()
        if damage == "unsafe_file":
            outside = args.runtime_root.parent / "outside-source.md"
            outside.write_bytes(content)
            path.symlink_to(outside)
    archive.watch_once(args, scope, (), now)
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    assert manifest["status"] == "partial"
    assert manifest["source_gaps"]


def test_opt_in_pruning_keeps_manifest_receipt_and_all_originals(archive, watcher, fake_wandb):
    args, scope, now, run = watcher
    args.prune_verified_payloads = True
    raw_before = (run / "case/juror.trace.calls.jsonl").read_bytes()
    source_before = (args.runtime_root / "CONSTITUTION.md").read_bytes()
    state = archive.watch_once(args, scope, (), now)
    stage = next(args.stage.glob("snapshot-*"))
    manifest_path = stage / archive.MANIFEST
    manifest = json.loads(manifest_path.read_bytes())
    receipt = json.loads(Path(state["last_receipt"]).read_bytes())
    assert receipt["download_verified"] is True
    assert hashlib.sha256(manifest_path.read_bytes()).hexdigest() == receipt["manifest_sha256"]
    assert all(not (stage / row["path"]).exists() for row in manifest["files"])
    assert (run / "case/juror.trace.calls.jsonl").read_bytes() == raw_before
    assert (args.runtime_root / "CONSTITUTION.md").read_bytes() == source_before
    assert (run / "case/recovery.sqlite").read_bytes() == b"private recovery"


def test_failed_upload_never_prunes_unverified_staging_payload(archive, watcher, monkeypatch):
    args, scope, now, run = watcher
    args.prune_verified_payloads = True

    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture upload unavailable")

    monkeypatch.setattr(archive, "publish_snapshot", unavailable)
    with pytest.raises(RuntimeError):
        archive.watch_once(args, scope, (), now)
    stage = next(args.stage.glob("snapshot-*"))
    manifest = json.loads((stage / archive.MANIFEST).read_bytes())
    assert all((stage / row["path"]).is_file() for row in manifest["files"])


def test_pruning_rejects_mismatched_receipt_without_deleting_files(
    archive,
    watcher,
    fake_wandb,
):
    args, scope, now, run = watcher
    state = archive.watch_once(args, scope, (), now)
    stage = next(args.stage.glob("snapshot-*"))
    receipt_path = Path(state["last_receipt"])
    receipt = json.loads(receipt_path.read_bytes())
    receipt["content_sha256"] = "0" * 64
    receipt_path.write_text(json.dumps(receipt))
    before = {
        str(path.relative_to(stage)): path.read_bytes()
        for path in stage.rglob("*")
        if path.is_file()
    }
    with pytest.raises(ValueError, match="receipt"):
        archive.prune_verified_payloads(stage, receipt_path)
    assert before == {
        str(path.relative_to(stage)): path.read_bytes()
        for path in stage.rglob("*")
        if path.is_file()
    }


def test_cached_watch_verifies_every_file_before_pruning(archive, watcher, fake_wandb):
    args, scope, now, run = watcher
    args.use_sdk_cache_for_verification = True
    args.prune_verified_payloads = True
    state = archive.watch_once(args, scope, (), now)
    receipt = json.loads(Path(state["last_receipt"]).read_bytes())
    assert fake_wandb.downloaded == [False]
    assert len(fake_wandb.sdk_verified) == 1
    assert len(fake_wandb.api_lookups) == 1
    assert receipt["verification_download_mode"] == "sdk_cache_enabled"
    assert receipt["all_payloads_sha256_verified"] is True
    assert state["final_verified"] is True
    assert Path(state["last_pruned_snapshot"], archive.MANIFEST).is_file()


def test_cached_watch_keeps_payload_if_sdk_verification_fails(archive, watcher, fake_wandb):
    args, scope, now, run = watcher
    args.use_sdk_cache_for_verification = True
    args.prune_verified_payloads = True
    fake_wandb.sdk_verify_fails = True
    with pytest.raises(ValueError, match="SDK verification"):
        archive.watch_once(args, scope, (), now)
    assert fake_wandb.downloaded == [False]
    assert len(fake_wandb.sdk_verified) == 1
    stage = next(args.stage.glob("snapshot-*"))
    manifest = json.loads((stage / archive.MANIFEST).read_bytes())
    assert all((stage / row["path"]).is_file() for row in manifest["files"])
    assert not list(args.stage.glob("receipt-*"))


def test_sdk_cache_cli_flag_requires_watch_upload(archive, tmp_path):
    with pytest.raises(SystemExit) as error:
        archive.main(
            [
                "--runtime-root",
                str(tmp_path),
                "--campaign-root",
                str(tmp_path),
                "--stage",
                str(tmp_path / "stage"),
                "--dotenv",
                str(tmp_path / ".env"),
                "--campaign-id",
                "fixture",
                "--use-sdk-cache-for-verification",
            ]
        )
    assert error.value.code == 2


def test_oserror_diagnostic_keeps_numeric_errno_without_exception_text(
    archive,
    watcher,
    monkeypatch,
    capsys,
):
    args, scope, now, run = watcher
    args.finalization_grace_seconds = 0

    class Clock:
        @staticmethod
        def now(zone):
            return args.deadline

    def unavailable(*args, **kwargs):
        raise OSError(28, "fixture-private-credential must never appear")

    monkeypatch.setattr(archive, "datetime", Clock)
    monkeypatch.setattr(archive, "watch_once", unavailable)
    assert archive.watch(args, scope, ()) == 1
    output = capsys.readouterr().out
    event = json.loads(output.splitlines()[0])
    assert event["errno"] == 28
    assert event["error_type"] == "OSError"
    assert "fixture-private-credential" not in output


def set_controller_status(root, status):
    path = root / "progress.json"
    progress = json.loads(path.read_bytes())
    progress["controller_status"] = status
    path.write_text(json.dumps(progress))


def test_unlimited_watch_is_explicit_in_binding_and_missing_phase_state(
    archive,
    watcher,
    fake_wandb,
):
    args, scope, now, run = watcher
    args.deadline, args.no_deadline = None, True
    write_progress(args.campaign_root / "pilot-first", complete=1)
    set_controller_status(args.campaign_root / "pilot-first", "complete")
    state = archive.watch_once(args, scope, (), now)
    assert state["binding"]["no_deadline"] is True
    assert state["binding"]["deadline_utc"] is None
    assert state["controllers"] == {"pilot-first": "complete", "pilot-rest": "missing"}
    assert state["all_controllers_stopped"] is False
    assert state["phases"]["pilot-rest"] == "pending"


def test_existing_bounded_binding_cannot_become_unlimited(archive, watcher, fake_wandb):
    args, scope, now, run = watcher
    archive.watch_once(args, scope, (), now)
    args.deadline, args.no_deadline = None, True
    with pytest.raises(ValueError, match="deadline"):
        archive.watch_once(args, scope, (), now + timedelta(seconds=90))


def test_unlimited_watch_naturally_finishes_after_verified_terminal_reobservation(
    archive,
    watcher,
    fake_wandb,
    monkeypatch,
):
    args, scope, now, run = watcher
    args.deadline, args.no_deadline = None, True
    for phase in args.phase:
        write_progress(args.campaign_root / phase, complete=1)
        set_controller_status(args.campaign_root / phase, "complete")
    monkeypatch.setattr(archive.time, "sleep", lambda _: pytest.fail("terminal watcher slept"))
    assert archive.watch(args, scope, ()) == 0
    assert len(fake_wandb.initialized) == 1
    state = json.loads((args.stage / "watch-state.json").read_bytes())
    assert state["all_controllers_stopped"] is True
    assert state["final_verified"] is True


@pytest.mark.parametrize("stopped", ["budget_stopped", "failed", "interrupted"])
def test_unlimited_stopped_controller_keeps_pending_evidence_incomplete(
    archive,
    watcher,
    fake_wandb,
    stopped,
):
    args, scope, now, run = watcher
    args.deadline, args.no_deadline, args.phase = None, True, ["pilot-rest"]
    root = args.campaign_root / "pilot-rest"
    write_progress(root, pending=1)
    set_controller_status(root, stopped)
    assert archive.watch(args, scope, ()) == 0
    state = json.loads((args.stage / "watch-state.json").read_bytes())
    assert state["controllers"]["pilot-rest"] == stopped
    assert state["phases"]["pilot-rest"] == "incomplete"
    manifest = json.loads(next(args.stage.glob("snapshot-*/archive-manifest.json")).read_bytes())
    assert manifest["status"] == "partial"
    assert manifest["assignments"][0]["status"] == "pending"


def test_unlimited_missing_and_running_controllers_keep_waiting(
    archive,
    watcher,
    fake_wandb,
    monkeypatch,
):
    args, scope, now, run = watcher
    args.deadline, args.no_deadline = None, True
    write_progress(args.campaign_root / "pilot-first", complete=1)
    set_controller_status(args.campaign_root / "pilot-first", "complete")
    observed = []

    def next_controller(seconds):
        state = json.loads((args.stage / "watch-state.json").read_bytes())
        observed.append(state["controllers"]["pilot-rest"])
        root = args.campaign_root / "pilot-rest"
        if len(observed) == 1:
            write_progress(root, running=1)
            set_controller_status(root, "running")
        else:
            write_progress(root, complete=1)
            set_controller_status(root, "complete")

    monkeypatch.setattr(archive.time, "sleep", next_controller)
    assert archive.watch(args, scope, ()) == 0
    assert observed == ["missing", "running"]


def test_unlimited_final_verification_failure_returns_nonzero(archive, watcher, monkeypatch):
    args, scope, now, run = watcher
    args.deadline, args.no_deadline, args.phase = None, True, ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", complete=1)
    set_controller_status(args.campaign_root / "pilot-first", "complete")

    def unavailable(*args, **kwargs):
        raise RuntimeError("fixture verification failed")

    monkeypatch.setattr(archive, "publish_snapshot", unavailable)
    monkeypatch.setattr(archive.time, "sleep", lambda _: pytest.fail("stopped failure slept"))
    assert archive.watch(args, scope, ()) == 1


def test_unlimited_watch_verifies_late_changed_terminal_bytes(
    archive,
    watcher,
    fake_wandb,
    monkeypatch,
):
    args, scope, now, run = watcher
    args.deadline, args.no_deadline, args.phase = None, True, ["pilot-first"]
    write_progress(args.campaign_root / "pilot-first", complete=1)
    set_controller_status(args.campaign_root / "pilot-first", "complete")
    publish = archive.publish_snapshot
    published = []

    def finish_late(*arguments, **kwargs):
        receipt = publish(*arguments, **kwargs)
        published.append(receipt["content_sha256"])
        if len(published) == 1:
            path = run / "case/evidence.json"
            evidence = json.loads(path.read_bytes())
            evidence["late_retained_metadata"] = True
            path.write_text(json.dumps(evidence))
        return receipt

    monkeypatch.setattr(archive, "publish_snapshot", finish_late)
    assert archive.watch(args, scope, ()) == 0
    assert len(published) == 2 and published[0] != published[1]
    state = json.loads((args.stage / "watch-state.json").read_bytes())
    assert state["last_observed_content_sha256"] == published[-1]
    assert state["final_verified"] is True


@pytest.mark.parametrize(
    "lifetime_args", [[], ["--deadline", "2026-11-18T00:00:00+00:00", "--no-deadline"]]
)
def test_watch_cli_rejects_implicit_or_conflicting_unlimited_mode(archive, tmp_path, lifetime_args):
    with pytest.raises(SystemExit) as error:
        archive.main(
            [
                "--runtime-root",
                str(tmp_path),
                "--campaign-root",
                str(tmp_path),
                "--stage",
                str(tmp_path / "stage"),
                "--dotenv",
                str(tmp_path / ".env"),
                "--campaign-id",
                "fixture",
                "--watch",
                "--upload",
                "--phase",
                "pilot",
                *lifetime_args,
            ]
        )
    assert error.value.code == 2


def test_watch_cli_accepts_explicit_unlimited_without_synthetic_deadline(
    archive,
    tmp_path,
    monkeypatch,
):
    selected = []
    monkeypatch.setattr(archive, "watch", lambda args, scope, accounts: selected.append(args) or 0)
    assert (
        archive.main(
            [
                "--runtime-root",
                str(tmp_path),
                "--campaign-root",
                str(tmp_path),
                "--stage",
                str(tmp_path / "stage"),
                "--dotenv",
                str(tmp_path / ".env"),
                "--campaign-id",
                "fixture",
                "--watch",
                "--upload",
                "--phase",
                "pilot",
                "--no-deadline",
            ]
        )
        == 0
    )
    assert selected[0].no_deadline is True and selected[0].deadline is None


def test_unrecognized_controller_status_does_not_establish_stop(archive, watcher):
    args, scope, now, run = watcher
    write_progress(args.campaign_root / "pilot-first", complete=1)
    set_controller_status(args.campaign_root / "pilot-first", ["complete"])
    assert archive.observe_controllers(args.campaign_root, args.phase) == {
        "pilot-first": "unknown",
        "pilot-rest": "missing",
    }
