"""Public observations must come from the game forum, never a harness shadow log."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agents.scripted import HonestAgent
from experiments.runner import ExperimentRunner
from experiments.treatments import TreatmentConfig
from game_api.mock import MockGameAPI
from game_api.types import DeliberateAction, Message, Scenario, Verdict


class ForumGame(MockGameAPI):
    def __init__(self, *, fail_send=False, fail_after_first=False, fail_audit=False):
        super().__init__()
        self.calls = []
        self.posts = []
        self.fail_send = fail_send
        self.fail_after_first = fail_after_first
        self.fail_audit = fail_audit

    async def send_forum_message(self, episode_id, sender_id, content, round_num):
        self.calls.append(("send", sender_id))
        if self.fail_send:
            raise RuntimeError("forum publication failed")
        message = Message(sender_id, "ENGINE: " + content, round_num)
        self.posts.append(message)
        return message

    async def get_forum_messages(self, episode_id, participant_id):
        self.calls.append(("read", participant_id))
        if self.fail_after_first and self.posts:
            raise RuntimeError("later forum read failed")
        return copy.deepcopy(self.posts)

    async def get_forum_audit(self, episode_id):
        self.calls.append(("audit", episode_id))
        if self.fail_audit:
            raise RuntimeError("unavailable")
        return {"episode_id": episode_id, "message_count": len(self.posts), "events": [],
                "forum_used": bool(self.posts), "communication_used": bool(self.posts)}


class ForumAgent(HonestAgent):
    observations = []

    async def deliberate(self, observation):
        self.observations.append(("deliberate", self.agent_id, copy.deepcopy(observation)))
        return DeliberateAction(self.agent_id, observation.episode_id, "from agent", "public",
                                straw_vote=Verdict.CREATOR_SUPPORTED)

    async def final_vote(self, observation):
        self.observations.append(("vote", self.agent_id, copy.deepcopy(observation)))
        return await super().final_vote(observation)


class ForumRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def run_forum(self, game, enabled=True):
        treatment = TreatmentConfig("forum", "Forum", "No models", jury_size=3,
            deliberation_rounds=2, num_episodes=1, public_messaging=enabled,
            use_scripted_creator=True, use_scripted_challenger=True,
            scripted_juror_indices=[0, 1, 2])
        scenario = Scenario("scenario", "Claim", "Evidence", "Counter", True)
        ForumAgent.observations = []
        with tempfile.TemporaryDirectory() as directory, patch("experiments.runner.HonestAgent", ForumAgent):
            metrics = await ExperimentRunner(game, Path(directory)).run_experiment(treatment, [scenario], "forum")
            self.exported = json.loads((Path(directory) / "forum" / "episodes.jsonl").read_text())
        return metrics.episodes[0]

    async def test_publication_and_each_agents_observations_use_game_history_including_final_vote(self):
        game = ForumGame()
        record = await self.run_forum(game)
        self.assertEqual(record.status, "completed", record.failure_reason)
        self.assertEqual(len(game.posts), 6)
        self.assertEqual([kind for kind, _ in game.calls], ["read", "send"] * 6 + ["read"] * 3 + ["audit"])
        for phase, _, observation in ForumAgent.observations:
            self.assertTrue(all(message.content.startswith("ENGINE:") for message in observation.visible_messages))
            if phase == "vote":
                self.assertEqual(len(observation.visible_messages), 6)
        self.assertTrue(all(message["content"].startswith("ENGINE:") for message in record.messages))
        self.assertEqual(record.forum_audit["message_count"], 6)
        self.assertEqual(self.exported["forum_audit"], record.forum_audit)
        self.assertEqual(self.exported["messages"], record.messages)

    async def test_disabled_public_messaging_does_not_send_or_read_forum_and_exports_nonuse(self):
        game = ForumGame()
        record = await self.run_forum(game, enabled=False)
        self.assertEqual(record.status, "completed", record.failure_reason)
        self.assertEqual([kind for kind, _ in game.calls], ["audit"])
        self.assertEqual(record.messages, [])
        self.assertFalse(record.forum_audit["communication_used"])
        for _, _, observation in ForumAgent.observations:
            self.assertEqual(observation.visible_messages, [])
            self.assertEqual(observation.straw_polls, [])

    async def test_failed_publication_fails_episode_without_local_message_fallback(self):
        game = ForumGame(fail_send=True)
        with self.assertLogs("experiments.runner", level="ERROR"):
            record = await self.run_forum(game)
        self.assertEqual(record.status, "failed")
        self.assertTrue(record.infrastructure_failure)
        self.assertEqual(record.messages, [])
        self.assertEqual(game.posts, [])
        self.assertEqual(len(ForumAgent.observations), 1)

    async def test_failure_after_accepted_post_exports_partial_audit_without_observing_it(self):
        game = ForumGame(fail_after_first=True)
        with self.assertLogs("experiments.runner", level="ERROR"):
            record = await self.run_forum(game)
        self.assertEqual(record.status, "failed")
        self.assertEqual(record.forum_audit["message_count"], 1)
        self.assertEqual(self.exported["forum_audit"]["message_count"], 1)
        self.assertEqual(len(record.messages), 1)
        self.assertEqual(len(ForumAgent.observations), 1)
        self.assertFalse(hasattr(ForumAgent.observations[0][2], "forum_audit"))

    async def test_unavailable_failure_audit_has_explicit_safe_diagnostic(self):
        game = ForumGame(fail_send=True, fail_audit=True)
        with self.assertLogs("experiments.runner", level="ERROR"):
            record = await self.run_forum(game)
        self.assertEqual(record.failure_reason, "forum publication failed")
        self.assertEqual(record.forum_audit, {})
        self.assertIn("could not be collected", record.forum_audit_error)
        self.assertEqual(self.exported["forum_audit_error"], record.forum_audit_error)
