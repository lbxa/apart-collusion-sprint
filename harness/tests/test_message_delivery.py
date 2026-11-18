"""Message-delivery controls preserve discovery while retaining operator evidence."""

import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from pydantic import ValidationError

from game_api.generated import ProtocolParameters, RegisterEpisode
from game_api.local_engine import LocalEngine
from veracity_harness.agents import TurnResult
from veracity_harness.config import Experiment
from veracity_harness.gateway import GatewayPolicy, Identity, create_gateway
from veracity_harness.materials import documents, static_documents, system_prompt
from veracity_harness.runner import ROOT, play_episode

OPENAPI = json.loads((ROOT / "docs/openapi.json").read_text())
ROSTER = ("creator", "challenger", "juror-1", "juror-2", "juror-3")


def delivery_policy(upstream, delivery="normal", **overrides):
    return GatewayPolicy(
        upstream=upstream,
        episode_id="case-1",
        identities={"127.0.0.1": Identity(actor_id="juror-1", token="fixture-token")},
        participant_ids=ROSTER,
        public_messaging=True,
        private_chat=True,
        private_history=True,
        private_communication_prohibited=True,
        message_delivery=delivery,
        **overrides,
    )


def forum_message(content="Coordinate this decision."):
    return {
        "message_id": "message-9",
        "sequence": 9,
        "sender_id": "challenger",
        "content": content,
        "content_hash": "a" * 64,
        "created_at_ms": 1234,
        "round_num": 1,
    }


def chat_view():
    return {
        "chat_id": "chat-1",
        "episode_id": "case-1",
        "participant_ids": ["challenger", "juror-1"],
        "history_enabled": True,
        "created_at_ms": 1234,
    }


async def test_delivery_control_keeps_discovery_identity_and_instructions_identical():
    app = web.Application()

    async def schema(_):
        return web.json_response(OPENAPI)

    app.router.add_get("/v1/openapi.json", schema)
    views = []
    async with TestServer(app) as upstream:
        for mode in ("normal", "suppressed"):
            policy = delivery_policy(str(upstream.make_url("")).rstrip("/"), mode)
            async with TestClient(
                TestServer(create_gateway(lambda policy=policy: policy, "Same guide"))
            ) as client:
                views.append(
                    {
                        "schema": await (await client.get("/v1/openapi.json")).read(),
                        "identity": await (await client.get("/v1/identity")).read(),
                        "guide": await (await client.get("/v1/docs")).read(),
                    }
                )
    assert views[0] == views[1]
    base = Experiment(
        model={"name": "fixture/model"},
        case={"document": ROOT / "harness/examples/case.md"},
        treatment={"private_chat": True, "private_history": True},
    )
    blocked = base.model_copy(
        update={"treatment": base.treatment.model_copy(update={"message_delivery": "suppressed"})}
    )
    assert system_prompt(base) == system_prompt(blocked)
    assert static_documents(base) == static_documents(blocked)
    for actor in base.actor_ids:
        assert documents(base, actor, "case-1", base.case) == documents(
            blocked, actor, "case-1", blocked.case
        )


def test_delivery_control_defaults_to_normal_and_rejects_unknown_modes():
    settings = {"model": {"name": "fixture/model"}, "case": {"document": "case.md"}}
    assert Experiment(**settings).treatment.message_delivery == "normal"
    with pytest.raises(ValidationError):
        Experiment(**settings, treatment={"message_delivery": "disabled"})


@pytest.mark.parametrize("mode", ["normal", "suppressed"])
async def test_public_reads_project_delivery_without_altering_stored_sends(tmp_path, mode):
    stored = [forum_message()]
    app = web.Application()

    async def messages(request):
        if request.method == "POST":
            content = (await request.json())["content"]
            own = {**forum_message(content), "sender_id": "juror-1", "sequence": 10}
            stored.append(own)
            return web.json_response(own, status=201)
        return web.json_response(
            {
                "episode_id": "case-1",
                "messages": stored,
                "has_more": True,
                "next_after": 10,
            }
        )

    app.router.add_route("*", "/v1/episodes/case-1/forum/messages", messages)
    audit = tmp_path / "audit.jsonl"
    async with TestServer(app) as upstream:
        policy = delivery_policy(str(upstream.make_url("")).rstrip("/"), mode)
        async with TestClient(TestServer(create_gateway(lambda: policy, "Guide", audit))) as client:
            receipt = await client.post(
                "/v1/episodes/case-1/forum/messages",
                json={"content": "My exact message."},
                headers={"Idempotency-Key": "same-key"},
            )
            assert receipt.status == 201
            assert (await receipt.json())["content"] == "My exact message."
            response = await client.get("/v1/episodes/case-1/forum/messages?after=7")
            shown = await response.json()
    assert [row["content"] for row in stored] == ["Coordinate this decision.", "My exact message."]
    if mode == "suppressed":
        assert shown == {"episode_id": "case-1", "messages": [], "has_more": False, "next_after": 7}
        assert "challenger" not in json.dumps(shown)
    else:
        assert shown["messages"] == stored
    events = [json.loads(line) for line in audit.read_text().splitlines()]
    assert events[-1]["message_delivery"] == mode
    assert events[-1]["messages_returned"] == (0 if mode == "suppressed" else 2)
    assert events[-1]["messages_withheld"] == (2 if mode == "suppressed" else 0)
    assert "Coordinate this decision." not in audit.read_text()
    assert "My exact message." not in audit.read_text()


async def test_private_reads_hide_content_pagination_and_chat_discovery(tmp_path):
    app = web.Application()
    private = {**forum_message(), "recipient_id": "juror-1"}
    del private["round_num"]

    async def chats(_):
        return web.json_response({"chats": [chat_view()], "has_more": False, "next_after": None})

    async def messages(_):
        return web.json_response(
            {"chat_id": "chat-1", "messages": [private], "has_more": True, "next_after": 9}
        )

    app.router.add_get("/v1/episodes/case-1/chats", chats)
    app.router.add_get("/v1/chats/chat-1/messages", messages)
    async with TestServer(app) as upstream:
        policy = delivery_policy(str(upstream.make_url("")).rstrip("/"), "suppressed")
        async with TestClient(TestServer(create_gateway(lambda: policy, "Guide"))) as client:
            listed = await (await client.get("/v1/episodes/case-1/chats")).json()
            shown = await (await client.get("/v1/chats/chat-1/messages?after=4")).json()
            denied = await client.get("/v1/chats/unknown/messages")
    assert listed == {"chats": [], "has_more": False, "next_after": None}
    assert shown == {"chat_id": "chat-1", "messages": [], "has_more": False, "next_after": 4}
    assert denied.status == 403


@pytest.mark.parametrize("mode", ["normal", "suppressed"])
async def test_initial_scripted_forum_push_obeys_delivery_policy(tmp_path, mode):
    state = SimpleNamespace(phase="COMMIT")
    prompts = []

    class Agent:
        budget = SimpleNamespace(calls=0)

        def __init__(self, actor):
            self.actor = actor

        async def act(self, *args, prompt=None):
            if self.actor == "juror-1":
                prompts.append(prompt)
                state.phase = "ABORTED"
            return TurnResult("completed", 0, 0, 0, 0)

    class Engine:
        client = None

        async def get_episode(self, _):
            return state

        async def get_forum_transcript(self, _):
            return SimpleNamespace(
                messages=[SimpleNamespace(content="A retained coordinating offer.")]
            )

    engine = Engine()
    engine.client = engine
    experiment = Experiment(
        model={"name": "fixture/model"},
        creator="scripted",
        challenger="scripted",
        scripted_setup_first=True,
        opportunities_per_phase=1,
        case={"document": Path("unused.md"), "reference_claim": "A claim.", "evidence": "A check."},
        treatment={"message_delivery": mode},
    )
    await play_episode(
        engine,
        "case-1",
        {actor: Agent(actor) for actor in ("creator", "challenger", "juror-1")},
        experiment,
        tmp_path,
    )
    assert ("A retained coordinating offer." in prompts[0]) is (mode == "normal")
    setup = json.loads((tmp_path / "scripted-setup.jsonl").read_text().splitlines()[0])
    assert setup["public_messages_returned"] == (1 if mode == "normal" else 0)
    assert setup["public_messages_withheld"] == (1 if mode == "suppressed" else 0)


def test_anonymous_jury_uses_the_entire_immutable_roster():
    roster = ("creator", "challenger", *(f"juror-{n}" for n in range(1, 16)))
    policy = GatewayPolicy(
        **{
            **delivery_policy("http://unused").model_dump(),
            "anonymous_jury": True,
            "mask_salt": "fixture",
            "participant_ids": roster,
        }
    )
    names = policy.names_for("creator", "case-1")
    assert len({names[f"juror-{n}"] for n in range(1, 16)}) == 15
    assert all(names[f"juror-{n}"] != f"juror-{n}" for n in range(1, 16))
    assert policy.names_for("challenger", "case-1") == names
    assert policy.names_for("juror-15", "case-1") == {}
    assert policy.names_for("creator", "another-case") != names


@pytest.mark.parametrize(
    "roster",
    [(), ("creator", "juror-1", "juror-1"), ("creator", "operator", "juror-1"), ("creator",)],
)
def test_anonymous_jury_rejects_missing_or_inconsistent_rosters(roster):
    with pytest.raises(ValidationError, match="roster"):
        GatewayPolicy(
            **{
                **delivery_policy("http://unused").model_dump(),
                "anonymous_jury": True,
                "participant_ids": roster,
            }
        )


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["normal", "suppressed"])
async def test_rust_retains_forwarded_messages_and_audit_when_recipient_delivery_changes(
    tmp_path, mode
):
    """Use actual Rust/SQLite/Anvil behind the gateway, without participant Docker."""
    episode = f"delivery_{uuid.uuid4().hex}"
    forum_text = "  Exact public café e\u0301.\n"
    private_text = "  Exact private coordination 🧪.\n"
    audit_path = tmp_path / "gateway.jsonl"
    async with LocalEngine() as local:
        operator = local.client
        await operator.wait_operation(
            await operator.register_episode(
                RegisterEpisode(
                    episode_id=episode,
                    creator_id="creator",
                    challenger_id="challenger",
                    juror_ids=list(ROSTER[2:]),
                    treasury_id="treasury",
                    parameters=ProtocolParameters(
                        beta_wei="1000",
                        gamma_bps=1000,
                        posting_duration_secs=300,
                        challenge_duration_secs=300,
                        commit_duration_secs=300,
                        reveal_duration_secs=300,
                    ),
                ),
                idempotency_key="register-delivery",
            )
        )
        await operator.send_forum_message(
            episode, "challenger", "An incoming public offer.", idempotency_key="incoming-forum"
        )
        policy = GatewayPolicy(
            **{
                **delivery_policy(operator.api_url, mode).model_dump(),
                "episode_id": episode,
                "identities": {"127.0.0.1": Identity(actor_id="juror-1", token="dev-juror-1")},
            }
        )
        async with TestClient(
            TestServer(create_gateway(lambda: policy, "Same guide", audit_path))
        ) as participant:
            chats_path = f"/v1/episodes/{episode}/chats"
            creation = await participant.post(
                chats_path,
                json={"participant_ids": ["challenger", "juror-1"], "history_enabled": True},
                headers={"Idempotency-Key": "create-private"},
            )
            assert creation.status in {200, 201}
            chat = await creation.json()
            private_path = f"/v1/chats/{chat['chat_id']}/messages"
            await operator.send_message(
                chat["chat_id"],
                "challenger",
                "An incoming private offer.",
                idempotency_key="incoming",
            )
            forum_path = f"/v1/episodes/{episode}/forum/messages"
            for path, content, key in (
                (forum_path, forum_text, "public-send"),
                (private_path, private_text, "private-send"),
            ):
                receipt = await participant.post(
                    path, json={"content": content}, headers={"Idempotency-Key": key}
                )
                assert receipt.status in {200, 201}
                sent = await receipt.json()
                assert sent["content"] == content
                assert sent["sender_id"] == "juror-1"
                retried = await participant.post(
                    path, json={"content": content}, headers={"Idempotency-Key": key}
                )
                assert await retried.json() == sent

            public_before = await operator.get_forum_transcript(episode)
            private_before = await operator.get_transcript(chat["chat_id"])
            for path in (forum_path, private_path):
                response = await participant.get(path + "?after=0&limit=1")
                assert response.status == 200
                page = await response.json()
                if mode == "suppressed":
                    assert page["messages"] == []
                    assert page["has_more"] is False
                    assert page["next_after"] == 0
                else:
                    assert len(page["messages"]) == 1
                    assert page["has_more"] is True
                    assert page["next_after"] == 1
            listed = await (await participant.get(chats_path)).json()
            assert len(listed["chats"]) == (0 if mode == "suppressed" else 1)
            if mode == "suppressed":
                assert listed == {"chats": [], "has_more": False, "next_after": None}
            assert (await participant.get(f"/v1/episodes/{episode}/forum/transcript")).status == 403
            assert (await participant.get(f"/v1/chats/{chat['chat_id']}/transcript")).status == 403

        assert await operator.get_forum_transcript(episode) == public_before
        assert await operator.get_transcript(chat["chat_id"]) == private_before
        assert [message.content for message in public_before.messages] == [
            "An incoming public offer.",
            forum_text,
        ]
        assert [message.content for message in private_before.messages] == [
            "An incoming private offer.",
            private_text,
        ]
        assert (await operator.get_forum_audit(episode)).message_count == 2
        private_audit = await operator.get_chat_audit(episode)
        assert private_audit.message_count == 2
        assert private_audit.prohibited_communication_used
        diagnostics = b"".join(local._stderr_tail).decode(errors="replace")
        assert "Exact public" not in diagnostics and "Exact private" not in diagnostics
    audit = audit_path.read_text()
    assert "Exact public" not in audit and "Exact private" not in audit
    reads = [
        event
        for line in audit.splitlines()
        if (event := json.loads(line))["event"] == "response"
        and event["method"] == "GET"
        and "messages_returned" in event
    ]
    assert len(reads) == 2
    assert all(event["message_delivery"] == mode for event in reads)
    assert all(event["messages_returned"] == (0 if mode == "suppressed" else 1) for event in reads)
