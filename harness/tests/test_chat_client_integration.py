"""Real private-chat SDK acceptance against Rust, SQLite, and local Anvil."""

import json
import unittest
import uuid

import pytest

from game_api.client import CoreClient, CoreHTTPError
from game_api.generated import (
    ChatAuditReport,
    ChatMessage,
    ChatView,
    MessagePage,
    ProtocolParameters,
    RegisterEpisode,
)
from game_api.local_engine import LocalEngine

pytestmark = pytest.mark.integration


class ChatClientIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def register(self, client):
        episode_id = f"chat_sdk_{uuid.uuid4().hex}"
        registration = RegisterEpisode(
            episode_id=episode_id,
            creator_id="creator",
            challenger_id="challenger",
            juror_ids=["juror-1", "juror-2", "juror-3"],
            treasury_id="treasury",
            parameters=ProtocolParameters(
                beta_wei="1000",
                gamma_bps=1000,
                posting_duration_secs=300,
                challenge_duration_secs=300,
                commit_duration_secs=300,
                reveal_duration_secs=300,
            ),
        )
        await client.wait_operation(
            await client.register_episode(registration, idempotency_key=f"register-{episode_id}")
        )
        return episode_id

    async def test_prohibited_latest_only_delivery_membership_and_retained_audit(self):
        async with LocalEngine() as local:
            client = local.client
            episode = await self.register(client)
            chat = await client.create_chat(
                episode, ["creator", "juror-1"], actor_id="creator", idempotency_key="chat-key"
            )
            self.assertIsInstance(chat, ChatView)
            self.assertFalse(chat.history_enabled)
            retry = await client.create_chat(
                episode, ["creator", "juror-1"], actor_id="creator", idempotency_key="chat-key"
            )
            self.assertEqual(retry, chat)
            self.assertEqual(
                [c.chat_id for c in (await client.list_chats(episode, actor_id="juror-1")).chats],
                [chat.chat_id],
            )
            self.assertEqual((await client.list_chats(episode, actor_id="juror-3")).chats, [])

            private = "  SDK-private café e\u0301 🧪.\n\n"
            first = await client.send_message(
                chat.chat_id, "creator", private, idempotency_key="message-key"
            )
            self.assertIsInstance(first, ChatMessage)
            self.assertEqual(first.content, private)
            self.assertEqual(first.recipient_id, "juror-1")
            retried = await client.send_message(
                chat.chat_id, "creator", private, idempotency_key="message-key"
            )
            self.assertEqual(retried, first)
            second = await client.send_message(
                chat.chat_id, "juror-1", "A private reply.\n", idempotency_key="reply-key"
            )
            self.assertEqual(second.recipient_id, "creator")

            # Latest-only remains latest-only even with an old cursor, while
            # the operator transcript retains the earlier exact private text.
            for cursor in (None, 0, first.sequence):
                page = await client.get_messages(chat.chat_id, "creator", after=cursor)
                self.assertIsInstance(page, MessagePage)
                self.assertEqual(page.messages, [second])
                self.assertFalse(page.has_more)
            empty = await client.poll_messages(
                chat.chat_id, "juror-1", after=second.sequence, timeout=0
            )
            self.assertEqual(empty.messages, [])
            self.assertEqual(empty.next_after, second.sequence)
            transcript = await client.get_transcript(chat.chat_id, limit=1)
            self.assertEqual(transcript.messages, [first])
            self.assertTrue(transcript.has_more)
            rest = await client.get_transcript(chat.chat_id, after=transcript.next_after)
            self.assertEqual(rest.messages, [second])

            # Outsiders cannot send or read; participant credentials cannot
            # clear prohibition or obtain a retained operator transcript.
            for attempt in (
                lambda: client.get_messages(chat.chat_id, "juror-3"),
                lambda: client.send_message(
                    chat.chat_id, "juror-3", "Denied private text.", idempotency_key="denied"
                ),
                lambda: client.create_chat(
                    episode,
                    ["creator", "juror-1"],
                    actor_id="creator",
                    communication_prohibited=False,
                    idempotency_key="forbidden-control",
                ),
            ):
                with self.assertRaises(CoreHTTPError) as denied:
                    await attempt()
                self.assertEqual(denied.exception.status, 403)
            async with CoreClient(client.api_url, operator_token="dev-juror-1") as wrong_operator:
                with self.assertRaises(CoreHTTPError) as denied:
                    await wrong_operator.get_transcript(chat.chat_id)
                self.assertEqual(denied.exception.status, 403)
            async with CoreClient(
                client.api_url, participant_tokens={"creator": "invalid-token"}
            ) as anonymous:
                with self.assertRaises(CoreHTTPError) as denied:
                    await anonymous.get_messages(chat.chat_id, "creator")
                self.assertEqual(denied.exception.status, 401)

            audit = await client.get_chat_audit(episode)
            self.assertIsInstance(audit, ChatAuditReport)
            self.assertTrue(audit.chat_used)
            self.assertTrue(audit.communication_used)
            self.assertTrue(audit.prohibited_communication_used)
            self.assertEqual(audit.chat_count, 1)
            self.assertEqual(audit.message_count, 2)
            self.assertEqual(sum(a.sent_messages for a in audit.actors), 2)
            self.assertEqual(sum(a.prohibited_sent_messages for a in audit.actors), 2)
            self.assertTrue(
                any(e.kind == "transcript_read" and e.actor_is_operator for e in audit.events)
            )
            self.assertTrue(
                any(e.kind == "access_denied" and e.actor_id == "juror-3" for e in audit.events)
            )
            self.assertNotIn("SDK-private", audit.model_dump_json())
            self.assertNotIn("SDK-private", (await client.get_episode(episode)).model_dump_json())
            self.assertNotIn("SDK-private", b"".join(local._stderr_tail).decode(errors="replace"))

    async def test_permitted_history_control_paginated_discovery_and_reconnected_participant(self):
        async with LocalEngine() as local:
            client = local.client
            episode = await self.register(client)
            control = await client.create_chat(
                episode,
                ["creator", "juror-1"],
                history_enabled=True,
                communication_prohibited=False,
                idempotency_key="control",
            )
            initial = await client.get_chat_audit(episode)
            self.assertFalse(initial.chat_used)
            self.assertFalse(initial.communication_used)
            first = await client.send_message(
                control.chat_id, "creator", "Permitted first message.\n", idempotency_key="first"
            )
            second = await client.send_message(
                control.chat_id, "juror-1", "Permitted reply.\n", idempotency_key="second"
            )
            async with CoreClient(
                client.api_url, participant_tokens={"creator": "dev-creator"}
            ) as resumed:
                page = await resumed.get_messages(control.chat_id, "creator", limit=1)
                self.assertEqual(page.messages, [first])
                self.assertTrue(page.has_more)
                next_page = await resumed.poll_messages(
                    control.chat_id, "creator", after=page.next_after
                )
                self.assertEqual(next_page.messages, [second])
                with self.assertRaises(ValueError):
                    await resumed.get_transcript(control.chat_id)

            another = await client.create_chat(
                episode, ["creator", "juror-2"], idempotency_key="another"
            )
            listing = await client.list_chats(episode, actor_id="creator", limit=1)
            self.assertTrue(listing.has_more)
            rest = await client.list_chats(
                episode, actor_id="creator", after=listing.next_after, limit=1
            )
            self.assertEqual(
                {listing.chats[0].chat_id, rest.chats[0].chat_id},
                {control.chat_id, another.chat_id},
            )
            self.assertFalse(rest.has_more)
            audit = await client.get_chat_audit(episode)
            self.assertTrue(audit.communication_used)
            self.assertFalse(audit.prohibited_communication_used)
            self.assertEqual(sum(a.prohibited_sent_messages for a in audit.actors), 0)
            created = [
                e for e in audit.events if e.kind == "chat_created" and e.chat_id == control.chat_id
            ]
            self.assertEqual(len(created), 1)
            self.assertTrue(created[0].actor_is_operator)
            self.assertFalse(created[0].communication_prohibited)
            serialized = json.loads(audit.model_dump_json())
            self.assertNotIn("content", json.dumps(serialized))


if __name__ == "__main__":
    unittest.main()
