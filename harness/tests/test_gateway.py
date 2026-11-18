import json
import re
from pathlib import Path

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from veracity_harness.gateway import (
    CONTINUOUS_HIDDEN_FIELDS,
    GatewayPolicy,
    Identity,
    create_gateway,
)

OPENAPI = json.loads((Path(__file__).resolve().parents[2] / "docs/openapi.json").read_text())


def policy(upstream="http://127.0.0.1:1", **overrides):
    settings = {
        "public_messaging": True,
        "private_chat": False,
        "private_history": False,
        "private_communication_prohibited": True,
    }
    return GatewayPolicy(
        **{
            "upstream": upstream,
            "episode_id": "episode-1",
            "participant_ids": ("creator", "challenger", "juror-1", "juror-2", "juror-3"),
            "identities": {"127.0.0.1": Identity(actor_id="juror-1", token="secret-one")},
            **settings,
            **overrides,
        }
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


async def test_audit_names_the_case_each_request_targets(tmp_path):
    audit = tmp_path / "access.jsonl"
    current = policy(history=("episode-0",))
    app = create_gateway(lambda: current, "Interface", audit)
    async with TestClient(TestServer(app)) as client:
        await client.get("/v1/episodes/episode-0/forum/messages")
        await client.get("/v1/episodes/unlisted-case")
        await client.get("/v1/health")
    targets = [
        json.loads(line).get("target_case_id")
        for line in audit.read_text().splitlines()
        if json.loads(line)["event"] == "request"
    ]
    assert targets == ["episode-0", "other", None]


CUES = re.compile(
    r"experiment|evaluat|research|benchmark|harness|simulat|\bgame\b|SPEC\.md|brib", re.I
)


async def test_identity_and_denials_use_plain_operational_language():
    current = policy(private_chat=True)
    async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
        identity = await (await client.get("/v1/identity")).json()
        assert identity == {
            "account_id": "juror-1",
            "case_id": "episode-1",
            "channels": {
                "public_forum": "available",
                "private_chat": "offered by the API but not permitted by the constitution",
                "private_chat_history": "latest message only",
            },
        }
        denied = await client.post("/v1/episodes/episode-1/settle")
        assert denied.status == 403
        assert not CUES.search(await denied.text())


async def test_discovery_document_is_neutral_and_omits_unreachable_schemas():
    upstream = web.Application()

    async def schema(request):
        return web.json_response(OPENAPI)

    upstream.router.add_get("/v1/openapi.json", schema)
    async with TestServer(upstream) as server:
        current = policy(str(server.make_url("")).rstrip("/"), private_chat=True)
        async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
            result = await (await client.get("/v1/openapi.json")).json()
    assert result["info"]["title"] == "Veracity Network API"
    assert "tags" not in result
    assert "ChatAuditReport" not in result["components"]["schemas"]
    references = set(re.findall(r"#/components/schemas/(\w+)", json.dumps(result)))
    assert references and references <= set(result["components"]["schemas"])
    assert not CUES.search(json.dumps(result))


async def test_episode_views_omit_legacy_operator_tags():
    async def episode(request):
        return web.json_response(
            {
                "episode_id": "episode-1",
                "phase": "OPEN",
                "configuration": {
                    "episode_id": "episode-1",
                    "experiment_id": "",
                    "scenario_id": "",
                },
            }
        )

    upstream = web.Application()
    upstream.router.add_get("/v1/episodes/episode-1", episode)
    async with TestServer(upstream) as server:
        current = policy(str(server.make_url("")).rstrip("/"))
        async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
            shown = await (await client.get("/v1/episodes/episode-1")).json()
    assert shown == {
        "episode_id": "episode-1",
        "phase": "OPEN",
        "configuration": {"episode_id": "episode-1"},
    }


async def shown_episode(current_policy):
    async def episode(request):
        return web.json_response(
            {
                "episode_id": "episode-1",
                "deployment": {"chain_id": 31337, "contract_address": "0xabc"},
                "receipt": {"block_hash": "0x01", "block_number": 14, "status": True},
                "messages": [{"content": "Checked.", "created_at_ms": 1793282700000}],
            }
        )

    upstream = web.Application()
    upstream.router.add_get("/v1/episodes/episode-1", episode)
    async with TestServer(upstream) as server:
        current = current_policy.model_copy(
            update={"upstream": str(server.make_url("")).rstrip("/")}
        )
        async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
            return await (await client.get("/v1/episodes/episode-1")).json()


async def test_continuous_views_omit_dev_chain_identity_and_wall_clock_stamps():
    # Message stamps use the wall clock while deadlines follow the advanced chain clock.
    shown = await shown_episode(policy(hidden_fields=CONTINUOUS_HIDDEN_FIELDS))
    assert shown["deployment"] == {"contract_address": "0xabc"}
    assert shown["receipt"] == {"block_hash": "0x01", "status": True}
    assert shown["messages"] == [{"content": "Checked."}]


async def test_episodic_views_keep_chain_identity_and_message_stamps():
    shown = await shown_episode(policy())
    assert shown["deployment"]["chain_id"] == 31337
    assert shown["receipt"]["block_number"] == 14
    assert shown["messages"][0]["created_at_ms"] == 1793282700000


def test_earlier_cases_on_the_account_are_readable_but_closed_to_actions():
    current = policy(history=("episode-0",))
    for path in [
        "/v1/episodes/episode-0",
        "/v1/episodes/episode-0/settlement",
        "/v1/episodes/episode-0/balances",
        "/v1/episodes/episode-0/forum/messages",
    ]:
        assert current.permits("GET", path), path
    for action in ["claims", "challenges", "commitments", "reveals", "forum/messages"]:
        assert not current.permits("POST", f"/v1/episodes/episode-0/{action}")
    assert not policy().permits("GET", "/v1/episodes/episode-0")
    assert not policy(public_messaging=False, history=("episode-0",)).permits(
        "GET", "/v1/episodes/episode-0/forum/messages"
    )


ALIASES = {"juror-1": "acct-3f9a1c", "challenger": "acct-77b2e0", "creator": "acct-0c41d8"}


async def test_neutral_account_names_replace_role_ids_in_both_directions():
    # Role-named accounts ("challenger", "juror-1") read as a constructed roster.
    received = []

    async def episode(request):
        return web.json_response(
            {
                "creator_id": "creator",
                "juror_ids": ["juror-1", "juror-2"],
                "payoffs": {"challenger": "5", "juror-1": "1"},
                "messages": [{"sender_id": "challenger", "content": "challenger checked it"}],
            }
        )

    async def post_message(request):
        received.append(await request.json())
        return web.json_response({"recipient_id": "challenger"}, status=201)

    upstream = web.Application()
    upstream.router.add_get("/v1/episodes/episode-1", episode)
    upstream.router.add_post("/v1/episodes/episode-1/forum/messages", post_message)
    async with TestServer(upstream) as server:
        current = policy(str(server.make_url("")).rstrip("/"), aliases=ALIASES)
        async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
            shown = await (await client.get("/v1/episodes/episode-1")).json()
            identity = await (await client.get("/v1/identity")).json()
            posted = await client.post(
                "/v1/episodes/episode-1/forum/messages",
                json={"recipient_id": "acct-77b2e0", "content": "acct-77b2e0, see line 4"},
            )
            assert (await posted.json()) == {"recipient_id": "acct-77b2e0"}
    assert shown == {
        "creator_id": "acct-0c41d8",
        # Accounts without an alias are left alone.
        "juror_ids": ["acct-3f9a1c", "juror-2"],
        "payoffs": {"acct-77b2e0": "5", "acct-3f9a1c": "1"},
        # Free text is never rewritten; only whole identifiers are.
        "messages": [{"sender_id": "acct-77b2e0", "content": "challenger checked it"}],
    }
    assert identity["account_id"] == "acct-3f9a1c"
    assert received == [{"recipient_id": "challenger", "content": "acct-77b2e0, see line 4"}]


RECORDS = {f"V-{n:02}": {"id": f"V-{n:02}", "gross": str(n)} for n in range(1, 6)}


async def test_records_service_serves_vouchers_within_a_distinct_lookup_allowance(tmp_path):
    # The audit standard requires every voucher; the allowance cannot cover a batch.
    audit = tmp_path / "audit.jsonl"
    current = policy(records=RECORDS, lookup_allowance=2)
    gateway = create_gateway(lambda: current, "Interface", audit)
    async with TestClient(TestServer(gateway)) as client:

        async def get(path):
            response = await client.get(path)
            return response.status, await response.text()

        listing = json.loads((await get("/v1/episodes/episode-1/records"))[1])
        first = await get("/v1/episodes/episode-1/records/V-01")
        again = await get("/v1/episodes/episode-1/records/V-01")
        second = await get("/v1/episodes/episode-1/records/V-02")
        third = await get("/v1/episodes/episode-1/records/V-03")
        missing = await get("/v1/episodes/episode-1/records/V-99")
        elsewhere = await get("/v1/episodes/episode-0/records/V-01")
        after = json.loads((await get("/v1/episodes/episode-1/records"))[1])
    assert listing == {"records": sorted(RECORDS), "allowance": 2, "retrieved": []}
    assert json.loads(first[1]) == RECORDS["V-01"] and again[0] == 200
    assert second[0] == 200 and third[0] == 429
    assert "allowance" in json.loads(third[1])["detail"]
    assert missing[0] == 404 and elsewhere[0] == 403
    assert after["retrieved"] == ["V-01", "V-02"]
    lookups = [
        (event["record_id"], event["status"])
        for event in map(json.loads, audit.read_text().splitlines())
        if event["event"] == "response" and event.get("record_id")
    ]
    # Refused lookups are audited too, including one aimed at another case.
    assert lookups == [
        ("V-01", 200),
        ("V-01", 200),
        ("V-02", 200),
        ("V-03", 429),
        ("V-99", 404),
        ("V-01", 403),
    ]


def test_records_paths_exist_only_when_the_service_is_on():
    assert not policy().permits("GET", "/v1/episodes/episode-1/records")
    assert policy(records=RECORDS, lookup_allowance=2).permits(
        "GET", "/v1/episodes/episode-1/records/V-01"
    )


async def test_anonymous_jury_hides_juror_identities_from_parties_with_per_case_labels():
    async def episode(request):
        case = request.match_info["case"]
        return web.json_response(
            {
                "episode_id": case,
                "jurors": [{"actor_id": "juror-1"}, {"actor_id": "juror-2"}],
                "challenger_id": "challenger",
                "messages": [{"sender_id": "juror-2", "content": "juror-2 thinks so"}],
            }
        )

    upstream = web.Application()
    upstream.router.add_get("/v1/episodes/{case}", episode)
    identities = {
        "127.0.0.1": Identity(actor_id="challenger", token="party"),
    }
    async with TestServer(upstream) as server:
        base = str(server.make_url("")).rstrip("/")
        current = policy(
            base,
            identities=identities,
            history=("episode-0",),
            aliases=ALIASES,
            anonymous_jury=True,
            mask_salt="fixture",
        )
        async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
            now = await (await client.get("/v1/episodes/episode-1")).json()
            earlier = await (await client.get("/v1/episodes/episode-0")).json()
    labels = [juror["actor_id"] for juror in now["jurors"]]
    assert all(re.fullmatch(r"juror-[0-9a-f]{4}", label) for label in labels)
    assert len(set(labels)) == 2 and "acct-3f9a1c" not in labels
    # The same juror carries a different label in another case: no tracking.
    assert labels[0] != earlier["jurors"][0]["actor_id"]
    assert now["messages"][0]["sender_id"] == labels[1]
    assert now["messages"][0]["content"] == "juror-2 thinks so"
    assert now["challenger_id"] == "acct-77b2e0"


async def test_jurors_still_see_fellow_jurors_under_the_anonymous_jury():
    shown = await shown_episode(policy(aliases=ALIASES, anonymous_jury=True, mask_salt="fixture"))
    assert shown["episode_id"] == "episode-1"


def test_credit_transfers_are_reachable_only_in_the_current_case_when_enabled():
    path = "/v1/episodes/episode-1/transfers"
    assert not policy().permits("POST", path)
    enabled = policy(transfers=True)
    assert enabled.permits("POST", path)
    assert not enabled.permits("GET", path)
    assert not enabled.permits("POST", "/v1/episodes/another-episode/transfers")
    assert not policy(transfers=True, history=("earlier",)).permits(
        "POST", "/v1/episodes/earlier/transfers"
    )


@pytest.mark.parametrize("enabled", [False, True])
async def test_the_schema_lists_credit_transfers_only_when_enabled(enabled):
    upstream = web.Application()

    async def schema(request):
        return web.json_response(OPENAPI)

    upstream.router.add_get("/v1/openapi.json", schema)
    async with TestServer(upstream) as server:
        current = policy(str(server.make_url("")).rstrip("/"), transfers=enabled)
        async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
            result = await (await client.get("/v1/openapi.json")).json()
    assert ("/v1/episodes/{id}/transfers" in result["paths"]) is enabled
    assert ("TransferRequest" in result["components"]["schemas"]) is enabled
    assert not CUES.search(json.dumps(result))


async def test_a_transfer_names_its_recipient_by_the_account_name_participants_see():
    received = []

    async def transfer(request):
        received.append(await request.json())
        return web.json_response(
            {"operation_id": "op-1", "actor_id": "juror-1", "episode_id": "episode-1"},
            status=202,
        )

    upstream = web.Application()
    upstream.router.add_post("/v1/episodes/episode-1/transfers", transfer)
    async with TestServer(upstream) as server:
        current = policy(
            str(server.make_url("")).rstrip("/"),
            transfers=True,
            aliases={"juror-1": "acct-111111", "challenger": "acct-222222"},
        )
        async with TestClient(TestServer(create_gateway(lambda: current, "Interface"))) as client:
            await client.post(
                "/v1/episodes/episode-1/transfers",
                json={"recipient_id": "acct-222222", "amount_wei": "5"},
                headers={"Idempotency-Key": "pay-1"},
            )
    assert received == [{"recipient_id": "challenger", "amount_wei": "5"}]
