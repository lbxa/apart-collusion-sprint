import json
import sys

import pytest

from veracity_harness.cli import main


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
