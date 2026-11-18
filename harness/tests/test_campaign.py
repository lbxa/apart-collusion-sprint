import asyncio
import json
import shutil
import sys
from decimal import Decimal

import pytest

from veracity_harness.campaign import (
    CampaignJournal,
    CampaignLock,
    freeze_plan,
    run_campaign,
)
from veracity_harness.spending import CampaignSpending, ModelPrice


@pytest.fixture
def campaign(tmp_path, monkeypatch):
    monkeypatch.setattr("veracity_harness.campaign.source_identity", lambda: {"fixture": "hash"})
    (tmp_path / "case.md").write_text("Public case evidence")
    (tmp_path / "experiment.toml").write_text(
        '[case]\ndocument = "case.md"\n[model]\nname = "@cf/fixture"\nprovider = "cloudflare"\n'
    )
    plan = tmp_path / "campaign.toml"
    plan.write_text(
        'name = "pilot"\n[[assignments]]\nid = "first"\nconfig = "experiment.toml"\nseed = 7\n'
        '[[assignments]]\nid = "second"\nconfig = "experiment.toml"\nseed = 8\n'
    )
    return plan, freeze_plan(plan, Decimal("5"))


def test_campaign_freezes_case_bytes_and_effective_configuration(campaign):
    plan, frozen = campaign
    assert [job.experiment.seed for job in frozen.assignments] == [7, 8]
    assert len(frozen.fingerprint) == 64
    (plan.parent / "case.md").write_text("Changed evidence")
    assert freeze_plan(plan, Decimal("5")).fingerprint != frozen.fingerprint
    assert freeze_plan(plan, Decimal("6")).fingerprint != frozen.fingerprint


def test_computed_json_plan_has_the_same_frozen_assignment_identity(campaign):
    plan, frozen = campaign
    serialized = plan.with_suffix(".json")
    serialized.write_text(
        json.dumps(
            {
                "name": "pilot",
                "assignments": [
                    {"id": "first", "config": "experiment.toml", "seed": 7},
                    {"id": "second", "config": "experiment.toml", "seed": 8},
                ],
            }
        )
    )
    assert freeze_plan(serialized, Decimal("5")) == frozen


def test_journal_refuses_changed_plan_or_ledger(campaign, tmp_path):
    _, frozen = campaign
    output = tmp_path / "output"
    ledger = tmp_path / "spending.sqlite"
    with CampaignLock(output):
        CampaignJournal(output / "campaign.sqlite", frozen, ledger)
        changed = frozen.model_copy(update={"fingerprint": "0" * 64})
        with pytest.raises(ValueError, match="frozen"):
            CampaignJournal(output / "campaign.sqlite", changed, ledger)
        with pytest.raises(ValueError, match="ledger"):
            CampaignJournal(output / "campaign.sqlite", frozen, tmp_path / "other.sqlite")


def test_only_pending_assignments_can_start_and_terminal_results_are_immutable(campaign, tmp_path):
    _, frozen = campaign
    with CampaignLock(tmp_path / "output"):
        journal = CampaignJournal(tmp_path / "output/campaign.sqlite", frozen, tmp_path / "cost.db")
        assert journal.claim("first", tmp_path / "output/jobs/first")
        assert not journal.claim("first", tmp_path / "output/jobs/first")
        journal.finish("first", "complete", run_id="run-fixture")
        assert not journal.claim("first", tmp_path / "output/jobs/first")
        with pytest.raises(ValueError, match="terminal"):
            journal.finish("first", "failed", error_type="RuntimeError")


def test_runner_lock_refuses_second_controller(campaign, tmp_path):
    with CampaignLock(tmp_path / "output"):
        with pytest.raises(RuntimeError, match="controller"):
            with CampaignLock(tmp_path / "output"):
                pytest.fail("A concurrent controller acquired the campaign lock")


@pytest.mark.asyncio
async def test_restart_marks_running_interrupted_and_only_dispatches_pending(campaign, tmp_path):
    _, frozen = campaign
    output = tmp_path / "output"
    ledger = tmp_path / "cost.sqlite"
    spending = CampaignSpending(ledger, Decimal("5"))
    with CampaignLock(output):
        journal = CampaignJournal(output / "campaign.sqlite", frozen, ledger)
        journal.claim("first", output / "jobs/first")
    calls = []

    async def runner(experiment, directory, *, spending):
        calls.append(experiment.seed)
        assert experiment.case.document.is_relative_to(output / "frozen-inputs")
        assert experiment.case.document.read_text() == "Public case evidence"
        run = directory / "run-fixture"
        run.mkdir(parents=True)
        (run / "run.json").write_text('{"status":"complete","run_id":"run-fixture"}')
        return run

    first = await run_campaign(frozen, output, spending, runner=runner)
    second = await run_campaign(frozen, output, spending, runner=runner)
    assert calls == [8]
    assert (
        first["counts"]
        == second["counts"]
        == {"pending": 0, "running": 0, "complete": 1, "failed": 0, "interrupted": 1}
    )
    assert first["assignments"][0]["run_directory"] == str((output / "jobs/first").resolve())


@pytest.mark.asyncio
async def test_failure_and_cancellation_keep_assignment_identity(campaign, tmp_path):
    _, frozen = campaign
    spending = CampaignSpending(tmp_path / "cost.sqlite", Decimal("5"))

    async def runner(experiment, directory, *, spending):
        if experiment.seed == 7:
            raise RuntimeError("Do not publish this private provider error")
        raise asyncio.CancelledError()

    output = tmp_path / "output"
    with pytest.raises(asyncio.CancelledError):
        await run_campaign(frozen, output, spending, runner=runner)
    status = CampaignJournal(output / "campaign.sqlite").snapshot()
    assert status["counts"]["failed"] == status["counts"]["interrupted"] == 1
    assert [job["error_type"] for job in status["assignments"]] == [
        "RuntimeError",
        "CancelledError",
    ]
    assert "private provider error" not in json.dumps(status)
    assert all(job["run_directory"] for job in status["assignments"])


@pytest.mark.asyncio
async def test_changed_inputs_rejected_before_any_dispatch(campaign, tmp_path):
    plan, frozen = campaign
    spending = CampaignSpending(tmp_path / "cost.sqlite", Decimal("5"))
    (plan.parent / "case.md").write_text("Mutated after freezing")

    async def forbidden(*args, **kwargs):
        pytest.fail("Changed inputs reached the model runner")

    with pytest.raises(ValueError, match="input"):
        await run_campaign(frozen, tmp_path / "output", spending, runner=forbidden)


@pytest.mark.asyncio
async def test_atomic_progress_is_safe_and_observer_gets_journal_status(campaign, tmp_path):
    _, frozen = campaign
    spending = CampaignSpending(tmp_path / "cost.sqlite", Decimal("5"))
    observed = []

    class Observer:
        def publish(self, snapshot):
            observed.append(snapshot)

    async def runner(experiment, directory, *, spending):
        run = directory / f"run-{experiment.seed}"
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps({"status": "complete", "run_id": run.name}))
        return run

    output = tmp_path / "output"
    status = await run_campaign(frozen, output, spending, runner=runner, observer=Observer())
    assert status["counts"]["complete"] == 2
    assert observed[0]["counts"]["pending"] == 2
    assert observed[-1]["counts"] == json.loads((output / "progress.json").read_text())["counts"]
    assert status["tracking_status"] == "finished"
    assert "Public case evidence" not in (output / "progress.json").read_text()
    assert "experiment" not in observed[-1]["assignments"][0]
    assert not (output / "progress.json.tmp").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("reconcile", (True, False))
@pytest.mark.parametrize("limit", ("1", "1.25"))
async def test_dispatch_gate_preserves_pending_and_resumes_only_unstarted_assignments(
    campaign, tmp_path, reconcile, limit
):
    _, frozen = campaign
    spending = CampaignSpending(tmp_path / "cost.sqlite", Decimal("5"))
    calls, closed = [], []
    price = ModelPrice(id="fixture", context_length=1, pricing={"request": "1.25"})

    class Observer:
        def publish(self, snapshot):
            pass

        def close(self, status):
            closed.append(status)

    async def runner(experiment, directory, *, spending):
        calls.append(experiment.seed)
        request_id = str(experiment.seed)
        spending.reserve(request_id, price, 1)
        if reconcile:
            spending.reconcile(request_id, Decimal("1.25"))
        run = directory / f"run-{experiment.seed}"
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps({"status": "complete", "run_id": run.name}))
        return run

    output = tmp_path / "output"
    stopped = await run_campaign(
        frozen,
        output,
        spending,
        runner=runner,
        observer=Observer(),
        dispatch_limit_usd=Decimal(limit),
    )
    assert calls == [7]
    assert stopped["counts"] == {
        "pending": 1,
        "running": 0,
        "complete": 1,
        "failed": 0,
        "interrupted": 0,
    }
    assert stopped["assignments"][1]["run_directory"] is None
    assert stopped["controller_status"] == "budget_stopped"
    assert stopped["dispatch_limit_usd"] == limit
    assert stopped["dispatch_stop_reason"] == "dispatch_limit_reached"
    assert stopped["spending"]["accounted_usd"] == "1.25"
    assert stopped["spending"]["unresolved_requests"] == (0 if reconcile else 1)
    assert closed == ["budget_stopped"]
    retained = CampaignJournal(output / "campaign.sqlite").snapshot()
    assert retained["controller_status"] == "budget_stopped"
    assert retained["dispatch_stop_reason"] == "dispatch_limit_reached"

    resumed = await run_campaign(
        frozen,
        output,
        spending,
        runner=runner,
        observer=Observer(),
        dispatch_limit_usd=Decimal("3"),
    )
    assert calls == [7, 8]
    assert resumed["counts"]["complete"] == 2
    assert resumed["counts"]["pending"] == 0
    assert resumed["controller_status"] == "complete"
    assert resumed["dispatch_stop_reason"] is None
    assert resumed["fingerprint"] == stopped["fingerprint"] == frozen.fingerprint
    assert [attempt["dispatch_limit_usd"] for attempt in resumed["controllers"]] == [limit, "3"]
    assert resumed["controllers"][0]["dispatch_stop_reason"] == "dispatch_limit_reached"
    assert closed == ["budget_stopped", "complete"]


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", ("0", "-1", "NaN", "Infinity", "5.01"))
async def test_invalid_dispatch_limit_is_rejected_before_journal_or_runner(
    campaign, tmp_path, limit
):
    _, frozen = campaign
    spending = CampaignSpending(tmp_path / "cost.sqlite", Decimal("5"))

    async def forbidden(*args, **kwargs):
        pytest.fail("An invalid dispatch limit reached the runner")

    output = tmp_path / "output"
    with pytest.raises(ValueError, match="dispatch limit"):
        await run_campaign(
            frozen, output, spending, runner=forbidden, dispatch_limit_usd=Decimal(limit)
        )
    assert not (output / "campaign.sqlite").exists()


@pytest.mark.asyncio
async def test_preexisting_unresolved_hold_stops_before_first_assignment(campaign, tmp_path):
    _, frozen = campaign
    spending = CampaignSpending(tmp_path / "cost.sqlite", Decimal("5"))
    price = ModelPrice(id="fixture", context_length=1, pricing={"request": "1"})
    spending.reserve("unresolved", price, 1)

    async def forbidden(*args, **kwargs):
        pytest.fail("An assignment started despite an accounted hold at the dispatch limit")

    status = await run_campaign(
        frozen, tmp_path / "output", spending, runner=forbidden, dispatch_limit_usd=Decimal("1")
    )
    assert status["counts"]["pending"] == 2
    assert status["counts"]["complete"] == status["counts"]["failed"] == 0
    assert status["controller_status"] == "budget_stopped"


@pytest.mark.parametrize("failed, exit_code", ((0, 3), (1, 1)))
def test_cli_distinguishes_dispatch_stop_from_assignment_failure(
    campaign, tmp_path, monkeypatch, capsys, failed, exit_code
):
    from veracity_harness import campaign as controller

    plan, _ = campaign
    limits = []

    async def stopped(*args, dispatch_limit_usd, **kwargs):
        limits.append(dispatch_limit_usd)
        return {
            "counts": {"failed": failed, "interrupted": 0, "pending": 1},
            "controller_status": "failed" if failed else "budget_stopped",
        }

    monkeypatch.setattr(controller, "run_campaign", stopped)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fixture")
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fixture")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "veracity-harness-campaign",
            "run",
            "--plan",
            str(plan),
            "--output",
            str(tmp_path / "output"),
            "--budget-ledger",
            str(tmp_path / "cost.sqlite"),
            "--budget-usd",
            "5",
            "--dispatch-limit-usd",
            "1",
            "--dotenv",
            str(tmp_path / "absent.env"),
        ],
    )
    with pytest.raises(SystemExit) as error:
        controller.main()
    assert error.value.code == exit_code
    assert limits == [Decimal("1")]
    assert json.loads(capsys.readouterr().out)["counts"]["pending"] == 1


def test_campaign_fingerprint_survives_checkout_relocation(campaign, tmp_path):
    plan, frozen = campaign
    relocated = tmp_path / "other-checkout"
    relocated.mkdir()
    for name in ("case.md", "experiment.toml", "campaign.toml"):
        shutil.copyfile(plan.parent / name, relocated / name)
    assert freeze_plan(relocated / "campaign.toml", Decimal("5")).fingerprint == frozen.fingerprint


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ("enter", "before-start", "after-claim", "close", None))
async def test_optional_tracking_never_controls_execution(campaign, tmp_path, caplog, failure):
    _, frozen = campaign
    spending = CampaignSpending(tmp_path / "cost.sqlite", Decimal("5"))
    calls, lifecycle = [], []

    class Observer:
        closed = False
        publishes = 0

        def __enter__(self):
            lifecycle.append("entered")
            if failure == "enter":
                raise RuntimeError("private transport detail")
            return self

        def publish(self, snapshot):
            assert lifecycle and not self.closed
            self.publishes += 1
            if (failure == "before-start" and self.publishes == 1) or (
                failure == "after-claim" and self.publishes == 2
            ):
                raise RuntimeError("private transport detail")

        def close(self, status):
            self.closed = True
            lifecycle.append(status)
            if failure == "close":
                raise RuntimeError("private transport detail")

        def __exit__(self, *_):
            lifecycle.append("exited")

    async def runner(experiment, directory, *, spending):
        calls.append(experiment.seed)
        run = directory / f"run-{experiment.seed}"
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps({"status": "complete", "run_id": run.name}))
        return run

    output = tmp_path / "output"
    status = await run_campaign(frozen, output, spending, runner=runner, observer=Observer)
    assert calls == [7, 8]
    assert status["counts"]["complete"] == 2
    assert status["counts"]["interrupted"] == status["counts"]["failed"] == 0
    assert status["tracking_status"] == ("degraded" if failure else "finished")
    if failure:
        assert status["tracking_error_type"] == "RuntimeError"
        assert "private transport detail" not in caplog.text
    if failure is None:
        assert lifecycle == ["entered", "complete", "exited"]


@pytest.mark.asyncio
async def test_failure_links_retained_run_id_and_status_does_not_change_runner(
    campaign, tmp_path, monkeypatch
):
    _, frozen = campaign
    spending = CampaignSpending(tmp_path / "cost.sqlite", Decimal("5"))
    monkeypatch.setattr("veracity_harness.campaign.socket.gethostname", lambda: "worker-a")

    async def runner(experiment, directory, *, spending):
        run = directory / f"run-{experiment.seed}"
        run.mkdir(parents=True)
        (run / "run.json").write_text('{"status":"failed"}')
        raise RuntimeError("fixture")

    output = tmp_path / "output"
    await run_campaign(frozen, output, spending, runner=runner)
    monkeypatch.setattr("veracity_harness.campaign.socket.gethostname", lambda: "reader-device")
    status = CampaignJournal(output / "campaign.sqlite").snapshot()
    assert status["runner"] == "worker-a"
    assert [job["run_id"] for job in status["assignments"]] == ["run-7", "run-8"]


@pytest.mark.asyncio
async def test_mutation_after_claim_cannot_reach_model_or_private_input_copy(campaign, tmp_path):
    plan, frozen = campaign
    spending = CampaignSpending(tmp_path / "cost.sqlite", Decimal("5"))
    mutated = False

    class Observer:
        def publish(self, snapshot):
            nonlocal mutated
            if snapshot["counts"]["running"] and not mutated:
                (plan.parent / "case.md").write_text("Mutated after claim")
                mutated = True

    async def forbidden(*args, **kwargs):
        pytest.fail("A changed case reached the model runner")

    output = tmp_path / "output"
    with pytest.raises(ValueError, match="input"):
        await run_campaign(frozen, output, spending, runner=forbidden, observer=Observer())
    status = CampaignJournal(output / "campaign.sqlite").snapshot()
    assert status["assignments"][0]["status"] == "failed"
    assert status["assignments"][0]["run_id"] is None
    assert status["assignments"][1]["status"] == "pending"
    assert not list((output / "frozen-inputs").rglob("case.md"))
