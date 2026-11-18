import json
import os
import sys

import pytest

from veracity_harness.cli import main
from veracity_harness.config import Experiment


def test_default_config_selects_cloudflare_without_loading_credentials(monkeypatch, capsys):
    def unexpected_credentials(*args, **kwargs):
        pytest.fail("Validation must not load operator credentials")

    monkeypatch.setattr("veracity_harness.cli.load_dotenv", unexpected_credentials)
    monkeypatch.setattr(sys, "argv", ["veracity-harness", "validate", "--model", "@cf/fixture"])
    main()
    config = json.loads(capsys.readouterr().out)
    assert config["model"]["provider"] == "cloudflare"
    assert config["model"]["name"] == "@cf/fixture"


def test_missing_model_is_rejected_before_reading_credentials(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["veracity-harness", "validate"])
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2
    assert "Select an experiment model" in capsys.readouterr().err


def test_smoke_preserves_experiment_reasoning_and_completion_budget(monkeypatch, tmp_path):
    (tmp_path / "case.md").write_text("Public evidence")
    config = tmp_path / "experiment.toml"
    config.write_text(
        '[case]\ndocument = "case.md"\n[model]\nmax_tokens = 65536\n'
        "calls_per_turn = 2\ncalls_per_episode = 3\n"
        "[model.reasoning]\nmax_tokens = 32768\n"
    )
    received = {}

    async def run(experiment, output, *, smoke, spending):
        received.update(model=experiment.model, smoke=smoke)
        (tmp_path / "run.json").write_text(json.dumps({"status": "complete"}))
        return tmp_path

    monkeypatch.setattr("veracity_harness.cli.run_experiment", run)
    monkeypatch.setattr("veracity_harness.cli.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "fixture-not-a-credential")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "veracity-harness",
            "smoke",
            "--config",
            str(config),
            "--model",
            "fixture/selected",
            "--budget-ledger",
            str(tmp_path / "campaign.sqlite"),
            "--budget-usd",
            "100",
        ],
    )
    main()
    assert received["model"].name == "fixture/selected"
    assert received["model"].max_tokens == 65536
    assert received["model"].reasoning.max_tokens == 32768
    assert received["model"].calls_per_turn == 2
    assert received["model"].calls_per_episode == 3
    assert received["smoke"] is True


def test_smoke_retains_a_valid_single_case_schedule(monkeypatch, tmp_path):
    (tmp_path / "case.md").write_text("Public evidence")
    config = tmp_path / "experiment.toml"
    config.write_text(
        'episodes = 2\n[model]\nname = "@cf/fixture"\nprovider = "cloudflare"\n'
        '[[schedule]]\ndocument = "case.md"\n'
        '[[schedule]]\ndocument = "case.md"\n'
    )
    received = {}

    async def run(experiment, output, *, smoke, spending):
        validated = Experiment.model_validate(experiment.model_dump())
        received.update(experiment=validated, smoke=smoke)
        (tmp_path / "run.json").write_text(json.dumps({"status": "complete"}))
        return tmp_path

    monkeypatch.setattr("veracity_harness.cli.run_experiment", run)
    monkeypatch.setattr("veracity_harness.cli.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fixture-not-a-credential")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fixture-account")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "veracity-harness",
            "smoke",
            "--config",
            str(config),
            "--budget-ledger",
            str(tmp_path / "campaign.sqlite"),
            "--budget-usd",
            "5",
        ],
    )
    main()
    assert received["smoke"] is True
    assert received["experiment"].episodes == len(received["experiment"].schedule) == 1


def run_cli_with_provider(monkeypatch, tmp_path, provider, extra=()):
    (tmp_path / "case.md").write_text("Public evidence")
    config = tmp_path / "experiment.toml"
    config.write_text('[case]\ndocument = "case.md"\n[model]\nname = "@cf/fixture"\n')
    received = {}

    async def run(experiment, output, *, smoke, spending):
        received.update(model=experiment.model)
        (tmp_path / "run.json").write_text(json.dumps({"status": "complete"}))
        return tmp_path

    monkeypatch.setattr("veracity_harness.cli.run_experiment", run)
    monkeypatch.setattr("veracity_harness.cli.load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "veracity-harness",
            "smoke",
            "--config",
            str(config),
            "--provider",
            provider,
            "--budget-ledger",
            str(tmp_path / "campaign.sqlite"),
            "--budget-usd",
            "5",
            *extra,
        ],
    )
    main()
    return received


def test_cloudflare_provider_requires_its_own_credentials(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("CLOUDFLARE_API_TOKEN", raising=False)
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fixture-account")
    with pytest.raises(SystemExit) as stopped:
        run_cli_with_provider(monkeypatch, tmp_path, "cloudflare")
    assert stopped.value.code == 2
    assert "CLOUDFLARE_API_TOKEN" in capsys.readouterr().err


def test_cloudflare_provider_is_selected_without_openrouter_credentials(monkeypatch, tmp_path):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fixture-not-a-credential")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fixture-account")
    received = run_cli_with_provider(monkeypatch, tmp_path, "cloudflare")
    assert received["model"].provider == "cloudflare"


def test_live_run_keeps_a_mac_awake_for_its_own_lifetime(monkeypatch, tmp_path):
    # A sleeping Mac pauses asyncio's clock, so turn timeouts stall and connections drop.
    spawned = []
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr("veracity_harness.cli.shutil.which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr("veracity_harness.cli.subprocess.Popen", spawned.append)
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fixture-not-a-credential")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fixture-account")
    run_cli_with_provider(monkeypatch, tmp_path, "cloudflare")
    assert spawned == [["/usr/bin/caffeinate", "-i", "-w", str(os.getpid())]]


def test_backup_credential_is_rejected_for_cloudflare(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("CLOUDFLARE_API_TOKEN", "fixture-not-a-credential")
    monkeypatch.setenv("CLOUDFLARE_ACCOUNT_ID", "fixture-account")
    with pytest.raises(SystemExit) as stopped:
        run_cli_with_provider(monkeypatch, tmp_path, "cloudflare", extra=["--credential", "backup"])
    assert stopped.value.code == 2
    assert "OpenRouter" in capsys.readouterr().err
