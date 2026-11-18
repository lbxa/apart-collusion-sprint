from veracity_harness.config import load_experiment
from veracity_harness.materials import ROOT, static_documents, system_prompt


def test_full_inspection_standard_is_in_initial_prompt_and_linked_from_interface():
    experiment = load_experiment(ROOT / "harness/research/frontier-2026-10-31/verify-alone.toml")
    documents = static_documents(experiment)
    assert documents["standard.md"] in system_prompt(experiment)
    assert "/veracity/standard.md" in documents["interface.md"]
