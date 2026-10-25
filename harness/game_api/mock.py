"""Local mock of the game for multi-turn deliberation.

Implements the simple $10/$10 bet with configurable payout splits.
The game tracks: bets, bonds, votes, and settlement.
The harness manages: deliberation rounds, agent prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import copy
import hashlib
import time
import uuid

from .interface import GameAPI
from .types import (
    EpisodeConfig,
    Message,
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
    forum_messages: list[Message] = field(default_factory=list)
    forum_events: list[dict] = field(default_factory=list)


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

    def _forum_actor(self, episode_id: str, actor_id: str) -> _EpisodeRecord:
        rec = self._episodes[episode_id]
        if actor_id not in [rec.creator_id, rec.challenger_id, *rec.juror_ids, rec.treasury_id]:
            self._forum_event(rec, episode_id, actor_id, "access_denied")
            raise ValueError("Participant is not assigned to this episode")
        return rec

    @staticmethod
    def _forum_event(rec, episode_id, actor_id, kind, **metadata):
        event = {"sequence": len(rec.forum_events) + 1, "episode_id": episode_id,
                 "actor_id": actor_id, "actor_is_operator": False, "kind": kind,
                 "message_sequence": None, "message_hash": None, "message_bytes": None,
                 "round_num": None, "returned_sequences": [],
                 "created_at_ms": time.time_ns() // 1_000_000} | metadata
        rec.forum_events.append(event)

    async def send_forum_message(self, episode_id: str, sender_id: str,
                                 content: str, round_num: int) -> Message:
        rec = self._forum_actor(episode_id, sender_id)
        if (not content.strip() or len(content.encode("utf-8")) > 16384
                or type(round_num) is not int or not 1 <= round_num <= 2**32 - 1):
            raise ValueError("Invalid public forum message")
        existing = next((msg for msg in rec.forum_messages
                         if msg.sender_id == sender_id and msg.round_num == round_num), None)
        if existing is not None:
            if existing.content != content:
                raise ValueError("Forum message retry changed its content")
            return copy.deepcopy(existing)
        created_at_ms = time.time_ns() // 1_000_000
        message = Message(sender_id, content, round_num, timestamp=created_at_ms / 1000,
            message_id=uuid.uuid4().hex, sequence=len(rec.forum_messages) + 1,
            content_hash="sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest(),
            created_at_ms=created_at_ms)
        rec.forum_messages.append(message)
        self._forum_event(rec, episode_id, sender_id, "message_sent",
            message_sequence=message.sequence, message_hash=message.content_hash,
            message_bytes=len(content.encode("utf-8")), round_num=round_num)
        return copy.deepcopy(message)

    async def get_forum_messages(self, episode_id: str, participant_id: str) -> list[Message]:
        rec = self._forum_actor(episode_id, participant_id)
        self._forum_event(rec, episode_id, participant_id, "messages_read",
            returned_sequences=[message.sequence for message in rec.forum_messages])
        return copy.deepcopy(rec.forum_messages)

    async def get_forum_audit(self, episode_id: str) -> dict:
        rec = self._episodes[episode_id]
        actors = {}
        for event in rec.forum_events:
            usage = actors.setdefault(event["actor_id"], {"actor_id": event["actor_id"],
                "sent_messages": 0, "read_requests": 0, "messages_returned": 0,
                "denied_requests": 0, "sent_bytes": 0})
            if event["kind"] == "message_sent":
                usage["sent_messages"] += 1
                usage["sent_bytes"] += event["message_bytes"]
            elif event["kind"] == "messages_read":
                usage["read_requests"] += 1
                usage["messages_returned"] += len(event["returned_sequences"])
            else:
                usage["denied_requests"] += 1
        return {"episode_id": episode_id, "forum_used": bool(rec.forum_events),
                "communication_used": bool(rec.forum_messages),
                "message_count": len(rec.forum_messages),
                "total_message_bytes": sum(usage["sent_bytes"] for usage in actors.values()),
                "active_sender_count": sum(usage["sent_messages"] > 0 for usage in actors.values()),
                "first_message_at_ms": rec.forum_messages[0].created_at_ms if rec.forum_messages else None,
                "last_message_at_ms": rec.forum_messages[-1].created_at_ms if rec.forum_messages else None,
                "actors": copy.deepcopy(list(actors.values())), "events": copy.deepcopy(rec.forum_events),
                "next_after": len(rec.forum_events), "has_more": False}

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
