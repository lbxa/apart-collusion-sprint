import asyncio
import json
import secrets

import pytest

from veracity_harness.gateway import GatewayPolicy, Identity
from veracity_harness.sandbox import DockerArena


@pytest.mark.integration
async def test_actual_network_filesystem_and_identity_isolation(tmp_path):
    arena = DockerArena(f"isolation-{secrets.token_hex(4)}")
    try:
        await asyncio.to_thread(arena.build_image)
        policy_dir = tmp_path / "policy"
        policy_dir.mkdir()
        gateway = await asyncio.to_thread(arena.start_gateway, policy_dir)
        sandboxes, identities = [], {}
        for actor in ("creator", "challenger"):
            docs = tmp_path / actor
            docs.mkdir(mode=0o755)
            (docs / "rules.md").write_text("Public game rules")
            sandbox, address = await asyncio.to_thread(
                arena.start_participant, actor, docs, gateway
            )
            sandboxes.append((sandbox, address))
            identities[address] = Identity(actor_id=actor, token=f"private-{actor}")
        policy = GatewayPolicy(
            upstream="http://unreachable.invalid",
            episode_id="episode-isolation",
            identities=identities,
            public_messaging=False,
            private_chat=False,
            private_history=False,
            private_communication_prohibited=True,
        )
        (policy_dir / "policy.json").write_text(policy.model_dump_json())
        first, second = sandboxes[0][0], sandboxes[1][0]
        for _ in range(20):
            probe = await asyncio.to_thread(first.execute, "curl -fsS $GAME_URL/v1/identity")
            if probe.exit_code == 0:
                break
            await asyncio.sleep(0.2)
        assert probe.exit_code == 0
        assert json.loads(probe.output)["actor_id"] == "creator"
        spoofed = await asyncio.to_thread(
            first.execute,
            "curl -fsS -H 'Authorization: Bearer private-challenger' $GAME_URL/v1/identity",
        )
        assert json.loads(spoofed.output)["actor_id"] == "creator"
        environment = await asyncio.to_thread(first.execute, "env")
        assert "OPENROUTER_API_KEY" not in environment.output
        assert "private-challenger" not in environment.output
        readonly = await asyncio.to_thread(first.execute, "echo changed > /game/rules.md")
        assert readonly.exit_code != 0
        absent_host = await asyncio.to_thread(
            first.execute, "test -e /Users/lucas/c/apart-collusion-sprint/.env"
        )
        assert absent_host.exit_code != 0
        uploaded = await asyncio.to_thread(
            first.upload_files,
            [("/workspace/private.txt", b"private note"), ("/game/rules.md", b"bad")],
        )
        assert uploaded[0].error is None
        assert uploaded[1].error == "permission_denied"
        downloaded = await asyncio.to_thread(first.download_files, ["/workspace/private.txt"])
        assert downloaded[0].content == b"private note"
        missing = await asyncio.to_thread(second.execute, "cat /workspace/private.txt")
        assert missing.exit_code != 0
        await asyncio.to_thread(
            second.execute, "python -m http.server 8081 >/tmp/server.log 2>&1 &"
        )
        peer = await asyncio.to_thread(
            first.execute,
            f"curl -fsS --connect-timeout 1 --max-time 2 http://{sandboxes[1][1]}:8081",
        )
        assert peer.exit_code != 0
        timeout = await asyncio.to_thread(first.execute, "sleep 5", timeout=1)
        assert timeout.exit_code == 124
        assert (await asyncio.to_thread(first.execute, "echo alive")).exit_code == 0
    finally:
        await asyncio.to_thread(arena.close)
