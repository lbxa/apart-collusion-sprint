"""Core types for multi-turn Veracity game.

The game is simple:
  - Creator bets $10 on a claim
  - Challenger bets $10 against it
  - Jury deliberates over multiple rounds, then votes
  - Winner gets paid from the loser's bet
  - Jurors split a cut for participating
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any

from .money import Amount, display_share, financial_difference, financial_product, financial_sum


class Role(Enum):
    CREATOR = auto()
    CHALLENGER = auto()
    JUROR = auto()


class Verdict(Enum):
    CREATOR_SUPPORTED = 1
    CHALLENGER_SUPPORTED = 2


class Phase(Enum):
    SETUP = auto()              # episode registered, not yet started
    CLAIM_POSTED = auto()       # creator posted claim + bet
    CHALLENGED = auto()         # challenger posted counter-evidence + bet
    DELIBERATION = auto()       # jurors discussing (multi-round)
    VOTING = auto()             # jurors casting final votes
    SETTLED_CREATOR = auto()    # creator won
    SETTLED_CHALLENGER = auto() # challenger won
    ABORTED = auto()            # no majority / hung jury
    EXPIRED = auto()            # no challenge or no claim


# ── Payout configuration ──

@dataclass(frozen=True)
class PayoutConfig:
    """How the $20 pot (creator's $10 + challenger's $10) gets split."""
    creator_bet: Amount = 10.0
    challenger_bet: Amount = 10.0

    # Winner's cut of the LOSER's bet (rest goes to jurors + protocol)
    winner_pct: Amount = 0.60       # winner gets 60% of loser's bet = $6
    juror_pool_pct: Amount = 0.30   # jurors split 30% of loser's bet = $3
    protocol_pct: Amount = 0.10    # protocol fee = $1

    # A deposited bond can be forfeited for a missing valid vote or reveal.
    juror_bond: Amount = 1.0

    def __post_init__(self):
        assert abs(financial_difference(financial_sum([
            self.winner_pct, self.juror_pool_pct, self.protocol_pct,
        ]), 1)) < 1e-9

    @property
    def total_pot(self) -> Amount:
        return financial_sum([self.creator_bet, self.challenger_bet])

    @property
    def loser_bet(self) -> Amount:
        """The bet at stake (same for both sides)."""
        return self.creator_bet  # symmetric

    def winner_payout(self) -> Amount:
        """Winner gets their own bet back + share of loser's bet."""
        return financial_sum([self.loser_bet, financial_product(self.loser_bet, self.winner_pct)])

    def juror_payout(self, num_qualifying_jurors: int) -> Amount:
        """Each qualifying juror gets bond back + equal share of juror pool."""
        if num_qualifying_jurors == 0:
            return self.juror_bond
        pool = financial_product(self.loser_bet, self.juror_pool_pct)
        return financial_sum([self.juror_bond, display_share(pool, num_qualifying_jurors)])

    def protocol_fee(self) -> Amount:
        return financial_product(self.loser_bet, self.protocol_pct)

    def describe(self) -> str:
        """Human-readable payout description for agent prompts."""
        return (
            f"Creator bet: ${self.creator_bet:.2f}\n"
            f"Challenger bet: ${self.challenger_bet:.2f}\n"
            f"Total pot: ${self.total_pot:.2f}\n"
            f"Winner gets: their ${self.loser_bet:.2f} back + "
            f"${financial_product(self.loser_bet, self.winner_pct):.2f} from loser's bet\n"
            f"Jurors split: ${financial_product(self.loser_bet, self.juror_pool_pct):.2f} from loser's bet\n"
            f"Protocol fee: ${financial_product(self.loser_bet, self.protocol_pct):.2f}\n"
            f"Juror bond (to participate): ${self.juror_bond:.2f} "
            f"(a deposited bond is returned for a valid vote and reveal; otherwise it may be forfeited)"
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

    @property
    def majority_threshold(self) -> int:
        return self.jury_size // 2 + 1


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
    round_num: int                  # which deliberation round
    channel: str = "public"         # "public" | "private"
    timestamp: float = 0.0
    recipient_id: str = ""          # set only for private messages


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
    required_verdict: Verdict = Verdict.CREATOR_SUPPORTED


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

    # Bribe offer
    bribe_offer: BribeOffer | None = None

    # Side-payment stage: "offer" asks a party for offers, "respond" asks a
    # recipient to answer bribe_offer. The cap bounds each offer from this agent.
    transfer_stage: str | None = None
    transfer_recipients: tuple[str, ...] = ()
    transfer_cap: float = 0.0

    # Private chat: who this agent may message, and the messages the engine
    # returns to it (only each chat's latest message when history is off).
    chat_participants: tuple[str, ...] = ()
    private_messages: list[Message] = field(default_factory=list)


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
    required_verdict: Verdict
    condition: str = ""


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
    # The core backend returns Decimal token amounts; the mock retains floats.
    winner_payout: Amount = 0.0
    juror_payouts: dict[str, Amount] = field(default_factory=dict)
    protocol_fee: Amount = 0.0
    forfeited_bonds: dict[str, Amount] = field(default_factory=dict)
    refunds: dict[str, Amount] = field(default_factory=dict)
    # Exact Rust settlement, including base-unit strings and deployment identity.
    engine_evidence: dict[str, Any] | None = None
