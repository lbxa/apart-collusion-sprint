"""Real Python → Rust → SQLite forum and experiment acceptance."""

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from experiments.runner import ExperimentRunner
from experiments.treatments import TreatmentConfig
from game_api.client import CoreClient, CoreHTTPError
from game_api.core_engine import CoreEngineAPI
from game_api.generated import ProtocolParameters, RegisterEpisode
from game_api.local_engine import LocalEngine
from game_api.types import Scenario


class ForumClientIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def register(self, client):
        episode = "forum_" + uuid.uuid4().hex
        registration = RegisterEpisode(episode_id=episode, creator_id="creator", challenger_id="challenger",
            juror_ids=["juror-1", "juror-2", "juror-3"], treasury_id="treasury",
            parameters=ProtocolParameters(beta_wei="1000", gamma_bps=1000,
                posting_duration_secs=300, challenge_duration_secs=300,
                commit_duration_secs=300, reveal_duration_secs=300))
        await client.wait_operation(await client.register_episode(registration, idempotency_key=episode))
        return episode

    async def test_shared_history_pagination_operator_signals_and_private_chat_remain_separate(self):
        async with LocalEngine() as local:
            client = local.client
            episode = await self.register(client)
            # Evaluator reads do not establish participant forum use.
            self.assertFalse((await client.get_forum_audit(episode)).forum_used)
            await client.get_forum_transcript(episode)
            self.assertFalse((await client.get_forum_audit(episode)).forum_used)
            private = await client.create_chat(episode, ["creator", "juror-1"],
                actor_id="creator", idempotency_key="pair")
            await client.send_message(private.chat_id, "creator", "PRIVATE-BODY", idempotency_key="private")

            first = await client.send_forum_message(episode, "creator", "  Public café 🧪\n",
                round_num=1, idempotency_key="first")
            self.assertEqual(await client.send_forum_message(episode, "creator", first.content,
                round_num=1, idempotency_key="first"), first)
            for index in range(2, 102):
                await client.send_forum_message(episode, "juror-1", f"Public post {index}",
                    round_num=2, idempotency_key=f"message-{index}")
            messages = []
            after = 0
            while True:
                page = await client.get_forum_messages(episode, "challenger", after=after, limit=100)
                messages.extend(page.messages)
                if not page.has_more:
                    break
                after = page.next_after
            self.assertEqual([message.sequence for message in messages], list(range(1, 102)))
            self.assertEqual(messages[0], first)
            self.assertNotIn("PRIVATE-BODY", page.model_dump_json())
            with self.assertRaises(CoreHTTPError) as denied:
                await client.get_forum_messages(episode, "juror-4")
            self.assertEqual(denied.exception.status, 403)
            async with CoreClient(client.api_url, operator_token="dev-juror-1") as participant:
                with self.assertRaises(CoreHTTPError):
                    await participant.get_forum_audit(episode)
            events = []
            after = 0
            while True:
                audit = await client.get_forum_audit(episode, after=after, limit=100)
                events.extend(audit.events)
                if not audit.has_more:
                    break
                after = audit.next_after
            self.assertEqual(audit.message_count, 101)
            self.assertEqual(audit.active_sender_count, 2)
            self.assertEqual(sum(event.kind == "message_sent" for event in events), 101)
            self.assertNotIn("PRIVATE-BODY", audit.model_dump_json())
            self.assertNotIn("Public post", audit.model_dump_json())
            self.assertEqual((await client.get_chat_audit(episode)).message_count, 1)

    async def test_real_experiment_reads_each_observation_and_exports_exact_communication_shape(self):
        api = CoreEngineAPI()
        try:
            with tempfile.TemporaryDirectory() as directory:
                treatment = TreatmentConfig("forum", "Forum", "No models", jury_size=3,
                    deliberation_rounds=2, num_episodes=1, public_messaging=True,
                    use_scripted_creator=True, use_scripted_challenger=True,
                    scripted_juror_indices=[0, 1, 2])
                metrics = await ExperimentRunner(api, Path(directory)).run_experiment(treatment,
                    [Scenario("s", "Claim", "Evidence", "Counter", True)], "forum_e2e")
                record = metrics.episodes[0]
                self.assertEqual(record.status, "completed", record.failure_reason)
                audit = record.forum_audit
                self.assertEqual(audit["message_count"], 6)
                self.assertEqual(audit["active_sender_count"], 3)
                actors = sorted(audit["actors"], key=lambda item: item["actor_id"])
                self.assertEqual([actor["sent_messages"] for actor in actors], [2, 2, 2])
                self.assertEqual([actor["read_requests"] for actor in actors], [3, 3, 3])
                self.assertEqual([actor["messages_returned"] for actor in actors], [9, 11, 13])
                transcript = await api.client.get_forum_transcript(record.episode_id)
                self.assertEqual(len(record.messages), 6)
                for exported, stored in zip(record.messages, transcript.messages):
                    self.assertEqual(exported["message_id"], stored.message_id)
                    self.assertEqual(exported["sequence"], stored.sequence)
                    self.assertEqual(exported["content_hash"], stored.content_hash)
                    self.assertEqual(exported["created_at_ms"], stored.created_at_ms)
                saved = json.loads((Path(directory) / "forum_e2e" / "episodes.jsonl").read_text())
                self.assertEqual(saved["forum_audit"], audit)
                self.assertEqual(sum(actor["messages_returned"] for actor in actors), 33)
        finally:
            await api.stop()
