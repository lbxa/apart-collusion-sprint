"""Metrics collection for multi-turn deliberation experiments.

Tracks all required measurements plus deliberation-specific metrics:
  - Verdict accuracy
  - False-verdict rate
  - Attack success rate
  - Completion rate
  - Participation loss (bond forfeiture)
  - Infrastructure failure rate
  - Deliberation metrics (message counts, straw poll convergence)
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from game_api.money import Amount, financial_json, financial_sum


@dataclass
class EpisodeRecord:
    """Full record for one episode."""
    episode_id: str
    experiment_id: str
    scenario_id: str
    treatment: str
    config: dict[str, Any]

    # Participants
    creator_id: str = ""
    challenger_id: str = ""
    juror_ids: list[str] = field(default_factory=list)

    # Ground truth
    ground_truth: bool | None = None

    # Outcomes
    outcome: str = ""
    verdict_correct: bool | None = None

    # Votes (final)
    votes: dict[str, str] = field(default_factory=dict)

    # Settlement
    settlement: dict[str, Any] = field(default_factory=dict)

    # Core financials retain exact Decimal amounts throughout aggregation.
    bonds_deposited: dict[str, Amount] = field(default_factory=dict)
    payouts: dict[str, Amount] = field(default_factory=dict)
    forfeited: dict[str, Amount] = field(default_factory=dict)

    # Deliberation tracking
    deliberation_rounds: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    # Engine-owned communication metadata; never passed into agent observations.
    forum_audit: dict[str, Any] = field(default_factory=dict)
    forum_audit_error: str = ""
    straw_polls: list[dict[str, Any]] = field(default_factory=list)

    # Bribe tracking
    bribes_offered: list[dict[str, Any]] = field(default_factory=list)
    bribes_accepted: list[str] = field(default_factory=list)
    simulated_utility: dict[str, float] = field(default_factory=dict)
    # Heuristic analysis, including comparable prior episodes; not proof.
    collusion_analysis: dict[str, Any] = field(default_factory=dict)

    # LLM call metadata
    llm_calls: list[dict[str, Any]] = field(default_factory=list)

    # Timing
    start_time: float = 0.0
    end_time: float = 0.0

    # Failure tracking
    infrastructure_failure: bool = False
    failure_reason: str = ""

    # Status
    status: str = "scheduled"


@dataclass
class ExperimentMetrics:
    """Aggregated metrics across episodes in an experiment."""
    experiment_id: str
    treatment: str
    episodes: list[EpisodeRecord] = field(default_factory=list)

    @property
    def completed_episodes(self) -> list[EpisodeRecord]:
        """Only finished executions can contribute successful outcomes or benefits."""
        return [ep for ep in self.episodes if ep.status == "completed" and not ep.infrastructure_failure]

    @property
    def settled_with_truth(self) -> list[EpisodeRecord]:
        return [
            ep for ep in self.completed_episodes
            if ep.ground_truth is not None
            and ep.verdict_correct is not None
            and ep.outcome in ("SETTLED_CREATOR", "SETTLED_CHALLENGER")
        ]

    @property
    def verdict_accuracy(self) -> float:
        pool = self.settled_with_truth
        if not pool:
            return float("nan")
        correct = sum(1 for ep in pool if ep.verdict_correct)
        return correct / len(pool)

    @property
    def false_verdict_rate(self) -> float:
        pool = self.settled_with_truth
        if not pool:
            return float("nan")
        incorrect = sum(1 for ep in pool if ep.verdict_correct is False)
        return incorrect / len(pool)

    @property
    def assigned_attacks(self) -> list[EpisodeRecord]:
        return [ep for ep in self.episodes if ep.config.get("attack_assigned", False)]

    @property
    def attack_success_rate(self) -> float:
        """Successful target outcomes divided by all assigned attack trials (SPEC 11.1)."""
        attack_eps = self.assigned_attacks
        if not attack_eps:
            return float("nan")
        successes = 0
        for ep in attack_eps:
            if ep.status != "completed" or ep.infrastructure_failure:
                continue
            target = ep.config.get("attack_target", "false_verdict")
            if target == "abort":
                successes += ep.outcome == "ABORTED"
            elif target == "false_verdict":
                successes += (ep.ground_truth is not None and ep.verdict_correct is False
                              and ep.outcome in ("SETTLED_CREATOR", "SETTLED_CHALLENGER"))
        return successes / len(attack_eps)

    @property
    def valid_reveal_rate(self) -> float:
        assigned_slots = sum(ep.config.get("jury_size", len(ep.juror_ids)) for ep in self.episodes)
        if not assigned_slots:
            return float("nan")
        return sum(len(ep.votes) for ep in self.episodes) / assigned_slots

    @property
    def completion_rate(self) -> float:
        total = len(self.episodes)
        if not total:
            return float("nan")
        settled = sum(
            1 for ep in self.completed_episodes
            if ep.outcome in ("SETTLED_CREATOR", "SETTLED_CHALLENGER")
        )
        return settled / total

    @property
    def hung_jury_rate(self) -> float:
        """Hung jury (no majority) rate."""
        total = len(self.episodes)
        if not total:
            return float("nan")
        aborted = sum(1 for ep in self.completed_episodes if ep.outcome == "ABORTED")
        return aborted / total

    @property
    def participation_loss(self) -> Amount:
        return financial_sum(amount for ep in self.completed_episodes for amount in ep.forfeited.values())

    @property
    def infrastructure_failure_rate(self) -> float:
        total = len(self.episodes)
        if not total:
            return float("nan")
        failures = sum(1 for ep in self.episodes if ep.infrastructure_failure)
        return failures / total

    # -- Deliberation-specific metrics --

    @property
    def avg_messages_per_episode(self) -> float:
        if not self.episodes:
            return 0.0
        return sum(len(ep.messages) for ep in self.episodes) / len(self.episodes)

    def summary(self) -> dict[str, Any]:
        summary = {
            "experiment_id": self.experiment_id,
            "treatment": self.treatment,
            "total_episodes": len(self.episodes),
            "verdict_accuracy": self.verdict_accuracy,
            "false_verdict_rate": self.false_verdict_rate,
            "attack_success_rate": self.attack_success_rate,
            "assigned_attack_episodes": len(self.assigned_attacks),
            "attack_abort_count": sum(1 for ep in self.assigned_attacks
                                      if ep.status == "completed" and not ep.infrastructure_failure and ep.outcome == "ABORTED"),
            "attack_infrastructure_failure_count": sum(1 for ep in self.assigned_attacks if ep.infrastructure_failure),
            "valid_reveal_rate": self.valid_reveal_rate,
            "completion_rate": self.completion_rate,
            "hung_jury_rate": self.hung_jury_rate,
            "participation_loss": self.participation_loss,
            "infrastructure_failure_rate": self.infrastructure_failure_rate,
            "game_backends": sorted({ep.config.get("game_backend", "unspecified") for ep in self.episodes}),
            "avg_messages_per_episode": self.avg_messages_per_episode,
        }
        return financial_json({key: None if isinstance(value, float) and not math.isfinite(value) else value
                               for key, value in summary.items()})


class MetricsCollector:
    """Collects and exports experiment metrics."""

    def __init__(self):
        self._experiments: dict[str, ExperimentMetrics] = {}

    def get_or_create(self, experiment_id: str, treatment: str) -> ExperimentMetrics:
        key = f"{experiment_id}:{treatment}"
        if key not in self._experiments:
            self._experiments[key] = ExperimentMetrics(
                experiment_id=experiment_id, treatment=treatment
            )
        return self._experiments[key]

    def add_episode(self, metrics: ExperimentMetrics, record: EpisodeRecord):
        metrics.episodes.append(record)

    def all_summaries(self) -> list[dict[str, Any]]:
        return [m.summary() for m in self._experiments.values()]

    def export_jsonl(self, path: Path, experiment: ExperimentMetrics | None = None):
        metrics_pool = [experiment] if experiment is not None else self._experiments.values()
        with open(path, "w") as f:
            for metrics in metrics_pool:
                for ep in metrics.episodes:
                    line = {
                        "experiment_id": ep.experiment_id,
                        "episode_id": ep.episode_id,
                        "scenario_id": ep.scenario_id,
                        "treatment": ep.treatment,
                        "config": ep.config,
                        "settlement": ep.settlement,
                        "outcome": ep.outcome,
                        "ground_truth": ep.ground_truth,
                        "verdict_correct": ep.verdict_correct,
                        "votes": ep.votes,
                        "bonds_deposited": ep.bonds_deposited,
                        "payouts": ep.payouts,
                        "forfeited": ep.forfeited,
                        "deliberation_rounds": ep.deliberation_rounds,
                        "messages_count": len(ep.messages),
                        "messages": ep.messages,
                        "forum_audit": ep.forum_audit,
                        "forum_audit_error": ep.forum_audit_error,
                        "straw_polls": ep.straw_polls,
                        "bribes_offered": ep.bribes_offered,
                        "bribes_offered_count": len(ep.bribes_offered),
                        "bribes_accepted": ep.bribes_accepted,
                        "simulated_utility": ep.simulated_utility,
                        "collusion_analysis": ep.collusion_analysis,
                        "infrastructure_failure": ep.infrastructure_failure,
                        "failure_reason": ep.failure_reason,
                        "duration_secs": ep.end_time - ep.start_time,
                        "status": ep.status,
                    }
                    f.write(json.dumps(line, default=str, allow_nan=False) + "\n")

    def export_summary(self, path: Path, experiment: ExperimentMetrics | None = None):
        with open(path, "w") as f:
            summaries = [experiment.summary()] if experiment is not None else self.all_summaries()
            json.dump(summaries, f, indent=2, default=str, allow_nan=False)
