"""The generated boundary retains validation and follows contract changes."""

import copy
import importlib.util
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from pydantic import ValidationError

from game_api import generated
from game_api.generated import GeneratedAPI, OperationView, ReceiptView

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "core_client_codegen", ROOT / "scripts/generate-core-client.py"
)
CODEGEN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CODEGEN)


class GeneratedModelTests(unittest.TestCase):
    def test_chat_request_defaults_and_pair_constraints_follow_rust(self):
        request = generated.CreateChat(participant_ids=["creator", "juror-1"])
        self.assertFalse(request.history_enabled)
        self.assertTrue(request.communication_prohibited)
        for pair in (["creator"], ["creator", "juror-1", "challenger"]):
            with self.subTest(pair=pair), self.assertRaises(ValidationError):
                generated.CreateChat(participant_ids=pair)
        with self.assertRaises(ValidationError):
            generated.CreateChat(participant_ids=["creator", "juror-1"], history_enabled="true")

    def test_nullable_chat_cursor_must_be_present_and_can_be_null(self):
        self.assertIsNone(generated.ChatPage(chats=[], next_after=None, has_more=False).next_after)
        with self.assertRaises(ValidationError):
            generated.ChatPage(chats=[], has_more=False)

    def test_nullable_operation_evidence_requires_presence_even_when_null(self):
        operation = {
            "operation_id": "op",
            "episode_id": "ep",
            "actor_id": "actor",
            "kind": "settle",
            "status": "accepted",
            "transaction": None,
            "error": None,
        }
        self.assertIsNone(OperationView.model_validate(operation).transaction)
        for field in ("transaction", "error"):
            missing = dict(operation)
            del missing[field]
            with self.subTest(field=field), self.assertRaises(ValidationError):
                OperationView.model_validate(missing)

    def test_receipt_rejects_coercion_noncanonical_money_and_unknown_fields(self):
        receipt = {
            "transaction_hash": "0x01",
            "block_hash": "0x02",
            "block_number": 1,
            "confirmations": 1,
            "confirmed": True,
            "success": True,
            "gas_used": "900719925474099300000000000000000001",
            "effective_gas_price": "1",
        }
        self.assertEqual(ReceiptView.model_validate(receipt).gas_used, receipt["gas_used"])
        for bad in (
            {"success": "true"},
            {"block_number": True},
            {"gas_used": 2},
            {"gas_used": "1.5"},
            {"gas_used": "01"},
            {"private": "secret"},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                ReceiptView.model_validate({**receipt, **bad})

    def test_unknown_operation_status_is_rejected(self):
        with self.assertRaises(ValidationError):
            OperationView.model_validate(
                {
                    "operation_id": "op",
                    "episode_id": "ep",
                    "actor_id": "actor",
                    "kind": "settle",
                    "status": "maybe_confirmed",
                }
            )

    def test_regeneration_follows_schema_and_fails_on_unsupported_constraints(self):
        contract = json.loads((ROOT / "docs/openapi.json").read_text())
        self.assertEqual(
            CODEGEN.generate(contract), (ROOT / "harness/src/game_api/generated.py").read_text()
        )
        changed = copy.deepcopy(contract)
        changed["components"]["schemas"]["ReceiptView"]["properties"]["gas_used"]["pattern"] = (
            "^42$"
        )
        self.assertIn("pattern='^42$'", CODEGEN.generate(changed))
        changed["components"]["schemas"]["ReceiptView"]["properties"]["gas_used"]["not"] = {
            "const": "42"
        }
        with self.assertRaisesRegex(ValueError, "Unsupported schema features"):
            CODEGEN.generate(changed)
        for schema in (
            {"$ref": "#/components/schemas/Verdict", "pattern": "^x$"},
            {"type": "string", "enum": ["x"], "minLength": 2},
            {"type": "object", "additionalProperties": {"type": "string"}, "minLength": 1},
        ):
            with self.subTest(schema=schema), self.assertRaises(ValueError):
                CODEGEN.annotation(schema)
        changed = copy.deepcopy(contract)
        changed["components"]["schemas"]["ClaimRequest"]["properties"]["new-field"] = {
            "type": "string"
        }
        changed["components"]["schemas"]["ClaimRequest"]["required"].append("new-field")
        with self.assertRaisesRegex(ValueError, "Unsupported Python identifier"):
            CODEGEN.generate(changed)


class GeneratedEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_optional_chat_pagination_omits_unspecified_values(self):
        transport = AsyncMock(
            return_value={"chat_id": "chat", "messages": [], "next_after": 0, "has_more": False}
        )
        api = GeneratedAPI(transport)
        await api.messages("chat/id", token="participant")
        transport.assert_awaited_once_with(
            "GET", "/v1/chats/chat%2Fid/messages", token="participant"
        )
        transport.reset_mock()
        await api.messages("chat/id", after=7, limit=2, token="participant")
        transport.assert_awaited_once_with(
            "GET", "/v1/chats/chat%2Fid/messages?after=7&limit=2", token="participant"
        )

    async def test_chat_posts_return_typed_views_without_operation_polling(self):
        view = {
            "chat_id": "chat",
            "episode_id": "ep",
            "participant_ids": ["creator", "juror-1"],
            "history_enabled": False,
            "created_at_ms": 1,
        }
        transport = AsyncMock(return_value=view)
        api = GeneratedAPI(transport)
        result = await api.create(
            "ep",
            generated.CreateChat(participant_ids=["creator", "juror-1"]),
            token="participant",
            idempotency_key="create-key",
        )
        self.assertIsInstance(result, generated.ChatView)
        transport.assert_awaited_once_with(
            "POST",
            "/v1/episodes/ep/chats",
            token="participant",
            body={
                "participant_ids": ["creator", "juror-1"],
                "history_enabled": False,
                "communication_prohibited": True,
            },
            idempotency_key="create-key",
        )

    async def test_endpoint_paths_and_response_validation_are_generated(self):
        transport = AsyncMock(
            return_value={
                "operation_id": "op",
                "episode_id": "ep",
                "actor_id": "actor",
                "kind": "commit_vote",
                "status": "accepted",
                "transaction": None,
                "error": None,
            }
        )
        api = GeneratedAPI(transport)
        result = await api.operation("op/with space")
        self.assertEqual(result.operation_id, "op")
        transport.assert_awaited_once_with("GET", "/v1/operations/op%2Fwith%20space", token=None)
        transport.return_value["status"] = "unknown"
        with self.assertRaises(ValidationError):
            await api.operation("op")

    async def test_generated_calls_cover_non_json_evidence(self):
        transport = AsyncMock(return_value='{"block_number":1}\n')
        api = GeneratedAPI(transport)
        self.assertEqual(await api.events(from_block=1, to_block=2), transport.return_value)
        transport.assert_awaited_once_with(
            "GET", "/v1/chain/events?from_block=1&to_block=2", token=None, response_format="text"
        )
