"""No paid calls: exercise the detached operator launch boundary with fake children."""

import importlib.util
import json
import signal
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[1] / "research/collusion-resistance-v1/local_run.py"
SPEC = importlib.util.spec_from_file_location("local_study_runner", SCRIPT)
launcher = importlib.util.module_from_spec(SPEC)


@pytest.fixture
def loaded():
    SPEC.loader.exec_module(launcher)
    return launcher


@pytest.fixture
def inputs(tmp_path):
    runtime = tmp_path / "frozen"
    (runtime / "harness/src/veracity_harness").mkdir(parents=True)
    (runtime / "harness/src/veracity_harness/campaign.py").touch()
    python = tmp_path / "python"
    python.touch()
    provider = tmp_path / "provider.env"
    provider.write_text(
        "CLOUDFLARE_ACCOUNT_ID=account-fixture\n"
        "CLOUDFLARE_API_TOKEN=provider-secret-fixture\n"
        "WANDB_API_KEY=wrong-provider-key\nIGNORED_PROVIDER=private\n"
    )
    tracking = tmp_path / "tracking.env"
    tracking.write_text(
        "WANDB_API_KEY=tracking-secret-fixture\nWANDB_ENTITY=lbxa-corp\n"
        "WANDB_PROJECT=apart-collusion-sprint\nWANDB_BASE_URL=https://api.wandb.ai\n"
        "CLOUDFLARE_API_TOKEN=wrong-tracking-token\nIGNORED_TRACKING=private\n"
    )
    plan = tmp_path / "plan.json"
    plan.write_text('{"name":"fixture","assignments":[]}')
    return [
        "--runtime-root",
        str(runtime),
        "--python",
        str(python),
        "--provider-env",
        str(provider),
        "--tracking-env",
        str(tracking),
        "--plan",
        str(plan),
        "--output",
        str(tmp_path / "output"),
        "--budget-ledger",
        str(tmp_path / "shared.sqlite"),
        "--dispatch-limit-usd",
        "10",
        "--deadline",
        (datetime.now(UTC) + timedelta(hours=1)).isoformat(),
        "--wandb",
    ]


class Child:
    pid = 43210

    def __init__(self, waits=(0,)):
        self.waits = iter(waits)
        self.returncode = None
        self.timeouts = []

    def wait(self, timeout):
        self.timeouts.append(timeout)
        result = next(self.waits)
        if result == "timeout":
            raise subprocess.TimeoutExpired("fixture-child", timeout)
        self.returncode = result
        return result

    def poll(self):
        return self.returncode


def test_launch_scopes_credentials_and_default_budget(loaded, inputs, monkeypatch, capsys):
    calls = []
    child = Child()

    def popen(command, **kwargs):
        calls.append((command, kwargs))
        return child

    monkeypatch.setattr(loaded.subprocess, "Popen", popen)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "explicit-process-token")
    monkeypatch.setenv("WANDB_API_KEY", "epistemics-secret")
    monkeypatch.setenv("WANDB_PROJECT", "apart-epistemics-sprint")
    monkeypatch.setenv("WANDB_RUN_ID", "wrong-inherited-run")
    monkeypatch.setenv("PYTHONPATH", "/wrong/runtime")
    assert loaded.main(inputs) == 0
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:4] == [inputs[3], "-m", "veracity_harness.campaign", "run"]
    assert command[command.index("--budget-usd") + 1] == "100"
    assert command[command.index("--dispatch-limit-usd") + 1] == "10"
    assert command[command.index("--dotenv") + 1] == inputs[7]
    assert "--wandb" in command
    assert kwargs["cwd"] == Path(inputs[1])
    assert kwargs["start_new_session"] is True
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert "stdout" not in kwargs and "stderr" not in kwargs
    environment = kwargs["env"]
    assert environment["PYTHONPATH"] == str(Path(inputs[1]) / "harness/src")
    assert environment["CLOUDFLARE_API_TOKEN"] == "explicit-process-token"
    assert environment["CLOUDFLARE_ACCOUNT_ID"] == "account-fixture"
    assert environment["WANDB_API_KEY"] == "tracking-secret-fixture"
    assert environment["WANDB_PROJECT"] == "apart-collusion-sprint"
    assert "WANDB_RUN_ID" not in environment
    assert "IGNORED_PROVIDER" not in environment and "IGNORED_TRACKING" not in environment
    metadata = json.loads((Path(inputs[11]) / "local-run.json").read_text())
    assert metadata["child_pid"] == child.pid
    assert metadata["time_policy"] == "deadline"
    assert len(metadata["plan_sha256"]) == len(metadata["launcher_sha256"]) == 64
    safe = repr(command) + json.dumps(metadata) + capsys.readouterr().out
    for secret in ("tracking-secret-fixture", "explicit-process-token", "epistemics-secret"):
        assert secret not in safe


def test_authorized_budget_and_phase_limit_are_passed_to_same_ledger(loaded, inputs, monkeypatch):
    calls = []

    def popen(command, **kwargs):
        calls.append(command)
        return Child()

    monkeypatch.setattr(loaded.subprocess, "Popen", popen)
    inputs[inputs.index("--dispatch-limit-usd") + 1] = "280"
    assert loaded.main([*inputs, "--budget-usd", "300"]) == 0
    command = calls[0]
    assert command[command.index("--budget-usd") + 1] == "300"
    assert command[command.index("--dispatch-limit-usd") + 1] == "280"
    assert command[command.index("--budget-ledger") + 1] == inputs[13]


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity"])
def test_invalid_budget_is_rejected_before_spawn(loaded, inputs, value, monkeypatch):
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: pytest.fail("started child"))
    with pytest.raises(SystemExit, match="2"):
        loaded.main([*inputs, "--budget-usd", value])


def test_dispatch_limit_cannot_exceed_selected_budget(loaded, inputs, monkeypatch):
    inputs[inputs.index("--dispatch-limit-usd") + 1] = "300.01"
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: pytest.fail("started child"))
    with pytest.raises(SystemExit, match="2"):
        loaded.main([*inputs, "--budget-usd", "300"])


def test_explicit_no_deadline_waits_without_timeout(loaded, inputs, monkeypatch):
    class IndefiniteChild(Child):
        def wait(self):
            self.returncode = 0
            return 0

    child = IndefiniteChild()
    index = inputs.index("--deadline")
    del inputs[index : index + 2]
    inputs[inputs.index("--dispatch-limit-usd") + 1] = "280"
    calls = []

    def popen(command, **kwargs):
        calls.append(command)
        return child

    monkeypatch.setattr(loaded.subprocess, "Popen", popen)
    assert loaded.main([*inputs, "--no-deadline", "--budget-usd", "300"]) == 0
    assert len(calls) == 1
    assert calls[0][calls[0].index("--budget-usd") + 1] == "300"
    assert calls[0][calls[0].index("--dispatch-limit-usd") + 1] == "280"
    metadata = json.loads((Path(inputs[11]) / "local-run.json").read_text())
    assert metadata["deadline_utc"] is None
    assert metadata["time_policy"] == "none"
    assert metadata["outcome"] == "complete"


def test_time_policy_must_be_explicit(loaded, inputs, monkeypatch):
    index = inputs.index("--deadline")
    del inputs[index : index + 2]
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: pytest.fail("started child"))
    with pytest.raises(SystemExit, match="2"):
        loaded.main(inputs)


def test_deadline_and_no_deadline_are_mutually_exclusive(loaded, inputs, monkeypatch):
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: pytest.fail("started child"))
    with pytest.raises(SystemExit, match="2"):
        loaded.main([*inputs, "--no-deadline"])


def test_no_deadline_interrupt_still_stops_only_owned_child(loaded, inputs, monkeypatch):
    class InterruptedChild(Child):
        def wait(self, timeout=None):
            self.timeouts.append(timeout)
            if timeout is None:
                raise KeyboardInterrupt
            self.returncode = -signal.SIGINT
            return self.returncode

    child = InterruptedChild()
    index = inputs.index("--deadline")
    del inputs[index : index + 2]
    signals = []
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: child)
    monkeypatch.setattr(loaded.os, "killpg", lambda pid, signum: signals.append((pid, signum)))
    assert loaded.main([*inputs, "--no-deadline"]) == 130
    assert child.timeouts == [None, 60]
    assert signals == [(child.pid, signal.SIGINT)]
    metadata = json.loads((Path(inputs[11]) / "local-run.json").read_text())
    assert metadata["deadline_utc"] is None
    assert metadata["outcome"] == "interrupted"


def test_expired_deadline_never_starts_child(loaded, inputs, monkeypatch):
    inputs[inputs.index("--deadline") + 1] = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: pytest.fail("started child"))
    assert loaded.main(inputs) == 124


def test_dispatch_budget_stop_preserves_child_exit_code(loaded, inputs, monkeypatch):
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: Child((3,)))
    assert loaded.main(inputs) == 3
    metadata = json.loads((Path(inputs[11]) / "local-run.json").read_text())
    assert metadata["outcome"] == "budget_stopped"
    assert metadata["returncode"] == 3


def test_deadline_signals_only_owned_group_and_bounded_cleanup(loaded, inputs, monkeypatch):
    child = Child(("timeout", "timeout", -signal.SIGKILL))
    signals = []
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: child)
    monkeypatch.setattr(loaded.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    assert loaded.main(inputs) == 124
    assert signals == [(child.pid, signal.SIGINT), (child.pid, signal.SIGKILL)]
    assert child.timeouts[1:] == [60, 5]
    metadata = json.loads((Path(inputs[11]) / "local-run.json").read_text())
    assert metadata["outcome"] == "deadline"


def test_caffeinate_is_owned_by_handle_and_cleaned_up(loaded, inputs, monkeypatch):
    child = Child()

    class Caffeine(Child):
        pid = 43211

        def terminate(self):
            self.terminated = True

    caffeine = Caffeine()
    calls = []

    def popen(command, **kwargs):
        calls.append(command)
        return child if len(calls) == 1 else caffeine

    monkeypatch.setattr(loaded.subprocess, "Popen", popen)
    monkeypatch.setattr(loaded.shutil, "which", lambda name: "/usr/bin/caffeinate")
    monkeypatch.setattr(loaded.os, "killpg", lambda *a: pytest.fail("signaled other process"))
    assert loaded.main([*inputs, "--caffeinate"]) == 0
    assert calls[1] == ["/usr/bin/caffeinate", "-i", "-w", str(child.pid)]
    assert caffeine.terminated
    assert caffeine.timeouts == [5]


def test_tracking_key_must_come_from_selected_file(loaded, inputs, monkeypatch, capsys):
    Path(inputs[7]).write_text("WANDB_PROJECT=apart-collusion-sprint\n")
    monkeypatch.setenv("WANDB_API_KEY", "unrelated-epistemics-key")
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: pytest.fail("started child"))
    assert loaded.main(inputs) == 1
    assert "unrelated-epistemics-key" not in capsys.readouterr().out


@pytest.mark.parametrize("value", ["0", "101", "NaN", "Infinity"])
def test_rejects_invalid_phase_cap_before_spawn(loaded, inputs, value, monkeypatch):
    inputs[inputs.index("--dispatch-limit-usd") + 1] = value
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: pytest.fail("started child"))
    with pytest.raises(SystemExit, match="2"):
        loaded.main(inputs)


def test_deadline_must_be_utc_within_eight_hours(loaded, inputs, monkeypatch):
    monkeypatch.setattr(loaded.subprocess, "Popen", lambda *a, **kw: pytest.fail("started child"))
    for deadline in ("2026-11-17T12:00:00", (datetime.now(UTC) + timedelta(hours=9)).isoformat()):
        inputs[inputs.index("--deadline") + 1] = deadline
        with pytest.raises(SystemExit, match="2"):
            loaded.main(inputs)
