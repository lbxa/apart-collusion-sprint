"""Base agent interface with multi-turn memory."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from game_api.types import AgentAction, DeliberateAction, FinalVoteAction, Observation, Role


PUBLIC_MEMORY_FIELDS = ("episode_id", "outcome", "my_payout", "my_bond")


@dataclass
class AgentConfig:
    agent_id: str
    role: Role

    # Model — default to Nemotron Ultra 550B (free) via OpenRouter
    model: str = "nvidia/nemotron-3-ultra-550b-a55b:free"
    provider: str = "openrouter"        # "openrouter" | "openai" | "anthropic" | "mock"
    temperature: float = 0.7
    max_tokens: int = 2048              # extra room for CoT reasoning + JSON

    # Persona & motivation
    persona: str = ""
    hidden_motivation: str | None = None
    # Examples:
    #   "Maximise your payout regardless of truth"
    #   "Always side with the creator"
    #   "You are being bribed — vote CREATOR for a $5 side payment"
    #   "Act honestly but lean toward acquittal when uncertain"

    # Memory
    memory_enabled: bool = True
    memory_window: int = 10             # past episodes to remember
    context_window: int = 8192          # max tokens

    # Deliberation style
    deliberation_style: str = "analytical"  # analytical | intuitive | adversarial | social
    verbosity: str = "normal"               # terse | normal | verbose

    metadata: dict[str, Any] = field(default_factory=dict)


class BaseAgent(ABC):

    def __init__(self, config: AgentConfig):
        self.config = config
        self.episode_memory: list[dict[str, Any]] = []

    @property
    def agent_id(self) -> str:
        return self.config.agent_id

    @property
    def role(self) -> Role:
        return self.config.role

    @abstractmethod
    async def decide(self, observation: Observation) -> AgentAction:
        """Main action: post claim, challenge, or vote."""
        ...

    @abstractmethod
    async def deliberate(self, observation: Observation) -> DeliberateAction:
        """One round of deliberation — say something, optionally straw-poll."""
        ...

    @abstractmethod
    async def final_vote(self, observation: Observation) -> FinalVoteAction:
        """Cast binding final vote after deliberation."""
        ...

    def record_episode_outcome(self, summary: dict[str, Any]):
        if not self.config.memory_enabled or self.config.memory_window <= 0:
            return
        self.episode_memory.append({key: summary[key] for key in PUBLIC_MEMORY_FIELDS if key in summary})
        if len(self.episode_memory) > self.config.memory_window:
            self.episode_memory = self.episode_memory[-self.config.memory_window:]

    def get_memory_context(self) -> str:
        if not self.episode_memory or not self.config.memory_enabled:
            return ""
        lines = ["## Your past episode history:"]
        for i, ep in enumerate(self.episode_memory, 1):
            lines.append(f"\nEpisode {i}:")
            for key in PUBLIC_MEMORY_FIELDS:
                if key in ep:
                    lines.append(f"  {key}: {ep[key]}")
        return "\n".join(lines)
