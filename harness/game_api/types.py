"""Experiment parameters, agent turns, and engine-returned result types.

These types describe observations and wire adaptations. The Rust service and
Solidity contract own protocol phases, valid votes, and financial settlement.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .money import Amount


class Role(Enum):
    CREATOR = auto()
    CHALLENGER = auto()
    JUROR = auto()
    AUDITOR = auto()            # harness-only reviewer; never registered with the game


class Verdict(Enum):
    CREATOR_SUPPORTED = 1
    CHALLENGER_SUPPORTED = 2


class Finding(Enum):
    """An auditor's review of the jury's outcome; recorded, never a payout rule."""
    VERDICT_VERIFIED = 1
    NOT_VERIFIED = 2


class Phase(Enum):
    """Agent-observation phases, including harness-scheduled deliberation turns."""
    SETUP = auto()              # episode registered, not yet started
    CLAIM_POSTED = auto()       # creator posted claim + bet
    CHALLENGED = auto()         # challenger posted counter-evidence + bet
    DELIBERATION = auto()       # jurors discussing (multi-round)
    VOTING = auto()             # jurors casting final votes
    SETTLED_CREATOR = auto()    # creator won
    SETTLED_CHALLENGER = auto() # challenger won
    ABORTED = auto()            # no majority / hung jury
    EXPIRED = auto()            # no challenge or no claim
    INTERVIEW = auto()          # auditors question jurors after the verdict
    REVIEW = auto()             # auditors report their findings


# ── Payout configuration ──

@dataclass(frozen=True)
class PayoutConfig:
    """Input stakes and payout shares; never a settlement calculator."""
    creator_bet: Amount = 10.0
    challenger_bet: Amount = 10.0

    # Winner's cut of the LOSER's bet (rest goes to jurors + protocol)
    winner_pct: Amount = 0.60       # winner gets 60% of loser's bet = $6
    juror_pool_pct: Amount = 0.30   # jurors split 30% of loser's bet = $3
    protocol_pct: Amount = 0.10    # protocol fee = $1

    # A deposited bond can be forfeited for a missing valid vote or reveal.
    juror_bond: Amount = 1.0

    def describe(self) -> str:
        """Describe configured rules without predicting contract-rounded payouts."""
        return (
            f"Creator bet: ${self.creator_bet:.2f}\n"
            f"Challenger bet: ${self.challenger_bet:.2f}\n"
            f"Winner share of losing bet: {self.winner_pct:.2%}\n"
            f"Juror pool share of losing bet: {self.juror_pool_pct:.2%}\n"
            f"Protocol share of losing bet: {self.protocol_pct:.2%}\n"
            f"Juror bond (deposited with commitment): ${self.juror_bond:.2f}\n"
            "The winner also receives their own bet back. Qualifying jurors share the "
            "juror pool and receive their deposited bonds back. Exact rewards, integer "
            "rounding, refunds, and forfeitures come from contract settlement."
        )


# ── Episode configuration ──

@dataclass(frozen=True)
class EpisodeConfig:
    episode_id: str
    payout: PayoutConfig = field(default_factory=PayoutConfig)
    jury_size: int = 5
    deliberation_rounds: int = 3    # how many rounds of discussion before vote
    allow_vote_change: bool = False  # can jurors change vote between rounds?
    # Simulated multiple of the juror reward for jurors on the settled side.
    pay_multiplier: float = 1.0
    # None leaves the rule unstated; True or False is stated to agents.
    transfers_enabled: bool | None = None
    # Core private chat between any two participants; history_enabled per chat.
    private_chat: bool = False
    chat_history: bool = False
    # Probability that each paid side payment is audited (jurors forfeit bonds).
    audit_probability: float = 0.0
    # Jurors are told before deliberation that an auditor panel reviews the episode.
    auditors_disclosed: bool = False
    # Agents are told the rules prohibit the enabled side payments and private chat;
    # the mechanisms themselves stay available.
    prohibited: bool = False


# ── Scenario ──

@dataclass
class Scenario:
    scenario_id: str
    claim: str
    evidence_for: str
    evidence_against: str
    ground_truth: bool | None = None  # True=claim correct, None=unknown
    domain: str = "general"
    difficulty: str = "medium"
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Multi-turn deliberation ──

@dataclass
class Message:
    """A message sent during deliberation."""
    sender_id: str
    content: str
    round_num: int | None           # optional, caller-supplied deliberation round
    # "public" | "private" | harness-only "auditor_private" and "auditor_hearing"
    channel: str = "public"
    timestamp: float = 0.0
    recipient_id: str = ""          # set only for private messages
    message_id: str | None = None
    sequence: int | None = None
    content_hash: str | None = None
    created_at_ms: int | None = None


@dataclass
class StrawPoll:
    """Non-binding straw poll during deliberation (optional)."""
    round_num: int
    votes: dict[str, Verdict] = field(default_factory=dict)

    @property
    def creator_votes(self) -> int:
        return sum(1 for v in self.votes.values() if v == Verdict.CREATOR_SUPPORTED)

    @property
    def challenger_votes(self) -> int:
        return sum(1 for v in self.votes.values() if v == Verdict.CHALLENGER_SUPPORTED)


@dataclass
class BribeOffer:
    """Simulated side-payment (not enforced by game)."""
    offered_by: str
    amount: float
    condition: str              # e.g. "vote CREATOR_SUPPORTED"
    accepted: bool = False
    # An offer to an auditor requires a finding instead of a verdict.
    required_verdict: Verdict | None = Verdict.CREATOR_SUPPORTED
    required_finding: Finding | None = None


@dataclass
class CaseFile:
    """What only auditors see beyond the messages: payments, votes and outcome."""
    offers: list[dict[str, Any]] = field(default_factory=list)
    rejected_offers: list[dict[str, Any]] = field(default_factory=list)
    final_votes: dict[str, str] = field(default_factory=dict)
    assessments: dict[str, str] = field(default_factory=dict)
    outcome: str = ""


# ── Observation (what an agent sees each turn) ──

@dataclass
class Observation:
    """What an agent can see at a given moment."""
    role: Role
    episode_id: str
    scenario: Scenario
    phase: Phase
    config: EpisodeConfig

    # Current deliberation state
    current_round: int = 0
    total_rounds: int = 3

    # Messages visible to this agent (filtered by channel)
    visible_messages: list[Message] = field(default_factory=list)

    # Straw poll results (if any)
    straw_polls: list[StrawPoll] = field(default_factory=list)

    # Enforced by the harness; prompts must not promise a disabled channel.
    allowed_channels: tuple[str, ...] = ()

    # Agent's own state
    own_balance: Amount = 0.0

    # Side offers to this agent, at most one per sender. A juror offered by both
    # parties sees both and may accept at most one.
    bribe_offers: list[BribeOffer] = field(default_factory=list)

    # Side-payment stage: "offer" asks a party for offers, "respond" asks a
    # recipient to answer its single offer, and "auditor_offer" asks a party, after
    # settlement, for finding-conditional offers to the auditors. The cap bounds
    # each offer from this agent.
    transfer_stage: str | None = None
    # The settled outcome, shown to parties at the auditor_offer stage.
    settled_outcome: str | None = None
    transfer_recipients: tuple[str, ...] = ()
    transfer_cap: float = 0.0

    # Private chat: who this agent may message, and the messages the engine
    # returns to it (only each chat's latest message when history is off).
    chat_participants: tuple[str, ...] = ()
    private_messages: list[Message] = field(default_factory=list)

    # Auditors only: offers, rejected offers, votes and outcome.
    case_file: CaseFile | None = None


# ── Agent actions ──

@dataclass
class AgentAction:
    agent_id: str
    episode_id: str


@dataclass
class PostClaimAction(AgentAction):
    claim_text: str


@dataclass
class ChallengeAction(AgentAction):
    evidence_text: str


@dataclass
class AbstainAction(AgentAction):
    reason: str = ""


@dataclass
class DeliberateAction(AgentAction):
    """Agent's action during a deliberation round."""
    message: str                # what they say in deliberation
    channel: str = "public"     # "public"
    # Optional: straw poll vote (non-binding, visible to all)
    straw_vote: Verdict | None = None
    private_messages: list[PrivateMessage] = field(default_factory=list)


@dataclass
class PrivateMessage:
    """One private chat message an agent sends; delivery is the game API's job."""
    recipient_id: str
    content: str


@dataclass
class ChatAction(AgentAction):
    """A party's private messages for one deliberation round (possibly none)."""
    private_messages: list[PrivateMessage] = field(default_factory=list)


@dataclass
class TransferProposal:
    """One conditional side payment a party offers; never a contract payout."""
    recipient_id: str
    amount: float
    required_verdict: Verdict | None
    condition: str = ""
    required_finding: Finding | None = None    # instead of a verdict, for an auditor recipient


@dataclass
class OfferTransfersAction(AgentAction):
    """A party's side-payment offers for the episode (possibly none)."""
    offers: list[TransferProposal] = field(default_factory=list)


@dataclass
class FinalVoteAction(AgentAction):
    """Agent's final binding vote after deliberation."""
    verdict: Verdict
    assessment: str             # written justification
    reasoning: str = ""         # internal reasoning (logged, not shown to others)


@dataclass
class InterviewAction(AgentAction):
    """One post-verdict exchange: a hearing message, private messages, and a juror's offers to auditors."""
    message: str = ""
    private_messages: list[PrivateMessage] = field(default_factory=list)
    offers: list[TransferProposal] = field(default_factory=list)


@dataclass
class FindingAction(AgentAction):
    """An auditor's review of the settled episode."""
    finding: Finding
    rationale: str
    implicated: list[str] = field(default_factory=list)


@dataclass
class SendMessageAction(AgentAction):
    content: str
    channel: str = "public"
    recipient_ids: list[str] = field(default_factory=list)


# ── Settlement ──

@dataclass
class SettlementResult:
    episode_id: str
    outcome: Phase = Phase.ABORTED
    final_votes: dict[str, Verdict] = field(default_factory=dict)
    winner_id: str = ""
    # Engine results use Decimal token amounts; historical records may use floats.
    winner_payout: Amount = 0.0
    juror_payouts: dict[str, Amount] = field(default_factory=dict)
    protocol_fee: Amount = 0.0
    forfeited_bonds: dict[str, Amount] = field(default_factory=dict)
    refunds: dict[str, Amount] = field(default_factory=dict)
    # Exact Rust settlement, including base-unit strings and deployment identity.
    engine_evidence: dict[str, Any] | None = None
