from pathlib import Path

import pytest
from pydantic import ValidationError

from veracity_harness.config import Experiment, ModelSettings, load_experiment


def test_model_selection_has_no_implicit_default():
    with pytest.raises(ValidationError, match="name"):
        ModelSettings()


def test_experiment_requires_explicit_model_selection():
    with pytest.raises(ValidationError, match="model"):
        Experiment(case={"document": "case.md"})


def test_config_does_not_admit_strategy_or_unbounded_budgets():
    with pytest.raises(ValidationError):
        Experiment(
            case={"document": "case.md"}, model={"name": "fixture/model"}, strategy="collude"
        )
    with pytest.raises(ValidationError):
        Experiment(
            case={"document": "case.md"}, model={"name": "fixture/model", "calls_per_episode": 0}
        )


def test_case_path_is_relative_to_config_not_working_directory(tmp_path):
    (tmp_path / "case.md").write_text("Public evidence", encoding="utf-8")
    config = tmp_path / "run.toml"
    config.write_text('[case]\ndocument = "case.md"\n', encoding="utf-8")
    experiment = load_experiment(config, model_name="fixture/model")
    assert experiment.case.document == tmp_path / "case.md"
    assert experiment.case.expected_verdict is None
    assert experiment.actor_ids == ("creator", "challenger", "juror-1", "juror-2", "juror-3")


def test_incentives_must_obey_the_contract():
    base = Experiment(case={"document": Path("case.md")}, model={"name": "fixture/model"})
    data = base.model_dump()
    data["parameters"]["winner_bps"] = 9999
    with pytest.raises(ValidationError, match="sum to 10000"):
        Experiment.model_validate(data)


@pytest.mark.parametrize(
    "model_id",
    [
        "deepseek/frontier-fixture",
        "google/gemini-frontier-fixture",
        "anthropic/frontier-fixture",
        "openai/frontier-fixture",
    ],
)
def test_experiment_accepts_provider_models_without_selecting_or_capping_them(model_id):
    settings = ModelSettings(name=model_id, max_tokens=131072, reasoning={"effort": "high"})
    assert settings.name == model_id
    assert settings.max_tokens == 131072
    assert settings.reasoning.model_dump(exclude_none=True) == {"effort": "high"}


def test_reasoning_settings_are_optional_and_validate_explicit_budget():
    assert ModelSettings(name="fixture/model").reasoning is None
    with pytest.raises(ValidationError, match="not both"):
        ModelSettings(name="fixture/model", reasoning={"effort": "high", "max_tokens": 1024})
    with pytest.raises(ValidationError, match="leave room"):
        ModelSettings(name="fixture/model", max_tokens=2048, reasoning={"max_tokens": 2048})


def test_cli_model_override_is_applied_before_validation_and_preserves_other_settings(tmp_path):
    (tmp_path / "case.md").write_text("Public evidence")
    config = tmp_path / "run.toml"
    config.write_text(
        '[case]\ndocument = "case.md"\n[model]\nmax_tokens = 65536\n'
        '[model.reasoning]\neffort = "high"\n'
    )
    selected = load_experiment(config, model_name="fixture/selected")
    assert selected.model.name == "fixture/selected"
    assert selected.model.max_tokens == 65536
    assert selected.model.reasoning.effort == "high"


def test_launch_seed_override_preserves_experiment_model_and_treatments(tmp_path):
    (tmp_path / "case.md").write_text("Public evidence")
    config = tmp_path / "run.toml"
    config.write_text('[case]\ndocument = "case.md"\n[model]\nname = "fixture/model"\n')
    selected = load_experiment(config, seed=43)
    assert selected.seed == 43
    assert selected.model.name == "fixture/model"
    assert selected.treatment.memory is False
