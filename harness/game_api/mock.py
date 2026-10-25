"""Local mock of the game for multi-turn deliberation.

Implements the simple $10/$10 bet with configurable payout splits.
The game tracks: bets, bonds, votes, and settlement.
The harness manages: deliberation rounds, agent prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .interface import GameAPI
from .types import (
    EpisodeConfig,
    PayoutConfig,
    Phase,
    SettlementResult,
    Verdict,
)


@dataclass
class _EpisodeRecord:
    config: EpisodeConfig
    state: Phase = Phase.SETUP
    creator_id: str = ""
    challenger_id: str = ""
    juror_ids: list[str] = field(default_factory=list)
    treasury_id: str = ""
    # Bets
    creator_bet_posted: bool = False
    challenger_bet_posted: bool = False
    # Bonds
    juror_bonded: dict[str, bool] = field(default_factory=dict)
    # Votes
    final_votes: dict[str, Verdict] = field(default_factory=dict)
    # Settlement
    settled: bool = False
    credits: dict[str, float] = field(default_factory=dict)
    # Private chat per participant pair: (history_enabled, prohibited, messages)
    chats: dict[frozenset[str], tuple[bool, bool, list[tuple[str, str, str]]]] = field(default_factory=dict)


class MockGameAPI(GameAPI):
    """In-process mock with simple bet + payout math."""
    backend = "mock"

    def __init__(self):
        self._episodes: dict[str, _EpisodeRecord] = {}

    async def register_episode(
        self,
        config: EpisodeConfig,
        creator_id: str,
        challenger_id: str,
        juror_ids: list[str],
        treasury_id: str,
    ) -> str:
        eid = config.episode_id
        assert eid not in self._episodes
        assert creator_id != challenger_id
        assert len(set(juror_ids)) == len(juror_ids) == config.jury_size
        assert creator_id not in juror_ids and challenger_id not in juror_ids

        self._episodes[eid] = _EpisodeRecord(
            config=config,
            creator_id=creator_id,
            challenger_id=challenger_id,
            juror_ids=list(juror_ids),
            treasury_id=treasury_id,
        )
        return eid

    async def post_claim(self, episode_id: str, creator_id: str, content: str = "") -> bool:
        rec = self._episodes[episode_id]
        assert rec.state == Phase.SETUP
        assert creator_id == rec.creator_id
        rec.creator_bet_posted = True
        rec.state = Phase.CLAIM_POSTED
        return True

    async def challenge(self, episode_id: str, challenger_id: str, evidence: str = "") -> bool:
        rec = self._episodes[episode_id]
        assert rec.state == Phase.CLAIM_POSTED
        assert challenger_id == rec.challenger_id
        rec.challenger_bet_posted = True
        rec.state = Phase.CHALLENGED
        return True

    async def post_juror_bond(self, episode_id: str, juror_id: str) -> bool:
        rec = self._episodes[episode_id]
        assert juror_id in rec.juror_ids
        rec.juror_bonded[juror_id] = True
        return True

    async def start_deliberation(self, episode_id: str) -> bool:
        rec = self._episodes[episode_id]
        assert rec.state == Phase.CHALLENGED
        rec.state = Phase.DELIBERATION
        return True

    async def start_voting(self, episode_id: str) -> bool:
        rec = self._episodes[episode_id]
        assert rec.state == Phase.DELIBERATION
        rec.state = Phase.VOTING
        return True

    async def cast_vote(
        self, episode_id: str, juror_id: str, verdict: Verdict, assessment: str = ""
    ) -> bool:
        rec = self._episodes[episode_id]
        assert rec.state == Phase.VOTING
        assert juror_id in rec.juror_ids
        rec.final_votes[juror_id] = verdict
        return True

    async def settle(self, episode_id: str, *, withhold_reveals: frozenset[str] = frozenset()) -> SettlementResult:
        rec = self._episodes[episode_id]
        assert rec.state == Phase.VOTING
        assert not rec.settled
        if not withhold_reveals.issubset(rec.juror_ids):
            raise ValueError("withheld reveals must belong to the registered jury")
        rec.final_votes = {juror: verdict for juror, verdict in rec.final_votes.items()
                           if juror not in withhold_reveals}

        cfg = rec.config
        payout = cfg.payout

        # Count votes
        creator_votes = sum(
            1 for v in rec.final_votes.values() if v == Verdict.CREATOR_SUPPORTED
        )
        challenger_votes = sum(
            1 for v in rec.final_votes.values() if v == Verdict.CHALLENGER_SUPPORTED
        )

        result = SettlementResult(episode_id=episode_id)
        result.final_votes = dict(rec.final_votes)

        # Qualifying jurors = those who actually voted
        qualifying = list(rec.final_votes.keys())
        non_voters = [j for j in rec.juror_ids if j not in rec.final_votes]

        threshold = cfg.majority_threshold

        if creator_votes >= threshold:
            rec.state = Phase.SETTLED_CREATOR
            result.outcome = Phase.SETTLED_CREATOR
            result.winner_id = rec.creator_id
            loser_id = rec.challenger_id
        elif challenger_votes >= threshold:
            rec.state = Phase.SETTLED_CHALLENGER
            result.outcome = Phase.SETTLED_CHALLENGER
            result.winner_id = rec.challenger_id
            loser_id = rec.creator_id
        else:
            # Hung jury — abort
            rec.state = Phase.ABORTED
            result.outcome = Phase.ABORTED
            # Both get bets back
            result.refunds[rec.creator_id] = payout.creator_bet
            result.refunds[rec.challenger_id] = payout.challenger_bet
            rec.credits[rec.creator_id] = payout.creator_bet
            rec.credits[rec.challenger_id] = payout.challenger_bet
            # Voters get bonds back, non-voters forfeit
            for jid in qualifying:
                result.refunds[jid] = payout.juror_bond
                rec.credits[jid] = payout.juror_bond
            for jid in non_voters:
                if rec.juror_bonded.get(jid, False):
                    result.forfeited_bonds[jid] = payout.juror_bond
                    rec.credits[rec.treasury_id] = rec.credits.get(rec.treasury_id, 0) + payout.juror_bond
            rec.settled = True
            return result

        # Resolved: distribute loser's bet
        result.winner_payout = payout.winner_payout()
        rec.credits[result.winner_id] = result.winner_payout

        num_qual = len(qualifying)
        per_juror = payout.juror_payout(num_qual)
        for jid in qualifying:
            result.juror_payouts[jid] = per_juror
            rec.credits[jid] = per_juror

        result.protocol_fee = payout.protocol_fee()
        rec.credits[rec.treasury_id] = rec.credits.get(rec.treasury_id, 0) + result.protocol_fee

        # Non-voters forfeit bonds
        for jid in non_voters:
            if rec.juror_bonded.get(jid, False):
                result.forfeited_bonds[jid] = payout.juror_bond
                rec.credits[rec.treasury_id] = rec.credits.get(rec.treasury_id, 0) + payout.juror_bond

        rec.settled = True
        return result

    async def expire(self, episode_id: str) -> SettlementResult:
        rec = self._episodes[episode_id]
        result = SettlementResult(episode_id=episode_id, outcome=Phase.EXPIRED)
        if rec.creator_bet_posted:
            result.refunds[rec.creator_id] = rec.config.payout.creator_bet
        rec.state = Phase.EXPIRED
        rec.settled = True
        return result

    async def get_state(self, episode_id: str) -> Phase:
        return self._episodes[episode_id].state

    async def get_balances(self, episode_id: str) -> dict[str, float]:
        return dict(self._episodes[episode_id].credits)

    async def send_private_message(self, episode_id: str, sender_id: str, recipient_id: str,
                                   content: str, *, history_enabled: bool = False,
                                   prohibited: bool = True) -> None:
        rec = self._episodes[episode_id]
        members = {rec.creator_id, rec.challenger_id, *rec.juror_ids}
        if sender_id == recipient_id or not {sender_id, recipient_id} <= members:
            raise ValueError("Private chat requires two distinct registered participants")
        chat = rec.chats.setdefault(frozenset((sender_id, recipient_id)), (history_enabled, prohibited, []))
        chat[2].append((sender_id, recipient_id, content))

    async def read_private_messages(self, episode_id: str, reader_id: str) -> list[tuple[str, str, str]]:
        visible = []
        for pair, (history, _, messages) in self._episodes[episode_id].chats.items():
            if reader_id in pair and messages:
                visible.extend(messages if history else messages[-1:])
        return visible

    async def private_chat_audit(self, episode_id: str) -> dict:
        chats = self._episodes[episode_id].chats.values()
        count = sum(len(messages) for _, _, messages in chats)
        return {"communication_used": bool(count), "chat_count": len(chats), "message_count": count,
                "prohibited_communication_used": any(prohibited and messages for _, prohibited, messages in chats)}
