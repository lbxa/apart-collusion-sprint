import json

from veracity_harness.watch import Follower


def test_follower_prints_reasoning_commands_and_actions_as_they_are_appended(tmp_path):
    run = tmp_path / "run-abc"
    case = run / "VR-1"
    (case / "gateway-audit").mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"models": {"creator": "@cf/strong"}}))
    calls = case / "creator.trace.calls.jsonl"
    audit = case / "gateway-audit/access.jsonl"
    follower = Follower(tmp_path)
    assert follower.poll() == []
    message = {
        "content": "",
        "additional_kwargs": {"reasoning_content": "The jury must see it my way."},
        "tool_calls": [{"name": "execute", "args": {"command": "curl -X POST forum"}}],
    }
    calls.write_text(
        json.dumps({"event": "model_end", "response": {"generations": [[{"message": message}]]}})
        + "\n"
    )
    audit.write_text(
        json.dumps(
            {
                "event": "response",
                "method": "POST",
                "actor_id": "creator",
                "endpoint": "messages",
                "status": 201,
            }
        )
        + "\n"
    )
    lines = follower.poll()
    assert any(
        "VR-1 creator (@cf/strong) thinks: The jury must see it my way." in line for line in lines
    )
    assert any("runs: curl -X POST forum" in line for line in lines)
    assert any("VR-1 creator POST messages -> 201" in line for line in lines)
    # Nothing is printed twice; only new lines appear on the next poll.
    assert follower.poll() == []


def test_follower_skips_scripted_parties_and_archived_runs(tmp_path):
    run = tmp_path / "run-abc"
    (run / "VR-1").mkdir(parents=True)
    (run / "run.json").write_text(json.dumps({"config": {"challenger": "scripted"}}))
    archived = tmp_path / "excluded/stopped/run-old/VR-0"
    archived.mkdir(parents=True)
    follower = Follower(tmp_path)
    entry = json.dumps(
        {"event": "model_end", "response": {"generations": [[{"message": {"content": "Done."}}]]}}
    )
    (run / "VR-1/challenger.trace.calls.jsonl").write_text(entry + "\n")
    (archived / "juror-1.trace.calls.jsonl").write_text(entry + "\n")
    assert follower.poll() == []


def test_follower_skips_every_scripted_juror_peer(tmp_path):
    run = tmp_path / "run-abc"
    (run / "VR-1").mkdir(parents=True)
    config = {"peer_offers": {"juror-5": "a", "juror-6": "b"}}
    (run / "run.json").write_text(json.dumps({"config": config}))
    follower = Follower(tmp_path)
    entry = json.dumps(
        {"event": "model_end", "response": {"generations": [[{"message": {"content": "Seed."}}]]}}
    )
    for actor in ("juror-5", "juror-6"):
        (run / f"VR-1/{actor}.trace.calls.jsonl").write_text(entry + "\n")
    assert follower.poll() == []
    (run / "VR-1/juror-1.trace.calls.jsonl").write_text(entry + "\n")
    assert any("juror-1" in line for line in follower.poll())
