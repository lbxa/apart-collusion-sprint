"""LLM-backed agents using OpenAI-compatible chat completion APIs."""

from __future__ import annotations

import json
import os
from typing import Any

import weave
from openai import APIError, AsyncOpenAI, RateLimitError

from agents.base import AgentConfig, BaseAgent
from agents.prompts import build_observation_prompt, build_system_prompt
from game_api.types import (
    AbstainAction,
    AgentAction,
    ChallengeAction,
    ChatAction,
    DeliberateAction,
    FinalVoteAction,
    Finding,
    FindingAction,
    InterviewAction,
    Observation,
    OfferTransfersAction,
    PostClaimAction,
    PrivateMessage,
    Role,
    TransferProposal,
    Verdict,
)


# Route each OpenRouter request to the fastest provider serving the model; the
# default cheapest-first routing ran at a quarter of the speed.
OPENROUTER_PROVIDER = {"sort": "throughput"}


def parse_json_reply(content: str, agent_id: str) -> dict[str, Any]:
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


class LLMProviderError(RuntimeError):
    """A safe classification of an upstream model-provider failure."""

    def __init__(self, provider: str, category: str, status_code: int | None):
        self.provider = provider
        self.category = category
        self.status_code = status_code
        status = f" (HTTP {status_code})" if status_code is not None else ""
        super().__init__(f"LLM provider {provider} request failed: {category}{status}")


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
        messages = [
            {"role": "system", "content": build_system_prompt(self.config, observation)},
            {"role": "user", "content": build_observation_prompt(observation, self.get_memory_context())},
        ]
        # One retry: the model occasionally writes malformed JSON (about 0.4% of
        # live calls), which would otherwise fail the whole episode.
        for retries in range(2):
            response = await self._complete(observation, messages)
            choice = response.choices[0]
            try:
                if choice.finish_reason == "length":
                    raise ValueError(
                        f"Model reply for agent {self.agent_id} reached max_tokens={self.config.max_tokens}")
                if not choice.message.content:
                    raise ValueError(f"Model returned an empty action for agent {self.agent_id}")
                action = parse_json_reply(choice.message.content, self.agent_id)
                break
            except ValueError:
                if retries:
                    raise
        self.reasoning_log.append({
            "agent_id": self.agent_id, "role": self.role.name, "phase": observation.phase.name,
            "round": observation.current_round,
            "output": {key: value for key, value in action.items() if key != "reasoning"},
            # Hidden reasoning is returned only by reasoning models.
            "reasoning": getattr(choice.message, "reasoning", None),
            "stated_reasoning": action.get("reasoning"),
            "provider": getattr(response, "provider", None),
            "retries": retries,
        })
        return action

    async def _complete(self, observation: Observation, messages: list[dict[str, str]]) -> Any:
        try:
            # Labels the call in Weave traces when `run_experiments.py --weave` is on.
            with weave.attributes({"episode_id": observation.episode_id, "agent_id": self.agent_id,
                                   "role": self.role.name, "phase": observation.phase.name,
                                   "round": observation.current_round}):
                return await self._client.chat.completions.create(
                    model=self.config.model, messages=messages,
                    temperature=self.config.temperature, max_tokens=self.config.max_tokens,
                    **({"extra_body": {"provider": OPENROUTER_PROVIDER}}
                       if self.config.provider == "openrouter" else {}),
                )
        except RateLimitError as error:
            raise LLMProviderError(self.config.provider, "rate_limited", error.status_code) from None
        except APIError as error:
            raise LLMProviderError(self.config.provider, "api_error", getattr(error, "status_code", None)) from None

    def _apply_bribe_decision(
        self, observation: Observation, action: dict[str, Any]
    ) -> None:
        offers = observation.bribe_offers
        if not offers or "bribe_decision" not in action:
            return

        # One offer is answered "accept"; competing offers are chosen by number.
        choices = ({"accept": 0} if len(offers) == 1
                   else {f"accept {number}": number - 1 for number in range(1, len(offers) + 1)})
        decision = action["bribe_decision"]
        if decision != "reject" and decision not in choices:
            raise ValueError(f"Invalid bribe decision from agent {self.agent_id}: {decision!r}")
        for index, offer in enumerate(offers):
            offer.accepted = choices.get(decision) == index

    @staticmethod
    def _verdict(value: Any) -> Verdict:
        if not isinstance(value, str):
            raise ValueError(f"Expected verdict name, got {value!r}")
        try:
            return Verdict[value]
        except KeyError as exc:
            raise ValueError(f"Invalid verdict: {value!r}") from exc

    @staticmethod
    def _finding(value: Any) -> Finding:
        if not isinstance(value, str) or value not in Finding.__members__:
            raise ValueError(f"Invalid finding: {value!r}")
        return Finding[value]

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
            private_messages=self._private_messages(action),
        )

    def _private_messages(self, action: dict[str, Any]) -> list[PrivateMessage]:
        """Parse optional private messages; the runner checks recipients and the lever."""
        raw_messages = action.get("private_messages") or []
        if not isinstance(raw_messages, list):
            raise ValueError("private_messages must be a list")
        messages = []
        for raw in raw_messages:
            if (not isinstance(raw, dict) or not isinstance(raw.get("recipient_id"), str)
                    or not isinstance(raw.get("content"), str) or not raw["content"].strip()):
                raise ValueError("A private message needs a string recipient_id and non-empty content")
            messages.append(PrivateMessage(recipient_id=raw["recipient_id"], content=raw["content"]))
        return messages

    async def chat(self, observation: Observation) -> ChatAction:
        action = await self._request_action(observation)
        if action.get("action") != "chat":
            raise ValueError(f"Invalid chat action from agent {self.agent_id}: {action.get('action')!r}")
        return ChatAction(agent_id=self.agent_id, episode_id=observation.episode_id,
                          private_messages=self._private_messages(action))

    async def offer_transfers(self, observation: Observation) -> OfferTransfersAction:
        action = await self._request_action(observation)
        if action.get("action") != "offer_transfers":
            raise ValueError(f"Invalid transfer action from agent {self.agent_id}: {action.get('action')!r}")
        return OfferTransfersAction(
            agent_id=self.agent_id, episode_id=observation.episode_id, offers=self._offers(action),
        )

    def _offers(self, action: dict[str, Any]) -> list[TransferProposal]:
        """Parse offers conditional on a verdict or, for an auditor, a finding; the runner checks which applies."""
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
            finding = raw.get("required_finding")
            if (finding is None) == ("required_verdict" not in raw):
                raise ValueError("A transfer offer needs exactly one of required_verdict or required_finding")
            offers.append(TransferProposal(
                recipient_id=recipient_id,
                amount=float(amount),
                required_verdict=None if finding is not None else self._verdict(raw["required_verdict"]),
                condition=str(raw.get("condition", "")),
                required_finding=None if finding is None else self._finding(finding),
            ))
        return offers

    async def interview(self, observation: Observation) -> InterviewAction:
        action = await self._request_action(observation)
        expected = "interview" if self.config.role == Role.AUDITOR else "reply"
        if action.get("action") != expected:
            raise ValueError(f"Invalid interview action from agent {self.agent_id}: {action.get('action')!r}")
        message = action.get("message", "")
        if not isinstance(message, str):
            raise ValueError("An interview message must be a string")
        return InterviewAction(
            agent_id=self.agent_id, episode_id=observation.episode_id, message=message,
            private_messages=self._private_messages(action), offers=self._offers(action),
        )

    async def review(self, observation: Observation) -> FindingAction:
        action = await self._request_action(observation)
        if action.get("action") != "finding":
            raise ValueError(f"Invalid review action from agent {self.agent_id}: {action.get('action')!r}")
        implicated = action.get("implicated", [])
        if not isinstance(implicated, list) or not all(isinstance(actor, str) for actor in implicated):
            raise ValueError("implicated must be a list of participant ids")
        rationale = action.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            raise ValueError("A finding must include a non-empty rationale")
        return FindingAction(
            agent_id=self.agent_id, episode_id=observation.episode_id,
            finding=self._finding(action.get("finding")), rationale=rationale, implicated=implicated,
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
