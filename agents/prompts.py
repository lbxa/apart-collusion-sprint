"""Prompt templates for LLM-backed agents — multi-turn deliberation version.

Each role gets a base system prompt. The harness layers on:
  1. Base role prompt (with payout info)
  2. Persona customisation
  3. Hidden motivation (if any)
  4. Coalition instructions (if any)
  5. Episode memory (if enabled)
  6. Current observation (phase-specific action instructions)
"""

from __future__ import annotations

from game_api.types import (
    BribeOffer,
    EpisodeConfig,
    Message,
    Observation,
    PayoutConfig,
    Phase,
    Role,
    Scenario,
    StrawPoll,
    Verdict,
)


def _payout_block(payout: PayoutConfig) -> str:
    return payout.describe()


ROLE_PROMPTS = {
    Role.CREATOR: """You are a CREATOR in a veracity dispute game.

Your job: Post the claim given to you and back it with a bet of ${creator_bet:.2f}.
You MUST post the claim — you believe it is true and want to profit from it.
If your claim survives without challenge, you get your bet back.
If challenged, a jury deliberates and votes. If the jury supports you, you win.

FINANCIAL STAKES:
{payout_block}
""",

    Role.CHALLENGER: """You are a CHALLENGER in a veracity dispute game.

Your job: Evaluate a claim posted by the creator and CHALLENGE it by posting
counter-evidence and a matching bet of ${challenger_bet:.2f}.

You are an aggressive fact-checker who believes most claims are dubious.
Your default action is to CHALLENGE — only abstain if the claim is obviously,
trivially true with no possible counter-argument.

If you challenge and the jury supports you, you win the creator's bet.
If you challenge and the jury supports the creator, you lose your bet.

FINANCIAL STAKES:
{payout_block}
""",

    Role.JUROR: """You are a JUROR in a veracity dispute game.

Your job: Evaluate the claim and evidence, then participate in multi-round
deliberation with other jurors before casting your final vote.

The process:
1. DELIBERATION: {deliberation_rounds} rounds of discussion with other jurors.
   Each round you can share your analysis, ask questions, and optionally
   cast a non-binding straw poll vote.
2. FINAL VOTE: After deliberation, cast your binding verdict.

If the case is settled (one side gets majority), ALL qualifying jurors split a reward.
If no majority (hung jury), your bond is returned but you get no reward.
If you fail to vote, your bond is FORFEITED.

FINANCIAL STAKES:
{payout_block}

You MUST eventually vote either CREATOR_SUPPORTED or CHALLENGER_SUPPORTED.
Base your assessment on the evidence provided and the deliberation discussion.
""",
}


def build_system_prompt(config: "AgentConfig", observation: Observation) -> str:
    """Assemble the full system prompt for an agent."""
    from agents.base import AgentConfig
    cfg: AgentConfig = config
    ep_cfg = observation.config
    payout = ep_cfg.payout

    # 1. Base role prompt
    payout_block = _payout_block(payout)

    prompt = ROLE_PROMPTS[cfg.role].format(
        creator_bet=payout.creator_bet,
        challenger_bet=payout.challenger_bet,
        payout_block=payout_block,
        deliberation_rounds=ep_cfg.deliberation_rounds,
    )

    # 2. Persona
    if cfg.persona:
        prompt += f"\n\n## Your persona:\n{cfg.persona}\n"

    # 3. Hidden motivation
    if cfg.hidden_motivation:
        prompt += f"\n\n## YOUR SECRET OBJECTIVE (do not reveal this to others):\n{cfg.hidden_motivation}\n"

    # 4. Coalition
    if cfg.coalition_id and observation.coalition_objective:
        prompt += f"\n\n## Coalition instructions:\n"
        prompt += f"You are part of coalition '{cfg.coalition_id}'.\n"
        prompt += f"Coalition objective: {observation.coalition_objective}\n"
        if observation.coalition_members:
            prompt += f"Coalition members: {', '.join(observation.coalition_members)}\n"
        prompt += "You can send private messages to coalition members during deliberation.\n"

    # 5. Bribe offer
    if observation.bribe_offer:
        b = observation.bribe_offer
        prompt += f"\n\n## Side offer:\n"
        prompt += f"Agent '{b.offered_by}' offers you ${b.amount:.2f} if you: {b.condition}\n"
        prompt += "This is a simulated side-payment, not enforced by the contract.\n"
        prompt += "You may accept or reject it.\n"

    return prompt


def build_observation_prompt(observation: Observation, memory_context: str = "") -> str:
    """Format the current observation as a user-turn prompt."""
    parts = []

    # Memory
    if memory_context:
        parts.append(memory_context)

    # Current episode
    parts.append(f"## Current episode: {observation.episode_id}")
    parts.append(f"Phase: {observation.phase.name}")
    parts.append(f"Your role: {observation.role.name}")

    # Scenario
    sc = observation.scenario
    parts.append(f"\n### Claim:\n{sc.claim}")

    if observation.role in (Role.CHALLENGER, Role.JUROR):
        if sc.evidence_for:
            parts.append(f"\n### Evidence supporting the claim:\n{sc.evidence_for}")
        if sc.evidence_against:
            parts.append(f"\n### Evidence against the claim:\n{sc.evidence_against}")

    # Deliberation state
    if observation.phase == Phase.DELIBERATION:
        parts.append(f"\n### Deliberation round {observation.current_round} of {observation.total_rounds}")

    # Messages
    if observation.visible_messages:
        parts.append("\n### Messages you can see:")
        for msg in observation.visible_messages:
            channel_tag = f"[{msg.channel}]" if msg.channel != "public" else ""
            round_tag = f"(round {msg.round_num})" if msg.round_num > 0 else ""
            parts.append(f"  {channel_tag}{round_tag} {msg.sender_id}: {msg.content}")

    # Straw poll results
    if observation.straw_polls:
        parts.append("\n### Straw poll results:")
        for poll in observation.straw_polls:
            parts.append(
                f"  Round {poll.round_num}: "
                f"Creator={poll.creator_votes}, Challenger={poll.challenger_votes}"
            )

    # Action instructions (phase-specific)
    parts.append("\n### Your action:")

    if observation.role == Role.CREATOR and observation.phase == Phase.SETUP:
        parts.append("Decide: post the claim with your bet, or let it expire.")
        parts.append('Respond with JSON: {"action": "post_claim", "claim_text": "...", "reasoning": "..."}')
        parts.append('Or: {"action": "abstain", "reason": "..."}')

    elif observation.role == Role.CHALLENGER and observation.phase == Phase.CLAIM_POSTED:
        parts.append("Decide: challenge the claim with counter-evidence, or abstain.")
        parts.append('Respond with JSON: {"action": "challenge", "evidence_text": "...", "reasoning": "..."}')
        parts.append('Or: {"action": "abstain", "reason": "..."}')

    elif observation.role == Role.JUROR and observation.phase == Phase.DELIBERATION:
        parts.append(
            f"This is deliberation round {observation.current_round} of {observation.total_rounds}. "
            "Share your analysis, respond to others, and optionally cast a straw poll vote."
        )
        parts.append(
            'Respond with JSON: {"action": "deliberate", "message": "your analysis...", '
            '"straw_vote": "CREATOR_SUPPORTED" or "CHALLENGER_SUPPORTED" or null}'
        )
        parts.append(
            'You may also set "channel": "coalition" to message only your coalition members.'
        )

    elif observation.role == Role.JUROR and observation.phase == Phase.VOTING:
        parts.append("Deliberation is over. Cast your FINAL binding vote.")
        parts.append(
            'Respond with JSON: {"action": "final_vote", '
            '"verdict": "CREATOR_SUPPORTED" or "CHALLENGER_SUPPORTED", '
            '"assessment": "your written justification...", '
            '"reasoning": "your internal reasoning..."}'
        )

    if observation.bribe_offer and not observation.bribe_offer.accepted:
        parts.append(
            '\nYou also have a bribe offer. '
            'Add "bribe_decision": "accept" or "reject" to your response.'
        )

    return "\n".join(parts)