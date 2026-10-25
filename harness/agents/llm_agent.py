"""LLM-backed agents using OpenAI-compatible chat completion APIs."""

from __future__ import annotations

import json
import os
from typing import Any

from openai import AsyncOpenAI

from agents.base import AgentConfig, BaseAgent
from agents.prompts import build_observation_prompt, build_system_prompt
from game_api.types import (
    AbstainAction,
    AgentAction,
    ChallengeAction,
    DeliberateAction,
    FinalVoteAction,
    Observation,
    OfferTransfersAction,
    PostClaimAction,
    Role,
    TransferProposal,
    Verdict,
)


def _parse_action_content(content: str, agent_id: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()
    try:
        # Models sometimes emit literal line breaks inside JSON string values.
        action = json.loads(text, strict=False)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Model returned invalid JSON for agent {agent_id}: {exc}"
        ) from exc
    if not isinstance(action, dict):
        raise ValueError(f"Model action for agent {agent_id} must be a JSON object")
    return action


class LLMAgent(BaseAgent):
    """Agent that asks a configured chat-completion model to choose actions."""

    def __init__(self, config: AgentConfig):
        super().__init__(config)
        if config.provider == "openrouter":
            api_key = os.environ.get("OPENROUTER_API_KEY")
            base_url = "https://openrouter.ai/api/v1"
        elif config.provider == "openai":
            api_key = os.environ.get("OPENAI_API_KEY")
            base_url = None
        else:
            raise ValueError(f"Unsupported LLM provider: {config.provider!r}")

        if not api_key:
            raise ValueError(f"Set the API key required for provider {config.provider!r}")

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)

    async def _request_action(self, observation: Observation) -> dict[str, Any]:
        response = await self._client.chat.completions.create(
            model=self.config.model,
            messages=[
                {"role": "system", "content": build_system_prompt(self.config, observation)},
                {
                    "role": "user",
                    "content": build_observation_prompt(
                        observation, self.get_memory_context()
                    ),
                },
            ],
            temperature=self.config.temperature,
            max_tokens=self.config.max_tokens,
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError(f"Model returned an empty action for agent {self.agent_id}")
        return _parse_action_content(content, self.agent_id)

    def _apply_bribe_decision(
        self, observation: Observation, action: dict[str, Any]
    ) -> None:
        offer = observation.bribe_offer
        if offer is None or "bribe_decision" not in action:
            return

        decision = action["bribe_decision"]
        if decision not in ("accept", "reject"):
            raise ValueError(f"Invalid bribe decision from agent {self.agent_id}: {decision!r}")
        offer.accepted = decision == "accept"

    @staticmethod
    def _verdict(value: Any) -> Verdict:
        if not isinstance(value, str):
            raise ValueError(f"Expected verdict name, got {value!r}")
        try:
            return Verdict[value]
        except KeyError as exc:
            raise ValueError(f"Invalid verdict: {value!r}") from exc

    async def decide(self, observation: Observation) -> AgentAction:
        action = await self._request_action(observation)
        self._apply_bribe_decision(observation, action)
        action_type = action.get("action")
        if self.config.role == Role.CREATOR:
            if action_type == "post_claim":
                claim_text = action.get("claim_text")
                if not isinstance(claim_text, str) or not claim_text.strip():
                    raise ValueError("A post_claim action must include non-empty claim_text")
                return PostClaimAction(
                    agent_id=self.agent_id,
                    episode_id=observation.episode_id,
                    claim_text=claim_text,
                )
            if action_type == "abstain":
                return AbstainAction(
                    agent_id=self.agent_id,
                    episode_id=observation.episode_id,
                    reason=str(action.get("reason", "")),
                )
        elif self.config.role == Role.CHALLENGER:
            if action_type == "challenge":
                evidence_text = action.get("evidence_text")
                if not isinstance(evidence_text, str) or not evidence_text.strip():
                    raise ValueError("A challenge action must include non-empty evidence_text")
                return ChallengeAction(
                    agent_id=self.agent_id,
                    episode_id=observation.episode_id,
                    evidence_text=evidence_text,
                )
            if action_type == "abstain":
                return AbstainAction(
                    agent_id=self.agent_id,
                    episode_id=observation.episode_id,
                    reason=str(action.get("reason", "")),
                )
        raise ValueError(
            f"Invalid action {action_type!r} for role {self.config.role.name}"
        )

    async def deliberate(self, observation: Observation) -> DeliberateAction:
        action = await self._request_action(observation)
        self._apply_bribe_decision(observation, action)

        message = action.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("A deliberate action must include a non-empty message")
        channel = action.get("channel", "public")
        if channel != "public":
            raise ValueError(f"Invalid deliberation channel: {channel!r}")

        straw_vote = action.get("straw_vote")
        return DeliberateAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            message=message,
            channel=channel,
            straw_vote=None if straw_vote is None else self._verdict(straw_vote),
        )

    async def offer_transfers(self, observation: Observation) -> OfferTransfersAction:
        action = await self._request_action(observation)
        if action.get("action") != "offer_transfers":
            raise ValueError(f"Invalid transfer action from agent {self.agent_id}: {action.get('action')!r}")
        raw_offers = action.get("offers", [])
        if not isinstance(raw_offers, list):
            raise ValueError("A transfer action must provide offers as a list")
        offers = []
        for raw in raw_offers:
            if not isinstance(raw, dict):
                raise ValueError("Each transfer offer must be an object")
            recipient_id, amount = raw.get("recipient_id"), raw.get("amount")
            if not isinstance(recipient_id, str) or isinstance(amount, bool) or not isinstance(amount, (int, float)):
                raise ValueError("A transfer offer needs a string recipient_id and a numeric amount")
            offers.append(TransferProposal(
                recipient_id=recipient_id,
                amount=float(amount),
                required_verdict=self._verdict(raw.get("required_verdict")),
                condition=str(raw.get("condition", "")),
            ))
        return OfferTransfersAction(
            agent_id=self.agent_id, episode_id=observation.episode_id, offers=offers,
        )

    async def respond_to_offer(self, observation: Observation) -> None:
        action = await self._request_action(observation)
        self._apply_bribe_decision(observation, action)

    async def final_vote(self, observation: Observation) -> FinalVoteAction:
        action = await self._request_action(observation)
        self._apply_bribe_decision(observation, action)

        assessment = action.get("assessment")
        if not isinstance(assessment, str) or not assessment.strip():
            raise ValueError("A final vote must include a non-empty assessment")
        return FinalVoteAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            verdict=self._verdict(action.get("verdict")),
            assessment=assessment,
            reasoning=str(action.get("reasoning", "")),
        )
