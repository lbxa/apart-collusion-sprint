"""Forum SDK calls preserve participant authority and reject misleading responses."""

import unittest

from aiohttp import web

from game_api.client import CoreClient, CoreClientError, CoreHTTPError


def message(**changes):
    return {
        "message_id": "post-1",
        "sequence": 1,
        "sender_id": "alice",
        "content": "  Public café 🧪\n",
        "content_hash": "0xhash",
        "round_num": 2,
        "created_at_ms": 3,
    } | changes


def page(**changes):
    return {
        "episode_id": "episode",
        "messages": [message()],
        "next_after": 1,
        "has_more": False,
    } | changes


def audit(**changes):
    return {
        "episode_id": "episode",
        "forum_used": True,
        "communication_used": True,
        "message_count": 1,
        "total_message_bytes": 19,
        "active_sender_count": 1,
        "first_message_at_ms": 3,
        "last_message_at_ms": 3,
        "actors": [],
        "events": [],
        "next_after": 0,
        "has_more": False,
    } | changes


class ForumClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.response = message()
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
        )

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()

    async def serve(self, request):
        self.requests.append(
            (
                request.method,
                request.path,
                dict(request.headers),
                await request.json() if request.can_read_body else None,
                dict(request.query),
            )
        )
        return web.json_response(self.response, status=self.status)

    async def test_send_uses_participant_key_and_exact_content_and_round_without_operation_poll(
        self,
    ):
        sent = await self.client.send_forum_message(
            "episode", "alice", message()["content"], round_num=2, idempotency_key="saved-key"
        )
        self.assertEqual(sent.content, message()["content"])
        self.assertEqual(len(self.requests), 1)
        method, path, headers, body, _ = self.requests[0]
        self.assertEqual((method, path), ("POST", "/v1/episodes/episode/forum/messages"))
        self.assertEqual(headers["Authorization"], "Bearer alice-secret")
        self.assertEqual(headers["Idempotency-Key"], "saved-key")
        self.assertEqual(body, {"content": message()["content"], "round_num": 2})

    async def test_participant_read_and_operator_transcript_audit_have_distinct_authority(self):
        self.response = page()
        await self.client.get_forum_messages("episode", "bob", after=0, limit=2)
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer bob-secret")
        self.assertEqual(self.requests[-1][4], {"after": "0", "limit": "2"})
        await self.client.get_forum_transcript("episode")
        self.assertEqual(self.requests[-1][1], "/v1/episodes/episode/forum/transcript")
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer operator-secret")
        self.response = audit()
        result = await self.client.get_forum_audit("episode")
        self.assertTrue(result.communication_used)
        self.assertEqual(self.requests[-1][1], "/v1/episodes/episode/forum-audit")
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer operator-secret")

    async def test_wrong_sender_content_round_episode_or_invalid_sequence_fail_closed(self):
        for changes in (
            {"sender_id": "bob"},
            {"content": "other"},
            {"round_num": 3},
            {"sequence": "1"},
        ):
            self.response = message(**changes)
            with self.subTest(changes=changes), self.assertRaises(CoreClientError):
                await self.client.send_forum_message(
                    "episode", "alice", message()["content"], round_num=2, idempotency_key="key"
                )
        self.response = page(episode_id="other")
        with self.assertRaises(CoreClientError):
            await self.client.get_forum_messages("episode", "alice")
        self.response = audit(episode_id="other")
        with self.assertRaises(CoreClientError):
            await self.client.get_forum_audit("episode")

    async def test_nonadvancing_or_out_of_order_history_is_rejected(self):
        for response in (
            page(messages=[message(sequence=2), message(sequence=1)], next_after=1),
            page(messages=[], next_after=0, has_more=True),
            page(messages=[message()], next_after=0),
        ):
            self.response = response
            with self.subTest(response=response), self.assertRaises(CoreClientError):
                await self.client.get_forum_messages("episode", "alice", after=0)

    async def test_bad_pagination_and_missing_credentials_fail_before_http(self):
        for kwargs in ({"after": -1}, {"after": True}, {"after": 2**63}, {"limit": 101}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                await self.client.get_forum_messages("episode", "alice", **kwargs)
        async with CoreClient(self.url, participant_tokens={"alice": "token"}) as client:
            with self.assertRaises(ValueError):
                await client.get_forum_audit("episode")
            with self.assertRaises(ValueError):
                await client.get_forum_transcript("episode")
            with self.assertRaises(ValueError):
                await client.send_forum_message("episode", "bob", "text", idempotency_key="key")
        self.assertFalse(self.requests)

    async def test_http_failure_retains_retry_key_without_echoing_content(self):
        self.status = 403
        self.response = {"error": {"code": "FORBIDDEN", "message": "Not assigned."}}
        with self.assertRaises(CoreHTTPError) as failure:
            await self.client.send_forum_message(
                "episode", "alice", "content not for logs", idempotency_key="saved-key"
            )
        self.assertEqual(failure.exception.idempotency_key, "saved-key")
        self.assertNotIn("content not for logs", str(failure.exception))
