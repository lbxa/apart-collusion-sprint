import json
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from veracity_harness.gateway import GatewayPolicy, Identity, create_gateway

OPENAPI = json.loads((Path(__file__).resolve().parents[2] / "docs/openapi.json").read_text())


def policy(upstream="http://127.0.0.1:1", **overrides):
    return GatewayPolicy(
        upstream=upstream,
        episode_id="episode-1",
        identities={"127.0.0.1": Identity(actor_id="juror-1", token="secret-one")},
        public_messaging=True,
        private_chat=False,
        private_history=False,
        private_communication_prohibited=True,
        **overrides,
    )


@pytest.mark.parametrize(
    "method,path",
    [
        ("POST", "/v1/episodes"),
        ("POST", "/v1/episodes/episode-1/settle"),
        ("POST", "/v1/episodes/episode-1/expire"),
        ("POST", "/v1/chain/replay"),
        ("GET", "/v1/episodes/episode-1/chat-audit"),
        ("GET", "/v1/episodes/episode-1/forum/transcript"),
        ("GET", "/v1/episodes/another-episode"),
        ("GET", "/v1/chats/chat/messages"),
        ("GET", "/v1/episodes/episode-1/chats"),
        ("GET", "/v1/chain/events"),
    ],
)
def test_operator_and_other_episode_interfaces_are_denied(method, path):
    assert not policy().permits(method, path)


async def test_caller_cannot_change_identity_or_query_operator_evidence():
    received = []

    async def upstream(request):
        received.append((request.path, request.headers.get("Authorization")))
        return web.json_response({"ok": True})

    upstream_app = web.Application()
    upstream_app.router.add_route("*", "/{path:.*}", upstream)
    async with TestServer(upstream_app) as server:
        current = policy(str(server.make_url("")).rstrip("/"))
        async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
            response = await client.get(
                "/v1/episodes/episode-1",
                headers={"Authorization": "Bearer dev-operator", "X-Actor-ID": "juror-2"},
            )
            assert response.status == 200
            assert received == [("/v1/episodes/episode-1", "Bearer secret-one")]
            response = await client.get("/v1/operations/another-actors-operation")
            assert response.status == 403
            response = await client.get("/v1/episodes/episode-1/chat-audit")
            assert response.status == 403


async def test_discovery_does_not_advertise_operator_or_disabled_communication():
    upstream = web.Application()

    async def schema(request):
        return web.json_response(OPENAPI)

    upstream.router.add_get("/v1/openapi.json", schema)
    async with TestServer(upstream) as server:
        current = policy(str(server.make_url("")).rstrip("/"))
        async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
            response = await client.get("/v1/openapi.json")
            result = await response.json()
            paths = result["paths"]
            assert "/v1/episodes/{id}/commitments" in paths
            assert "/v1/episodes" not in paths
            assert not any("audit" in path or "transcript" in path for path in paths)
            assert not any("chats" in path for path in paths)
            assert result["security"] == []


async def test_unknown_network_fails_closed():
    current = policy().model_copy(update={"identities": {}})
    async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
        assert (await client.get("/v1/identity")).status == 403


def test_communication_policy_enforces_availability():
    closed = policy().model_copy(update={"public_messaging": False})
    assert not closed.permits("POST", "/v1/episodes/episode-1/forum/messages")
    opened = policy().model_copy(update={"private_chat": True})
    assert opened.permits("POST", "/v1/episodes/episode-1/chats")
    assert not opened.permits("GET", "/v1/chats/chat/transcript")


async def test_denied_attempts_are_retained_without_message_bodies(tmp_path):
    audit = tmp_path / "access.jsonl"
    current = policy()
    app = create_gateway(lambda: current, "Interface", audit)
    async with TestClient(TestServer(app)) as client:
        response = await client.post("/v1/chats/unknown/messages", json={"content": "private body"})
        assert response.status == 403
    records = [json.loads(line) for line in audit.read_text().splitlines()]
    assert records[-1]["status"] == 403
    assert records[-1]["actor_id"] == "juror-1"
    assert "private body" not in audit.read_text()
