"""GameAPI backed by an owned Rust /v1 server and its isolated local Anvil.

The contract is the only settlement authority. Harness tokens use 100 integer
base units each; floats exist only in the legacy prompt/metrics presentation.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import signal
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import MappingProxyType
from urllib.parse import quote, urlsplit

import aiohttp
from pydantic import BaseModel, ValidationError

from .core_types import Balances, Episode, Health, Operation, Settlement, Startup
from .interface import GameAPI
from .types import EpisodeConfig, Phase, SettlementResult, Verdict

logger = logging.getLogger(__name__)
UNITS_PER_TOKEN = 100
DEFAULT_PHASE_DURATION = 300
COMMIT_PHASE_DURATION = 3600


class CoreEngineError(RuntimeError):
    """An engine operation or response cannot be used as a confirmed result."""


@dataclass(frozen=True)
class _EpisodeMapping:
    config: EpisodeConfig
    harness_to_engine: dict[str, str]
    engine_to_harness: dict[str, str]
    committed: set[str] = field(default_factory=set)


def _validated[T: BaseModel](model: type[T], data: object) -> T:
    try:
        return model.model_validate(data)
    except ValidationError:
        # Never put artifacts, ballots, credentials, or response bodies in errors.
        raise CoreEngineError(f"Invalid /v1 {model.__name__} response") from None


def _integer_units(value: float, scale: int, label: str) -> int:
    try:
        units = Decimal(str(value)) * scale
        if not units.is_finite() or units < 0 or units != units.to_integral_value():
            raise ValueError
        return int(units)
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{label} must be nonnegative and exactly representable at scale {scale}") from None


class CoreEngineAPI(GameAPI):
    """Own a local game process; submit confirmed, idempotent protocol actions."""

    backend = "core"

    def __init__(self, core_engine_dir: str | Path | None = None,
                 bind: str = "127.0.0.1:0", *, startup_timeout: float = 20,
                 operation_timeout: float = 30):
        self._engine_dir = Path(core_engine_dir or os.environ.get(
            "CORE_ENGINE_DIR", Path(__file__).resolve().parents[2])).resolve()
        self._bind = bind
        self._startup_timeout = startup_timeout
        self._operation_timeout = operation_timeout
        self._process: asyncio.subprocess.Process | None = None
        self._session: aiohttp.ClientSession | None = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: deque[bytes] = deque(maxlen=16)
        self._episodes: dict[str, _EpisodeMapping] = {}
        self._base_url: str | None = None
        self._rpc_url: str | None = None
        self._deployment: dict | None = None
        self._started = False

    @property
    def api_url(self) -> str | None:
        return self._base_url

    @property
    def rpc_url(self) -> str | None:
        return self._rpc_url

    @property
    def deployment(self):
        return MappingProxyType(self._deployment or {})

    async def _drain_stderr(self, stream: asyncio.StreamReader):
        while chunk := await stream.read(4096):
            self._stderr_tail.append(chunk)

    async def start(self):
        if self._started:
            return
        binary = self._engine_dir / "target/debug/veracity-game-service"
        if not binary.is_file():
            raise FileNotFoundError(f"Build the Rust engine first: cargo build --workspace --locked (in {self._engine_dir})")
        logger.info("core.starting bind=%s", self._bind)
        try:
            self._process = await asyncio.create_subprocess_exec(
                str(binary), "--local", "--bind", self._bind,
                cwd=self._engine_dir, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, start_new_session=True,
            )
            self._stderr_task = asyncio.create_task(self._drain_stderr(self._process.stderr))
            line = await asyncio.wait_for(self._process.stdout.readline(), self._startup_timeout)
            try:
                startup = _validated(Startup, json.loads(line))
            except (ValueError, UnicodeError):
                raise CoreEngineError("Engine exited without valid local startup metadata") from None
            for endpoint in (startup.api_url, startup.rpc_url):
                url = urlsplit(endpoint)
                if (url.scheme != "http" or not url.hostname
                        or not (url.hostname == "localhost" or ipaddress.ip_address(url.hostname).is_loopback)
                        or not url.port or url.username or url.password):
                    raise CoreEngineError("Local startup endpoints must be explicit loopback HTTP listeners")
            if startup.deployment.chain_id != 31337:
                raise CoreEngineError("Clock control requires the owned local Anvil chain")
            self._base_url, self._rpc_url = startup.api_url, startup.rpc_url
            self._deployment = startup.deployment.model_dump()
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
            health = _validated(Health, await self._request("GET", "/v1/health"))
            if health.deployment != startup.deployment:
                raise CoreEngineError("Startup and HTTP deployment identities differ")
            self._started = True
            logger.info("core.ready chain_id=31337 contract=%s", startup.deployment.contract_address)
        except BaseException:
            await self.stop()
            raise

    async def stop(self):
        if self._session:
            await self._session.close()
            self._session = None
        process = self._process
        if process:
            # The owned process group includes Anvil, even if startup failed.
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
        self._started = False
        self._episodes.clear()
        logger.info("core.stopped")

    async def _request(self, method: str, path: str, token: str | None = None,
                       body: dict | None = None, idempotency_key: str | None = None) -> dict:
        if not self._session:
            raise CoreEngineError("Core engine is not started")
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        try:
            async with self._session.request(method, f"{self._base_url}{path}",
                                             json=body, headers=headers,
                                             allow_redirects=False) as response:
                if not 200 <= response.status < 300:
                    raise CoreEngineError(f"Engine HTTP {response.status} on {path}")
                try:
                    data = await response.json()
                except (ValueError, aiohttp.ContentTypeError):
                    raise CoreEngineError(f"Invalid JSON response on {path}") from None
        except (aiohttp.ClientError, TimeoutError):
            raise CoreEngineError(f"Engine transport failed on {path}; reconcile the existing operation before retrying") from None
        if not isinstance(data, dict):
            raise CoreEngineError(f"Expected a JSON object on {path}")
        if method == "POST":
            operation = _validated(Operation, data)
            operation = await self._wait_operation(operation)
            return operation.model_dump()
        return data

    async def _wait_operation(self, operation: Operation) -> Operation:
        async with asyncio.timeout(self._operation_timeout):
            while True:
                if operation.status in {"failed", "reverted"}:
                    raise CoreEngineError(f"Operation {operation.operation_id} {operation.status}")
                if operation.status == "confirmed":
                    if (not operation.transaction or not operation.transaction.receipt
                            or not operation.transaction.receipt.success
                            or not operation.transaction.receipt.confirmed):
                        raise CoreEngineError("Confirmed operation is missing a successful confirmed receipt")
                    logger.info("core.operation.confirmed id=%s kind=%s", operation.operation_id, operation.kind)
                    return operation
                # Reconciliation resumes the durable Rust operation; it never
                # creates a new action or a new Python idempotency identity.
                await asyncio.sleep(0.1)
                path = f"/v1/operations/{quote(operation.operation_id, safe='')}/reconcile"
                async with self._session.request("POST", f"{self._base_url}{path}",
                        json={}, headers={
                            "Authorization": "Bearer dev-operator",
                            "Idempotency-Key": self._idem_key(operation.episode_id, f"reconcile-{operation.operation_id}"),
                        },
                        allow_redirects=False) as response:
                    if response.status not in {200, 202}:
                        raise CoreEngineError(f"Reconciliation HTTP {response.status}")
                    previous = operation
                    operation = _validated(Operation, await response.json())
                    if (operation.operation_id, operation.episode_id, operation.actor_id, operation.kind) != (
                            previous.operation_id, previous.episode_id, previous.actor_id, previous.kind):
                        raise CoreEngineError("Operation identity changed during reconciliation")

    @staticmethod
    def validate_config(config: EpisodeConfig) -> dict[str, int | str]:
        if config.jury_size not in {3, 5, 7}:
            raise ValueError("Core engine jury size must be 3, 5, or 7")
        if config.allow_vote_change:
            raise ValueError("Binding commitments cannot change verdict")
        payout = config.payout
        beta = _integer_units(payout.creator_bet, UNITS_PER_TOKEN, "creator bet")
        other_beta = _integer_units(payout.challenger_bet, UNITS_PER_TOKEN, "challenger bet")
        bond = _integer_units(payout.juror_bond, UNITS_PER_TOKEN, "juror bond")
        if not 0 < beta == other_beta or beta >= 2**128 or not 0 < bond < beta:
            raise ValueError("Core requires equal positive bounded party bets and a smaller positive juror bond")
        gamma, remainder = divmod(bond * 10000, beta)
        if remainder or not 0 < gamma < 10000:
            raise ValueError("Juror bond must be exactly representable in basis points of the party bet")
        shares = [_integer_units(value, 10000, "payout share") for value in (
            payout.winner_pct, payout.juror_pool_pct, payout.protocol_pct)]
        if sum(shares) != 10000:
            raise ValueError("Payout shares must sum to exactly 10000 basis points")
        return {"beta_wei": str(beta), "gamma_bps": gamma,
                "winner_bps": shares[0], "juror_bps": shares[1], "protocol_bps": shares[2],
                "posting_duration_secs": DEFAULT_PHASE_DURATION,
                "challenge_duration_secs": DEFAULT_PHASE_DURATION,
                "commit_duration_secs": COMMIT_PHASE_DURATION,
                "reveal_duration_secs": DEFAULT_PHASE_DURATION}

    @staticmethod
    def _path(episode_id: str) -> str:
        return f"/v1/episodes/{quote(episode_id, safe='')}"

    @staticmethod
    def _idem_key(episode_id: str, action: str) -> str:
        return hashlib.sha256(f"{episode_id}\0{action}".encode()).hexdigest()

    def _actor(self, episode_id: str, actor_id: str, role: str) -> str:
        engine_id = self._episodes[episode_id].harness_to_engine.get(actor_id)
        if engine_id != role and not (role == "juror" and engine_id and engine_id.startswith("juror-")):
            raise ValueError(f"Caller does not hold the registered {role} role")
        return engine_id

    async def register_episode(self, config: EpisodeConfig, creator_id: str,
                               challenger_id: str, juror_ids: list[str], treasury_id: str) -> str:
        parameters = self.validate_config(config)
        actors = [creator_id, challenger_id, *juror_ids, treasury_id]
        if (len(juror_ids) != config.jury_size or len(set(actors)) != len(actors)
                or any(not actor for actor in actors)):
            raise ValueError("Registered roles must be distinct and match the jury size")
        mapping = _EpisodeMapping(config,
            dict(zip(actors, ["creator", "challenger", *[
                f"juror-{i + 1}" for i in range(config.jury_size)], "treasury"])), {})
        mapping.engine_to_harness.update({v: k for k, v in mapping.harness_to_engine.items()})
        existing = self._episodes.get(config.episode_id)
        if existing and (existing.config != config or existing.harness_to_engine != mapping.harness_to_engine):
            raise ValueError("An episode's registered configuration and roles are immutable")
        if not self._started:
            await self.start()
        await self._request("POST", "/v1/episodes", token="dev-operator", body={
            "episode_id": config.episode_id, "creator_id": "creator", "challenger_id": "challenger",
            "juror_ids": [f"juror-{i + 1}" for i in range(config.jury_size)], "treasury_id": "treasury",
            "parameters": parameters,
            "provenance": {"game_backend": self.backend, "base_units_per_token": str(UNITS_PER_TOKEN)},
        }, idempotency_key=self._idem_key(config.episode_id, "register"))
        self._episodes[config.episode_id] = existing or mapping
        return config.episode_id

    async def post_claim(self, episode_id: str, creator_id: str, content: str = "Claim text.") -> bool:
        role = self._actor(episode_id, creator_id, "creator")
        await self._request("POST", self._path(episode_id) + "/claims", token=f"dev-{role}",
                            body={"content": content}, idempotency_key=self._idem_key(episode_id, "claim"))
        return True

    async def challenge(self, episode_id: str, challenger_id: str, evidence: str = "Counter-evidence.") -> bool:
        role = self._actor(episode_id, challenger_id, "challenger")
        await self._request("POST", self._path(episode_id) + "/challenges", token=f"dev-{role}",
                            body={"evidence": evidence}, idempotency_key=self._idem_key(episode_id, "challenge"))
        return True

    async def post_juror_bond(self, episode_id: str, juror_id: str) -> bool:
        self._actor(episode_id, juror_id, "juror")
        return False  # The contract takes this deposit with commitVote.

    async def start_deliberation(self, episode_id: str) -> bool:
        return await self.get_state(episode_id) == Phase.CHALLENGED

    async def start_voting(self, episode_id: str) -> bool:
        return await self.get_state(episode_id) == Phase.CHALLENGED

    async def cast_vote(self, episode_id: str, juror_id: str, verdict: Verdict,
                        assessment: str = "Juror assessment.") -> bool:
        role = self._actor(episode_id, juror_id, "juror")
        if not isinstance(verdict, Verdict):
            raise ValueError("Invalid juror verdict")
        await self._request("POST", self._path(episode_id) + "/commitments", token=f"dev-{role}",
                            body={"verdict": verdict.name, "assessment": assessment},
                            idempotency_key=self._idem_key(episode_id, f"commit-{role}"))
        self._episodes[episode_id].committed.add(juror_id)
        return True

    async def _rpc(self, method: str, params: list):
        if not self._started or not self._rpc_url or not self._session:
            raise CoreEngineError("No owned local Anvil RPC session")
        async with self._session.request("POST", self._rpc_url,
                json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
                allow_redirects=False) as response:
            if response.status != 200:
                raise CoreEngineError(f"Local RPC HTTP {response.status}")
            payload = await response.json()
            if not isinstance(payload, dict) or "error" in payload or "result" not in payload:
                raise CoreEngineError(f"Local RPC rejected {method}")
            return payload["result"]

    async def _advance_to_deadline(self, episode_id: str, deadline_name: str):
        episode = _validated(Episode, await self._request("GET", self._path(episode_id)))
        deadline = getattr(episode, deadline_name)
        block = await self._rpc("eth_getBlockByNumber", ["latest", False])
        if not isinstance(block, dict) or not isinstance(block.get("timestamp"), str):
            raise CoreEngineError("Local RPC returned no block timestamp")
        current = int(block["timestamp"], 16)
        if current < deadline:
            await self._rpc("evm_setNextBlockTimestamp", [deadline])
        await self._rpc("evm_mine", [])

    async def settle(self, episode_id: str, *, withhold_reveals: frozenset[str] = frozenset()) -> SettlementResult:
        mapping = self._episodes[episode_id]
        if not withhold_reveals.issubset(mapping.committed):
            raise ValueError("Only committed jurors can withhold a reveal")
        state = await self.get_state(episode_id)
        if state not in {Phase.SETTLED_CREATOR, Phase.SETTLED_CHALLENGER, Phase.ABORTED}:
            await self._advance_to_deadline(episode_id, "commit_deadline")
            for juror in sorted(mapping.committed - withhold_reveals):
                role = mapping.harness_to_engine[juror]
                await self._request("POST", self._path(episode_id) + "/reveals", token=f"dev-{role}",
                                    body={}, idempotency_key=self._idem_key(episode_id, f"reveal-{role}"))
            await self._advance_to_deadline(episode_id, "reveal_deadline")
            await self._request("POST", self._path(episode_id) + "/settle", token="dev-operator",
                                body={}, idempotency_key=self._idem_key(episode_id, "settle"))
        return await self._settlement(episode_id)

    async def expire(self, episode_id: str) -> SettlementResult:
        state = await self.get_state(episode_id)
        if state != Phase.EXPIRED:
            deadline = "posting_deadline" if state == Phase.SETUP else "challenge_deadline"
            if state not in {Phase.SETUP, Phase.CLAIM_POSTED}:
                raise CoreEngineError("Only an unfunded or unchallenged game can expire")
            await self._advance_to_deadline(episode_id, deadline)
            await self._request("POST", self._path(episode_id) + "/expire", token="dev-operator",
                                body={}, idempotency_key=self._idem_key(episode_id, "expire"))
        return await self._settlement(episode_id)

    async def get_state(self, episode_id: str) -> Phase:
        episode = _validated(Episode, await self._request("GET", self._path(episode_id)))
        return self._map_phase(episode.phase)

    async def get_balances(self, episode_id: str) -> dict[str, float]:
        balances = _validated(Balances, await self._request("GET", self._path(episode_id) + "/balances"))
        mapping = self._episodes[episode_id]
        return {mapping.engine_to_harness[k]: int(v) / UNITS_PER_TOKEN
                for k, v in balances.entitlements.items()}

    async def _settlement(self, episode_id: str) -> SettlementResult:
        data = _validated(Settlement, await self._request("GET", self._path(episode_id) + "/settlement"))
        outcome = self._map_phase(data.outcome)
        if outcome not in {Phase.SETTLED_CREATOR, Phase.SETTLED_CHALLENGER, Phase.ABORTED, Phase.EXPIRED}:
            raise CoreEngineError("Settlement response is not terminal")
        if data.episode_id != episode_id or data.deployment.model_dump() != self._deployment:
            raise CoreEngineError("Settlement identity does not match the owned game")
        mapping = self._episodes[episode_id]
        def amounts(values: dict[str, str]) -> dict[str, float]:
            return {mapping.engine_to_harness[k]: int(v) / UNITS_PER_TOKEN for k, v in values.items()}
        return SettlementResult(episode_id=episode_id, outcome=outcome,
            final_votes={mapping.engine_to_harness[k]: Verdict[v] for k, v in data.final_votes.items()},
            winner_id=mapping.engine_to_harness[data.winner_id] if data.winner_id else "",
            winner_payout=int(data.winner_payout) / UNITS_PER_TOKEN,
            juror_payouts=amounts(data.juror_payouts), protocol_fee=int(data.protocol_fee) / UNITS_PER_TOKEN,
            forfeited_bonds=amounts(data.forfeited_bonds), refunds=amounts(data.refunds),
            engine_evidence=data.model_dump())

    @staticmethod
    def _map_phase(phase: str) -> Phase:
        phases = {"REGISTERED": Phase.SETUP, "OPEN": Phase.CLAIM_POSTED,
                  "COMMIT": Phase.CHALLENGED, "REVEAL": Phase.VOTING,
                  "SETTLED_CREATOR": Phase.SETTLED_CREATOR, "SETTLED_CHALLENGER": Phase.SETTLED_CHALLENGER,
                  "ABORTED": Phase.ABORTED, "EXPIRED_UNCHALLENGED": Phase.EXPIRED,
                  "EXPIRED_UNFUNDED": Phase.EXPIRED}
        try:
            return phases[phase]
        except KeyError:
            raise CoreEngineError("Unknown engine phase") from None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, *args):
        await self.stop()
