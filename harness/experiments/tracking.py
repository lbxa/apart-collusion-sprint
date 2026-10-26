"""Opt-in W&B boundary for scientific metadata, never raw experiment content."""

from __future__ import annotations

import importlib
import json
import math
from pathlib import Path
import subprocess

from agents.base import AgentConfig
from agents.llm_agent import OPENROUTER_PROVIDER
from experiments.design import Cell
from experiments.treatments import TreatmentConfig
from metrics.collector import ExperimentMetrics
from metrics.cot_monitor import ACTION_WEIGHT, ROGUE_THRESHOLD


SUMMARY_METRICS = (
    "total_episodes", "verdict_accuracy", "false_verdict_rate", "attack_success_rate",
    "assigned_attack_episodes", "attack_abort_count", "attack_infrastructure_failure_count",
    "valid_reveal_rate", "completion_rate", "hung_jury_rate", "infrastructure_failure_rate",
    "avg_messages_per_episode",
)


class WandbTracker:
    """Own remote run lifecycle and the allowlist crossing the W&B boundary.

    Local episode exports remain authoritative. There are no application retries:
    the SDK owns transport, and any initialization/logging exception fails the run.
    """

    def __init__(self, *, treatment: TreatmentConfig, name: str, group: str,
                 project: str, entity: str | None, backend: str, purpose: str,
                 blocks: int | None, block_index: int | None,
                 output_dir: Path, scenario_ids: list[str]):
        self.treatment = treatment
        self.name = name
        self.group = group
        self.project = project
        self.entity = entity
        self.backend = backend
        self.purpose = purpose
        self.blocks = blocks
        self.block_index = block_index
        self.output_dir = output_dir
        self.scenario_ids = scenario_ids
        self.run = None
        self.failed = False

    def __enter__(self):
        self.sdk = importlib.import_module("wandb")
        treatment = self.treatment
        cell_id = treatment.metadata.get("cell")
        factors = None
        if cell_id is not None:
            cell = Cell.parse(cell_id)
            factors = dict(zip("MCTRSEAVD", map(int, (
                cell.pay_majority, cell.channel, cell.transfers, cell.repeated,
                cell.high_stakes, cell.ambiguous_evidence, cell.audit,
                cell.auditor_panel, cell.auditors_disclosed,
            ))))
        root = Path(__file__).resolve().parents[2]
        revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                  capture_output=True, text=True, check=True).stdout.strip()
        dirty = bool(subprocess.run(["git", "status", "--porcelain"], cwd=root,
                                    capture_output=True, text=True, check=True).stdout.strip())
        config = {
            "treatment_id": treatment.treatment_id,
            "cell": cell_id,
            "lineup": treatment.metadata.get("lineup"),
            "factors": factors,
            "backend": self.backend,
            "purpose": self.purpose,
            "scene": "jury",
            "code_revision": revision,
            "code_dirty": dirty,
            "scenario_order": self.scenario_ids,
            "seed": treatment.seed,
            "episodes_per_run": treatment.num_episodes,
            "episodes_per_block": treatment.num_episodes if self.blocks is not None else None,
            "blocks": self.blocks,
            "block_index": self.block_index,
            "jury_size": treatment.jury_size,
            "deliberation_rounds": treatment.deliberation_rounds,
            "memory_enabled": treatment.memory_enabled,
            "memory_window": treatment.memory_window,
            "private_chat": treatment.private_chat,
            "public_messaging": treatment.public_messaging,
            "transfers_enabled": treatment.transfers_enabled,
            "pay_multiplier": treatment.pay_multiplier,
            "audit_probability": treatment.audit_probability,
            "auditor_count": treatment.auditor_count,
            "auditor_interview_rounds": treatment.auditor_interview_rounds,
            "auditors_disclosed": treatment.auditors_disclosed,
            "party_auditor_offers": treatment.party_auditor_offers,
            "creator_bet": str(treatment.payout.creator_bet),
            "challenger_bet": str(treatment.payout.challenger_bet),
            "juror_bond": str(treatment.payout.juror_bond),
            "financial_metric_units": "harness_tokens",
            "creator_model": treatment.creator_model,
            "challenger_model": treatment.challenger_model,
            "juror_model": treatment.juror_model,
            "auditor_model": treatment.auditor_model,
            "creator_provider": treatment.creator_provider,
            "challenger_provider": treatment.challenger_provider,
            "juror_provider": treatment.juror_provider,
            "auditor_provider": treatment.auditor_provider,
            "scripted_creator": treatment.use_scripted_creator,
            "scripted_challenger": treatment.use_scripted_challenger,
            "scripted_jurors": len(treatment.scripted_juror_indices),
            "scripted_auditors": len(treatment.scripted_auditor_indices),
            "temperature": AgentConfig.__dataclass_fields__["temperature"].default,
            "max_tokens": AgentConfig.__dataclass_fields__["max_tokens"].default,
            "openrouter_provider_routing": OPENROUTER_PROVIDER,
            "cot_monitor_model": treatment.cot_monitor_model,
            "cot_rogue_threshold": ROGUE_THRESHOLD if treatment.cot_monitor_model else None,
            "cot_action_weight": ACTION_WEIGHT if treatment.cot_monitor_model else None,
        }
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.run = self.sdk.init(
            project=self.project, entity=self.entity, name=self.name, group=self.group,
            job_type=self.purpose, tags=["jury", self.backend, self.purpose], config=config,
            mode="online", save_code=False, dir=str(self.output_dir),
            settings=self.sdk.Settings(
                console="off", disable_code=True, disable_git=True, x_disable_meta=True,
                x_disable_stats=True, x_disable_machine_info=True,
            ),
        )
        try:
            self.run.define_metric("episode")
            self.run.define_metric("jury/*", step_metric="episode")
            with (self.output_dir / "wandb_runs.jsonl").open("a") as output:
                json.dump({"name": self.name, "group": self.group, "run_id": self.run.id,
                           "url": self.run.url}, output)
                output.write("\n")
        except BaseException:
            self.run.finish(exit_code=1)
            raise
        return self

    def record_results(self, metrics: ExperimentMetrics):
        from metrics.jury import aggregate_jury_metrics, episode_jury_metrics

        self.failed = any(ep.infrastructure_failure or ep.status != "completed" for ep in metrics.episodes)
        self.failed |= len(metrics.episodes) != self.treatment.num_episodes
        summary = metrics.summary()
        for name in SUMMARY_METRICS:
            value = summary.get(name)
            if value is None or (isinstance(value, (int, float)) and math.isfinite(value)):
                self.run.summary[name] = value
        self.run.summary["experiment_id"] = metrics.experiment_id
        self.run.summary["participation_loss"] = float(metrics.participation_loss)
        rows = []
        history = []
        metric_names = []
        for index, episode in enumerate(metrics.episodes):
            jury = episode_jury_metrics(episode, history)
            history.append(episode)
            metric_names = list(jury)
            scalars = {f"jury/{name}": value for name, value in jury.items() if value is not None}
            self.run.log({"episode": index, **scalars})
            rows.append([
                episode.episode_id, episode.scenario_id, episode.status, episode.outcome,
                episode.infrastructure_failure, episode.ground_truth, episode.verdict_correct,
                *jury.values(),
            ])
        if rows:
            self.run.log({"episodes": self.sdk.Table(
                columns=["episode_id", "scenario_id", "status", "outcome",
                         "infrastructure_failure", "ground_truth", "verdict_correct", *metric_names],
                data=rows,
            )})
        for name, value in aggregate_jury_metrics(metrics.episodes).items():
            self.run.summary[f"block/{name}"] = value

    def __exit__(self, exception_type, exception, traceback):
        self.run.finish(exit_code=1 if exception_type is not None or self.failed else 0)
        return False
