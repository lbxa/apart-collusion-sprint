"""The operator guard never calls a provider or signals a real process in tests."""

import importlib.util
import json
import signal
import subprocess
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "research/collusion-resistance-v1/deadline_guard.py"
SPEC = importlib.util.spec_from_file_location("study_deadline_guard", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
DEADLINE = datetime.fromisoformat("2026-11-18T00:32:27.232525+00:00")


@pytest.fixture
def guard():
    SPEC.loader.exec_module(MODULE)
    return MODULE


@pytest.fixture
def target(guard):
    return guard.ProcessIdentity(
        pid=71119,
        process_group=71119,
        started="Tue Nov 17 12:21:01 2026",
        module="veracity_harness.campaign",
        output="/study/confirmation-deepseek",
    )


class Clock:
    def __init__(self, now, jump=None):
        self.now = now
        self.jump = jump
        self.sleeps = []

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now = self.jump or self.now + timedelta(seconds=seconds)
        self.jump = None


def fake_clock(guard, monkeypatch, clock):
    monkeypatch.setattr(guard, "utc_now", lambda: clock.now)
    monkeypatch.setattr(guard.time, "sleep", clock.sleep)


def test_forward_utc_jump_reaches_deadline_after_one_short_sleep(guard, target, monkeypatch):
    clock = Clock(DEADLINE - timedelta(hours=1), jump=DEADLINE + timedelta(seconds=1))
    fake_clock(guard, monkeypatch, clock)
    live = {target.pid: target}
    signals, events = [], []
    monkeypatch.setattr(guard, "read_process", lambda pid: live.get(pid))

    def send(group, signum):
        signals.append((group, signum))
        live.clear()

    monkeypatch.setattr(guard.os, "killpg", send)
    assert guard.watch([target], DEADLINE, events.append) == 124
    assert clock.sleeps == [1]
    assert signals == [(target.process_group, signal.SIGTERM)]


def test_already_exited_controller_finishes_without_sleep_or_signal(guard, target, monkeypatch):
    clock = Clock(DEADLINE - timedelta(hours=1))
    fake_clock(guard, monkeypatch, clock)
    monkeypatch.setattr(guard, "read_process", lambda pid: None)
    monkeypatch.setattr(guard.os, "killpg", lambda *a: pytest.fail("signaled exited process"))
    events = []
    assert guard.watch([target], DEADLINE, events.append) == 0
    assert clock.sleeps == []
    assert events[-1]["event"] == "process_exited"


@pytest.mark.parametrize(
    "change",
    [
        {"started": "Tue Nov 17 13:00:00 2026"},
        {"module": "unrelated.module"},
        {"output": "/study/unrelated"},
        {"process_group": 22222},
    ],
)
def test_changed_identity_never_gets_a_signal(guard, target, monkeypatch, change):
    fake_clock(guard, monkeypatch, Clock(DEADLINE))
    monkeypatch.setattr(guard, "read_process", lambda pid: replace(target, **change))
    monkeypatch.setattr(guard.os, "killpg", lambda *a: pytest.fail("signaled unrelated process"))
    events = []
    assert guard.watch([target], DEADLINE, events.append) == 0
    assert events[-1]["event"] == "identity_changed"


def test_owned_group_gets_bounded_interrupt_then_kill(guard, target, monkeypatch):
    clock = Clock(DEADLINE)
    fake_clock(guard, monkeypatch, clock)
    monkeypatch.setattr(guard, "read_process", lambda pid: target)
    signals, events = [], []
    monkeypatch.setattr(guard.os, "killpg", lambda group, signum: signals.append((group, signum)))
    assert guard.watch([target], DEADLINE, events.append) == 124
    assert signals == [(target.pid, signal.SIGTERM), (target.pid, signal.SIGKILL)]
    assert sum(clock.sleeps) == 5
    assert all(0 < delay <= 1 for delay in clock.sleeps)
    assert events[-1]["event"] == "sigkill_sent"


def test_pid_reused_during_cleanup_is_not_killed(guard, target, monkeypatch):
    clock = Clock(DEADLINE)
    fake_clock(guard, monkeypatch, clock)
    signals, events = [], []
    reused = replace(target, started="Tue Nov 17 20:00:00 2026")
    monkeypatch.setattr(guard, "read_process", lambda pid: reused if clock.sleeps else target)
    monkeypatch.setattr(guard.os, "killpg", lambda group, signum: signals.append((group, signum)))
    assert guard.watch([target], DEADLINE, events.append) == 124
    assert signals == [(target.pid, signal.SIGTERM)]
    assert events[-1]["event"] == "identity_changed"


def test_process_reader_extracts_identity_without_logging_arguments(guard, target, monkeypatch):
    command = (
        f"{target.pid} {target.process_group} {target.started} "
        "/target/harness/.venv/bin/python -m veracity_harness.campaign run "
        f"--output {target.output} --budget-usd 100 --dotenv /operator/.env\n"
    )
    calls = []

    def run(arguments, **kwargs):
        calls.append((arguments, kwargs))
        return subprocess.CompletedProcess(arguments, 0, stdout=command, stderr="")

    monkeypatch.setattr(guard.subprocess, "run", run)
    assert guard.read_process(target.pid) == target
    assert calls[0][0] == [
        "/bin/ps",
        "-ww",
        "-p",
        str(target.pid),
        "-o",
        "pid=,pgid=,lstart=,command=",
    ]
    assert calls[0][1]["timeout"] == 1


def test_capture_binds_known_receipt_to_exact_output(guard, target, monkeypatch, tmp_path):
    study = tmp_path / "study"
    study.mkdir()
    expected = replace(target, output=str(study / "confirmation-deepseek"))
    suspension = study / "suspension.json"
    suspension.write_text(
        json.dumps(
            [
                {
                    "phase": "confirmation-deepseek",
                    "controller_pid": target.pid,
                    "process_group": target.process_group,
                }
            ]
        )
    )
    targets = study / "guard-targets.json"
    monkeypatch.setattr(guard, "read_process", lambda pid: expected)
    assert (
        guard.main(
            [
                "capture",
                "--study-root",
                str(study),
                "--suspension",
                str(suspension),
                "--targets",
                str(targets),
            ]
        )
        == 0
    )
    payload = json.loads(targets.read_text())
    assert payload["targets"][0]["started"] == target.started
    assert payload["targets"][0]["output"] == expected.output


def test_non_utc_deadline_is_rejected_before_any_inspection(guard, monkeypatch, tmp_path):
    monkeypatch.setattr(guard, "read_process", lambda pid: pytest.fail("inspected process"))
    with pytest.raises(SystemExit, match="2"):
        guard.main(
            [
                "watch",
                "--targets",
                str(tmp_path / "targets.json"),
                "--deadline",
                "2026-11-18T00:32:27",
                "--receipt",
                str(tmp_path / "guard.jsonl"),
            ]
        )
