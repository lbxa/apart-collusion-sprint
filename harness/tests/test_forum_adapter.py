"""Role mapping and full forum pagination across the experiment boundary."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from game_api.core_engine import CoreEngineAPI
from game_api.generated import ForumAuditReport, ForumMessage, ForumMessagePage
from game_api.types import EpisodeConfig


def message(sequence):
    return ForumMessage(message_id=f"post-{sequence}", sequence=sequence, sender_id="juror-1",
        content=f"message {sequence}", content_hash="hash", round_num=1, created_at_ms=sequence)


def report(events=None, **changes):
    return ForumAuditReport.model_validate({"episode_id": "ep", "forum_used": True,
        "communication_used": True, "message_count": 101, "total_message_bytes": 1000,
        "active_sender_count": 1, "first_message_at_ms": 1, "last_message_at_ms": 101,
        "actors": [], "events": events or [], "next_after": 0, "has_more": False} | changes)


class ForumAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.api = CoreEngineAPI(core_engine_dir=".")
        self.api.local.client = SimpleNamespace(register_episode=AsyncMock(), wait_operation=AsyncMock())
        await self.api.register_episode(EpisodeConfig("ep", jury_size=3), "c", "x", ["a", "b", "d"], "t")

    async def test_publication_uses_registered_role_and_stable_round_key(self):
        self.api.client.send_forum_message = AsyncMock(return_value=message(1))
        sent = await self.api.send_forum_message("ep", "a", "message 1", 1)
        await self.api.send_forum_message("ep", "a", "message 1", 1)
        self.assertEqual(sent.sender_id, "a")
        self.assertEqual(sent.sequence, 1)
        calls = self.api.client.send_forum_message.call_args_list
        self.assertEqual(calls[0], calls[1])
        self.assertEqual(calls[0].args, ("ep", "juror-1", "message 1"))
        with self.assertRaises(ValueError):
            await self.api.send_forum_message("ep", "outside", "text", 1)

    async def test_history_follows_all_pages_and_maps_senders_without_operator_read(self):
        self.api.client.get_forum_messages = AsyncMock(side_effect=[
            ForumMessagePage(episode_id="ep", messages=[message(i) for i in range(1, 101)],
                             next_after=100, has_more=True),
            ForumMessagePage(episode_id="ep", messages=[message(101)], next_after=101, has_more=False)])
        messages = await self.api.get_forum_messages("ep", "b")
        self.assertEqual([item.sequence for item in messages], list(range(1, 102)))
        self.assertTrue(all(item.sender_id == "a" for item in messages))
        self.assertEqual([call.kwargs["after"] for call in self.api.client.get_forum_messages.call_args_list], [0, 100])
        self.assertTrue(all(call.args == ("ep", "juror-2") for call in self.api.client.get_forum_messages.call_args_list))

    async def test_audit_exports_all_pages_and_preserves_engine_identity(self):
        events = [{"sequence": i, "episode_id": "ep", "actor_id": "juror-1",
            "actor_is_operator": False, "kind": "messages_read", "message_sequence": None,
            "message_hash": None, "message_bytes": None, "round_num": None,
            "returned_sequences": [1], "created_at_ms": i} for i in range(1, 102)]
        self.api.client.get_forum_audit = AsyncMock(side_effect=[
            report(events[:100], next_after=100, has_more=True), report(events[100:], next_after=101)])
        audit = await self.api.get_forum_audit("ep")
        self.assertEqual(len(audit["events"]), 101)
        self.assertEqual(audit["events"][0]["actor_id"], "juror-1")
        self.assertEqual(audit["actor_mapping"]["juror-1"], "a")
        self.assertEqual(audit["message_count"], 101)
        self.assertEqual([call.kwargs["after"] for call in self.api.client.get_forum_audit.call_args_list], [0, 100])
