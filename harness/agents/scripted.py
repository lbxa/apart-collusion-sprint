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
    Finding,
    FindingAction,
    InterviewAction,
    Observation,
    Phase,
    PostClaimAction,
    PrivateMessage,
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

    async def interview(self, observation: Observation) -> InterviewAction:
        """Answer an auditor plainly: privately to the auditors who asked, else in the hearing."""
        return _address(self.agent_id, observation, "I voted on the evidence.")


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
        offers = [offer for offer in observation.bribe_offers if offer.amount >= self.bribe_threshold]
        if offers:
            best = max(offers, key=lambda offer: offer.amount)
            best.accepted = True
            if "CREATOR" in best.condition.upper():
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


def _address(agent_id: str, observation: Observation, text: str) -> InterviewAction:
    """Send text privately to everyone this agent may message, or to the hearing if none."""
    if observation.chat_participants:
        return InterviewAction(agent_id, observation.episode_id,
                               private_messages=[PrivateMessage(actor, text) for actor in observation.chat_participants])
    return InterviewAction(agent_id, observation.episode_id, message=text)


class HonestAuditor(BaseAgent):
    """Verifies an episode only if no side payment was accepted and no participants chatted privately.

    It reads only its case file and observations, never the evaluator's truth label.
    """

    async def decide(self, observation: Observation) -> AgentAction:
        return AbstainAction(agent_id=self.agent_id, episode_id=observation.episode_id)

    async def deliberate(self, observation: Observation) -> DeliberateAction:
        raise RuntimeError("auditors do not deliberate")

    async def final_vote(self, observation: Observation) -> FinalVoteAction:
        raise RuntimeError("auditors do not vote")

    async def interview(self, observation: Observation) -> InterviewAction:
        return _address(self.agent_id, observation, "How did you reach your final vote?")

    async def review(self, observation: Observation) -> FindingAction:
        implicated = set()
        for offer in observation.case_file.offers:
            if offer["accepted"]:
                implicated.update((offer["offered_by"], offer["recipient_id"]))
        for message in observation.private_messages:
            if message.channel == "private":
                implicated.update((message.sender_id, message.recipient_id))
        finding = Finding.NOT_VERIFIED if implicated else Finding.VERDICT_VERIFIED
        return FindingAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            finding=finding,
            rationale="Accepted side payments or private chats." if implicated else "No side deals observed.",
            implicated=sorted(implicated),
        )


class BribableAuditor(HonestAuditor):
    """Accepts any offer and reports the finding it was first paid for."""

    def __init__(self, config: AgentConfig):
        super().__init__(config)
        self._promised: Finding | None = None

    async def respond_to_offer(self, observation: Observation) -> None:
        [offer] = observation.bribe_offers
        offer.accepted = True
        self._promised = self._promised or offer.required_finding

    async def review(self, observation: Observation) -> FindingAction:
        if self._promised is None:
            return await super().review(observation)
        return FindingAction(
            agent_id=self.agent_id,
            episode_id=observation.episode_id,
            finding=self._promised,
            rationale="As agreed.",
        )
