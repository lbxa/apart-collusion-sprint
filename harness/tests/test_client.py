"""The reusable SDK boundary uses HTTP, durable operation identities, and exact values."""

import unittest

from aiohttp import web

from game_api.client import (
    CoreClient,
    CoreClientError,
    CoreHTTPError,
    CoreOperationError,
    CoreOperationTimeout,
    CoreTransportError,
)


def operation(status="accepted", *, operation_id="op-1", actor="juror-a"):
    return {
        "operation_id": operation_id,
        "episode_id": "episode",
        "actor_id": actor,
        "kind": "commit_vote",
        "status": status,
        "error": None,
        "transaction": None
        if status == "accepted"
        else {
            "transaction_hash": "0xtx",
            "sender": "0xactor",
            "nonce": 3,
            "receipt": {
                "transaction_hash": "0xtx",
                "success": status != "reverted",
                "block_number": 3,
                "block_hash": "0xblock",
                "gas_used": "21000",
                "effective_gas_price": "10000000000000000000000000000000001",
                "confirmations": 1,
                "confirmed": status == "confirmed",
            },
        },
    }


class ClientTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.requests = []
        self.response = operation()
        self.status = 202
        self.response_headers = {}
        self.replies = []
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
            participant_tokens={"juror-a": "juror-secret", "creator-a": "creator-secret"},
            poll_interval=0.001,
        )
        await self.client.start()

    async def asyncTearDown(self):
        await self.client.close()
        await self.runner.cleanup()

    async def serve(self, request):
        body = await request.json() if request.can_read_body else None
        self.requests.append((request.method, request.path, dict(request.headers), body))
        data, status = self.replies.pop(0) if self.replies else (self.response, self.status)
        return web.json_response(data, status=status, headers=self.response_headers)

    async def test_commit_returns_handle_and_uses_configured_credential_and_caller_key(self):
        result = await self.client.commit(
            "episode",
            "juror-a",
            "CREATOR_SUPPORTED",
            "Assessment with café.\n",
            idempotency_key="saved-command-key",
        )
        self.assertEqual(result.operation_id, "op-1")
        self.assertEqual(result.status, "accepted")
        self.assertEqual(len(self.requests), 1)
        method, path, headers, body = self.requests[0]
        self.assertEqual((method, path), ("POST", "/v1/episodes/episode/commitments"))
        self.assertEqual(headers["Authorization"], "Bearer juror-secret")
        self.assertEqual(headers["Idempotency-Key"], "saved-command-key")
        self.assertEqual(
            body, {"verdict": "CREATOR_SUPPORTED", "assessment": "Assessment with café.\n"}
        )

    async def test_reveal_and_settle_only_submit_the_named_action(self):
        self.response = operation() | {"kind": "reveal_vote"}
        await self.client.reveal("episode", "juror-a", idempotency_key="reveal-key")
        self.response = operation() | {"kind": "settle", "actor_id": "operator"}
        await self.client.settle("episode", idempotency_key="settle-key")
        self.assertEqual(
            [r[1] for r in self.requests],
            ["/v1/episodes/episode/reveals", "/v1/episodes/episode/settle"],
        )
        self.assertEqual([r[3] for r in self.requests], [{}, {}])
        self.assertEqual(self.requests[-1][2]["Authorization"], "Bearer operator-secret")

    async def test_action_response_must_belong_to_the_submitted_episode_actor_and_action(self):
        for changed in (
            {"episode_id": "another"},
            {"actor_id": "another"},
            {"kind": "reveal_vote"},
        ):
            self.response = operation() | changed
            with self.subTest(changed=changed), self.assertRaisesRegex(CoreClientError, "identity"):
                await self.client.commit(
                    "episode",
                    "juror-a",
                    "CREATOR_SUPPORTED",
                    "Assessment.",
                    idempotency_key="saved-key",
                )

    async def test_episode_response_must_belong_to_the_requested_episode(self):
        self.status = 200
        self.response = {"episode_id": "another", "entitlements": {}, "withdrawal_credits": {}}
        with self.assertRaisesRegex(CoreClientError, "identity"):
            await self.client.get_balances("episode")

    async def test_redirects_are_not_followed_with_bearer_credentials(self):
        self.status = 307
        self.response_headers = {"Location": self.url + "/redirected"}
        with self.assertRaises(CoreHTTPError) as error:
            await self.client.reveal("episode", "juror-a", idempotency_key="saved-key")
        self.assertEqual(error.exception.status, 307)
        self.assertEqual(len(self.requests), 1)

    async def test_new_client_can_reconcile_saved_operation_without_python_episode_state(self):
        self.replies = [(operation("submitted"), 200), (operation("confirmed"), 200)]
        async with CoreClient(
            self.url, operator_token="new-operator", poll_interval=0.001
        ) as resumed:
            result = await resumed.wait_operation("op-1")
        self.assertEqual(result.status, "confirmed")
        self.assertEqual(
            [r[1] for r in self.requests], ["/v1/operations/op-1", "/v1/operations/op-1/reconcile"]
        )
        self.assertEqual(self.requests[1][2]["Authorization"], "Bearer new-operator")
        self.assertTrue(self.requests[1][2]["Idempotency-Key"])

    async def test_operation_identity_cannot_change_during_reconciliation(self):
        self.response = operation("confirmed", operation_id="different-operation")
        with self.assertRaisesRegex(CoreClientError, "identity"):
            await self.client.wait_operation(await self._accepted_handle())

    async def test_reconciliation_cannot_replace_an_existing_transaction(self):
        from game_api.generated import OperationView

        previous = OperationView.model_validate(operation("submitted"))
        self.response = operation("confirmed")
        self.response["transaction"]["nonce"] += 1
        with self.assertRaisesRegex(CoreClientError, "identity"):
            await self.client.reconcile_operation(previous)

    async def _accepted_handle(self):
        from game_api.generated import OperationView

        return OperationView.model_validate(operation())

    async def test_confirmed_requires_matching_successful_confirmed_receipt(self):
        for mutate in (
            lambda value: value.update(transaction=None),
            lambda value: value["transaction"]["receipt"].update(success=False),
            lambda value: value["transaction"]["receipt"].update(confirmed=False),
            lambda value: value["transaction"]["receipt"].update(transaction_hash="other"),
        ):
            value = operation("confirmed")
            mutate(value)
            self.response = value
            with self.subTest(value=value), self.assertRaises(CoreClientError):
                await self.client.wait_operation("op-1")

    async def test_terminal_failure_carries_handle_without_leaking_api_error_text(self):
        self.response = operation("reverted")
        self.response["error"] = "private infrastructure details"
        with self.assertRaises(CoreOperationError) as error:
            await self.client.wait_operation("op-1")
        self.assertEqual(error.exception.operation.operation_id, "op-1")
        self.assertNotIn("private infrastructure details", str(error.exception))

    async def test_wait_timeout_preserves_pending_operation(self):
        self.response = operation("submitted")
        with self.assertRaises(CoreOperationTimeout) as error:
            await self.client.wait_operation("op-1", timeout=0.02)
        self.assertEqual(error.exception.operation.operation_id, "op-1")
        self.assertEqual(error.exception.operation.status, "submitted")

    async def test_structured_http_errors_remain_inspectable_but_are_safe_to_log(self):
        self.status = 409
        self.response = {
            "error": {"code": "CONFLICT", "message": "A particular request conflicts."}
        }
        with self.assertRaises(CoreHTTPError) as error:
            await self.client.commit(
                "episode",
                "juror-a",
                "CREATOR_SUPPORTED",
                "private ballot",
                idempotency_key="keep-this-key",
            )
        self.assertEqual(error.exception.status, 409)
        self.assertEqual(error.exception.problem.code, "CONFLICT")
        self.assertEqual(error.exception.problem.message, "A particular request conflicts.")
        self.assertEqual(error.exception.idempotency_key, "keep-this-key")
        self.assertNotIn("private ballot", str(error.exception))
        self.assertNotIn("secret", str(error.exception))

    async def test_strict_generated_response_validation_rejects_coercion_and_extra_fields(self):
        for update in (
            {"status": "not-a-status"},
            {"unexpected": "private response content"},
            {"actor_id": 42},
        ):
            self.response = operation() | update
            with self.subTest(update=update), self.assertRaises(CoreClientError) as error:
                await self.client.get_operation("op-1")
            self.assertNotIn("private response content", str(error.exception))

    async def test_participant_client_polls_public_evidence_without_operator_authority(self):
        self.replies = [(operation("submitted"), 200), (operation("confirmed"), 200)]
        async with CoreClient(
            self.url, participant_tokens={"juror-a": "participant"}, poll_interval=0.001
        ) as participant:
            result = await participant.wait_operation("op-1")
        self.assertEqual(result.status, "confirmed")
        self.assertEqual([r[0] for r in self.requests], ["GET", "GET"])
        self.assertTrue(all("Authorization" not in r[2] for r in self.requests))

    async def test_financial_values_cross_http_as_exact_integer_strings(self):
        exact = str(2**200 + 1)
        self.status = 200
        self.response = {
            "episode_id": "episode",
            "entitlements": {"juror-a": exact},
            "withdrawal_credits": {"juror-a": exact},
        }
        result = await self.client.get_balances("episode")
        self.assertEqual(result.entitlements["juror-a"], exact)
        self.assertEqual(result.withdrawal_credits["juror-a"], exact)
        self.response["entitlements"]["juror-a"] = int(exact)
        with self.assertRaises(CoreClientError):
            await self.client.get_balances("episode")

    async def test_transport_failure_preserves_command_key_without_automatic_resubmission(self):
        from unittest.mock import patch

        import aiohttp

        with patch.object(
            self.client._session, "request", side_effect=aiohttp.ClientConnectionError("private")
        ):
            with self.assertRaises(CoreTransportError) as error:
                await self.client.commit(
                    "episode",
                    "juror-a",
                    "CREATOR_SUPPORTED",
                    "private ballot",
                    idempotency_key="persisted-key",
                )
        self.assertEqual(error.exception.idempotency_key, "persisted-key")
        self.assertEqual(self.requests, [])
        self.assertNotIn("private", str(error.exception))

    async def test_missing_credentials_and_bad_keys_fail_before_http(self):
        for key in ("", "space key", "\n", "x" * 129):
            with self.subTest(key=key), self.assertRaises(ValueError):
                await self.client.reveal("episode", "juror-a", idempotency_key=key)
        with self.assertRaises(ValueError):
            await self.client.reveal("episode", "unknown", idempotency_key="key")
        self.assertFalse(self.requests)

    def test_urls_cannot_embed_credentials_or_ambiguous_resource_parts(self):
        for url in (
            "https://user:password@example.com",
            "https://example.com?token=secret",
            "https://example.com#fragment",
            "file:///tmp/service",
            "https://example.com/v1",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                CoreClient(url)


if __name__ == "__main__":
    unittest.main()
