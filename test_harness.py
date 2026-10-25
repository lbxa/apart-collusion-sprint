#!/usr/bin/env python3
"""Test the multi-turn harness end-to-end with scripted agents and mock API.

Validates the full pipeline without requiring LLM API keys.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from experiments.runner import ExperimentRunner
from experiments.treatments import TreatmentConfig, CoalitionDef, BribeDef
from game_api.mock import MockGameAPI
from game_api.types import PayoutConfig
from scenarios.examples import FACTUAL_SCENARIOS, FALSE_CLAIMS_FOR_ATTACK


async def test_honest_baseline():
    """All honest scripted agents — should get perfect accuracy."""
    print("\n=== Test: Honest Baseline (Multi-Turn) ===")
    api = MockGameAPI()
    runner = ExperimentRunner(api, output_dir=Path("/tmp/test_results"))

    treatment = TreatmentConfig(
        treatment_id="test_honest",
        name="Test Honest Baseline",
        description="All scripted honest agents, 3 rounds of deliberation",
        jury_size=5,
        deliberation_rounds=3,
        num_episodes=5,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2, 3, 4],
        scripted_juror_type="honest",
    )

    metrics = await runner.run_experiment(treatment, FACTUAL_SCENARIOS)
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
    api = MockGameAPI()
    runner = ExperimentRunner(api, output_dir=Path("/tmp/test_results"))

    treatment = TreatmentConfig(
        treatment_id="test_adversarial",
        name="Test Adversarial Majority",
        description="5 adversarial jurors on false claims",
        jury_size=5,
        deliberation_rounds=2,
        num_episodes=3,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2, 3, 4],
        scripted_juror_type="adversarial",
    )

    metrics = await runner.run_experiment(treatment, FALSE_CLAIMS_FOR_ATTACK)
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
    api = MockGameAPI()
    runner = ExperimentRunner(api, output_dir=Path("/tmp/test_results"))

    treatment = TreatmentConfig(
        treatment_id="test_non_voter",
        name="Test Non-Voter Attack",
        description="All jurors refuse to cast final votes",
        jury_size=5,
        deliberation_rounds=2,
        num_episodes=3,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2, 3, 4],
        scripted_juror_type="non_voting",
    )

    metrics = await runner.run_experiment(treatment, FALSE_CLAIMS_FOR_ATTACK)
    summary = metrics.summary()

    print(f"  Hung jury rate: {summary['hung_jury_rate']}")
    print(f"  Completion rate: {summary['completion_rate']}")
    print(f"  Participation loss: {summary['participation_loss']}")

    assert summary["hung_jury_rate"] == 1.0, f"Expected 100% hung juries, got {summary['hung_jury_rate']}"
    assert summary["completion_rate"] == 0.0
    assert summary["participation_loss"] > 0, "Expected bond forfeitures from non-voters"
    print("  PASSED ✓")


async def test_settlement_accounting():
    """Verify payout math with $10/$10 bets."""
    print("\n=== Test: Settlement Accounting ===")
    api = MockGameAPI()
    runner = ExperimentRunner(api, output_dir=Path("/tmp/test_results"))

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
        description="Verify $10/$10 payout math",
        jury_size=5,
        payout=payout,
        deliberation_rounds=1,
        num_episodes=2,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2, 3, 4],
        scripted_juror_type="honest",
    )

    metrics = await runner.run_experiment(treatment, FACTUAL_SCENARIOS[:2])

    for ep in metrics.episodes:
        if ep.outcome in ("SETTLED_CREATOR", "SETTLED_CHALLENGER"):
            settlement = ep.settlement
            winner_payout = settlement["winner_payout"]
            juror_total = sum(settlement["juror_payouts"].values())
            protocol_fee = settlement["protocol_fee"]

            # Winner gets bet back ($10) + 60% of loser's bet ($6) = $16
            assert abs(winner_payout - 16.0) < 0.01, f"Expected winner to get $16, got {winner_payout}"

            # 5 jurors split 30% of $10 = $3, plus bonds back
            # Each juror: $1 bond + $0.60 share = $1.60
            expected_juror_total = 5 * (1.0 + 0.60)
            assert abs(juror_total - expected_juror_total) < 0.01, \
                f"Expected juror total ${expected_juror_total}, got {juror_total}"

            # Protocol gets 10% of $10 = $1
            assert abs(protocol_fee - 1.0) < 0.01, f"Expected protocol fee $1, got {protocol_fee}"

            print(f"  Episode {ep.episode_id}: winner=${winner_payout:.2f}, "
                  f"jurors=${juror_total:.2f}, protocol=${protocol_fee:.2f}")

    print("  PASSED ✓")


async def test_deliberation_messages():
    """Verify deliberation produces messages and straw polls."""
    print("\n=== Test: Deliberation Messages ===")
    api = MockGameAPI()
    runner = ExperimentRunner(api, output_dir=Path("/tmp/test_results"))

    treatment = TreatmentConfig(
        treatment_id="test_deliberation",
        name="Test Deliberation",
        description="Verify multi-round deliberation works",
        jury_size=3,
        deliberation_rounds=5,
        num_episodes=1,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2],
        scripted_juror_type="honest",
    )

    metrics = await runner.run_experiment(treatment, FACTUAL_SCENARIOS[:1])
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
    api = MockGameAPI()
    runner = ExperimentRunner(api, output_dir=Path("/tmp/test_results"))

    # 80% to winner, 15% to jurors, 5% protocol
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
        description="80/15/5 split with $2 bond",
        jury_size=3,
        payout=payout,
        deliberation_rounds=1,
        num_episodes=1,
        use_scripted_creator=True,
        use_scripted_challenger=True,
        scripted_juror_indices=[0, 1, 2],
        scripted_juror_type="honest",
    )

    metrics = await runner.run_experiment(treatment, FACTUAL_SCENARIOS[:1])
    ep = metrics.episodes[0]

    assert ep.outcome in ("SETTLED_CREATOR", "SETTLED_CHALLENGER")
    settlement = ep.settlement

    # Winner: $10 bet + 80% of $10 = $18
    assert abs(settlement["winner_payout"] - 18.0) < 0.01

    # 3 jurors split 15% of $10 = $1.50, plus $2 bond each
    # Each juror: $2 + $0.50 = $2.50
    for jid, jpay in settlement["juror_payouts"].items():
        assert abs(jpay - 2.50) < 0.01, f"Expected juror payout $2.50, got {jpay}"

    # Protocol: 5% of $10 = $0.50
    assert abs(settlement["protocol_fee"] - 0.50) < 0.01

    print(f"  Winner: ${settlement['winner_payout']:.2f}")
    print(f"  Per juror: ${list(settlement['juror_payouts'].values())[0]:.2f}")
    print(f"  Protocol: ${settlement['protocol_fee']:.2f}")
    print("  PASSED ✓")


async def run_all_tests():
    print("=" * 60)
    print("MULTI-TURN HARNESS INTEGRATION TESTS")
    print("=" * 60)

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
