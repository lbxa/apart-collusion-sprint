"""Private chat uses explicit credentials and immediate, validated API responses."""

import unittest
from unittest.mock import AsyncMock, patch

from aiohttp import web

from game_api.client import CoreClient, CoreClientError, CoreHTTPError


def chat(**changes):
    return {
        "chat_id": "chat-1",
        "episode_id": "episode",
        "participant_ids": ["alice", "bob"],
        "history_enabled": False,
        "created_at_ms": 1,
    } | changes


def message(**changes):
    return {
        "message_id": "message-1",
        "sequence": 1,
        "sender_id": "alice",
        "recipient_id": "bob",
        "content": "  Private café e\u0301 🧪.\n",
        "content_hash": "0xhash",
        "created_at_ms": 2,
    } | changes


def messages(items=None, **changes):
    return {
        "chat_id": "chat-1",
        "messages": items or [],
        "next_after": 0,
        "has_more": False,
    } | changes


class ChatClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.replies = []
        self.response = chat()
        self.status = 200
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", self.serve)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        await site.start()
        self.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
        self.client = CoreClient(
            self.url,
            operator_token="operator-secret",
            participant_tokens={"alice": "alice-secret", "bob": "bob-secret"},
            poll_interval=0.001,
        )
        await self.client.start()

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()

    async def serve(self, request):
        body = await request.json() if request.can_read_body else None
        self.requests.append(
            (request.method, request.path, dict(request.headers), body, dict(request.query))
        )
        value, status = self.replies.pop(0) if self.replies else (self.response, self.status)
        return web.json_response(value, status=status)

    async def test_create_defaults_prohibited_latest_only_without_operation_polling(self):
        created = await self.client.create_chat(
            "episode", ["alice", "bob"], idempotency_key="chat-key", actor_id="alice"
        )
        self.assertEqual(created.chat_id, "chat-1")
        self.assertEqual(len(self.requests), 1)
        method, path, headers, body, query = self.requests[0]
        self.assertEqual((method, path), ("POST", "/v1/episodes/episode/chats"))
        self.assertEqual(headers["Authorization"], "Bearer alice-secret")
        self.assertEqual(headers["Idempotency-Key"], "chat-key")
        self.assertEqual(
            body,
            {
                "participant_ids": ["alice", "bob"],
                "history_enabled": False,
                "communication_prohibited": True,
            },
        )

    async def test_operator_can_provision_immutable_permitted_history_control(self):
        self.response = chat(history_enabled=True)
        created = await self.client.create_chat(
            "episode",
            ["alice", "bob"],
            history_enabled=True,
            communication_prohibited=False,
            idempotency_key="control-key",
        )
        self.assertTrue(created.history_enabled)
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer operator-secret")
        self.assertFalse(self.requests[-1][3]["communication_prohibited"])

    async def test_send_preserves_content_and_participant_identity_without_operation_polling(self):
        self.response = message()
        sent = await self.client.send_message(
            "chat-1", "alice", self.response["content"], idempotency_key="message-key"
        )
        self.assertEqual(sent.content, self.response["content"])
        self.assertEqual(sent.sequence, 1)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0][2]["Authorization"], "Bearer alice-secret")
        self.assertEqual(self.requests[0][3], {"content": self.response["content"]})

    async def test_list_and_read_use_caller_credentials_and_only_supplied_cursors(self):
        self.response = {"chats": [chat()], "next_after": None, "has_more": False}
        result = await self.client.list_chats("episode", actor_id="alice")
        self.assertEqual(result.chats[0].chat_id, "chat-1")
        self.assertEqual(self.requests[-1][4], {})
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer alice-secret")
        self.response = messages([message()], next_after=1)
        read = await self.client.get_messages("chat-1", "bob", after=0, limit=2)
        self.assertEqual(read.messages[0].sender_id, "alice")
        self.assertEqual(self.requests[-1][4], {"after": "0", "limit": "2"})
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer bob-secret")

    async def test_polling_only_reads_participant_history_and_preserves_cursor(self):
        self.replies = [
            (messages(next_after=4), 200),
            (messages([message(sequence=5)], next_after=5), 200),
        ]
        received = await self.client.poll_messages("chat-1", "bob", after=4, timeout=1)
        self.assertEqual(received.next_after, 5)
        self.assertEqual(len(received.messages), 1)
        self.assertEqual([r[1] for r in self.requests], ["/v1/chats/chat-1/messages"] * 2)
        self.assertTrue(all(r[4]["after"] == "4" for r in self.requests))
        self.assertTrue(all(r[2]["Authorization"] == "Bearer bob-secret" for r in self.requests))

    async def test_empty_poll_timeout_returns_latest_valid_empty_page(self):
        self.response = messages(next_after=3)
        # Expire after the first valid HTTP response instead of racing a 10 ms
        # wall-clock budget against local server startup on a busy machine.
        with patch("game_api.client.asyncio.sleep", new_callable=AsyncMock) as sleep:
            sleep.side_effect = TimeoutError
            result = await self.client.poll_messages("chat-1", "bob", after=3)
        sleep.assert_awaited_once()
        self.assertEqual(result.messages, [])
        self.assertEqual(result.next_after, 3)

    async def test_private_transcript_and_metadata_audit_always_use_operator_credential(self):
        self.response = messages([message()], next_after=1)
        transcript = await self.client.get_transcript("chat-1", after=0, limit=1)
        self.assertEqual(transcript.messages[0].content, self.response["messages"][0]["content"])
        self.assertEqual(self.requests[-1][1], "/v1/chats/chat-1/transcript")
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer operator-secret")
        self.response = {
            "episode_id": "episode",
            "chat_used": True,
            "communication_used": True,
            "prohibited_communication_used": True,
            "chat_count": 1,
            "message_count": 1,
            "actors": [],
            "events": [],
            "next_after": 0,
            "has_more": False,
        }
        audit = await self.client.get_chat_audit("episode")
        self.assertTrue(audit.prohibited_communication_used)
        self.assertEqual(self.requests[-1][1], "/v1/episodes/episode/chat-audit")
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer operator-secret")

    async def test_response_identity_must_match_chat_episode_and_sender(self):
        self.response = chat(episode_id="another")
        with self.assertRaises(CoreClientError):
            await self.client.create_chat("episode", ["alice", "bob"], idempotency_key="key")
        self.response = message(sender_id="another")
        with self.assertRaises(CoreClientError):
            await self.client.send_message(
                "chat-1", "alice", "Private content.", idempotency_key="key"
            )
        self.response = messages(chat_id="another")
        with self.assertRaises(CoreClientError):
            await self.client.get_messages("chat-1", "alice")

    async def test_invalid_responses_do_not_leak_private_content_in_errors(self):
        private = "private message body must never appear in logs"
        self.response = message(content=private, sequence="coerced")
        with self.assertRaises(CoreClientError) as error:
            await self.client.send_message("chat-1", "alice", private, idempotency_key="key")
        self.assertNotIn(private, str(error.exception))
        self.assertNotIn("alice-secret", str(error.exception))

    async def test_membership_denial_keeps_structured_problem_without_private_request(self):
        self.status = 403
        self.response = {"error": {"code": "FORBIDDEN", "message": "Not a chat member."}}
        with self.assertRaises(CoreHTTPError) as error:
            await self.client.send_message(
                "chat-1", "alice", "private request", idempotency_key="key"
            )
        self.assertEqual(error.exception.problem.code, "FORBIDDEN")
        self.assertEqual(error.exception.idempotency_key, "key")
        self.assertNotIn("private request", str(error.exception))

    async def test_bad_pagination_and_missing_credentials_fail_before_http(self):
        for kwargs in ({"after": -1}, {"limit": 0}, {"limit": 101}, {"after": True}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.client.get_messages("chat-1", "alice", **kwargs)
        async with CoreClient(self.url, participant_tokens={"alice": "token"}) as participant:
            with self.assertRaises(ValueError):
                await participant.get_transcript("chat-1")
            with self.assertRaises(ValueError):
                await participant.get_chat_audit("episode")
        self.assertFalse(self.requests)


if __name__ == "__main__":
    unittest.main()
