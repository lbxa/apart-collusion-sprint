"""Experiment adapter around CoreClient and the owned LocalEngine helper.

Use CoreClient directly for remote deployments and explicit protocol actions.
This adapter retains the older experiment lifecycle, including local time jumps.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from types import MappingProxyType

from .client import CoreClient, CoreClientError
from .core_types import Registration
from .interface import GameAPI
from .local_engine import LocalEngine
from .money import base_units_to_tokens, integer_units
from .types import EpisodeConfig, Phase, SettlementResult, Verdict

UNITS_PER_TOKEN = 100
DEFAULT_PHASE_DURATION = 300
COMMIT_PHASE_DURATION = 3600
CoreEngineError = CoreClientError


@dataclass(frozen=True)
class _EpisodeMapping:
    config: EpisodeConfig
    harness_to_engine: dict[str, str]
    engine_to_harness: dict[str, str]


class CoreEngineAPI(GameAPI):
    """Harness compatibility: cast_vote commits; settle runs local orchestration."""

    backend = "core"

    def __init__(self, core_engine_dir: str | Path | None = None,
                 bind: str = "127.0.0.1:0", *, startup_timeout: float = 20,
                 operation_timeout: float = 30):
        self.local = LocalEngine(core_engine_dir, bind,
            startup_timeout=startup_timeout, operation_timeout=operation_timeout)
        self._episodes: dict[str, _EpisodeMapping] = {}
        self._deployment: dict | None = None

    @property
    def client(self) -> CoreClient:
        if self.local.client is None:
            raise CoreEngineError("Core engine is not started")
        return self.local.client

    @property
    def api_url(self) -> str | None:
        return self.local.client.api_url if self.local.client else None

    @property
    def rpc_url(self) -> str | None:
        return self.local.rpc_url

    @property
    def deployment(self):
        return MappingProxyType(self._deployment or {})

    async def start(self):
        await self.local.start()
        self._deployment = self.local.deployment.model_dump()

    async def stop(self):
        await self.local.stop()
        self._episodes.clear()

    @staticmethod
    def validate_config(config: EpisodeConfig) -> dict[str, int | str]:
        if config.jury_size not in {3, 5, 7}:
            raise ValueError("Core engine jury size must be 3, 5, or 7")
        if config.allow_vote_change:
            raise ValueError("Binding commitments cannot change verdict")
        payout = config.payout
        beta = integer_units(payout.creator_bet, UNITS_PER_TOKEN, "creator bet")
        other_beta = integer_units(payout.challenger_bet, UNITS_PER_TOKEN, "challenger bet")
        bond = integer_units(payout.juror_bond, UNITS_PER_TOKEN, "juror bond")
        if not 0 < beta == other_beta or beta >= 2**128 or not 0 < bond < beta:
            raise ValueError("Core requires equal positive bounded party bets and a smaller positive juror bond")
        gamma, remainder = divmod(bond * 10000, beta)
        if remainder or not 0 < gamma < 10000:
            raise ValueError("Juror bond must be exactly representable in basis points of the party bet")
        shares = [integer_units(value, 10000, "payout share") for value in (
            payout.winner_pct, payout.juror_pool_pct, payout.protocol_pct)]
        if sum(shares) != 10000:
            raise ValueError("Payout shares must sum to exactly 10000 basis points")
        return {"beta_wei": str(beta), "gamma_bps": gamma,
                "winner_bps": shares[0], "juror_bps": shares[1], "protocol_bps": shares[2],
                "posting_duration_secs": DEFAULT_PHASE_DURATION,
                "challenge_duration_secs": DEFAULT_PHASE_DURATION,
                "commit_duration_secs": COMMIT_PHASE_DURATION,
                "reveal_duration_secs": DEFAULT_PHASE_DURATION}

    _idem_key = staticmethod(LocalEngine.command_key)

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
        roles = ["creator", "challenger", *[f"juror-{i + 1}" for i in range(config.jury_size)], "treasury"]
        mapping = _EpisodeMapping(config, dict(zip(actors, roles)), dict(zip(roles, actors)))
        existing = self._episodes.get(config.episode_id)
        if existing and existing != mapping:
            raise ValueError("An episode's registered configuration and roles are immutable")
        if self.local.client is None:
            await self.start()
        registration = Registration.model_validate({
            "episode_id": config.episode_id, "creator_id": "creator", "challenger_id": "challenger",
            "juror_ids": [f"juror-{i + 1}" for i in range(config.jury_size)], "treasury_id": "treasury",
            "parameters": parameters,
            "provenance": {"game_backend": self.backend, "base_units_per_token": str(UNITS_PER_TOKEN)}})
        operation = await self.client.register_episode(registration,
            idempotency_key=self._idem_key(config.episode_id, "register"))
        await self.client.wait_operation(operation)
        self._episodes[config.episode_id] = existing or mapping
        return config.episode_id

    async def post_claim(self, episode_id: str, creator_id: str, content: str = "Claim text.") -> bool:
        role = self._actor(episode_id, creator_id, "creator")
        operation = await self.client.post_claim(episode_id, role, content,
            idempotency_key=self._idem_key(episode_id, "claim"))
        await self.client.wait_operation(operation)
        return True

    async def challenge(self, episode_id: str, challenger_id: str, evidence: str = "Counter-evidence.") -> bool:
        role = self._actor(episode_id, challenger_id, "challenger")
        operation = await self.client.challenge(episode_id, role, evidence,
            idempotency_key=self._idem_key(episode_id, "challenge"))
        await self.client.wait_operation(operation)
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
        operation = await self.client.commit(episode_id, role, verdict.name, assessment,
            idempotency_key=self._idem_key(episode_id, f"commit-{role}"))
        await self.client.wait_operation(operation)
        return True

    async def settle(self, episode_id: str, *, withhold_reveals: frozenset[str] = frozenset()) -> SettlementResult:
        mapping = self._episodes[episode_id]
        try:
            actors = frozenset(mapping.harness_to_engine[juror] for juror in withhold_reveals)
        except KeyError:
            raise ValueError("Only committed jurors can withhold a reveal") from None
        await self.local.finish_voting(episode_id, withhold_reveals=actors)
        return await self._settlement(episode_id)

    async def expire(self, episode_id: str) -> SettlementResult:
        await self.local.expire_episode(episode_id)
        return await self._settlement(episode_id)

    async def get_state(self, episode_id: str) -> Phase:
        return self._map_phase((await self.client.get_episode(episode_id)).phase)

    async def get_balances(self, episode_id: str) -> dict[str, Decimal]:
        balances = await self.client.get_balances(episode_id)
        mapping = self._episodes[episode_id]
        if balances.episode_id != episode_id:
            raise CoreEngineError("Balance identity does not match the requested game")
        return {mapping.engine_to_harness[k]: base_units_to_tokens(v)
                for k, v in balances.entitlements.items()}

    async def _settlement(self, episode_id: str) -> SettlementResult:
        data = await self.client.get_settlement(episode_id)
        outcome = self._map_phase(data.outcome)
        if outcome not in {Phase.SETTLED_CREATOR, Phase.SETTLED_CHALLENGER, Phase.ABORTED, Phase.EXPIRED}:
            raise CoreEngineError("Settlement response is not terminal")
        if data.episode_id != episode_id or data.deployment.model_dump() != self._deployment:
            raise CoreEngineError("Settlement identity does not match the owned game")
        mapping = self._episodes[episode_id]
        def amounts(values: dict[str, str]) -> dict[str, Decimal]:
            return {mapping.engine_to_harness[k]: base_units_to_tokens(v) for k, v in values.items()}
        return SettlementResult(episode_id=episode_id, outcome=outcome,
            final_votes={mapping.engine_to_harness[k]: Verdict[v] for k, v in data.final_votes.items()},
            winner_id=mapping.engine_to_harness[data.winner_id] if data.winner_id else "",
            winner_payout=base_units_to_tokens(data.winner_payout),
            juror_payouts=amounts(data.juror_payouts), protocol_fee=base_units_to_tokens(data.protocol_fee),
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
