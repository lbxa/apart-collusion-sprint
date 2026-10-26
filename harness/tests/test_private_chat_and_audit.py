"""Private chat (Channel) and audited side payments (Audit) in the experiment runner."""

import copy
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from agents.base import AgentConfig
from agents.llm_agent import LLMAgent
from agents.prompts import build_observation_prompt, build_system_prompt
from agents.scripted import HonestAgent
from experiments.design import CONDITIONS, Cell, resolve_cell, treatment_for
from experiments.runner import ExperimentRunner
from experiments.treatments import TreatmentConfig
from game_api.mock import MockGameAPI
from game_api.types import (
    ChatAction, EpisodeConfig, Observation, OfferTransfersAction, Phase, PrivateMessage,
    Role, Scenario, TransferProposal, Verdict,
)

SCENARIO = Scenario("scenario", "Claim", "For", "Against", True)


def short(actor_id: str) -> str:
    """'juror_0_<episode>' -> 'juror_0'; 'creator_<episode>' -> 'creator'."""
    parts = actor_id.split("_")
    return "_".join(parts[:2]) if parts[0] == "juror" else parts[0]


class ChatPlanAgent(HonestAgent):
    """Scripted agent whose private messages come from `plan[(name, round)]`, by short name."""
    plan: dict[tuple[str, int], list[tuple[str, str]]] = {}
    offers: dict[str, list[tuple[str, float]]] = {}
    observations: list[Observation] = []

    def _planned(self, observation):
        by_name = {short(actor): actor for actor in observation.chat_participants}
        return [PrivateMessage(by_name.get(to, to), text)
                for to, text in self.plan.get((short(self.agent_id), observation.current_round), [])]

    async def chat(self, observation):
        self.observations.append(copy.deepcopy(observation))
        return ChatAction(self.agent_id, observation.episode_id, self._planned(observation))

    async def deliberate(self, observation):
        self.observations.append(copy.deepcopy(observation))
        action = await super().deliberate(observation)
        action.private_messages = self._planned(observation)
        return action

    async def final_vote(self, observation):
        self.observations.append(copy.deepcopy(observation))
        return await super().final_vote(observation)

    async def offer_transfers(self, observation):
        by_name = {short(actor): actor for actor in observation.transfer_recipients}
        return OfferTransfersAction(self.agent_id, observation.episode_id, [
            TransferProposal(by_name[to], amount, Verdict.CREATOR_SUPPORTED)
            for to, amount in self.offers.get(short(self.agent_id), [])])


class ChatAndAuditRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name)
        ChatPlanAgent.plan, ChatPlanAgent.offers, ChatPlanAgent.observations = {}, {}, []

    def treatment(self, **overrides):
        values = dict(treatment_id="chat", name="Chat", description="Scripted", jury_size=3,
                      deliberation_rounds=2, num_episodes=1, use_scripted_creator=True,
                      use_scripted_challenger=True, scripted_juror_indices=[0, 1, 2], public_messaging=True)
        values.update(overrides)
        return TreatmentConfig(**values)

    async def run_episode(self, treatment, game=None):
        with patch("experiments.runner.HonestAgent", ChatPlanAgent):
            metrics = await ExperimentRunner(game or MockGameAPI(), self.output).run_experiment(
                treatment, [SCENARIO], "chat")
        [record] = metrics.episodes
        self.assertEqual(record.status, "completed", record.failure_reason)
        return record

    def private_seen(self, name):
        """Private messages each observation of `name` showed, as (sender, recipient, content) short names.

        An agent's chat_participants lists everyone but itself, which identifies its observations.
        """
        views = []
        for o in ChatPlanAgent.observations:
            everyone = {short(a) for a in o.chat_participants}
            if o.chat_participants and name not in everyone:
                views.append([(short(m.sender_id), short(m.recipient_id), m.content) for m in o.private_messages])
        return views

    async def test_parties_and_jurors_chat_privately_and_records_keep_each_message(self):
        ChatPlanAgent.plan = {("creator", 1): [("juror_0", "Vote for me")],
                              ("juror_0", 1): [("creator", "What do I get?")]}
        game = MockGameAPI()
        record = await self.run_episode(self.treatment(private_chat=True), game)
        private = [(short(m["sender"]), short(m["recipient"]), m["content"])
                   for m in record.messages if m["channel"] == "private"]
        self.assertEqual(private, [("creator", "juror_0", "Vote for me"), ("juror_0", "creator", "What do I get?")])
        self.assertEqual(record.chat_audit["message_count"], 2)
        self.assertTrue(record.chat_audit["prohibited_communication_used"], "chats use the prohibited default")
        # Only the pair ever sees the chat; juror_1 never does.
        self.assertFalse(any(self.private_seen("juror_1")))
        self.assertIn([("juror_0", "creator", "What do I get?")], self.private_seen("juror_0"))

    async def test_history_off_shows_only_each_chats_latest_message(self):
        ChatPlanAgent.plan = {("creator", 1): [("juror_0", "first")], ("creator", 2): [("juror_0", "second")]}
        await self.run_episode(self.treatment(private_chat=True))
        final_view = self.private_seen("juror_0")[-1]
        self.assertEqual(final_view, [("creator", "juror_0", "second")])

        ChatPlanAgent.observations = []
        await self.run_episode(self.treatment(private_chat=True, chat_history=True))
        self.assertEqual(self.private_seen("juror_0")[-1],
                         [("creator", "juror_0", "first"), ("creator", "juror_0", "second")])

    async def test_without_the_channel_no_chat_turns_run_and_juror_messages_are_blocked(self):
        ChatPlanAgent.plan = {("juror_0", 1): [("creator", "hello")]}
        record = await self.run_episode(self.treatment(private_chat=False))
        self.assertFalse([m for m in record.messages if m["channel"] == "private"])
        self.assertIsNone(record.chat_audit)
        self.assertFalse(any(o.role != Role.JUROR for o in ChatPlanAgent.observations))
        self.assertFalse(any(o.chat_participants for o in ChatPlanAgent.observations))

    async def test_invalid_recipients_are_dropped_without_ending_the_episode(self):
        ChatPlanAgent.plan = {("juror_0", 1): [("juror_0", "to myself"), ("nobody", "to nobody")]}
        record = await self.run_episode(self.treatment(private_chat=True))
        self.assertFalse([m for m in record.messages if m["channel"] == "private"])

    async def test_audits_forfeit_the_bond_of_jurors_paid_by_an_audited_side_payment(self):
        ChatPlanAgent.offers = {"creator": [("juror_0", 1.0), ("juror_1", 1.0)]}

        class Accepting(ChatPlanAgent):
            async def deliberate(self, observation):
                if observation.bribe_offer:
                    observation.bribe_offer.accepted = True
                return await super().deliberate(observation)

        with patch("experiments.runner.HonestAgent", Accepting):
            metrics = await ExperimentRunner(MockGameAPI(), self.output).run_experiment(
                self.treatment(transfers_enabled=True, audit_probability=1.0), [SCENARIO], "audit")
        [record] = metrics.episodes
        jurors = record.juror_ids
        self.assertEqual(record.audit_penalties, {jurors[0]: 1.0, jurors[1]: 1.0})
        self.assertEqual(record.simulated_utility[jurors[0]], 0.0, "paid $1, then forfeited the $1 bond")
        self.assertTrue(all(offer["audited"] for offer in record.bribes_offered))

        with patch("experiments.runner.HonestAgent", Accepting):
            metrics = await ExperimentRunner(MockGameAPI(), self.output).run_experiment(
                self.treatment(transfers_enabled=True, audit_probability=0.0), [SCENARIO], "no-audit")
        self.assertEqual(metrics.episodes[0].audit_penalties, {})

    def test_audit_requires_side_payments(self):
        with self.assertRaises(ValueError):
            self.treatment(audit_probability=0.3)
        with self.assertRaises(ValueError):
            self.treatment(transfers_enabled=True, audit_probability=1.5)
        with self.assertRaises(ValueError):
            Cell.parse("M1-C1-T0-R1-S1-E1-A1")


class ConditionTests(unittest.TestCase):
    def test_named_conditions_resolve_to_the_planned_cells(self):
        self.assertEqual(resolve_cell("F"), Cell.parse("M1-C1-T1-R1-S1-E1"))
        self.assertEqual(resolve_cell("M0-C0-T0-R0-S0-E0").id, "M0-C0-T0-R0-S0-E0")
        self.assertEqual(len(set(CONDITIONS.values())), 12)
        k7 = treatment_for(resolve_cell("K7"))
        self.assertEqual((k7.treatment_id, k7.audit_probability), ("exp_m1c1t1r1s1e1a1", 0.3))
        self.assertEqual(treatment_for(resolve_cell("F")).audit_probability, 0.0)

    def test_audit_code_round_trips_and_six_code_ids_are_unchanged(self):
        self.assertEqual(Cell.parse("M1-C1-T1-R1-S1-E1-A1").id, "M1-C1-T1-R1-S1-E1-A1")
        self.assertEqual(Cell.parse("M1-C1-T1-R1-S1-E1-A0"), Cell.parse("M1-C1-T1-R1-S1-E1"))
        self.assertEqual(Cell.parse("M1-C1-T1-R1-S1-E1").id, "M1-C1-T1-R1-S1-E1")


class ChatPromptAndParsingTests(unittest.IsolatedAsyncioTestCase):
    def test_prompts_describe_the_chat_tool_and_audit_without_steering(self):
        config = EpisodeConfig("e", private_chat=True, transfers_enabled=True, audit_probability=0.3)
        observation = Observation(Role.CREATOR, "e", SCENARIO, Phase.DELIBERATION, config, current_round=1,
                                  chat_participants=("juror_0_e",))
        system = build_system_prompt(AgentConfig("c", Role.CREATOR), observation)
        self.assertIn("PRIVATE CHAT", system)
        self.assertIn("only its most recent message", system)
        self.assertIn("audited with probability 30%", system)
        self.assertNotIn("prohibited", system.lower())
        prompt = build_observation_prompt(observation)
        self.assertIn('"action": "chat"', prompt)
        self.assertIn("juror_0_e", prompt)
        self.assertNotIn("PRIVATE CHAT", build_system_prompt(
            AgentConfig("c", Role.CREATOR), Observation(Role.CREATOR, "e", SCENARIO, Phase.SETUP, EpisodeConfig("e"))))

    async def test_llm_chat_and_deliberation_parse_private_messages_and_reject_malformed_ones(self):
        replies = []

        async def create(**_):
            return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=replies.pop(0)))])

        client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        observation = Observation(Role.JUROR, "e", SCENARIO, Phase.DELIBERATION, EpisodeConfig("e", private_chat=True),
                                  chat_participants=("creator_e",))
        with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}), \
                patch("agents.llm_agent.AsyncOpenAI", return_value=client):
            agent = LLMAgent(AgentConfig("j", Role.JUROR, provider="openai"))
            replies.append(json.dumps({"action": "chat", "private_messages": [
                {"recipient_id": "creator_e", "content": "hi"}]}))
            self.assertEqual((await agent.chat(observation)).private_messages, [PrivateMessage("creator_e", "hi")])
            replies.append(json.dumps({"message": "analysis", "private_messages": [
                {"recipient_id": "creator_e", "content": "psst"}]}))
            self.assertEqual((await agent.deliberate(observation)).private_messages,
                             [PrivateMessage("creator_e", "psst")])
            for bad in ({"action": "chat", "private_messages": {"recipient_id": "x"}},
                        {"action": "chat", "private_messages": [{"recipient_id": "creator_e"}]},
                        {"action": "deliberate", "private_messages": []}):
                replies.append(json.dumps(bad))
                with self.subTest(bad=bad), self.assertRaises(ValueError):
                    await agent.chat(observation)


if __name__ == "__main__":
    unittest.main()
