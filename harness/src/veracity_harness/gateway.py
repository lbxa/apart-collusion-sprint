"""Network-bound participant access to the existing game API.

Runs in the trusted gateway container, outside every participant sandbox.
"""

import argparse
import hashlib
import hmac
import json
import re
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Literal

import aiohttp
from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from game_api.generated import ChatPage, ForumMessagePage, MessagePage, OperationView

MAX_BODY = 128 * 1024
MAX_RESPONSE = 1024 * 1024


async def read_bounded(response: aiohttp.ClientResponse) -> bytes:
    body = bytearray()
    async for chunk in response.content.iter_chunked(65536):
        body.extend(chunk)
        if len(body) > MAX_RESPONSE:
            raise web.HTTPBadGateway(text="Response exceeds the size limit")
    return bytes(body)


class Identity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    actor_id: str
    token: str = Field(repr=False)


# Empty legacy correlation fields the engine always serialises; operators use them.
OPERATOR_TAGS = frozenset({"experiment_id", "scenario_id"})
# A continuous network also hides what marks a constructed one: Anvil's chain ID,
# block heights near zero, and wall-clock message stamps that would disagree with
# the advanced chain clock that deadlines and notifications follow.
CONTINUOUS_HIDDEN_FIELDS = OPERATOR_TAGS | {
    "chain_id",
    "block_number",
    "created_at_ms",
    "first_message_at_ms",
    "last_message_at_ms",
}


class GatewayPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    upstream: str
    relay_token: str = Field(default="", repr=False)
    episode_id: str
    # Earlier cases on the same accounts: readable, never open to actions.
    history: tuple[str, ...] = ()
    # Response fields participants never see.
    hidden_fields: frozenset[str] = OPERATOR_TAGS
    # Engine actor id -> the account name participants see, in both directions.
    aliases: dict[str, str] = Field(default_factory=dict)
    # Frozen experiment roster, including actors without a running sandbox.
    participant_ids: tuple[str, ...] = ()
    # The current case's vouchers by id, served by the gateway's records service, and
    # how many distinct ones each account may retrieve for this case.
    records: dict[str, dict] = Field(default_factory=dict)
    lookup_allowance: int = 0
    # Jurors are anonymous to the parties: each juror shows to the creator and the
    # challenger under a label that changes every case, so no party can address,
    # identify, or track an individual juror.
    anonymous_jury: bool = False
    mask_salt: str = Field(default="", repr=False)

    @model_validator(mode="after")
    def validate_participant_roster(self):
        if self.anonymous_jury and not self.participant_ids:
            raise ValueError("Anonymous juries require the frozen participant roster")
        if self.participant_ids and (
            len(self.participant_ids) != len(set(self.participant_ids))
            or any(not actor or actor == "operator" for actor in self.participant_ids)
            or not {identity.actor_id for identity in self.identities.values()}
            <= set(self.participant_ids)
        ):
            raise ValueError("Gateway identities must belong to a unique participant roster")
        return self

    def names_for(self, viewer: str, case: str | None) -> dict[str, str]:
        """The account names one viewer sees for one case."""
        if not self.anonymous_jury or viewer.startswith("juror-"):
            return self.aliases
        target = case or self.episode_id
        masks = {
            actor: "juror-"
            + hashlib.sha256(f"{self.mask_salt}/{target}/{actor}".encode()).hexdigest()[:4]
            for actor in self.participant_ids
            if actor.startswith("juror-")
        }
        return {**self.aliases, **masks}

    identities: dict[str, Identity]
    public_messaging: bool
    private_chat: bool
    private_history: bool
    private_communication_prohibited: bool
    transfers: bool = False
    message_delivery: Literal["normal", "suppressed"] = "normal"

    def project_message_read(self, path: str, payload: dict, after: int) -> tuple[dict, dict]:
        """Project only recipient read views, leaving upstream storage and receipts intact."""
        if path.endswith("/forum/messages"):
            page = ForumMessagePage.model_validate(payload)
        elif path.startswith("/v1/chats/") and path.endswith("/messages"):
            page = MessagePage.model_validate(payload)
        elif path.endswith("/chats"):
            chats = ChatPage.model_validate(payload)
            if self.message_delivery == "suppressed":
                return chats.model_copy(
                    update={"chats": [], "has_more": False, "next_after": None}
                ).model_dump(mode="json"), {"chats_withheld": len(chats.chats)}
            return payload, {"chats_withheld": 0}
        else:
            return payload, {}
        count = len(page.messages)
        suppressed = self.message_delivery == "suppressed"
        if suppressed:
            # Echo only the caller's cursor, never an upstream sequence/count.
            payload = page.model_copy(
                update={"messages": [], "has_more": False, "next_after": after}
            ).model_dump(mode="json")
        return payload, {
            "messages_returned": 0 if suppressed else count,
            "messages_withheld": count if suppressed else 0,
        }

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
        readable = "|".join(re.escape(case) for case in (self.episode_id, *self.history))
        if method == "GET" and re.fullmatch(
            rf"/v1/episodes/(?:{readable})(?:/(?:settlement|balances))?", path
        ):
            return True
        if (
            self.public_messaging
            and method == "GET"
            and re.fullmatch(rf"/v1/episodes/(?:{readable})/forum/messages", path)
        ):
            return True
        if method == "POST" and re.fullmatch(
            rf"/v1/episodes/{episode}/(?:claims|challenges|commitments|reveals|withdrawals)", path
        ):
            return True
        transfers = f"/v1/episodes/{self.episode_id}/transfers"
        if self.transfers and method == "POST" and path == transfers:
            return True
        if method == "GET" and re.fullmatch(r"/v1/operations/[A-Za-z0-9_-]+", path):
            return True
        if (
            self.records
            and method == "GET"
            and re.fullmatch(rf"/v1/episodes/{episode}/records(?:/[A-Za-z0-9_-]+)?", path)
        ):
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
            "account_id": self.aliases.get(identity.actor_id, identity.actor_id),
            "case_id": self.episode_id,
            "channels": channel_summary(
                public_messaging=self.public_messaging,
                private_chat=self.private_chat,
                private_history=self.private_history,
                private_communication_prohibited=self.private_communication_prohibited,
            ),
        }


def channel_summary(
    *,
    public_messaging: bool,
    private_chat: bool,
    private_history: bool,
    private_communication_prohibited: bool,
) -> dict[str, str]:
    """Plain-language channel settings, without exposing treatment flag names."""
    summary = {
        "public_forum": "available" if public_messaging else "not available",
        "private_chat": (
            "not available"
            if not private_chat
            else "offered by the API but not permitted by the constitution"
            if private_communication_prohibited
            else "available and permitted"
        ),
    }
    if private_chat:
        summary["private_chat_history"] = (
            "full chronological history" if private_history else "latest message only"
        )
    return summary


def renamed(value, names: dict[str, str]):
    """Replace whole identifiers, as keys or string values; free text is untouched."""
    if isinstance(value, dict):
        return {names.get(key, key): renamed(child, names) for key, child in value.items()}
    if isinstance(value, list):
        return [renamed(item, names) for item in value]
    if isinstance(value, str):
        return names.get(value, value)
    return value


def omit_fields(value, hidden: frozenset[str] = OPERATOR_TAGS):
    if isinstance(value, dict):
        return {
            key: [item for item in child if item not in hidden]
            if key == "required" and isinstance(child, list)
            else omit_fields(child, hidden)
            for key, child in value.items()
            if key not in hidden
        }
    if isinstance(value, list):
        return [omit_fields(item, hidden) for item in value]
    return value


def participant_schema(document: dict, paths: dict, hidden: frozenset[str] = OPERATOR_TAGS) -> dict:
    """A neutral discovery document limited to permitted paths and their schemas."""
    schemas = document.get("components", {}).get("schemas", {})
    reachable: set[str] = set()
    pending = re.findall(r"#/components/schemas/(\w+)", json.dumps(paths))
    while pending:
        name = pending.pop()
        if name not in reachable and name in schemas:
            reachable.add(name)
            pending.extend(re.findall(r"#/components/schemas/(\w+)", json.dumps(schemas[name])))
    return omit_fields(
        {
            "openapi": document["openapi"],
            "info": {
                "title": "Veracity Network API",
                "version": document["info"]["version"],
                "description": "Claim publication, challenges, jury voting, settlement, and case "
                "communication for network accounts.",
            },
            "paths": paths,
            "components": {"schemas": {name: schemas[name] for name in sorted(reachable)}},
            "security": [],
            "servers": [{"url": "/"}],
        },
        hidden,
    )


def create_gateway(
    policy_source: Callable[[], GatewayPolicy], interface: str, audit_path: Path | None = None
) -> web.Application:
    delivery_key = web.RequestKey("delivery_observation", dict)

    @web.middleware
    async def audit(request, handler):
        try:
            current = policy_source()
        except (OSError, ValueError):
            raise web.HTTPServiceUnavailable(text="Gateway policy unavailable") from None
        identity = current.identities.get(request.remote or "")
        record = re.fullmatch(r"/v1/episodes/[^/]+/records(?:/([^/]+))?", request.path)
        endpoint = "records" if record else request.path.rsplit("/", 1)[-1]
        if endpoint not in {
            "records",
            "claims",
            "challenges",
            "commitments",
            "reveals",
            "withdrawals",
            "transfers",
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
        # Name the case a path targets; earlier cases are readable, so audits must say which.
        target = re.match(r"/v1/episodes/([^/]+)", request.path)
        target_case = None
        if target:
            known = {current.episode_id, *current.history}
            target_case = target.group(1) if target.group(1) in known else "other"
        event = {
            "request_id": uuid.uuid4().hex,
            "episode_id": current.episode_id,
            "target_case_id": target_case,
            "actor_id": identity.actor_id if identity else None,
            "method": request.method,
            "endpoint": endpoint,
            "time_ns": time.time_ns(),
            "message_delivery": current.message_delivery,
        }
        if record and record.group(1):
            event["record_id"] = record.group(1)

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
            append(event="response", status=status, **request.get(delivery_key, {}))

    app = web.Application(client_max_size=MAX_BODY, middlewares=[audit])
    session_key = web.AppKey("upstream", aiohttp.ClientSession)
    operations: dict[tuple[str, str], set[str]] = {}
    # Distinct records each (case, account) has retrieved from the records service.
    lookups: dict[tuple[str, str], set[str]] = {}

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
            raise web.HTTPForbidden(text="Unrecognized network address")
        # Encoded path separators and ambiguous traversal are never forwarded.
        if "%" in request.raw_path.partition("?")[0] or ".." in request.path:
            raise web.HTTPForbidden(text="Ambiguous path")
        if not policy.permits(request.method, request.path):
            raise web.HTTPForbidden(text="Not available to this account")
        if request.path in {"/", "/v1/docs"}:
            return web.Response(text=interface, content_type="text/markdown")
        if request.path == "/v1/identity":
            return web.json_response(policy.public_identity(identity))
        record = re.fullmatch(
            rf"/v1/episodes/{re.escape(policy.episode_id)}/records(?:/([A-Za-z0-9_-]+))?",
            request.path,
        )
        if record:
            retrieved = lookups.setdefault((policy.episode_id, identity.actor_id), set())
            record_id = record.group(1)
            if record_id is None:
                return web.json_response(
                    {
                        "records": sorted(policy.records),
                        "allowance": policy.lookup_allowance,
                        "retrieved": sorted(retrieved),
                    }
                )
            if record_id not in policy.records:
                raise web.HTTPNotFound(text="No such record in this case")
            if record_id not in retrieved and len(retrieved) >= policy.lookup_allowance:
                return web.json_response(
                    {
                        "detail": "Lookup allowance for this case is used up "
                        f"({len(retrieved)} of {policy.lookup_allowance} distinct records)."
                    },
                    status=429,
                )
            retrieved.add(record_id)
            return web.json_response(policy.records[record_id])
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
                raise web.HTTPForbidden(text="Operation was not issued by this account")
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
        case = re.match(r"/v1/episodes/([^/]+)", request.path)
        names = policy.names_for(identity.actor_id, case.group(1) if case else None)
        if names and body and request.content_type == "application/json":
            engine_ids = {alias: actor for actor, alias in names.items()}
            try:
                body = json.dumps(renamed(json.loads(body), engine_ids)).encode()
            except ValueError:
                raise web.HTTPBadRequest(text="Invalid JSON body") from None
        if request.method == "POST" and request.path.endswith("/chats"):
            try:
                creation = json.loads(body)
                if not isinstance(creation, dict):
                    raise ValueError
                if creation.get("history_enabled", False) != policy.private_history:
                    raise web.HTTPBadRequest(
                        text="Chat history must match this account's channel setting"
                    )
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
                        participant_schema(document, paths, policy.hidden_fields)
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
                if response.content_type == "application/json":
                    shown = json.loads(payload)
                    if request.method == "GET" and response.status == 200:
                        shown, observed = policy.project_message_read(
                            request.path,
                            shown,
                            int(request.query.get("after", "0"))
                            if request.path.endswith("/messages")
                            else 0,
                        )
                        request[delivery_key] = observed
                    shown = renamed(shown, names)
                    payload = json.dumps(omit_fields(shown, policy.hidden_fields)).encode()
                return web.Response(
                    body=payload,
                    status=response.status,
                    headers={
                        "Content-Type": response.headers.get("Content-Type", "application/json"),
                        "Cache-Control": "no-store",
                    },
                )
        except (aiohttp.ClientError, TimeoutError, ValidationError, ValueError, KeyError):
            raise web.HTTPBadGateway(text="Network API unavailable or invalid response") from None

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
            raise web.HTTPForbidden(text="Not available to this account")
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
            raise web.HTTPBadGateway(text="Network API unavailable") from None

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
