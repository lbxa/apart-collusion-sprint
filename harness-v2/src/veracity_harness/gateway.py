"""Network-bound participant access to the existing game API.

Runs in the trusted gateway container, outside every participant sandbox.
"""

import argparse
import hmac
import json
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path

import aiohttp
from aiohttp import web
from game_api.generated import ChatPage, OperationView
from pydantic import BaseModel, ConfigDict, Field, ValidationError

MAX_BODY = 128 * 1024
MAX_RESPONSE = 1024 * 1024


async def read_bounded(response: aiohttp.ClientResponse) -> bytes:
    body = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        body.extend(chunk)
        if len(body) > MAX_RESPONSE:
            raise web.HTTPBadGateway(text="Game response exceeds the response limit")
    return bytes(body)


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    actor_id: str
    token: str = Field(repr=False)


class GatewayPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    upstream: str
    relay_token: str = Field(default="", repr=False)
    episode_id: str
    identities: dict[str, Identity]
    public_messaging: bool
    private_chat: bool
    private_history: bool
    private_communication_prohibited: bool

    def permits(self, method: str, path: str) -> bool:
        episode = re.escape(self.episode_id)
        if method == "GET" and path in {
            "/",
            "/v1/docs",
            "/v1/openapi.json",
            "/v1/identity",
            "/v1/health",
            "/v1/participants",
        }:
            return True
        if method == "GET" and re.fullmatch(
            rf"/v1/episodes/{episode}(?:/(?:settlement|balances))?", path
        ):
            return True
        if method == "POST" and re.fullmatch(
            rf"/v1/episodes/{episode}/(?:claims|challenges|commitments|reveals|withdrawals)", path
        ):
            return True
        if method == "GET" and re.fullmatch(r"/v1/operations/[A-Za-z0-9_-]+", path):
            return True
        if self.public_messaging and method in {"GET", "POST"}:
            if path == f"/v1/episodes/{self.episode_id}/forum/messages":
                return True
        if self.private_chat and method in {"GET", "POST"}:
            if method == "POST" and path.endswith("/chats"):
                if not self.private_communication_prohibited:
                    return False
            return bool(
                path == f"/v1/episodes/{self.episode_id}/chats"
                or re.fullmatch(r"/v1/chats/[A-Za-z0-9_-]+/messages", path)
            )
        return False

    def public_identity(self, identity: Identity) -> dict:
        return {
            "actor_id": identity.actor_id,
            "episode_id": self.episode_id,
            "public_messaging": self.public_messaging,
            "private_chat": self.private_chat,
            "private_history": self.private_history,
            "private_communication_prohibited": self.private_communication_prohibited,
        }


def create_gateway(
    policy_source: Callable[[], GatewayPolicy], interface: str, audit_path: Path | None = None
) -> web.Application:
    @web.middleware
    async def audit(request, handler):
        try:
            current = policy_source()
        except (OSError, ValueError):
            raise web.HTTPServiceUnavailable(text="Gateway policy unavailable") from None
        identity = current.identities.get(request.remote or "")
        endpoint = request.path.rsplit("/", 1)[-1]
        if endpoint not in {
            "claims",
            "challenges",
            "commitments",
            "reveals",
            "withdrawals",
            "messages",
            "chats",
            "settlement",
            "balances",
            "identity",
            "health",
            "participants",
            "docs",
            "openapi.json",
        }:
            endpoint = "other"
        event = {
            "request_id": uuid.uuid4().hex,
            "episode_id": current.episode_id,
            "actor_id": identity.actor_id if identity else None,
            "method": request.method,
            "endpoint": endpoint,
            "time_ns": time.time_ns(),
        }

        def append(**fields):
            if audit_path is not None:
                with audit_path.open("a") as file:
                    file.write(json.dumps({**event, **fields}) + "\n")

        append(event="request")
        status = 500
        try:
            response = await handler(request)
            status = response.status
            return response
        except web.HTTPException as error:
            status = error.status
            raise
        finally:
            append(event="response", status=status)

    app = web.Application(client_max_size=MAX_BODY, middlewares=[audit])
    session_key = web.AppKey("upstream", aiohttp.ClientSession)
    operations: dict[tuple[str, str], set[str]] = {}

    async def session_lifecycle(application):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35)) as session:
            application[session_key] = session
            yield

    app.cleanup_ctx.append(session_lifecycle)

    async def dispatch(request: web.Request) -> web.Response:
        try:
            policy = policy_source()
        except (OSError, ValueError):
            raise web.HTTPServiceUnavailable(text="Gateway policy unavailable") from None
        identity = policy.identities.get(request.remote or "")
        if identity is None:
            raise web.HTTPForbidden(text="Unrecognized participant network")
        # Encoded path separators and ambiguous traversal are never forwarded.
        if "%" in request.raw_path.partition("?")[0] or ".." in request.path:
            raise web.HTTPForbidden(text="Ambiguous path")
        if not policy.permits(request.method, request.path):
            raise web.HTTPForbidden(text="Outside this participant's experimental interface")
        if request.path in {"/", "/v1/docs"}:
            return web.Response(text=interface, content_type="text/markdown")
        if request.path == "/v1/identity":
            return web.json_response(policy.public_identity(identity))
        headers = {"Authorization": f"Bearer {identity.token}"}
        if policy.relay_token:
            headers["X-Veracity-Relay"] = policy.relay_token
        for header in ("Content-Type", "Idempotency-Key"):
            if header in request.headers:
                headers[header] = request.headers[header]
        session = app[session_key]
        actor_scope = (policy.episode_id, identity.actor_id)
        if request.path.startswith("/v1/operations/"):
            operation_id = request.path.rsplit("/", 1)[1]
            if operation_id not in operations.get(actor_scope, set()):
                raise web.HTTPForbidden(text="Operation was not issued by this participant")
        if request.path.startswith("/v1/chats/"):
            chat_id = request.path.split("/")[3]
            cursor = ""
            while True:
                url = f"{policy.upstream}/v1/episodes/{policy.episode_id}/chats"
                async with session.get(
                    url,
                    headers=headers,
                    params={"after": cursor, "limit": 100},
                    allow_redirects=False,
                ) as response:
                    if response.status != 200:
                        raise web.HTTPBadGateway(text="Could not verify chat scope")
                    page = ChatPage.model_validate_json(await read_bounded(response))
                if any(
                    chat.episode_id != policy.episode_id
                    or identity.actor_id not in chat.participant_ids
                    for chat in page.chats
                ):
                    raise web.HTTPBadGateway(text="Upstream chat scope mismatch")
                if any(chat.chat_id == chat_id for chat in page.chats):
                    break
                if not page.has_more:
                    raise web.HTTPForbidden(text="Chat is outside the current episode")
                if page.next_after is None or page.next_after <= cursor:
                    raise web.HTTPBadGateway(text="Invalid chat pagination")
                cursor = page.next_after
        body = await request.read()
        if request.method == "POST" and request.path.endswith("/chats"):
            try:
                creation = json.loads(body)
                if not isinstance(creation, dict):
                    raise ValueError
                if creation.get("history_enabled", False) != policy.private_history:
                    raise web.HTTPBadRequest(text="Chat history must match the experiment setting")
            except (ValueError, TypeError):
                raise web.HTTPBadRequest(text="Invalid chat request") from None
        try:
            async with session.request(
                request.method,
                f"{policy.upstream}{request.path}",
                params=request.query,
                headers=headers,
                data=body,
                allow_redirects=False,
            ) as response:
                payload = await read_bounded(response)
                if request.path == "/v1/openapi.json" and response.status == 200:
                    document = json.loads(payload)
                    paths = {}
                    for path, methods in document["paths"].items():
                        replacement = (
                            policy.episode_id if path.startswith("/v1/episodes/") else "resource"
                        )
                        candidate = path.replace("{id}", replacement)
                        permitted = {
                            method: {**operation, "security": []}
                            for method, operation in methods.items()
                            if method in {"get", "post"}
                            and policy.permits(method.upper(), candidate)
                        }
                        if permitted:
                            paths[path] = permitted
                    return web.json_response(
                        {**document, "paths": paths, "security": [], "servers": [{"url": "/"}]}
                    )
                if request.method == "POST" and response.status in {200, 201, 202}:
                    if not request.path.endswith(("/messages", "/chats")):
                        operation = OperationView.model_validate_json(payload)
                        if (
                            operation.actor_id != identity.actor_id
                            or operation.episode_id != policy.episode_id
                        ):
                            raise web.HTTPBadGateway(text="Upstream operation identity mismatch")
                        operations.setdefault(actor_scope, set()).add(operation.operation_id)
                return web.Response(
                    body=payload,
                    status=response.status,
                    headers={
                        "Content-Type": response.headers.get("Content-Type", "application/json"),
                        "Cache-Control": "no-store",
                    },
                )
        except (aiohttp.ClientError, TimeoutError, ValidationError, ValueError, KeyError):
            raise web.HTTPBadGateway(text="Game API unavailable or invalid response") from None

    app.router.add_route("*", "/{path:.*}", dispatch)
    return app


def create_loopback_relay(upstream: str, token: str) -> web.Application:
    """Bridge Docker to the loopback-only engine without exposing its development API."""
    app = web.Application(client_max_size=MAX_BODY)
    session_key = web.AppKey("relay_upstream", aiohttp.ClientSession)

    async def lifecycle(application):
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=35)) as session:
            application[session_key] = session
            yield

    app.cleanup_ctx.append(lifecycle)

    async def forward(request):
        if not hmac.compare_digest(request.headers.get("X-Veracity-Relay", ""), token):
            raise web.HTTPForbidden(text="Relay authentication required")
        if not request.path.startswith("/v1/"):
            raise web.HTTPForbidden(text="Outside the game interface")
        headers = {
            name: request.headers[name]
            for name in ("Authorization", "Idempotency-Key", "Content-Type")
            if name in request.headers
        }
        try:
            async with app[session_key].request(
                request.method,
                upstream + request.path,
                headers=headers,
                params=request.query,
                data=await request.read(),
                allow_redirects=False,
            ) as response:
                body = await read_bounded(response)
                return web.Response(
                    body=body,
                    status=response.status,
                    headers={
                        "Content-Type": response.headers.get("Content-Type", "application/json")
                    },
                )
        except (aiohttp.ClientError, TimeoutError):
            raise web.HTTPBadGateway(text="Game engine unavailable") from None

    app.router.add_route("*", "/{path:.*}", forward)
    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--interface", type=Path, required=True)
    parser.add_argument("--audit", type=Path)
    args = parser.parse_args()
    web.run_app(
        create_gateway(
            lambda: GatewayPolicy.model_validate_json(args.policy.read_bytes()),
            args.interface.read_text(),
            args.audit,
        ),
        host="0.0.0.0",
        port=8080,
        access_log=None,
        print=None,
    )


if __name__ == "__main__":
    main()
