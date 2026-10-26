import pytest

from veracity_harness.config import load_experiment
from veracity_harness.runner import ROOT


@pytest.mark.parametrize(
    "control,changed",
    [
        ("no-memory", {"memory": False}),
        ("no-communication", {"public_messaging": False, "private_chat": False}),
    ],
)
def test_repeated_controls_change_only_the_declared_treatment(control, changed):
    root = ROOT / "harness-v2/research"
    baseline = load_experiment(root / "repeated.toml")
    variant = load_experiment(root / f"{control}.toml")
    expected = baseline.model_copy(
        update={"name": variant.name, "treatment": baseline.treatment.model_copy(update=changed)}
    )
    assert variant == expected


def test_clear_case_control_matches_model_budgets_case_and_seed():
    root = ROOT / "harness-v2/research"
    baseline = load_experiment(root / "clear-case.toml", seed=43)
    control = load_experiment(root / "clear-no-communication.toml", seed=43)
    expected = baseline.model_copy(
        update={
            "name": control.name,
            "treatment": baseline.treatment.model_copy(
                update={
                    "public_messaging": False,
                    "private_chat": False,
                }
            ),
        }
    )
    assert control == expected
