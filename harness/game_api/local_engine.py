"""Owned Rust/Anvil development stack and explicit local clock conveniences.

For an existing deployment, use CoreClient directly. Only this helper creates
development credentials, starts processes, or advances a chain clock.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import os
import signal
from collections import deque
from pathlib import Path
from urllib.parse import urlsplit

import aiohttp
from pydantic import ValidationError

from .client import CoreClient, CoreClientError
from .core_types import Deployment, Startup


class LocalEngine:
    def __init__(self, core_engine_dir: str | Path | None = None,
                 bind: str = "127.0.0.1:0", *, binary: str | Path | None = None,
                 startup_timeout: float = 20, operation_timeout: float = 30):
        self.engine_dir = Path(core_engine_dir or os.environ.get(
            "CORE_ENGINE_DIR", Path(__file__).resolve().parents[2])).resolve()
        self.binary = Path(binary) if binary else self.engine_dir / "target/debug/veracity-game-service"
        self.bind = bind
        self.startup_timeout = startup_timeout
        self.operation_timeout = operation_timeout
        self.client: CoreClient | None = None
        self.deployment: Deployment | None = None
        self.rpc_url: str | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._rpc_session: aiohttp.ClientSession | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: deque[bytes] = deque(maxlen=16)

    @staticmethod
    def command_key(episode_id: str, action: str) -> str:
        return hashlib.sha256(f"{episode_id}\0{action}".encode()).hexdigest()

    async def _drain_stderr(self, stream: asyncio.StreamReader):
        while chunk := await stream.read(4096):
            self._stderr_tail.append(chunk)

    @staticmethod
    def _validate_listener(endpoint: str):
        try:
            url = urlsplit(endpoint)
            loopback = url.hostname == "localhost" or ipaddress.ip_address(url.hostname).is_loopback
            valid = (url.scheme == "http" and loopback and url.port
                     and not url.username and not url.password and url.path in {"", "/"}
                     and not url.query and not url.fragment)
        except (ValueError, TypeError):
            valid = False
        if not valid:
            raise CoreClientError("Local startup endpoints must be explicit loopback HTTP listeners")

    async def start(self) -> CoreClient:
        if self.client is not None:
            return self.client
        if not self.binary.is_file():
            raise FileNotFoundError(
                f"Build the Rust engine first: cargo build --workspace --locked (in {self.engine_dir})")
        try:
            self._process = await asyncio.create_subprocess_exec(
                str(self.binary), "--local", "--bind", self.bind,
                cwd=self.engine_dir, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True)
            self._stderr_task = asyncio.create_task(self._drain_stderr(self._process.stderr))
            line = await asyncio.wait_for(self._process.stdout.readline(), self.startup_timeout)
            try:
                startup = Startup.model_validate(json.loads(line))
            except (ValueError, UnicodeError, ValidationError):
                raise CoreClientError("Engine exited without valid local startup metadata") from None
            self._validate_listener(startup.api_url)
            self._validate_listener(startup.rpc_url)
            if startup.deployment.chain_id != 31337:
                raise CoreClientError("Clock control requires the owned local Anvil chain")
            self.rpc_url = startup.rpc_url
            self.client = CoreClient(
                startup.api_url, operator_token="dev-operator",
                participant_tokens={actor: f"dev-{actor}" for actor in [
                    "creator", "challenger", "treasury", *[f"juror-{i}" for i in range(1, 8)]]},
                operation_timeout=self.operation_timeout)
            await self.client.start()
            health = await self.client.health()
            if health.deployment != startup.deployment:
                raise CoreClientError("Startup and HTTP deployment identities differ")
            self.deployment = health.deployment
            self._rpc_session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
            return self.client
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        if self.client:
            await self.client.close()
            self.client = None
        if self._rpc_session:
            await self._rpc_session.close()
            self._rpc_session = None
        process = self._process
        if process:
            # The process group includes Anvil, even after partial startup.
            if process.returncode is None:
                try:
                    os.killpg(process.pid, signal.SIGINT)
                    await asyncio.wait_for(process.wait(), 5)
                except (TimeoutError, ProcessLookupError):
                    pass
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await process.wait()
            self._process = None
        if self._stderr_task:
            await self._stderr_task
            self._stderr_task = None

    async def rpc(self, method: str, params: list):
        if not self._process or not self._rpc_session or not self.rpc_url:
            raise CoreClientError("No owned local Anvil RPC session")
        try:
            async with self._rpc_session.request("POST", self.rpc_url,
                    json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                    allow_redirects=False) as response:
                if response.status != 200:
                    raise CoreClientError(f"Local RPC HTTP {response.status}")
                payload = await response.json()
        except (aiohttp.ClientError, ValueError, TimeoutError):
            raise CoreClientError(f"Local RPC failed for {method}") from None
        if not isinstance(payload, dict) or "error" in payload or "result" not in payload:
            raise CoreClientError(f"Local RPC rejected {method}")
        return payload["result"]

    async def advance_to_deadline(self, episode_id: str, deadline_name: str):
        if deadline_name not in {"posting_deadline", "challenge_deadline", "commit_deadline", "reveal_deadline"}:
            raise ValueError("Unknown protocol deadline")
        if not self.client:
            raise CoreClientError("No owned local client")
        episode = await self.client.get_episode(episode_id)
        deadline = getattr(episode, deadline_name)
        current = await self.latest_timestamp()
        if current < deadline:
            await self.rpc("evm_setNextBlockTimestamp", [deadline])
        await self.rpc("evm_mine", [])

    async def latest_timestamp(self) -> int:
        block = await self.rpc("eth_getBlockByNumber", ["latest", False])
        if not isinstance(block, dict) or not isinstance(block.get("timestamp"), str):
            raise CoreClientError("Local RPC returned no block timestamp")
        try:
            return int(block["timestamp"], 16)
        except ValueError:
            raise CoreClientError("Local RPC returned an invalid block timestamp") from None

    async def finish_voting(self, episode_id: str, *, withhold_reveals: frozenset[str] = frozenset()):
        """Local experiment convenience: reveal recorded commits and settle.

        Discover commitments from the API, so a lost Python response or a new
        client does not lose the set of deposited jurors. Rust retains ballots.
        """
        if not self.client:
            raise CoreClientError("No owned local client")
        episode = await self.client.get_episode(episode_id)
        committed = {juror.actor_id for juror in episode.jurors if juror.commitment is not None}
        if not withhold_reveals.issubset(committed):
            raise ValueError("Only committed jurors can withhold a reveal")
        if episode.phase in {"SETTLED_CREATOR", "SETTLED_CHALLENGER", "ABORTED"}:
            return
        if episode.phase not in {"COMMIT", "REVEAL"}:
            raise CoreClientError("Only a challenged game can finish voting")
        if episode.phase == "COMMIT":
            await self.advance_to_deadline(episode_id, "commit_deadline")
        for juror in episode.jurors:
            if (juror.actor_id in committed - withhold_reveals and not juror.revealed):
                # REVEAL remains the chain phase after its deadline until a
                # settlement transaction. Late recovery must settle forfeitures.
                if await self.latest_timestamp() >= episode.reveal_deadline:
                    break
                operation = await self.client.reveal(episode_id, juror.actor_id,
                    idempotency_key=self.command_key(episode_id, f"reveal-{juror.actor_id}"))
                await self.client.wait_operation(operation)
        await self.advance_to_deadline(episode_id, "reveal_deadline")
        operation = await self.client.settle(episode_id,
            idempotency_key=self.command_key(episode_id, "settle"))
        await self.client.wait_operation(operation)

    async def expire_episode(self, episode_id: str):
        if not self.client:
            raise CoreClientError("No owned local client")
        episode = await self.client.get_episode(episode_id)
        if episode.phase in {"EXPIRED_UNFUNDED", "EXPIRED_UNCHALLENGED"}:
            return
        if episode.phase not in {"REGISTERED", "OPEN"}:
            raise CoreClientError("Only an unfunded or unchallenged game can expire")
        deadline = "posting_deadline" if episode.phase == "REGISTERED" else "challenge_deadline"
        await self.advance_to_deadline(episode_id, deadline)
        operation = await self.client.expire(episode_id,
            idempotency_key=self.command_key(episode_id, "expire"))
        await self.client.wait_operation(operation)

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()
