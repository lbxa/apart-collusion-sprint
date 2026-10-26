#!/usr/bin/env python3
"""Test the multi-turn harness end-to-end with scripted agents and Rust/Anvil.

Validates the full pipeline without requiring LLM API keys.
"""

import asyncio
from decimal import Decimal
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from agents.llm_agent import parse_json_reply
from experiments.runner import ExperimentRunner
from experiments.treatments import TreatmentConfig
from game_api.core_engine import CoreEngineAPI
from game_api.types import PayoutConfig
from scenarios.examples import FACTUAL_SCENARIOS, FALSE_CLAIMS_FOR_ATTACK


def test_llm_action_with_literal_newline():
    """Model JSON strings may contain unescaped line breaks."""
    action = parse_json_reply(
        '{"action":"deliberate","message":"First point.\nSecond point."}',
        "test_juror",
    )
    assert action["message"] == "First point.\nSecond point."


async def run_scripted_experiment(treatment, scenarios):
    """Own the actual protocol processes and verify authoritative run evidence."""
    with tempfile.TemporaryDirectory(prefix="veracity-harness-") as directory:
        async with CoreEngineAPI() as api:
            metrics = await ExperimentRunner(api, output_dir=Path(directory)).run_experiment(
                treatment, scenarios)
    for episode in metrics.episodes:
        assert episode.status == "completed", episode.failure_reason
        assert not episode.infrastructure_failure, episode.failure_reason
        assert episode.config["game_backend"] == "core"
        assert episode.settlement["engine_evidence"]
    return metrics


async def test_honest_baseline():
    """All honest scripted agents — should get perfect accuracy."""
    print("\n=== Test: Honest Baseline (Multi-Turn) ===")

    treatment = TreatmentConfig(
        treatment_id="test_honest",
        name="Test Honest Baseline",
        description="All scripted honest agents, 3 rounds of deliberation",
        public_messaging=True,
        jury_size=5,
        deliberation_rounds=3,
        num_episodes=5,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2, 3, 4],
        scripted_juror_type="honest",
    )

    metrics = await run_scripted_experiment(treatment, FACTUAL_SCENARIOS)
    summary = metrics.summary()

    print(f"  Verdict accuracy: {summary['verdict_accuracy']}")
    print(f"  Completion rate: {summary['completion_rate']}")
    print(f"  Hung jury rate: {summary['hung_jury_rate']}")
    print(f"  Messages per episode: {summary['avg_messages_per_episode']}")
    print(f"  Infrastructure failures: {summary['infrastructure_failure_rate']}")

    assert summary["verdict_accuracy"] == 1.0, f"Expected 100% accuracy, got {summary['verdict_accuracy']}"
    assert summary["completion_rate"] == 1.0, f"Expected 100% completion, got {summary['completion_rate']}"
    assert summary["hung_jury_rate"] == 0.0
    assert summary["infrastructure_failure_rate"] == 0.0
    # 5 jurors * 3 rounds = 15 messages per episode
    assert summary["avg_messages_per_episode"] == 15.0
    print("  PASSED ✓")


async def test_adversarial_majority():
    """Adversarial majority on false claims — should produce false verdicts."""
    print("\n=== Test: Adversarial Majority (Multi-Turn) ===")

    treatment = TreatmentConfig(
        treatment_id="test_adversarial",
        name="Test Adversarial Majority",
        description="5 adversarial jurors on false claims",
        public_messaging=True,
        jury_size=5,
        deliberation_rounds=2,
        num_episodes=3,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2, 3, 4],
        scripted_juror_type="adversarial",
    )

    metrics = await run_scripted_experiment(treatment, FALSE_CLAIMS_FOR_ATTACK)
    summary = metrics.summary()

    print(f"  Verdict accuracy: {summary['verdict_accuracy']}")
    print(f"  False-verdict rate: {summary['false_verdict_rate']}")
    print(f"  Completion rate: {summary['completion_rate']}")

    assert summary["false_verdict_rate"] > 0, "Expected some false verdicts with adversarial majority"
    assert summary["completion_rate"] == 1.0
    print("  PASSED ✓")


async def test_non_voter_attack():
    """Non-voting agents should cause hung juries."""
    print("\n=== Test: Non-Voter Attack ===")

    treatment = TreatmentConfig(
        treatment_id="test_non_voter",
        name="Test Non-Voter Attack",
        description="All jurors refuse to cast final votes",
        public_messaging=True,
        jury_size=5,
        deliberation_rounds=2,
        num_episodes=3,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2, 3, 4],
        scripted_juror_type="non_voting",
    )

    metrics = await run_scripted_experiment(treatment, FALSE_CLAIMS_FOR_ATTACK)
    summary = metrics.summary()

    print(f"  Hung jury rate: {summary['hung_jury_rate']}")
    print(f"  Completion rate: {summary['completion_rate']}")
    print(f"  Participation loss: {summary['participation_loss']}")

    assert summary["hung_jury_rate"] == 1.0, f"Expected 100% hung juries, got {summary['hung_jury_rate']}"
    assert summary["completion_rate"] == 0.0
    assert Decimal(str(summary["participation_loss"])) == 0, "Absent jurors never deposit a bond"
    assert all(not record.forfeited for record in metrics.episodes)
    assert all(set(record.bonds_deposited) == {record.creator_id, record.challenger_id}
               for record in metrics.episodes)
    print("  PASSED ✓")


async def test_settlement_accounting():
    """Verify contract payout evidence with 10-token party stakes."""
    print("\n=== Test: Settlement Accounting ===")

    payout = PayoutConfig(
        creator_bet=10.0,
        challenger_bet=10.0,
        winner_pct=0.60,
        juror_pool_pct=0.30,
        protocol_pct=0.10,
        juror_bond=1.0,
    )

    treatment = TreatmentConfig(
        treatment_id="test_accounting",
        name="Test Accounting",
        description="Verify contract payouts with 10-token party stakes",
        public_messaging=True,
        jury_size=5,
        payout=payout,
        deliberation_rounds=1,
        num_episodes=2,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2, 3, 4],
        scripted_juror_type="honest",
    )

    metrics = await run_scripted_experiment(treatment, FACTUAL_SCENARIOS[:2])

    for ep in metrics.episodes:
        if ep.outcome in ("SETTLED_CREATOR", "SETTLED_CHALLENGER"):
            settlement = ep.settlement
            winner_payout = settlement["winner_payout"]
            juror_total = sum(settlement["juror_payouts"].values())
            protocol_fee = settlement["protocol_fee"]

            # The observed winner entitlement is 16 tokens.
            assert winner_payout == Decimal("16.00"), f"Expected winner to get 16 tokens, got {winner_payout}"

            # Five valid revealers receive 8 tokens including their bonds.
            assert juror_total == Decimal("8.00"), f"Expected juror total 8 tokens, got {juror_total}"

            # The observed protocol entitlement is 1 token.
            assert protocol_fee == Decimal("1.00"), f"Expected protocol fee 1 token, got {protocol_fee}"

            print(f"  Episode {ep.episode_id}: winner={winner_payout:.2f}, "
                  f"jurors={juror_total:.2f}, protocol={protocol_fee:.2f} tokens")

    print("  PASSED ✓")


async def test_deliberation_messages():
    """Verify deliberation produces messages and straw polls."""
    print("\n=== Test: Deliberation Messages ===")

    treatment = TreatmentConfig(
        treatment_id="test_deliberation",
        name="Test Deliberation",
        description="Verify multi-round deliberation works",
        public_messaging=True,
        jury_size=3,
        deliberation_rounds=5,
        num_episodes=1,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2],
        scripted_juror_type="honest",
    )

    metrics = await run_scripted_experiment(treatment, FACTUAL_SCENARIOS[:1])
    ep = metrics.episodes[0]

    # 3 jurors * 5 rounds = 15 messages
    assert len(ep.messages) == 15, f"Expected 15 messages, got {len(ep.messages)}"

    # 5 straw polls
    assert len(ep.straw_polls) == 5, f"Expected 5 straw polls, got {len(ep.straw_polls)}"

    # Each straw poll should have votes from honest agents
    for poll in ep.straw_polls:
        total = poll["creator_votes"] + poll["challenger_votes"]
        assert total == 3, f"Expected 3 straw votes per round, got {total}"

    print(f"  Messages: {len(ep.messages)}")
    print(f"  Straw polls: {len(ep.straw_polls)}")
    print(f"  Rounds per message recorded: {set(m['round'] for m in ep.messages)}")
    print("  PASSED ✓")


async def test_custom_payout_structure():
    """Test with different payout percentages."""
    print("\n=== Test: Custom Payout Structure ===")

    # Configure 80% to winner, 15% to jurors, 5% protocol.
    payout = PayoutConfig(
        creator_bet=10.0,
        challenger_bet=10.0,
        winner_pct=0.80,
        juror_pool_pct=0.15,
        protocol_pct=0.05,
        juror_bond=2.0,
    )

    treatment = TreatmentConfig(
        treatment_id="test_custom_payout",
        name="Test Custom Payout",
        description="80/15/5 split with a 2-token bond",
        public_messaging=True,
        jury_size=3,
        payout=payout,
        deliberation_rounds=1,
        num_episodes=1,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2],
        scripted_juror_type="honest",
    )

    metrics = await run_scripted_experiment(treatment, FACTUAL_SCENARIOS[:1])
    ep = metrics.episodes[0]

    assert ep.outcome in ("SETTLED_CREATOR", "SETTLED_CHALLENGER")
    settlement = ep.settlement

    # Verify entitlements returned by the contract, without a local calculator.
    assert settlement["winner_payout"] == Decimal("18.00")

    for jid, jpay in settlement["juror_payouts"].items():
        assert jpay == Decimal("2.50"), f"Expected juror payout 2.50 tokens, got {jpay}"

    assert settlement["protocol_fee"] == Decimal("0.50")

    print(f"  Winner: {settlement['winner_payout']:.2f} tokens")
    print(f"  Per juror: {list(settlement['juror_payouts'].values())[0]:.2f} tokens")
    print(f"  Protocol: {settlement['protocol_fee']:.2f} tokens")
    print("  PASSED ✓")


async def run_all_tests():
    print("=" * 60)
    print("MULTI-TURN HARNESS INTEGRATION TESTS")
    print("=" * 60)

    test_llm_action_with_literal_newline()
    print("  LLM newline JSON parsing: PASSED ✓")
    await test_honest_baseline()
    await test_adversarial_majority()
    await test_non_voter_attack()
    await test_settlement_accounting()
    await test_deliberation_messages()
    await test_custom_payout_structure()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_all_tests())
