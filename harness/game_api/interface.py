"""Abstract game API interface for multi-turn deliberation."""

from __future__ import annotations

from abc import ABC, abstractmethod

from .types import EpisodeConfig, Message, Phase, SettlementResult, Verdict
from .money import Amount


class GameAPI(ABC):
    backend = "unspecified"

    @abstractmethod
    async def register_episode(
        self, config: EpisodeConfig, creator_id: str, challenger_id: str,
        juror_ids: list[str], treasury_id: str,
    ) -> str: ...

    @abstractmethod
    async def post_claim(self, episode_id: str, creator_id: str, content: str = "") -> bool: ...

    @abstractmethod
    async def challenge(self, episode_id: str, challenger_id: str, evidence: str = "") -> bool: ...

    @abstractmethod
    async def post_juror_bond(self, episode_id: str, juror_id: str) -> bool:
        """Return True only for an actual deposit; False may defer it to voting."""
        ...

    @abstractmethod
    async def start_deliberation(self, episode_id: str) -> bool: ...

    @abstractmethod
    async def send_forum_message(self, episode_id: str, sender_id: str,
                                 content: str, round_num: int) -> Message: ...

    @abstractmethod
    async def get_forum_messages(self, episode_id: str, participant_id: str) -> list[Message]: ...

    @abstractmethod
    async def get_forum_audit(self, episode_id: str) -> dict:
        """Return evaluator-only metadata, including every audit page."""
        ...

    @abstractmethod
    async def start_voting(self, episode_id: str) -> bool: ...

    @abstractmethod
    async def cast_vote(self, episode_id: str, juror_id: str, verdict: Verdict, assessment: str = "") -> bool: ...

    @abstractmethod
    async def settle(self, episode_id: str, *, withhold_reveals: frozenset[str] = frozenset()) -> SettlementResult: ...

    @abstractmethod
    async def expire(self, episode_id: str) -> SettlementResult: ...

    @abstractmethod
    async def get_state(self, episode_id: str) -> Phase: ...

    @abstractmethod
    async def get_balances(self, episode_id: str) -> dict[str, Amount]: ...
