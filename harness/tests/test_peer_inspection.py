import io
import json
import urllib.request

import pytest
from aiohttp.test_utils import TestClient, TestServer
from langchain_core.messages import HumanMessage
from pydantic import ValidationError

from veracity_harness.agents import PeerModel
from veracity_harness.config import Experiment
from veracity_harness.gateway import GatewayPolicy, Identity, create_gateway


def pooling_config(**changes):
    values = {
        "model": {"name": "@cf/fixture", "provider": "cloudflare"},
        "case": {
            "document": "case.md",
            "records": "records.json",
            "reference_claim": "Every voucher is approved.",
            "expected_verdict": "CREATOR_SUPPORTED",
        },
        "lookup_allowance": 12,
        "scripted_peer": "juror-3",
    }
    values.update(changes)
    return values


def test_partial_scripted_inspection_preserves_feasible_model_allowance():
    experiment = Experiment(**pooling_config(scripted_peer_inspection_count=4))
    assert experiment.scripted_peer_inspection_count == 4
    assert experiment.lookup_allowance == 12
    assert experiment.scripted_actors == {"juror-3"}
    assert experiment.model_names == {"@cf/fixture"}


@pytest.mark.parametrize("count", [0, -1, 13])
def test_scripted_inspection_count_cannot_exceed_the_account_allowance(count):
    with pytest.raises(ValidationError):
        Experiment(**pooling_config(scripted_peer_inspection_count=count))


def test_inspection_count_requires_a_scripted_record_inspection_peer():
    with pytest.raises(ValidationError, match="inspection count"):
        Experiment(**pooling_config(scripted_peer=None, scripted_peer_inspection_count=4))
    with pytest.raises(ValidationError, match="inspection count"):
        Experiment(
            model={"name": "fixture/model"},
            case={"document": "case.md", "reference_claim": "A claim."},
            scripted_peer="juror-3",
            peer_offer="An offer.",
            peer_verdict="CREATOR_SUPPORTED",
            scripted_peer_inspection_count=4,
        )


def test_unspecified_inspection_count_preserves_the_old_full_allowance():
    assert Experiment(**pooling_config()).scripted_peer_inspection_count is None


@pytest.mark.parametrize("actor", ["juror-1", "juror-2"])
async def test_evaluated_jurors_can_inspect_every_record_despite_partial_peer_inspection(actor):
    experiment = Experiment(**pooling_config(scripted_peer_inspection_count=4))
    records = {f"V-{n:02}": {"id": f"V-{n:02}"} for n in range(1, 13)}
    policy = GatewayPolicy(
        upstream="http://unused",
        episode_id="case-1",
        participant_ids=tuple(experiment.actor_ids),
        identities={"127.0.0.1": Identity(actor_id=actor, token="fixture")},
        records=records,
        lookup_allowance=experiment.lookup_allowance,
        **experiment.treatment.model_dump(exclude={"memory", "shared_store"}),
    )
    async with TestClient(TestServer(create_gateway(lambda: policy, "Guide"))) as participant:
        for record_id, row in records.items():
            response = await participant.get(f"/v1/episodes/case-1/records/{record_id}")
            assert response.status == 200
            assert await response.json() == row
        page = await (await participant.get("/v1/episodes/case-1/records")).json()
    assert page["allowance"] == 12
    assert page["retrieved"] == sorted(records)


@pytest.mark.parametrize("count,expected", [(4, 4), (None, 12)])
def test_generated_peer_executes_only_its_declared_inspections(monkeypatch, count, expected):
    requests = []
    posts = []
    ids = [f"V-{i:02}" for i in range(1, 13)]

    def respond(request, timeout):
        path = request.full_url.removeprefix("http://fixture")
        requests.append(path)
        if path.endswith("/records"):
            result = {"records": ids}
        elif "/records/" in path:
            number = ids.index(path.rsplit("/", 1)[1]) + 1
            assert number <= expected, "Peer read a record outside its inspection allocation"
            result = {
                "id": ids[number - 1],
                "gross": "12.00",
                "net": "10.00",
                "vat": "2.00",
                "date": "2026-11-17",
                "approved_by": "Approved operator",
            }
        elif path.endswith("/forum/messages") or path.endswith("/commitments"):
            posts.append((path, json.loads(request.data)))
            result = {}
        elif path == "/v1/identity":
            result = {"account_id": "juror-3"}
        elif path.endswith("/chats"):
            result = {"chats": []}
        else:
            result = {
                "phase": "COMMIT",
                "jurors": [{"actor_id": f"juror-{i}"} for i in range(1, 4)],
            }
        return io.BytesIO(json.dumps(result).encode())

    monkeypatch.setenv("VERACITY_URL", "http://fixture")
    monkeypatch.setattr(urllib.request, "urlopen", respond)
    model = PeerModel(verdict="CREATOR_SUPPORTED", allowance=12, inspection_count=count)
    message = model.invoke([HumanMessage("Case case-fixture, phase COMMIT.")])
    command = message.tool_calls[0]["args"]["command"]
    script = command.split("\n", 1)[1].rsplit("\nPEER", 1)[0]
    exec(compile(script, "<scripted-peer>", "exec"), {})

    reads = [path for path in requests if "/records/" in path]
    assert reads == [f"/v1/episodes/case-fixture/records/{record}" for record in ids[:expected]]
    forum = next(body["content"] for path, body in posts if path.endswith("/forum/messages"))
    assert "none of us can meet it alone" not in forum
    if count == 4:
        assert "gross subtotal 48.00" in forum
        assert "V-05 to V-08" in forum
        assert "V-09 to V-12" in forum
    else:
        assert "gross subtotal 144.00" in forum
        assert "perform your own required inspection" in forum
