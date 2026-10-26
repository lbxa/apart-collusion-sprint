from aiohttp.test_utils import TestClient, TestServer

from veracity_harness.gateway import create_loopback_relay


async def test_relay_denies_unrecognized_host_callers_before_contacting_engine():
    app = create_loopback_relay("http://127.0.0.1:1", "relay-secret")
    async with TestClient(TestServer(app)) as client:
        assert (await client.get("/v1/health")).status == 403
        assert (await client.get("/v1/health", headers={"X-Veracity-Relay": "wrong"})).status == 403
        assert (
            await client.get("/not-the-engine", headers={"X-Veracity-Relay": "relay-secret"})
        ).status == 403
