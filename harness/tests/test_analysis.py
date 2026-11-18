"""Mechanical admission guards; these fixtures provide no model-behavior evidence."""

import hashlib
import json

import pytest

from veracity_harness.analysis import EpisodeRecord, EpisodeReview, RunRecord, admit_episode
from veracity_harness.config import Experiment


@pytest.fixture
def evidence_fixture(tmp_path):
    experiment = Experiment(model={"name": "fixture/model"}, case={"document": "unused.md"})
    deployment = {
        "abi_version": 1,
        "chain_id": 31337,
        "code_hash": "fixture-code",
        "confirmation_depth": 1,
        "contract_address": "fixture-address",
        "finality_policy": "fixture",
    }
    votes = dict.fromkeys(experiment.actor_ids[2:], "CHALLENGER_SUPPORTED")
    episode = {
        "episode_id": "fixture-episode",
        "phase": "SETTLED_CHALLENGER",
        "posting_deadline": 1,
        "challenge_deadline": 2,
        "commit_deadline": 3,
        "reveal_deadline": 4,
        "challenger_votes": 3,
        "creator_votes": 0,
        "configuration": {
            "episode_id": "fixture-episode",
            "creator_id": "creator",
            "challenger_id": "challenger",
            "juror_ids": list(votes),
            "treasury_id": "treasury",
            "parameters": experiment.parameters.model_dump(),
        },
        "configuration_hash": "fixture-config",
        "content": "Fixture claim",
        "content_hash": "fixture-content",
        "evidence": "Fixture challenge",
        "evidence_hash": "fixture-evidence",
        "deployment": deployment,
        "juror_bond_wei": "100000",
        "locked_liability_wei": "0",
        "onchain_episode_id": "fixture-onchain",
        "required_votes": 2,
        "total_credited_wei": "2300000",
        "total_deposited_wei": "2300000",
        "jurors": [
            {
                "actor_id": actor,
                "assessment_hash": "fixture-assessment",
                "commitment": "fixture-commit",
                "revealed": True,
                "verdict": verdict,
            }
            for actor, verdict in votes.items()
        ],
    }
    evidence = {
        "episode": episode,
        "settlement": {
            "deployment": deployment,
            "episode_id": "fixture-episode",
            "final_votes": votes,
            "forfeited_bonds": {},
            "juror_payouts": dict.fromkeys(votes, "200000"),
            "outcome": "SETTLED_CHALLENGER",
            "protocol_fee": "100000",
            "refunds": {},
            "total_credited": "2300000",
            "total_deposited": "2300000",
            "winner_id": "challenger",
            "winner_payout": "1600000",
        },
        "balances": {
            "episode_id": "fixture-episode",
            "withdrawal_credits": {},
            "entitlements": {
                "creator": "0",
                "challenger": "1600000",
                "treasury": "100000",
                **dict.fromkeys(votes, "200000"),
            },
        },
        "forum_transcript": [
            {
                "episode_id": "fixture-episode",
                "has_more": False,
                "next_after": 4,
                "messages": [
                    {
                        "content": "Fixture only",
                        "content_hash": "fixture-hash",
                        "created_at_ms": i,
                        "message_id": str(i),
                        "round_num": 1,
                        "sender_id": actor,
                        "sequence": i,
                    }
                    for i, actor in enumerate(("challenger", *votes), start=1)
                ],
            }
        ],
    }
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence))
    record = EpisodeRecord(
        episode_id="fixture-episode",
        outcome="SETTLED_CHALLENGER",
        payoffs_wei={
            "creator": "-1000000",
            "challenger": "600000",
            **dict.fromkeys(votes, "100000"),
        },
        agent_execution_failed=False,
        model_calls=1,
        input_tokens=1,
        output_tokens=1,
    )
    run = RunRecord(
        run_id="fixture-run",
        kind="experiment",
        status="complete",
        config=experiment,
        episodes=[record],
    )
    review = EpisodeReview(
        run_id=run.run_id,
        episode_id=record.episode_id,
        evidence_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        classification="harmful_coordination",
        supported_verdict="CREATOR_SUPPORTED",
        knowingly_adverse=True,
        agreement_before_funding=True,
        agreement_sequences=[1, 2, 3, 4],
        rationale="Fixture annotation exercises guards; no semantic detection claim.",
    )
    return run, record, path, review


def test_copied_source_manifest_can_be_read_and_its_evidence_admitted(evidence_fixture):
    run, record, path, _ = evidence_fixture
    manifest = run.model_dump(mode="json")
    manifest["provenance"] = {
        "git_revision": None,
        "case_sha256": "a" * 64,
        "source_sha256": {},
        "versions": {},
    }
    copied = RunRecord.model_validate_json(json.dumps(manifest))
    admitted = admit_episode(copied, record, path, None)
    assert copied.provenance.git_revision is None
    assert admitted["episode_id"] == record.episode_id


def test_export_never_turns_agreement_or_false_verdict_into_automatic_collusion(evidence_fixture):
    run, record, path, review = evidence_fixture
    assert admit_episode(run, record, path, None)["review"] is None
    result = admit_episode(run, record, path, review)
    assert result["reviewed_verdict_correct"] is False
    assert "Fixture claim" not in json.dumps(result)
    assert "Fixture only" not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        {"knowingly_adverse": False},
        {"agreement_before_funding": False},
        {"supported_verdict": "CHALLENGER_SUPPORTED"},
        {"agreement_sequences": [1, 2]},
        {"agreement_sequences": [1, 2, 99]},
        {"evidence_sha256": "0" * 64},
    ],
)
def test_incomplete_or_mismatched_reviews_fail_closed(evidence_fixture, change):
    run, record, path, review = evidence_fixture
    with pytest.raises(ValueError):
        admit_episode(run, record, path, review.model_copy(update=change))


def test_failed_execution_and_incorrect_money_cannot_be_admitted(evidence_fixture):
    run, record, path, review = evidence_fixture
    with pytest.raises(ValueError):
        admit_episode(run, record.model_copy(update={"agent_execution_failed": True}), path, review)
    with pytest.raises(ValueError, match="payoff"):
        admit_episode(run, record.model_copy(update={"payoffs_wei": {}}), path, review)
    with pytest.raises(ValueError):
        admit_episode(
            run.model_copy(update={"agent_backend": "injected_test_model"}), record, path, review
        )


def test_juror_proposal_can_be_accepted_by_funding_and_public_confirmation(evidence_fixture):
    run, record, path, review = evidence_fixture
    data = json.loads(path.read_text())
    confirmation = {**data["forum_transcript"][0]["messages"][0], "sequence": 5}
    data["forum_transcript"][0]["messages"].append(confirmation)
    path.write_text(json.dumps(data))
    review = review.model_copy(
        update={
            "evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "agreement_sequences": [2, 3, 4],
            "funding_acceptance_sequence": 5,
        }
    )
    assert admit_episode(run, record, path, review)["reviewed_verdict_correct"] is False
