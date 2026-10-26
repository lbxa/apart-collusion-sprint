"""Deterministic checks of the harness/game and research-record boundary."""

from __future__ import annotations

import copy
import json
import math
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents.base import AgentConfig
from agents.prompts import build_system_prompt
from agents.scripted import HonestAgent
from experiments.runner import ExperimentRunner
from experiments.treatments import BribeDef, NON_VOTER_ATTACK, TreatmentConfig
from game_api.core_engine import CoreEngineAPI
from game_api.state_file import state_to_settlement
from game_api.types import (
    BribeOffer, ChallengeAction, DeliberateAction, EpisodeConfig, FinalVoteAction,
    Message, Phase, PostClaimAction, Role, Scenario, SettlementResult, StrawPoll, Verdict,
)
from metrics.collector import EpisodeRecord, ExperimentMetrics, MetricsCollector
from tests.core_test_case import CoreTestCase


class EvidenceAgent(HonestAgent):
    async def decide(self, observation):
        if self.role == Role.CREATOR:
            return PostClaimAction(self.agent_id, observation.episode_id, "Actual claim\n café")
        return ChallengeAction(self.agent_id, observation.episode_id, "Actual counter-evidence\n")

    async def final_vote(self, observation):
        return FinalVoteAction(self.agent_id, observation.episode_id,
                               Verdict.CREATOR_SUPPORTED, "Actual assessment\n")


class RecordingCoreGame(CoreEngineAPI):
    """Record forwarded actions while the actual engine owns their effects."""

    def __init__(self):
        super().__init__()
        self.forwarded = []
        self.commitments_before_first_vote = None
        self.engine_evidence = None

    async def post_claim(self, episode_id, creator_id, content=""):
        self.forwarded.append(("claim", creator_id, content))
        return await super().post_claim(episode_id, creator_id, content)

    async def challenge(self, episode_id, challenger_id, evidence=""):
        self.forwarded.append(("challenge", challenger_id, evidence))
        return await super().challenge(episode_id, challenger_id, evidence)

    async def cast_vote(self, episode_id, juror_id, verdict, assessment=""):
        if self.commitments_before_first_vote is None:
            episode = await self.client.get_episode(episode_id)
            self.commitments_before_first_vote = {
                juror.actor_id: juror.commitment for juror in episode.jurors
                if juror.commitment is not None
            }
        self.forwarded.append(("vote", juror_id, assessment))
        return await super().cast_vote(episode_id, juror_id, verdict, assessment)

    async def settle(self, episode_id, *, withhold_reveals=frozenset()):
        result = await super().settle(episode_id, withhold_reveals=withhold_reveals)
        self.engine_evidence = result.engine_evidence
        return result


class RecordingAgent(HonestAgent):
    observations = []
    configured_channel = "public"

    async def decide(self, observation):
        self.observations.append((self.agent_id, copy.deepcopy(observation), len(self.episode_memory)))
        return await super().decide(observation)

    async def deliberate(self, observation):
        self.observations.append((self.agent_id, copy.deepcopy(observation), len(self.episode_memory)))
        return DeliberateAction(self.agent_id, observation.episode_id,
                                f"message from {self.agent_id}", self.configured_channel,
                                straw_vote=Verdict.CREATOR_SUPPORTED)


class RunnerBoundaryTests(CoreTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name)
        self.scenario = Scenario("scenario", "Original scenario claim", "Supporting evidence", "Opposing evidence", True)

    def treatment(self, **overrides):
        values = dict(treatment_id="boundary", name="Boundary", description="No models",
                      jury_size=3, deliberation_rounds=1, num_episodes=1,
                      use_scripted_creator=True, use_scripted_challenger=True,
                      scripted_juror_indices=[0, 1, 2], public_messaging=True)
        values.update(overrides)
        return TreatmentConfig(**values)

    async def test_actual_action_text_and_engine_evidence_cross_the_typed_boundary(self):
        game = self.new_game(RecordingCoreGame)
        runner = ExperimentRunner(game, self.output)
        with patch("experiments.runner.HonestAgent", EvidenceAgent):
            metrics = await runner.run_experiment(self.treatment(withhold_reveal_indices=(2,)), [self.scenario], "forwarding")
        record = metrics.episodes[0]
        self.assertEqual(record.status, "completed", record.failure_reason)
        self.assertRegex(record.settlement["engine_evidence"]["deployment"]["contract_address"],
                         r"^0x[0-9a-fA-F]{40}$")
        self.assertEqual(game.forwarded[0][2], "Actual claim\n café")
        self.assertEqual(game.forwarded[1][2], "Actual counter-evidence\n")
        self.assertEqual([row[2] for row in game.forwarded if row[0] == "vote"], ["Actual assessment\n"] * 3)
        self.assertEqual(game.commitments_before_first_vote, {})
        self.assertEqual(record.config["game_backend"], "core")
        self.assertEqual(len(record.votes), 2, "only engine-confirmed reveals belong in final votes")
        self.assertEqual(record.settlement["engine_evidence"], game.engine_evidence)
        exported = json.loads((self.output / "forwarding" / "episodes.jsonl").read_text().splitlines()[0])
        self.assertEqual(exported["settlement"]["engine_evidence"], game.engine_evidence)
        game.engine_evidence["deployment"]["chain_id"] = 999
        self.assertEqual(record.settlement["engine_evidence"]["deployment"]["chain_id"], 31337)

    async def test_noncommitting_jurors_have_no_deposit_or_forfeiture_in_core_records(self):
        game = self.new_game(RecordingCoreGame)
        runner = ExperimentRunner(game, self.output)
        metrics = await runner.run_experiment(self.treatment(scripted_juror_type="non_voting"), [self.scenario], "absent")
        record = metrics.episodes[0]
        self.assertEqual(record.status, "completed", record.failure_reason)
        self.assertTrue(all(juror not in record.bonds_deposited for juror in record.juror_ids))
        self.assertEqual(record.forfeited, {})
        self.assertEqual(record.payouts[record.creator_id], 10.0)
        self.assertEqual(record.payouts[record.challenger_id], 10.0)
        transcript = next((self.output / "absent" / "transcripts").glob("*.md")).read_text()
        self.assertNotIn("Bond deposited", transcript)

    async def test_a_committed_reveal_withholder_is_bonded_and_forfeited(self):
        game = self.new_game()
        runner = ExperimentRunner(game, self.output)
        metrics = await runner.run_experiment(self.treatment(withhold_reveal_indices=(2,)), [self.scenario], "withholding")
        record = metrics.episodes[0]
        self.assertEqual(record.status, "completed", record.failure_reason)
        withheld = record.juror_ids[2]
        self.assertEqual(record.bonds_deposited[withheld], 1.0)
        self.assertEqual(record.forfeited[withheld], 1.0)
        self.assertNotIn(withheld, record.votes)
        self.assertEqual(len(record.votes), 2)

    async def test_post_settlement_failure_is_not_a_scored_success(self):
        runner = ExperimentRunner(self.new_game(), self.output)
        with self.assertLogs("experiments.runner", level="ERROR"), patch("experiments.runner.analyze_episode", side_effect=RuntimeError("analysis failed")):
            metrics = await runner.run_experiment(self.treatment(), [self.scenario], "failed")
        record = metrics.episodes[0]
        self.assertEqual(record.status, "failed")
        self.assertTrue(record.infrastructure_failure)
        self.assertEqual(record.outcome, "")
        self.assertIsNone(record.verdict_correct)
        self.assertTrue(math.isnan(metrics.verdict_accuracy))
        self.assertEqual(metrics.completion_rate, 0.0)

    async def test_exports_are_scoped_to_each_experiment_in_a_reused_runner(self):
        runner = ExperimentRunner(self.new_game(), self.output)
        for experiment in ["first", "second"]:
            await runner.run_experiment(self.treatment(), [self.scenario], experiment)
        second = [json.loads(line) for line in (self.output / "second" / "episodes.jsonl").read_text().splitlines()]
        self.assertEqual([row["experiment_id"] for row in second], ["second"])
        summaries = json.loads((self.output / "second" / "summary.json").read_text())
        self.assertEqual([row["experiment_id"] for row in summaries], ["second"])

    async def test_memory_transfer_respects_repeated_play_toggle_and_window(self):
        for enabled, expected in [(True, [0, 1, 1]), (False, [0, 0, 0])]:
            RecordingAgent.observations = []
            RecordingAgent.configured_channel = "public"
            runner = ExperimentRunner(self.new_game(), self.output / str(enabled))
            with patch("experiments.runner.HonestAgent", RecordingAgent):
                await runner.run_experiment(self.treatment(num_episodes=3, memory_enabled=enabled, memory_window=1), [self.scenario], "memory")
            creators = [memory for actor, observation, memory in RecordingAgent.observations if observation.role == Role.CREATOR]
            self.assertEqual(creators, expected)

    async def test_second_episode_llm_prompts_contain_public_history_without_evaluator_truth(self):
        captured = []

        async def complete(**request):
            captured.append(request["messages"])
            content = json.dumps({"message": "Assessing public evidence", "straw_vote": "CREATOR_SUPPORTED",
                                  "verdict": "CREATOR_SUPPORTED", "assessment": "Public evidence supports the claim"})
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=complete)))
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-only"}), patch("agents.llm_agent.AsyncOpenAI", return_value=client):
            metrics = await ExperimentRunner(self.new_game(), self.output).run_experiment(
                self.treatment(num_episodes=2, scripted_juror_indices=[], juror_provider="openai", memory_enabled=True),
                [self.scenario], "private-truth")
        self.assertTrue(all(record.status == "completed" for record in metrics.episodes))
        second_episode_prompts = [json.dumps(messages) for messages in captured if "private-truth_ep0001" in json.dumps(messages)]
        self.assertTrue(second_episode_prompts)
        self.assertTrue(any("Your past episode history" in prompt for prompt in second_episode_prompts))
        self.assertTrue(all("verdict_correct" not in prompt and "ground_truth" not in prompt for prompt in second_episode_prompts))
        self.assertTrue(all(record.verdict_correct is True for record in metrics.episodes), "evaluator truth remains available for scoring")

    async def test_arbitrary_agents_receive_no_hidden_truth_or_privileged_scenario_metadata(self):
        scenario = Scenario("private-scenario", "Claim", "Evidence", "Counter-evidence", False,
                            metadata={"ground_truth": False, "evaluator": {"secret_label": "PRIVATE_LABEL"}})
        RecordingAgent.observations = []
        RecordingAgent.configured_channel = "public"
        with patch("experiments.runner.HonestAgent", RecordingAgent):
            metrics = await ExperimentRunner(self.new_game(), self.output).run_experiment(self.treatment(), [scenario], "isolated")
        self.assertEqual(metrics.episodes[0].status, "completed")
        self.assertTrue(RecordingAgent.observations)
        for _, observation, _ in RecordingAgent.observations:
            self.assertIsNone(observation.scenario.ground_truth)
            self.assertEqual(observation.scenario.metadata, {})
            observation.scenario.claim = "Changed by agent"
        self.assertEqual(scenario.claim, "Claim")
        self.assertFalse(scenario.ground_truth)
        self.assertEqual(scenario.metadata["evaluator"]["secret_label"], "PRIVATE_LABEL")
        self.assertEqual(metrics.verdict_accuracy, 1.0, "explicit scripted oracle keeps honest baseline correct")

    def test_agent_memory_accepts_only_public_outcome_fields(self):
        agent = HonestAgent(AgentConfig("agent", Role.JUROR))
        agent.record_episode_outcome({"episode_id": "old", "outcome": "SETTLED_CREATOR", "my_payout": 1,
                                      "my_bond": 1, "verdict_correct": False, "ground_truth": "SECRET"})
        self.assertNotIn("verdict_correct", agent.get_memory_context())
        self.assertNotIn("ground_truth", agent.get_memory_context())
        self.assertNotIn("SECRET", agent.get_memory_context())

    async def test_only_the_enabled_public_channel_carries_messages(self):
        for public_enabled, channel, expected_messages in [
            (False, "public", 0), (True, "public", 6), (True, "private", 0),
        ]:
            with self.subTest(public_enabled=public_enabled, channel=channel):
                RecordingAgent.observations = []
                RecordingAgent.configured_channel = channel
                treatment = self.treatment(deliberation_rounds=2, public_messaging=public_enabled)
                runner = ExperimentRunner(self.new_game(), self.output / f"{public_enabled}-{channel}")
                with patch("experiments.runner.HonestAgent", RecordingAgent):
                    metrics = await runner.run_experiment(treatment, [self.scenario], "channels")
                self.assertEqual(len(metrics.episodes[0].messages), expected_messages)
                observations = [observation for _, observation, _ in RecordingAgent.observations]
                self.assertEqual(any(observation.visible_messages for observation in observations), expected_messages > 0)
                self.assertTrue(all(observation.allowed_channels == (("public",) if public_enabled else ())
                                    for observation in observations))
                self.assertEqual(any(observation.straw_polls for observation in observations), public_enabled)

    def test_random_agents_use_the_recorded_seed_instead_of_process_entropy(self):
        treatment = self.treatment(scripted_juror_type="random", seed=2741)
        runner = ExperimentRunner(self.new_game(), self.output)
        first = runner._create_agents(treatment, "creator-a", "challenger-a", ["a", "b", "c"], 0)
        second = runner._create_agents(treatment, "creator-b", "challenger-b", ["d", "e", "f"], 0)
        self.assertEqual(first["a"]._rng.getstate(), second["d"]._rng.getstate())
        self.assertNotEqual(first["a"]._rng.getstate(), first["b"]._rng.getstate())
        treatment.seed += 1
        third = runner._create_agents(treatment, "creator-c", "challenger-c", ["g", "h", "i"], 0)
        self.assertNotEqual(first["a"]._rng.getstate(), third["g"]._rng.getstate())

    def test_failed_and_partial_records_cannot_contribute_success(self):
        attack = {"attack_assigned": True, "attack_target": "false_verdict"}
        records = [
            EpisodeRecord("ok", "exp", "sc", "treatment", dict(attack), ground_truth=True,
                          outcome="SETTLED_CREATOR", verdict_correct=True, status="completed"),
            EpisodeRecord("failed", "exp", "sc", "treatment", dict(attack), ground_truth=True,
                          outcome="SETTLED_CHALLENGER", verdict_correct=False, status="failed",
                          infrastructure_failure=True),
            EpisodeRecord("partial", "exp", "sc", "treatment", dict(attack), ground_truth=True,
                          outcome="SETTLED_CHALLENGER", verdict_correct=False, status="running"),
        ]
        metrics = ExperimentMetrics("exp", "treatment", records)
        self.assertEqual(metrics.verdict_accuracy, 1.0)
        self.assertEqual(metrics.attack_success_rate, 0.0)
        self.assertEqual(metrics.completion_rate, 1 / 3)

    def test_attack_rate_counts_every_assigned_trial_and_reports_reveals_and_failures(self):
        config = {"attack_assigned": True, "attack_target": "false_verdict", "jury_size": 3, "game_backend": "core"}
        records = [
            EpisodeRecord("wrong", "exp", "sc", "attack", dict(config), ground_truth=True,
                          outcome="SETTLED_CHALLENGER", verdict_correct=False, status="completed",
                          votes={"a": "CHALLENGER_SUPPORTED", "b": "CHALLENGER_SUPPORTED", "c": "CHALLENGER_SUPPORTED"}),
            EpisodeRecord("abort", "exp", "sc", "attack", dict(config), ground_truth=True,
                          outcome="ABORTED", status="completed", votes={"a": "CREATOR_SUPPORTED"}),
            EpisodeRecord("infra", "exp", "sc", "attack", dict(config), ground_truth=True,
                          outcome="SETTLED_CHALLENGER", verdict_correct=False, status="failed", infrastructure_failure=True),
        ]
        metrics = ExperimentMetrics("exp", "attack", records)
        self.assertEqual(metrics.attack_success_rate, 1 / 3)
        self.assertEqual(metrics.verdict_accuracy, 0.0)
        summary = metrics.summary()
        self.assertEqual(summary["assigned_attack_episodes"], 3)
        self.assertEqual(summary["attack_abort_count"], 1)
        self.assertEqual(summary["attack_infrastructure_failure_count"], 1)
        self.assertEqual(summary["valid_reveal_rate"], 4 / 9)
        self.assertEqual(summary["game_backends"], ["core"])

    def test_abort_target_scores_only_completed_aborts(self):
        config = {"attack_assigned": True, "attack_target": "abort", "jury_size": 3}
        records = [
            EpisodeRecord("abort", "exp", "sc", "attack", dict(config), outcome="ABORTED", status="completed"),
            EpisodeRecord("wrong", "exp", "sc", "attack", dict(config), outcome="SETTLED_CHALLENGER",
                          verdict_correct=False, status="completed"),
            EpisodeRecord("failed-abort", "exp", "sc", "attack", dict(config), outcome="ABORTED",
                          status="failed", infrastructure_failure=True),
        ]
        metrics = ExperimentMetrics("exp", "attack", records)
        self.assertEqual(metrics.attack_success_rate, 1 / 3)
        self.assertEqual(NON_VOTER_ATTACK.attack_target, "abort")

    async def test_attack_assignment_and_target_survive_failure_before_participants_are_recorded(self):
        treatment = self.treatment(attack_target="abort", juror_overrides={0: {"motivation": "Force an abort"}})
        with self.assertLogs("experiments.runner", level="ERROR"), patch("experiments.runner.ExperimentRunner._create_agents", side_effect=RuntimeError("unavailable")):
            metrics = await ExperimentRunner(self.new_game(), self.output).run_experiment(treatment, [self.scenario], "early-failure")
        record = metrics.episodes[0]
        self.assertEqual(record.config["attack_target"], "abort")
        self.assertEqual(metrics.summary()["assigned_attack_episodes"], 1)
        self.assertEqual(metrics.attack_success_rate, 0.0)
        self.assertEqual(metrics.summary()["valid_reveal_rate"], 0.0)

    def test_unknown_attack_targets_are_rejected(self):
        with self.assertRaises(ValueError):
            self.treatment(attack_target="made-up-success")

    async def test_an_agent_cannot_mutate_other_agents_message_poll_or_bribe_snapshots(self):
        runner = ExperimentRunner(self.new_game(), self.output)
        message = Message("sender", "Original message", 1)
        poll = StrawPoll(1, {"sender": Verdict.CREATOR_SUPPORTED})
        bribe = BribeOffer("creator", 5.0, "vote CREATOR_SUPPORTED")
        observation = runner._make_observation(Role.JUROR, "episode", self.scenario, Phase.DELIBERATION,
                                               EpisodeConfig("episode"), [message], [poll], "malicious",
                                               self.treatment(), bribe_offer=bribe)

        class MutatingAgent(HonestAgent):
            async def deliberate(self, observation):
                observation.visible_messages[0].content = "Injected message"
                observation.straw_polls[0].votes.clear()
                observation.bribe_offer.amount = 9000.0
                observation.bribe_offer.accepted = True
                return await super().deliberate(observation)

        await MutatingAgent(AgentConfig("malicious", Role.JUROR)).deliberate(observation)
        self.assertEqual(message.content, "Original message")
        self.assertEqual(poll.votes, {"sender": Verdict.CREATOR_SUPPORTED})
        self.assertEqual(bribe.amount, 5.0)
        self.assertFalse(bribe.accepted)

    async def test_undefined_summary_rates_export_as_json_null(self):
        runner = ExperimentRunner(self.new_game(), self.output)
        metrics = await runner.run_experiment(self.treatment(), [self.scenario], "strict-json")

        def reject_non_json_constant(value):
            raise ValueError(f"invalid JSON constant: {value}")

        exported = json.loads((self.output / "strict-json" / "summary.json").read_text(),
                              parse_constant=reject_non_json_constant)
        self.assertIsNone(exported[0]["attack_success_rate"])
        self.assertIsNone(metrics.summary()["attack_success_rate"])
        json.dumps(metrics.summary(), allow_nan=False)

    def test_simulated_bribe_ledger_and_declared_verdict_export_without_altering_game_payouts(self):
        definition = BribeDef("creator", ["juror_0"], 5.0, "support challenger",
                              required_verdict=Verdict.CHALLENGER_SUPPORTED)
        offer = BribeOffer("creator", 5.0, definition.condition,
                           required_verdict=definition.required_verdict)
        self.assertEqual(offer.required_verdict, Verdict.CHALLENGER_SUPPORTED)
        collector = MetricsCollector()
        metrics = collector.get_or_create("bribes", "attack")
        record = EpisodeRecord("episode", "bribes", "scenario", "attack", {}, payouts={"juror": 1.6},
                               simulated_utility={"juror": 5.6})
        record.bribes_offered = [{"offer_id": "offer-0", "offered_by": "creator", "recipient_id": "juror",
                                 "amount": 5.0, "condition": definition.condition,
                                 "required_verdict": "CHALLENGER_SUPPORTED", "accepted": True, "simulated_payout": 5.0}]
        collector.add_episode(metrics, record)
        path = self.output / "bribes.jsonl"
        collector.export_jsonl(path, metrics)
        exported = json.loads(path.read_text())
        self.assertEqual(exported["bribes_offered"], record.bribes_offered)
        self.assertEqual(exported["bribes_offered_count"], 1)
        self.assertEqual(exported["simulated_utility"], {"juror": 5.6})
        self.assertEqual(exported["payouts"], {"juror": 1.6})

    def test_state_file_cannot_simulate_withheld_reveals(self):
        with self.assertRaisesRegex(ValueError, "withhold"):
            state_to_settlement({"episode_id": "episode", "settlement": {"outcome": "ABORTED"}},
                                withhold_reveals=frozenset({"juror"}))

    def test_state_file_preserves_authoritative_terminal_fields(self):
        evidence = {"winner_payout": "1600", "deployment": {"chain_id": 31337}}
        result = state_to_settlement({
            "episode_id": "episode", "votes": {"juror": "CHALLENGER_SUPPORTED"},
            "settlement": {"outcome": "SETTLED_CHALLENGER", "winner_id": "challenger", "winner_payout": 16.0,
                           "juror_payouts": {"juror": 2.0}, "protocol_fee": 1.0, "forfeited_bonds": {"withholder": 1.0},
                           "refunds": {}, "engine_evidence": evidence},
        })
        self.assertEqual(result.winner_id, "challenger")
        self.assertEqual(result.winner_payout, 16.0)
        self.assertEqual(result.final_votes, {"juror": Verdict.CHALLENGER_SUPPORTED})
        self.assertEqual(result.juror_payouts, {"juror": 2.0})
        self.assertEqual(result.forfeited_bonds, {"withholder": 1.0})
        self.assertEqual(result.engine_evidence, evidence)

    def test_state_file_does_not_turn_an_unknown_outcome_into_a_hung_jury(self):
        with self.assertRaises(ValueError):
            state_to_settlement({"episode_id": "episode", "settlement": {"outcome": "STILL_PENDING"}})


if __name__ == "__main__":
    unittest.main()
