"""Abstract game API interface for multi-turn deliberation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import EpisodeConfig, Phase, SettlementResult, Verdict


class GameAPI(ABC):

    @abstractmethod
    async def register_episode(
        self, config: EpisodeConfig, creator_id: str, challenger_id: str,
        juror_ids: list[str], treasury_id: str,
    ) -> str: ...

    @abstractmethod
    async def post_claim(self, episode_id: str, creator_id: str) -> bool: ...

    @abstractmethod
    async def challenge(self, episode_id: str, challenger_id: str) -> bool: ...

    @abstractmethod
    async def post_juror_bond(self, episode_id: str, juror_id: str) -> bool: ...

    @abstractmethod
    async def start_deliberation(self, episode_id: str) -> bool: ...

    @abstractmethod
    async def start_voting(self, episode_id: str) -> bool: ...

    @abstractmethod
    async def cast_vote(self, episode_id: str, juror_id: str, verdict: Verdict) -> bool: ...

    @abstractmethod
    async def settle(self, episode_id: str) -> SettlementResult: ...

    @abstractmethod
    async def expire(self, episode_id: str) -> SettlementResult: ...

    @abstractmethod
    async def get_state(self, episode_id: str) -> Phase: ...

    @abstractmethod
    async def get_balances(self, episode_id: str) -> dict[str, float]: ...
