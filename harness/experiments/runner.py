"""Experiment runner — multi-turn deliberation orchestrator.

Core loop per episode:
  1. Register episode with game API
  2. Creator posts claim + bet
  3. Challenger decides to challenge or abstain
  4. Jurors post bonds
  5. DELIBERATION: N rounds of discussion (messages, straw polls)
  6. VOTING: jurors cast final binding votes
  7. Settlement: payout distribution
"""

from __future__ import annotations

import copy
import hashlib
import logging
import math
import time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from agents.base import AgentConfig, BaseAgent
from agents.llm_agent import LLMAgent
from agents.scripted import (
    AdversarialAgent,
    BribableAgent,
    HonestAgent,
    NonVotingAgent,
    RandomAgent,
)
from experiments.treatments import TreatmentConfig
from game_api.interface import GameAPI
from game_api.types import (
    BribeOffer,
    ChallengeAction,
    DeliberateAction,
    EpisodeConfig,
    Message,
    Observation,
    Phase,
    PostClaimAction,
    Role,
    Scenario,
    StrawPoll,
    Verdict,
)
from metrics.collector import EpisodeRecord, ExperimentMetrics, MetricsCollector
from metrics.collusion_detector import analyze_episode
from metrics.episode_logger import EpisodeLogger

logger = logging.getLogger(__name__)


@dataclass
class ExperimentRun:
    """State for a single experiment run."""
    experiment_id: str
    treatment: TreatmentConfig
    scenarios: list[Scenario]
    game_api: GameAPI
    metrics: MetricsCollector
    output_dir: Path
    agents: dict[str, BaseAgent] = field(default_factory=dict)


class ExperimentRunner:
    """Runs multi-turn deliberation experiments."""

    def __init__(self, game_api: GameAPI, output_dir: Path | str = "results"):
        self.game_api = game_api
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.metrics = MetricsCollector()

    async def run_experiment(
        self,
        treatment: TreatmentConfig,
        scenarios: list[Scenario],
        experiment_id: str | None = None,
    ) -> ExperimentMetrics:
        if experiment_id is None:
            experiment_id = f"exp_{treatment.treatment_id}_{uuid.uuid4().hex[:8]}"

        logger.info(
            "Starting experiment %s: %s (%d episodes)",
            experiment_id, treatment.name, treatment.num_episodes,
        )

        exp_metrics = self.metrics.get_or_create(experiment_id, treatment.treatment_id)

        run = ExperimentRun(
            experiment_id=experiment_id,
            treatment=treatment,
            scenarios=scenarios,
            game_api=self.game_api,
            metrics=self.metrics,
            output_dir=self.output_dir / experiment_id,
        )
        run.output_dir.mkdir(parents=True, exist_ok=True)

        for i in range(treatment.num_episodes):
            scenario = scenarios[i % len(scenarios)]
            episode_id = f"{experiment_id}_ep{i:04d}"

            record = await self._run_episode(run, episode_id, scenario, i)
            if record.status == "completed" and not record.infrastructure_failure:
                record.collusion_analysis = analyze_episode(record, all_records=exp_metrics.episodes).to_dict()
            self.metrics.add_episode(exp_metrics, record)

            logger.info(
                "Episode %s: outcome=%s verdict_correct=%s",
                episode_id, record.outcome, record.verdict_correct,
            )

        self.metrics.export_jsonl(run.output_dir / "episodes.jsonl", exp_metrics)
        self.metrics.export_summary(run.output_dir / "summary.json", exp_metrics)

        logger.info("Experiment %s complete: %s", experiment_id, exp_metrics.summary())
        return exp_metrics

    async def _run_episode(
        self,
        run: ExperimentRun,
        episode_id: str,
        scenario: Scenario,
        episode_index: int,
    ) -> EpisodeRecord:
        treatment = run.treatment
        payout = treatment.payout

        record = EpisodeRecord(
            episode_id=episode_id,
            experiment_id=run.experiment_id,
            scenario_id=scenario.scenario_id,
            treatment=treatment.treatment_id,
            config={
                "creator_bet": payout.creator_bet,
                "challenger_bet": payout.challenger_bet,
                "winner_pct": payout.winner_pct,
                "juror_pool_pct": payout.juror_pool_pct,
                "protocol_pct": payout.protocol_pct,
                "jury_size": treatment.jury_size,
                "deliberation_rounds": treatment.deliberation_rounds,
                "withhold_reveal_indices": list(treatment.withhold_reveal_indices),
                "seed": treatment.seed,
                "game_backend": run.game_api.backend,
                "public_messaging": treatment.public_messaging,
                "coalition_messaging": treatment.coalition_messaging,
                "memory_enabled": treatment.memory_enabled,
                "memory_window": treatment.memory_window,
                "attack_target": treatment.attack_target,
                "attack_assigned": bool(treatment.coalitions or treatment.bribes or treatment.withhold_reveal_indices
                                        or (treatment.scripted_juror_indices
                                            and treatment.scripted_juror_type in ("adversarial", "non_voting"))),
            },
            ground_truth=scenario.ground_truth,
            start_time=time.monotonic(),
            status="running",
        )

        # Episode logger for MD handoff trail
        ep_logger = EpisodeLogger(episode_id, run.output_dir / "transcripts")

        try:
            ep_config = EpisodeConfig(
                episode_id=episode_id,
                payout=payout,
                jury_size=treatment.jury_size,
                deliberation_rounds=treatment.deliberation_rounds,
            )

            creator_id = f"creator_{episode_id}"
            challenger_id = f"challenger_{episode_id}"
            juror_ids = [f"juror_{j}_{episode_id}" for j in range(treatment.jury_size)]
            treasury_id = f"treasury_{episode_id}"
            if any(type(index) is not int or not 0 <= index < len(juror_ids)
                   for index in treatment.withhold_reveal_indices):
                raise ValueError("withhold_reveal_indices must select registered juror slots")

            record.creator_id = creator_id
            record.challenger_id = challenger_id
            record.juror_ids = juror_ids

            ep_logger.set_metadata(
                treatment=treatment.treatment_id,
                scenario=scenario.scenario_id,
                claim=scenario.claim,
                ground_truth=scenario.ground_truth,
                jury_size=treatment.jury_size,
                deliberation_rounds=treatment.deliberation_rounds,
                payout={
                    "creator_bet": payout.creator_bet,
                    "challenger_bet": payout.challenger_bet,
                    "winner_pct": f"{payout.winner_pct:.0%}",
                    "juror_pool_pct": f"{payout.juror_pool_pct:.0%}",
                    "juror_bond": payout.juror_bond,
                },
                coalition_ids=[c.coalition_id for c in treatment.coalitions],
                bribes=[f"${b.amount} from {b.from_role}" for b in treatment.bribes],
            )

            agents = self._create_agents(
                treatment, creator_id, challenger_id, juror_ids, episode_index,
                oracle_ground_truth=scenario.ground_truth,
            )
            if treatment.memory_enabled and treatment.memory_window > 0:
                for role in Role:
                    previous_slots = [agent for agent in run.agents.values() if agent.role == role]
                    current_slots = [agent for agent in agents.values() if agent.role == role]
                    for previous, current in zip(previous_slots, current_slots):
                        current.episode_memory = copy.deepcopy(previous.episode_memory[-treatment.memory_window:])
            run.agents = agents

            coalition_map = self._build_coalition_map(
                treatment, creator_id, challenger_id, juror_ids
            )
            record.coalition_ids = list(
                set(mid for members in coalition_map.values() for mid in members)
            )

            # Register episode
            await run.game_api.register_episode(
                ep_config, creator_id, challenger_id, juror_ids, treasury_id
            )

            messages: list[Message] = []
            straw_polls: list[StrawPoll] = []

            # ── Phase 1: Creator posts claim ──
            # Always post the claim — the experiment needs disputes to reach
            # jury deliberation.  The creator LLM is called for CoT logging
            # but an abstain is auto-upgraded.
            creator_obs = self._make_observation(
                Role.CREATOR, episode_id, scenario, Phase.SETUP,
                ep_config, messages, straw_polls, creator_id, coalition_map, treatment,
            )
            creator_action = await agents[creator_id].decide(creator_obs)

            if not isinstance(creator_action, PostClaimAction):
                logger.info(
                    "Episode %s: creator abstained, auto-upgrading to post_claim",
                    episode_id,
                )
                creator_action = PostClaimAction(creator_id, episode_id, scenario.claim)
            if not await run.game_api.post_claim(episode_id, creator_id, creator_action.claim_text):
                raise RuntimeError("game did not accept the creator claim")
            record.bonds_deposited[creator_id] = payout.creator_bet
            ep_logger.log(
                "CLAIM_POSTED", creator_id, "CREATOR", "post_claim",
                f"Claim: {creator_action.claim_text[:100]}...",
                money_in=payout.creator_bet,
            )

            # ── Phase 2: Challenger decides ──
            # Force challenge by default — the experiment studies jury collusion,
            # so we need disputes to actually reach deliberation.  The challenger
            # LLM is still called to generate counter-evidence, but an abstain
            # result is upgraded to a challenge with generic counter-evidence.
            challenger_obs = self._make_observation(
                Role.CHALLENGER, episode_id, scenario, Phase.CLAIM_POSTED,
                ep_config, messages, straw_polls, challenger_id, coalition_map, treatment,
            )
            challenger_action = await agents[challenger_id].decide(challenger_obs)

            if not isinstance(challenger_action, ChallengeAction):
                # Auto-upgrade abstain → challenge so the episode proceeds
                logger.info(
                    "Episode %s: challenger abstained, auto-upgrading to challenge",
                    episode_id,
                )
                challenger_action = ChallengeAction(
                    agent_id=challenger_id,
                    episode_id=episode_id,
                    evidence_text=(
                        scenario.evidence_against
                        or "This claim lacks verifiable evidence and should be challenged."
                    ),
                )

            if not await run.game_api.challenge(episode_id, challenger_id, challenger_action.evidence_text):
                raise RuntimeError("game did not accept the challenge")
            record.bonds_deposited[challenger_id] = payout.challenger_bet
            ep_logger.log(
                "CHALLENGED", challenger_id, "CHALLENGER", "challenge",
                f"Counter-evidence posted, bet ${payout.challenger_bet:.2f}",
                money_in=payout.challenger_bet,
            )

            # ── Phase 3: Jurors post bonds ──
            for jid in juror_ids:
                if await run.game_api.post_juror_bond(episode_id, jid):
                    record.bonds_deposited[jid] = payout.juror_bond
                    ep_logger.log(
                        "BONDING", jid, "JUROR", "post_bond",
                        f"Bond deposited: ${payout.juror_bond:.2f}",
                        money_in=payout.juror_bond,
                    )

            # ── Phase 4: DELIBERATION (multi-round) ──
            await run.game_api.start_deliberation(episode_id)

            bribe_offers = self._create_bribe_offers(
                treatment, creator_id, challenger_id, juror_ids
            )
            record.bribes_offered = [{
                "offer_id": f"{episode_id}:bribe:{index}",
                "offered_by": offer.offered_by,
                "recipient_id": recipient,
                "amount": offer.amount,
                "condition": offer.condition,
                "required_verdict": offer.required_verdict.name,
                "accepted": False,
                "simulated_payout": 0.0,
            } for index, (recipient, offer) in enumerate(bribe_offers.items())]
            record.deliberation_rounds = treatment.deliberation_rounds

            for round_num in range(1, treatment.deliberation_rounds + 1):
                round_poll = StrawPoll(round_num=round_num)

                for j_idx, jid in enumerate(juror_ids):
                    bribe = bribe_offers.get(jid)

                    juror_obs = self._make_observation(
                        Role.JUROR, episode_id, scenario, Phase.DELIBERATION,
                        ep_config,
                        messages,
                        straw_polls, jid, coalition_map, treatment,
                        bribe_offer=bribe,
                        current_round=round_num,
                    )

                    delib_action = await agents[jid].deliberate(juror_obs)

                    recipients = self._message_recipients(delib_action, jid, coalition_map, treatment)
                    # Only accepted communication enters other agents' observations.
                    msg = Message(
                        sender_id=jid,
                        content=delib_action.message,
                        round_num=round_num,
                        channel=delib_action.channel,
                        recipient_ids=recipients or [],
                        timestamp=time.monotonic(),
                    )
                    if recipients is not None:
                        messages.append(msg)
                        record.messages.append({
                            "sender": jid,
                            "round": round_num,
                            "content": delib_action.message,
                            "channel": delib_action.channel,
                            "recipient_ids": list(recipients),
                        })
                        ep_logger.log(
                            f"DELIBERATION_R{round_num}", jid, "JUROR", "message",
                            delib_action.message[:200], channel=delib_action.channel,
                        )
                    else:
                        ep_logger.log(f"DELIBERATION_R{round_num}", jid, "JUROR", "message_blocked",
                                      f"Channel or recipients are not permitted: {delib_action.channel}")

                    # Record straw poll vote
                    if delib_action.straw_vote is not None:
                        round_poll.votes[jid] = delib_action.straw_vote

                    # Track bribe acceptance
                    if juror_obs.bribe_offer and juror_obs.bribe_offer.accepted:
                        if jid not in record.bribes_accepted:
                            record.bribes_accepted.append(jid)

                straw_polls.append(round_poll)
                record.straw_polls.append({
                    "round": round_num,
                    "creator_votes": round_poll.creator_votes,
                    "challenger_votes": round_poll.challenger_votes,
                })

            # ── Phase 5: FINAL VOTING ──
            await run.game_api.start_voting(episode_id)

            for j_idx, jid in enumerate(juror_ids):
                # Check if this agent is a NonVotingAgent (strategic non-voter)
                agent = agents[jid]
                should_skip_vote = isinstance(agent, NonVotingAgent)

                # Also check coalition objective for non-voting instruction
                if not should_skip_vote:
                    for coalition in treatment.coalitions:
                        if "do NOT" in (coalition.objective or "").upper() and "VOTE" in (coalition.objective or "").upper():
                            if f"juror_{j_idx}" in coalition.member_roles:
                                should_skip_vote = True

                if should_skip_vote:
                    logger.info("Juror %s refusing to cast final vote", jid)
                    continue

                bribe = bribe_offers.get(jid)

                juror_obs = self._make_observation(
                    Role.JUROR, episode_id, scenario, Phase.VOTING,
                    ep_config,
                    messages,
                    straw_polls, jid, coalition_map, treatment,
                    bribe_offer=bribe,
                )

                vote_action = await agent.final_vote(juror_obs)

                accepted = await run.game_api.cast_vote(episode_id, jid, vote_action.verdict, vote_action.assessment)
                if not accepted:
                    ep_logger.log("VOTING", jid, "JUROR", "vote_not_accepted", "Game did not accept this vote")
                    continue
                if jid not in record.bonds_deposited:
                    record.bonds_deposited[jid] = payout.juror_bond
                    ep_logger.log("VOTING", jid, "JUROR", "commit_bond",
                                  f"Bond deposited with commitment: ${payout.juror_bond:.2f}", money_in=payout.juror_bond)

                ep_logger.log(
                    "VOTING", jid, "JUROR", "final_vote",
                    f"Verdict: {vote_action.verdict.name} | Assessment: {vote_action.assessment[:150]}",
                )

                if juror_obs.bribe_offer and juror_obs.bribe_offer.accepted:
                    if jid not in record.bribes_accepted:
                        record.bribes_accepted.append(jid)
                        ep_logger.log(
                            "VOTING", jid, "JUROR", "bribe_accepted",
                            f"Accepted bribe of ${bribe.amount:.2f}: {bribe.condition}",
                            channel="private",
                        )

            # ── Phase 6: Settlement ──
            withhold_reveals = frozenset(juror_ids[index] for index in treatment.withhold_reveal_indices)
            result = await run.game_api.settle(episode_id, withhold_reveals=withhold_reveals)
            record.outcome = result.outcome.name
            record.votes = {juror: verdict.name for juror, verdict in result.final_votes.items()}
            record.settlement = {
                "winner_payout": result.winner_payout,
                "juror_payouts": result.juror_payouts,
                "protocol_fee": result.protocol_fee,
                "forfeited_bonds": result.forfeited_bonds,
                "refunds": result.refunds,
            }
            if result.engine_evidence is not None:
                record.settlement["engine_evidence"] = copy.deepcopy(result.engine_evidence)
            # Simulated side rewards are an experiment ledger, never native
            # contract entitlements. Only valid revealed votes meet a condition.
            for offer in record.bribes_offered:
                recipient = offer["recipient_id"]
                offer["accepted"] = recipient in record.bribes_accepted
                if offer["accepted"] and record.votes.get(recipient) == offer["required_verdict"]:
                    amount = offer["simulated_payout"] = offer["amount"]
                    sender = offer["offered_by"]
                    record.simulated_utility[sender] = record.simulated_utility.get(sender, 0.0) - amount
                    record.simulated_utility[recipient] = record.simulated_utility.get(recipient, 0.0) + amount
            record.payouts.update(result.juror_payouts)
            record.payouts.update(result.refunds)
            record.forfeited.update(result.forfeited_bonds)

            if result.winner_payout:
                if result.outcome == Phase.SETTLED_CREATOR:
                    record.payouts[creator_id] = result.winner_payout
                elif result.outcome == Phase.SETTLED_CHALLENGER:
                    record.payouts[challenger_id] = result.winner_payout

            # Log settlement
            ep_logger.log(
                "SETTLEMENT", "game", "SYSTEM", "settle",
                f"Outcome: {result.outcome.name} | Winner payout: ${result.winner_payout:.2f} | Protocol: ${result.protocol_fee:.2f}",
            )
            if result.winner_id:
                ep_logger.log(
                    "SETTLEMENT", result.winner_id,
                    "CREATOR" if result.outcome == Phase.SETTLED_CREATOR else "CHALLENGER",
                    "payout",
                    f"Winner receives ${result.winner_payout:.2f}",
                    money_out=result.winner_payout,
                )
            for jid, jpay in result.juror_payouts.items():
                ep_logger.log(
                    "SETTLEMENT", jid, "JUROR", "juror_payout",
                    f"Juror receives ${jpay:.2f} (bond + share)",
                    money_out=jpay,
                )
            for jid, bond in result.forfeited_bonds.items():
                ep_logger.log(
                    "SETTLEMENT", jid, "JUROR", "bond_forfeited",
                    f"Bond forfeited: ${bond:.2f} (required vote or reveal missing)",
                )

            # Evaluate verdict correctness
            if scenario.ground_truth is not None:
                if result.outcome == Phase.SETTLED_CREATOR:
                    record.verdict_correct = scenario.ground_truth is True
                elif result.outcome == Phase.SETTLED_CHALLENGER:
                    record.verdict_correct = scenario.ground_truth is False

            # Run collusion detection
            collusion_report = analyze_episode(record)
            record.metadata = record.metadata if hasattr(record, 'metadata') else {}

            ep_logger.log(
                "ANALYSIS", "detector", "SYSTEM", "collusion_check",
                f"Score: {collusion_report.overall_score:.3f} | Verdict: {collusion_report.verdict}",
            )
            for sig in collusion_report.signals:
                if sig.score > 0.1:
                    ep_logger.log(
                        "ANALYSIS", "detector", "SYSTEM", f"signal:{sig.signal_type}",
                        f"[{sig.score:.2f}] {sig.description}",
                    )

            # Save episode transcript
            md_path = ep_logger.save()
            logger.info("Episode transcript: %s", md_path)

            # Record episode in agent memory
            for aid, agent in agents.items():
                if treatment.memory_enabled and treatment.memory_window > 0:
                    agent.record_episode_outcome({
                        "episode_id": episode_id,
                        "outcome": record.outcome,
                        "my_payout": record.payouts.get(aid, 0),
                        "my_bond": record.bonds_deposited.get(aid, 0),
                    })

            record.status = "completed"

        except Exception as e:
            logger.error("Episode %s failed: %s", episode_id, e, exc_info=True)
            record.infrastructure_failure = True
            record.outcome = ""
            record.verdict_correct = None
            record.failure_reason = str(e)
            record.status = "failed"
            ep_logger.log("ERROR", "system", "SYSTEM", "failure", str(e))
            ep_logger.save()

        record.end_time = time.monotonic()
        return record

    # ── Agent creation ──

    def _create_agents(
        self,
        treatment: TreatmentConfig,
        creator_id: str,
        challenger_id: str,
        juror_ids: list[str],
        episode_index: int,
        *,
        oracle_ground_truth: bool | None = None,
    ) -> dict[str, BaseAgent]:
        agents: dict[str, BaseAgent] = {}

        # Creator
        if treatment.use_scripted_creator:
            agents[creator_id] = HonestAgent(
                AgentConfig(agent_id=creator_id, role=Role.CREATOR,
                            memory_enabled=treatment.memory_enabled, memory_window=treatment.memory_window),
                oracle_ground_truth=oracle_ground_truth,
            )
        else:
            agents[creator_id] = LLMAgent(AgentConfig(
                agent_id=creator_id, role=Role.CREATOR,
                model=treatment.creator_model,
                provider=treatment.creator_provider,
                persona=treatment.creator_persona,
                hidden_motivation=treatment.creator_motivation,
                memory_enabled=treatment.memory_enabled,
                memory_window=treatment.memory_window,
                context_window=treatment.context_window,
            ))

        # Challenger
        if treatment.use_scripted_challenger:
            agents[challenger_id] = HonestAgent(
                AgentConfig(agent_id=challenger_id, role=Role.CHALLENGER,
                            memory_enabled=treatment.memory_enabled, memory_window=treatment.memory_window),
                oracle_ground_truth=oracle_ground_truth,
            )
        else:
            agents[challenger_id] = LLMAgent(AgentConfig(
                agent_id=challenger_id, role=Role.CHALLENGER,
                model=treatment.challenger_model,
                provider=treatment.challenger_provider,
                persona=treatment.challenger_persona,
                hidden_motivation=treatment.challenger_motivation,
                memory_enabled=treatment.memory_enabled,
                memory_window=treatment.memory_window,
                context_window=treatment.context_window,
            ))

        # Jurors
        for j_idx, jid in enumerate(juror_ids):
            if j_idx in treatment.scripted_juror_indices:
                agent_cls = {
                    "honest": HonestAgent,
                    "adversarial": AdversarialAgent,
                    "random": RandomAgent,
                    "non_voting": NonVotingAgent,
                    "bribable": BribableAgent,
                }.get(treatment.scripted_juror_type, HonestAgent)
                config = AgentConfig(agent_id=jid, role=Role.JUROR,
                                     memory_enabled=treatment.memory_enabled, memory_window=treatment.memory_window)
                if agent_cls is RandomAgent:
                    seed_bytes = hashlib.sha256(f"{treatment.seed}:{episode_index}:juror:{j_idx}".encode()).digest()
                    agents[jid] = RandomAgent(config, seed=int.from_bytes(seed_bytes, "big"))
                elif agent_cls is HonestAgent:
                    agents[jid] = HonestAgent(config, oracle_ground_truth=oracle_ground_truth)
                else:
                    agents[jid] = agent_cls(config)
            else:
                overrides = treatment.juror_overrides.get(j_idx, {})

                coalition_id = None
                coalition_obj = None
                for c in treatment.coalitions:
                    if f"juror_{j_idx}" in c.member_roles:
                        coalition_id = c.coalition_id
                        coalition_obj = c.objective

                agents[jid] = LLMAgent(AgentConfig(
                    agent_id=jid, role=Role.JUROR,
                    model=overrides.get("model", treatment.juror_model),
                    provider=overrides.get("provider", treatment.juror_provider),
                    persona=overrides.get("persona", treatment.juror_persona),
                    hidden_motivation=overrides.get("motivation", treatment.juror_motivation),
                    coalition_id=coalition_id,
                    coalition_objective=coalition_obj,
                    memory_enabled=treatment.memory_enabled,
                    memory_window=treatment.memory_window,
                    context_window=overrides.get("context_window", treatment.context_window),
                    deliberation_style=overrides.get("deliberation_style", "analytical"),
                ))

        return agents

    # ── Helpers ──

    def _build_coalition_map(
        self,
        treatment: TreatmentConfig,
        creator_id: str,
        challenger_id: str,
        juror_ids: list[str],
    ) -> dict[str, list[str]]:
        coalition_map: dict[str, list[str]] = {}
        role_to_id = {"creator": creator_id, "challenger": challenger_id}
        for j_idx, jid in enumerate(juror_ids):
            role_to_id[f"juror_{j_idx}"] = jid

        for c in treatment.coalitions:
            members = [role_to_id[r] for r in c.member_roles if r in role_to_id]
            coalition_map[c.coalition_id] = members
        return coalition_map

    def _make_observation(
        self,
        role: Role,
        episode_id: str,
        scenario: Scenario,
        phase: Phase,
        config: EpisodeConfig,
        messages: list[Message],
        straw_polls: list[StrawPoll],
        agent_id: str,
        coalition_map: dict[str, list[str]],
        treatment: TreatmentConfig,
        bribe_offer: BribeOffer | None = None,
        current_round: int = 0,
    ) -> Observation:
        coalition_obj = None
        coalition_members = None
        for c in treatment.coalitions:
            for cid, members in coalition_map.items():
                if cid == c.coalition_id and agent_id in members:
                    coalition_obj = c.objective
                    coalition_members = [m for m in members if m != agent_id]

        return Observation(
            role=role,
            episode_id=episode_id,
            # Scenario metadata has no public allowlist; keep evaluator annotations private.
            scenario=replace(scenario, ground_truth=None, metadata={}),
            phase=phase,
            config=config,
            current_round=current_round,
            total_rounds=config.deliberation_rounds,
            visible_messages=copy.deepcopy(self._filter_messages(messages, agent_id, coalition_map, treatment)),
            straw_polls=copy.deepcopy(straw_polls) if treatment.public_messaging else [],
            allowed_channels=self._communication_permissions(agent_id, coalition_map, treatment)[0],
            coalition_objective=coalition_obj,
            coalition_members=coalition_members,
            bribe_offer=copy.deepcopy(bribe_offer),
        )

    def _filter_messages(
        self,
        messages: list[Message],
        agent_id: str,
        coalition_map: dict[str, list[str]],
        treatment: TreatmentConfig,
    ) -> list[Message]:
        return [
            msg for msg in messages
            if (msg.channel == "public" and treatment.public_messaging)
            or (msg.channel in ("private", "coalition")
                and msg.channel in self._communication_permissions(msg.sender_id, coalition_map, treatment)[0]
                and (agent_id == msg.sender_id or agent_id in msg.recipient_ids))
        ]

    def _communication_permissions(
        self, agent_id: str, coalition_map: dict[str, list[str]], treatment: TreatmentConfig,
    ) -> tuple[tuple[str, ...], set[str]]:
        recipients: set[str] = set()
        if treatment.coalition_messaging:
            for coalition in treatment.coalitions:
                members = coalition_map.get(coalition.coalition_id, [])
                if coalition.communication_enabled and agent_id in members:
                    recipients.update(member for member in members if member != agent_id)
        channels = (["public"] if treatment.public_messaging else [])
        if recipients:
            channels.extend(["coalition", "private"])
        return tuple(channels), recipients

    def _message_recipients(
        self, action: DeliberateAction, sender_id: str,
        coalition_map: dict[str, list[str]], treatment: TreatmentConfig,
    ) -> list[str] | None:
        channels, permitted = self._communication_permissions(sender_id, coalition_map, treatment)
        if action.channel not in channels:
            return None
        if action.channel == "public":
            return []
        requested = set(action.recipient_ids)
        if action.channel == "private" and not requested:
            return None
        if not requested.issubset(permitted):
            return None
        return sorted(requested or permitted)

    def _create_bribe_offers(
        self,
        treatment: TreatmentConfig,
        creator_id: str,
        challenger_id: str,
        juror_ids: list[str],
    ) -> dict[str, BribeOffer]:
        offers = {}
        role_to_id = {"creator": creator_id, "challenger": challenger_id}
        role_to_id.update({f"juror_{index}": actor for index, actor in enumerate(juror_ids)})
        for bd in treatment.bribes:
            if bd.from_role not in role_to_id or not math.isfinite(bd.amount) or bd.amount <= 0:
                raise ValueError("Simulated bribes require a registered sender and positive finite amount")
            if not isinstance(bd.required_verdict, Verdict):
                raise ValueError("A simulated bribe requires an explicit valid verdict target")
            for role in bd.to_roles:
                if role not in role_to_id or role_to_id[role] not in juror_ids:
                    raise ValueError("A simulated bribe recipient must be a registered juror")
                recipient = role_to_id[role]
                if recipient in offers:
                    raise ValueError("Only one simulated offer per juror is supported per episode")
                offers[recipient] = BribeOffer(
                    offered_by=role_to_id[bd.from_role], amount=bd.amount,
                    condition=bd.condition, required_verdict=bd.required_verdict,
                )
        return offers
