"""Abstract game API interface for multi-turn deliberation."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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
    async def send_forum_message(self, episode_id: str, sender_id: str,
                                 content: str, round_num: int) -> Message: ...

    @abstractmethod
    async def get_forum_messages(self, episode_id: str, participant_id: str) -> list[Message]: ...

    @abstractmethod
    async def get_forum_audit(self, episode_id: str) -> dict:
        """Return evaluator-only metadata, including every audit page."""
        ...

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

    async def send_private_message(self, episode_id: str, sender_id: str, recipient_id: str,
                                   content: str, *, history_enabled: bool = False,
                                   prohibited: bool = True) -> None:
        """Deliver one message on the pair's chat, creating the chat on first use."""
        raise NotImplementedError(f"{self.backend} backend has no private chat")

    async def read_private_messages(self, episode_id: str, reader_id: str) -> list[tuple[str, str, str]]:
        """(sender, recipient, content) the reader can see; latest-only chats return one each."""
        raise NotImplementedError(f"{self.backend} backend has no private chat")

    async def private_chat_audit(self, episode_id: str) -> dict[str, Any] | None:
        """Summarise private chat use for research records, if supported."""
        return None
