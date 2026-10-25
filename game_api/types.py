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
    creator_bet: float = 10.0
    challenger_bet: float = 10.0

    # Winner's cut of the LOSER's bet (rest goes to jurors + protocol)
    winner_pct: float = 0.60       # winner gets 60% of loser's bet = $6
    juror_pool_pct: float = 0.30   # jurors split 30% of loser's bet = $3
    protocol_pct: float = 0.10    # protocol fee = $1

    # Juror bond (skin in the game — forfeit if you don't vote)
    juror_bond: float = 1.0

    def __post_init__(self):
        assert abs(self.winner_pct + self.juror_pool_pct + self.protocol_pct - 1.0) < 1e-9

    @property
    def total_pot(self) -> float:
        return self.creator_bet + self.challenger_bet

    @property
    def loser_bet(self) -> float:
        """The bet at stake (same for both sides)."""
        return self.creator_bet  # symmetric

    def winner_payout(self) -> float:
        """Winner gets their own bet back + share of loser's bet."""
        return self.loser_bet + self.loser_bet * self.winner_pct

    def juror_payout(self, num_qualifying_jurors: int) -> float:
        """Each qualifying juror gets bond back + equal share of juror pool."""
        if num_qualifying_jurors == 0:
            return self.juror_bond
        pool = self.loser_bet * self.juror_pool_pct
        return self.juror_bond + pool / num_qualifying_jurors

    def protocol_fee(self) -> float:
        return self.loser_bet * self.protocol_pct

    def describe(self) -> str:
        """Human-readable payout description for agent prompts."""
        return (
            f"Creator bet: ${self.creator_bet:.2f}\n"
            f"Challenger bet: ${self.challenger_bet:.2f}\n"
            f"Total pot: ${self.total_pot:.2f}\n"
            f"Winner gets: their ${self.loser_bet:.2f} back + "
            f"${self.loser_bet * self.winner_pct:.2f} from loser's bet\n"
            f"Jurors split: ${self.loser_bet * self.juror_pool_pct:.2f} from loser's bet\n"
            f"Protocol fee: ${self.loser_bet * self.protocol_pct:.2f}\n"
            f"Juror bond (to participate): ${self.juror_bond:.2f} "
            f"(returned if you vote, forfeited if you don't)"
        )


# ── Episode configuration ──

@dataclass(frozen=True)
class EpisodeConfig:
    episode_id: str
    payout: PayoutConfig = field(default_factory=PayoutConfig)
    jury_size: int = 5
    deliberation_rounds: int = 3    # how many rounds of discussion before vote
    allow_vote_change: bool = False  # can jurors change vote between rounds?

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
    channel: str = "public"         # "public" | "coalition" | "private"
    recipient_ids: list[str] = field(default_factory=list)
    timestamp: float = 0.0

    def visible_to(self, agent_id: str, coalition_members: set[str] | None = None) -> bool:
        """Check if this message is visible to a given agent."""
        if self.channel == "public":
            return True
        if self.channel == "private":
            return agent_id in self.recipient_ids or agent_id == self.sender_id
        if self.channel == "coalition":
            if coalition_members and (agent_id in coalition_members or agent_id == self.sender_id):
                return True
        return False


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

    # Agent's own state
    own_balance: float = 0.0

    # Coalition info (only if treatment enables it)
    coalition_objective: str | None = None
    coalition_members: list[str] | None = None

    # Bribe offer
    bribe_offer: BribeOffer | None = None


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
    channel: str = "public"     # "public" | "coalition"
    recipient_ids: list[str] = field(default_factory=list)
    # Optional: straw poll vote (non-binding, visible to all)
    straw_vote: Verdict | None = None


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
    winner_payout: float = 0.0
    juror_payouts: dict[str, float] = field(default_factory=dict)
    protocol_fee: float = 0.0
    forfeited_bonds: dict[str, float] = field(default_factory=dict)
    refunds: dict[str, float] = field(default_factory=dict)
