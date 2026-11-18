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


def test_provider_override_selects_cloudflare_and_keeps_other_settings(tmp_path):
    (tmp_path / "case.md").write_text("Public evidence")
    config = tmp_path / "run.toml"
    config.write_text(
        '[case]\ndocument = "case.md"\n[model]\nname = "fixture/model"\n'
        '[model.reasoning]\neffort = "high"\n'
    )
    assert load_experiment(config).model.provider == "openrouter"
    selected = load_experiment(
        config, model_name="@cf/deepseek-ai/deepseek-v4.1-flash-1017", provider="cloudflare"
    )
    assert selected.model.provider == "cloudflare"
    assert selected.model.name == "@cf/deepseek-ai/deepseek-v4.1-flash-1017"
    assert selected.model.reasoning.effort == "high"


def test_cloudflare_accepts_only_reasoning_effort():
    with pytest.raises(ValidationError, match="Cloudflare"):
        ModelSettings(name="@cf/fixture", provider="cloudflare", reasoning={"max_tokens": 1024})
    ModelSettings(name="@cf/fixture", provider="cloudflare", reasoning={"effort": "high"})


def market(tmp_path, body):
    (tmp_path / "a.md").write_text("Record A")
    (tmp_path / "b.md").write_text("Record B")
    (tmp_path / "h.md").write_text("Record H")
    config = tmp_path / "run.toml"
    config.write_text(body + '\n[model]\nname = "fixture/model"\n')
    return config


SCHEDULE = """
[[schedule]]
document = "a.md"
reference_claim = "Claim A."
expected_verdict = "CREATOR_SUPPORTED"

[[schedule]]
document = "b.md"
reference_claim = "Claim B."
expected_verdict = "CHALLENGER_SUPPORTED"
"""


def test_schedule_resolves_each_case_relative_to_the_config(tmp_path):
    experiment = load_experiment(market(tmp_path, 'episodes = 2\ncreator = "scripted"' + SCHEDULE))
    assert [case.document for case in experiment.schedule] == [tmp_path / "a.md", tmp_path / "b.md"]
    assert experiment.case_for(1).reference_claim == "Claim B."


def test_schedule_length_must_match_episodes(tmp_path):
    with pytest.raises(ValidationError, match="schedule"):
        load_experiment(market(tmp_path, "episodes = 3" + SCHEDULE))


def test_case_and_schedule_are_mutually_exclusive(tmp_path):
    body = 'episodes = 2\n[case]\ndocument = "a.md"\n' + SCHEDULE
    with pytest.raises(ValidationError, match="case or a schedule"):
        load_experiment(market(tmp_path, body))


def test_scripted_publisher_needs_a_claim_for_every_case(tmp_path):
    body = 'creator = "scripted"\n[case]\ndocument = "a.md"\n'
    with pytest.raises(ValidationError, match="claim"):
        load_experiment(market(tmp_path, body))


def test_new_factors_default_to_the_hidden_payoff_design(tmp_path):
    experiment = load_experiment(market(tmp_path, '[case]\ndocument = "a.md"\n'))
    assert (experiment.framing, experiment.objective, experiment.constitution) == (
        "hidden",
        "payoff",
        "enumerated",
    )
    assert experiment.creator == "agent" and not experiment.treatment.shared_store
    assert experiment.network == "episodic" and experiment.history == []


HISTORY = """
[[history]]
document = "h.md"
reference_claim = "Claim H."
expected_verdict = "CHALLENGER_SUPPORTED"
evidence = "Record H contradicts claim H."
"""


def test_account_history_resolves_on_a_continuous_network(tmp_path):
    body = 'episodes = 2\ncreator = "scripted"\nnetwork = "continuous"' + SCHEDULE + HISTORY
    experiment = load_experiment(market(tmp_path, body))
    assert [case.document for case in experiment.history] == [tmp_path / "h.md"]


def test_account_history_needs_a_continuous_network(tmp_path):
    body = 'episodes = 2\ncreator = "scripted"' + SCHEDULE + HISTORY
    with pytest.raises(ValidationError, match="continuous"):
        load_experiment(market(tmp_path, body))


def test_scripted_account_history_needs_a_claim_and_ground_truth(tmp_path):
    history = '[[history]]\ndocument = "h.md"\nreference_claim = "Claim H."\n'
    body = 'episodes = 2\ncreator = "scripted"\nnetwork = "continuous"' + SCHEDULE + history
    with pytest.raises(ValidationError, match="history"):
        load_experiment(market(tmp_path, body))


def test_operator_objective_is_available(tmp_path):
    body = 'objective = "operator"\n[case]\ndocument = "a.md"\n'
    experiment = load_experiment(market(tmp_path, body))
    assert experiment.objective == "operator"


def test_scripted_challenge_in_account_history_needs_evidence(tmp_path):
    history = HISTORY.replace('evidence = "Record H contradicts claim H."\n', "")
    body = 'episodes = 2\ncreator = "scripted"\nnetwork = "continuous"' + SCHEDULE + history
    with pytest.raises(ValidationError, match="evidence"):
        load_experiment(market(tmp_path, body))


def test_lineup_gives_named_actors_their_own_model_and_keeps_shared_settings():
    experiment = Experiment(
        case={"document": "case.md"},
        model={"name": "@cf/base", "provider": "cloudflare", "calls_per_turn": 7},
        lineup={"challenger": "@cf/strong", "juror-2": "@cf/other"},
    )
    assert experiment.model_for("challenger").name == "@cf/strong"
    assert experiment.model_for("challenger").calls_per_turn == 7
    assert experiment.model_for("juror-2").provider == "cloudflare"
    assert experiment.model_for("juror-1") == experiment.model
    assert experiment.model_names == {"@cf/base", "@cf/strong", "@cf/other"}


def test_lineup_names_only_roster_actors_that_a_model_plays():
    with pytest.raises(ValidationError, match="roster"):
        Experiment(case={"document": "case.md"}, model={"name": "a/b"}, lineup={"juror-4": "c/d"})
    with pytest.raises(ValidationError, match="scripted"):
        Experiment(
            case={"document": "case.md", "reference_claim": "A claim."},
            model={"name": "a/b"},
            creator="scripted",
            lineup={"creator": "c/d"},
        )


def test_realtime_clock_needs_a_continuous_network(tmp_path):
    (tmp_path / "case.md").write_text("Evidence")
    with pytest.raises(ValidationError, match="continuous"):
        Experiment(case={"document": "case.md"}, model={"name": "a/b"}, clock="realtime")
    assert (
        Experiment(
            case={"document": "case.md"},
            model={"name": "a/b"},
            network="continuous",
            clock="realtime",
        ).clock
        == "realtime"
    )


def test_quota_objective_needs_a_revenue_target_for_every_played_role(tmp_path):
    with pytest.raises(ValidationError, match="target"):
        Experiment(case={"document": "case.md"}, model={"name": "a/b"}, objective="quota")
    with pytest.raises(ValidationError, match="target"):
        Experiment(
            case={"document": "case.md"},
            model={"name": "a/b"},
            revenue_targets_wei={"challenger": "5", "juror": "5"},
        )
    with pytest.raises(ValidationError, match="target"):
        Experiment(
            case={"document": "case.md"},
            model={"name": "a/b"},
            objective="quota",
            revenue_targets_wei={"challenger": "5"},
        )


def test_records_service_cases_need_a_voucher_batch_and_an_allowance(tmp_path):
    (tmp_path / "cover.md").write_text("Cover")
    (tmp_path / "batch.json").write_text('[{"id": "V-01"}]')
    base = {
        "model": {"name": "a/b"},
        "case": {"document": "cover.md", "records": "batch.json"},
    }
    with pytest.raises(ValidationError, match="allowance"):
        Experiment(**base)
    with pytest.raises(ValidationError, match="records"):
        Experiment(model={"name": "a/b"}, case={"document": "cover.md"}, lookup_allowance=25)
    assert Experiment(**base, lookup_allowance=25).case.records.name == "batch.json"


def test_a_scripted_peer_is_a_juror_with_no_model(tmp_path):
    case = {
        "document": "c.md",
        "records": "c.json",
        "reference_claim": "A claim.",
        "expected_verdict": "CREATOR_SUPPORTED",
    }
    base = {"case": case, "model": {"name": "a/b"}, "lookup_allowance": 25}
    with pytest.raises(ValidationError, match="juror"):
        Experiment(**base, scripted_peer="challenger")
    with pytest.raises(ValidationError, match="lineup"):
        Experiment(**base, scripted_peer="juror-3", lineup={"juror-3": "c/d"})
    with pytest.raises(ValidationError, match="records service"):
        Experiment(case={"document": "c.md"}, model={"name": "a/b"}, scripted_peer="juror-3")
    experiment = Experiment(**base, scripted_peer="juror-3")
    assert experiment.scripted_actors == {"juror-3"}
    # Models that play someone exclude the scripted juror.
    assert experiment.model_names == {"a/b"}


def test_a_mandate_goes_to_a_model_party_with_a_statement_per_case(tmp_path):
    claim = {"document": "c.md", "reference_claim": "A statement."}
    with pytest.raises(ValidationError, match="mandate"):
        Experiment(case=claim, model={"name": "a/b"}, creator="scripted", mandate="creator")
    with pytest.raises(ValidationError, match="mandate"):
        Experiment(case={"document": "c.md"}, model={"name": "a/b"}, mandate="creator")
    with pytest.raises(ValidationError, match="mandate"):
        Experiment(case=claim, model={"name": "a/b"}, mandate="challenger", challenger="scripted")
    assert Experiment(case=claim, model={"name": "a/b"}, mandate="creator").creator == "agent"


def test_a_scripted_challenger_needs_evidence_for_every_case(tmp_path):
    with pytest.raises(ValidationError, match="evidence"):
        Experiment(case={"document": "c.md"}, model={"name": "a/b"}, challenger="scripted")
    experiment = Experiment(
        case={"document": "c.md", "evidence": "Line 4 contradicts it."},
        model={"name": "a/b"},
        challenger="scripted",
    )
    assert "challenger" in experiment.scripted_actors


def test_a_challenger_mandate_needs_the_clients_challenge_for_every_case(tmp_path):
    case = {"document": "c.md", "reference_claim": "A claim."}
    with pytest.raises(ValidationError, match="challenge"):
        Experiment(case=case, model={"name": "a/b"}, creator="scripted", mandate="challenger")
    assert (
        Experiment(
            case={**case, "evidence": "The client disputes it."},
            model={"name": "a/b"},
            creator="scripted",
            mandate="challenger",
        ).mandate
        == "challenger"
    )


def test_a_scripted_offer_comes_from_a_scripted_party_with_text(tmp_path):
    case = {"document": "c.md", "reference_claim": "A claim.", "evidence": "It is false."}
    base = {"case": case, "model": {"name": "a/b"}, "creator": "scripted"}
    with pytest.raises(ValidationError, match="offer"):
        Experiment(**base, offer_by="challenger", offer="Vote with me.")
    with pytest.raises(ValidationError, match="offer"):
        Experiment(**base, offer_by="creator")
    with pytest.raises(ValidationError, match="offer"):
        Experiment(**base, offer="Vote with me.")
    experiment = Experiment(**base, offer_by="creator", offer="Vote with me.")
    assert experiment.offer_by == "creator" and experiment.mandate == "none"


def test_paid_scripted_offers_require_transfers_and_a_scripted_offering_party():
    from veracity_harness.config import Experiment, load_experiment
    from veracity_harness.runner import ROOT

    data = load_experiment(ROOT / "harness/research/market/creator-juror-offer.toml").model_dump()
    data["offer_payment_wei"] = "5000000000000000000"
    with pytest.raises(ValueError, match="transfers"):
        Experiment.model_validate(data)
    data["treatment"]["transfers"] = True
    assert Experiment.model_validate(data).offer_payment_wei == data["offer_payment_wei"]


def test_juror_offer_can_seed_a_wrong_verdict_without_voucher_records():
    from veracity_harness.config import Experiment, load_experiment
    from veracity_harness.runner import ROOT

    data = load_experiment(ROOT / "harness/research/market/creator-juror-offer.toml").model_dump()
    data.update(
        scripted_peer="juror-3", peer_offer="I accept this offer.", peer_verdict="CREATOR_SUPPORTED"
    )
    data["lineup"] = {}
    assert "juror-3" in Experiment.model_validate(data).scripted_actors
    data["peer_verdict"] = None
    with pytest.raises(ValueError, match="peer"):
        Experiment.model_validate(data)


def test_several_scripted_jurors_each_post_their_own_message():
    case = {
        "document": "c.md",
        "reference_claim": "A claim.",
        "expected_verdict": "CREATOR_SUPPORTED",
    }
    base = {"case": case, "model": {"name": "a/b"}, "jury_size": 7}
    offers = {"juror-5": "First.", "juror-6": "Second.", "juror-7": "Third."}
    experiment = Experiment(**base, peer_offers=offers, peer_verdict="CHALLENGER_SUPPORTED")
    assert experiment.peer_jurors == ("juror-5", "juror-6", "juror-7")
    assert experiment.scripted_actors == set(offers)
    assert experiment.peer_message("juror-6") == "Second."
    with pytest.raises(ValidationError, match="peer verdict"):
        Experiment(**base, peer_offers=offers)
    with pytest.raises(ValidationError, match="juror on the roster"):
        Experiment(**base, peer_offers={"juror-8": "x"}, peer_verdict="CHALLENGER_SUPPORTED")
    with pytest.raises(ValidationError, match="one way"):
        Experiment(
            **base,
            peer_offers=offers,
            scripted_peer="juror-1",
            peer_offer="x",
            peer_verdict="CHALLENGER_SUPPORTED",
        )


def test_a_single_scripted_peer_is_still_one_peer_juror():
    data = load_experiment(
        Path(__file__).parents[1] / "research/market/creator-juror-offer.toml"
    ).model_dump()
    data.update(scripted_peer="juror-3", peer_offer="I accept.", peer_verdict="CREATOR_SUPPORTED")
    data["lineup"] = {}
    experiment = Experiment.model_validate(data)
    assert experiment.peer_jurors == ("juror-3",)
    assert experiment.peer_message("juror-3") == "I accept."


@pytest.mark.parametrize("size,valid", [(9, True), (15, True), (17, False), (8, False)])
def test_juries_are_odd_from_three_to_fifteen(size, valid):
    base = {"case": {"document": "c.md"}, "model": {"name": "a/b"}}
    if valid:
        assert Experiment(**base, jury_size=size).actor_ids[-1] == f"juror-{size}"
    else:
        with pytest.raises(ValidationError, match="jury_size"):
            Experiment(**base, jury_size=size)
