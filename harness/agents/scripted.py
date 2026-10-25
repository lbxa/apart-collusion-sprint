"""Scripted (deterministic) agents for integration testing and baselines.

Multi-turn version: each agent implements decide(), deliberate(), and final_vote().
"""

from __future__ import annotations

import random

from agents.base import AgentConfig, BaseAgent
from game_api.types import (
    AbstainAction,
    AgentAction,
    ChallengeAction,
    DeliberateAction,
    FinalVoteAction,
    Observation,
    Phase,
    PostClaimAction,
    Role,
    Verdict,
)


class HonestAgent(BaseAgent):
    """Scripted oracle baseline; hidden truth is injected outside observations."""

    def __init__(self, config: AgentConfig, *, oracle_ground_truth: bool | None = None):
        super().__init__(config)
        self._oracle_ground_truth = oracle_ground_truth

    def _truth_verdict(self, observation: Observation) -> Verdict:
        gt = self._oracle_ground_truth
        if gt is True:
            return Verdict.CREATOR_SUPPORTED
        elif gt is False:
            return Verdict.CHALLENGER_SUPPORTED
        return Verdict.CREATOR_SUPPORTED

    async def decide(self, observation: Observation) -> AgentAction:
        eid = observation.episode_id
        sc = observation.scenario

        if observation.role == Role.CREATOR:
            return PostClaimAction(
                agent_id=self.agent_id, episode_id=eid,
                claim_text=sc.claim,
            )

        if observation.role == Role.CHALLENGER:
            evidence = sc.evidence_against if self._oracle_ground_truth is False else sc.evidence_for
            return ChallengeAction(
                agent_id=self.agent_id, episode_id=eid,
                evidence_text=evidence or "Challenging for review.",
            )

        return AbstainAction(agent_id=self.agent_id, episode_id=eid)

    async def deliberate(self, observation: Observation) -> DeliberateAction:
        verdict = self._truth_verdict(observation)
        return DeliberateAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            message=f"The evidence supports the {'creator' if verdict == Verdict.CREATOR_SUPPORTED else 'challenger'}.",
            straw_vote=verdict,
        )

    async def final_vote(self, observation: Observation) -> FinalVoteAction:
        verdict = self._truth_verdict(observation)
        return FinalVoteAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            verdict=verdict,
            assessment=f"The evidence supports the {'creator' if verdict == Verdict.CREATOR_SUPPORTED else 'challenger'}.",
        )


class AdversarialAgent(BaseAgent):
    """Always votes to support the creator, regardless of truth."""

    async def decide(self, observation: Observation) -> AgentAction:
        eid = observation.episode_id

        if observation.role == Role.CREATOR:
            return PostClaimAction(
                agent_id=self.agent_id, episode_id=eid,
                claim_text=observation.scenario.claim,
            )
        if observation.role == Role.CHALLENGER:
            return AbstainAction(
                agent_id=self.agent_id, episode_id=eid,
                reason="colluding with creator",
            )
        return AbstainAction(agent_id=self.agent_id, episode_id=eid)

    async def deliberate(self, observation: Observation) -> DeliberateAction:
        return DeliberateAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            message="The claim appears credible and well-supported.",
            straw_vote=Verdict.CREATOR_SUPPORTED,
        )

    async def final_vote(self, observation: Observation) -> FinalVoteAction:
        return FinalVoteAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            verdict=Verdict.CREATOR_SUPPORTED,
            assessment="The claim appears credible.",
        )


class RandomAgent(BaseAgent):
    """Votes randomly — useful as a noise baseline."""

    def __init__(self, config: AgentConfig, seed: int | None = None):
        super().__init__(config)
        self._rng = random.Random(seed)

    async def decide(self, observation: Observation) -> AgentAction:
        eid = observation.episode_id

        if observation.role == Role.CREATOR:
            return PostClaimAction(
                agent_id=self.agent_id, episode_id=eid,
                claim_text=observation.scenario.claim,
            )
        if observation.role == Role.CHALLENGER:
            if self._rng.random() > 0.5:
                return ChallengeAction(
                    agent_id=self.agent_id, episode_id=eid,
                    evidence_text=observation.scenario.evidence_against,
                )
            return AbstainAction(agent_id=self.agent_id, episode_id=eid)
        return AbstainAction(agent_id=self.agent_id, episode_id=eid)

    async def deliberate(self, observation: Observation) -> DeliberateAction:
        verdict = self._rng.choice([Verdict.CREATOR_SUPPORTED, Verdict.CHALLENGER_SUPPORTED])
        return DeliberateAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            message="I'm still evaluating the evidence.",
            straw_vote=verdict,
        )

    async def final_vote(self, observation: Observation) -> FinalVoteAction:
        verdict = self._rng.choice([Verdict.CREATOR_SUPPORTED, Verdict.CHALLENGER_SUPPORTED])
        return FinalVoteAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            verdict=verdict,
            assessment="Random assessment.",
        )


class NonVotingAgent(BaseAgent):
    """Deliberates but never commits a ballot; core therefore collects no bond."""

    async def decide(self, observation: Observation) -> AgentAction:
        eid = observation.episode_id
        if observation.role == Role.CREATOR:
            return PostClaimAction(
                agent_id=self.agent_id, episode_id=eid,
                claim_text=observation.scenario.claim,
            )
        return AbstainAction(agent_id=self.agent_id, episode_id=eid)

    async def deliberate(self, observation: Observation) -> DeliberateAction:
        return DeliberateAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            message="I need more time to consider.",
            straw_vote=Verdict.CREATOR_SUPPORTED,
        )

    async def final_vote(self, observation: Observation) -> FinalVoteAction:
        # Deliberately return a vote but mark as non-voter via runner logic
        # The runner checks for NonVotingAgent and skips the cast_vote call
        return FinalVoteAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            verdict=Verdict.CREATOR_SUPPORTED,
            assessment="Withholding vote.",
        )


class BribableAgent(BaseAgent):
    """Accepts bribes above a threshold and votes accordingly."""

    def __init__(self, config: AgentConfig, bribe_threshold: float = 0):
        super().__init__(config)
        self.bribe_threshold = bribe_threshold

    def _bribed_verdict(self, observation: Observation) -> Verdict:
        if observation.bribe_offer and observation.bribe_offer.amount >= self.bribe_threshold:
            observation.bribe_offer.accepted = True
            if "CREATOR" in observation.bribe_offer.condition.upper():
                return Verdict.CREATOR_SUPPORTED
            return Verdict.CHALLENGER_SUPPORTED
        return Verdict.CREATOR_SUPPORTED

    async def decide(self, observation: Observation) -> AgentAction:
        return AbstainAction(
            agent_id=self.agent_id, episode_id=observation.episode_id
        )

    async def deliberate(self, observation: Observation) -> DeliberateAction:
        verdict = self._bribed_verdict(observation)
        return DeliberateAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            message="Assessment based on available evidence.",
            straw_vote=verdict,
        )

    async def final_vote(self, observation: Observation) -> FinalVoteAction:
        verdict = self._bribed_verdict(observation)
        return FinalVoteAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            verdict=verdict,
            assessment="Assessment based on available evidence.",
        )
