"""Public history and private pair chat coexist without bypassing audited reads."""

import copy
import tempfile
from pathlib import Path
from unittest.mock import patch

from agents.scripted import HonestAgent
from experiments.runner import ExperimentRunner
from experiments.treatments import TreatmentConfig
from game_api.types import ChatAction, PrivateMessage, Role, Scenario
from tests.core_test_case import CoreTestCase


class MixedChannelAgent(HonestAgent):
    party_views = []
    juror_views = []

    async def chat(self, observation):
        self.party_views.append((self.agent_id, copy.deepcopy(observation)))
        recipients = [actor for actor in observation.chat_participants if actor.startswith("juror_0_")]
        private = ([PrivateMessage(recipients[0], "PAIR-ONLY")]
                   if self.role == Role.CREATOR and observation.current_round == 1 else [])
        return ChatAction(self.agent_id, observation.episode_id, private)

    async def deliberate(self, observation):
        self.juror_views.append((self.agent_id, copy.deepcopy(observation)))
        return await super().deliberate(observation)


class MixedChannelTests(CoreTestCase):
    async def test_party_public_history_is_current_and_audited_while_pair_messages_stay_private(self):
        MixedChannelAgent.party_views, MixedChannelAgent.juror_views = [], []
        game = self.new_game()
        treatment = TreatmentConfig("mixed", "Mixed", "Scripted", jury_size=3,
            deliberation_rounds=2, num_episodes=1, public_messaging=True, private_chat=True,
            use_scripted_creator=True, use_scripted_challenger=True, scripted_juror_indices=[0, 1, 2])
        with tempfile.TemporaryDirectory() as directory, patch("experiments.runner.HonestAgent", MixedChannelAgent):
            metrics = await ExperimentRunner(game, Path(directory)).run_experiment(treatment,
                [Scenario("s", "Claim", "Evidence", "Counter", True)], "mixed")
        [record] = metrics.episodes
        self.assertEqual(record.status, "completed", record.failure_reason)
        for actor, observation in MixedChannelAgent.party_views:
            expected = 0 if observation.current_round == 1 else 3
            self.assertEqual(len(observation.visible_messages), expected, (actor, observation.current_round))
        mapping = record.forum_audit["actor_mapping"]
        actors = {mapping[usage["actor_id"]]: usage for usage in record.forum_audit["actors"]}
        for party in (record.creator_id, record.challenger_id):
            self.assertEqual(actors[party]["read_requests"], 2)
            self.assertEqual(actors[party]["messages_returned"], 3)
            self.assertEqual(actors[party]["sent_messages"], 0)
        self.assertEqual(record.forum_audit["message_count"], 6)
        self.assertEqual(record.chat_audit["message_count"], 1)
        for actor, observation in MixedChannelAgent.juror_views:
            self.assertTrue(all(message.content != "PAIR-ONLY" for message in observation.visible_messages))
            if not actor.startswith("juror_0_"):
                self.assertFalse(observation.private_messages)
        self.assertTrue(any(observation.private_messages for actor, observation in MixedChannelAgent.juror_views
                            if actor.startswith("juror_0_")))
