"""Validated experimental inputs; no game strategy lives in configuration."""

import tomllib
from pathlib import Path
from typing import Literal, Self

from game_api.generated import ProtocolParameters, Verdict
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReasoningSettings(Settings):
    effort: Literal["max", "xhigh", "high", "medium", "low", "minimal", "none"] | None = None
    max_tokens: int | None = Field(default=None, ge=1)
    enabled: bool | None = None
    exclude: bool | None = None
    summary: Literal["auto", "concise", "detailed"] | None = None

    @model_validator(mode="after")
    def validate_budget_choice(self) -> Self:
        if self.effort is not None and self.max_tokens is not None:
            raise ValueError("Choose reasoning effort or a reasoning token budget, not both")
        return self


class ModelSettings(Settings):
    name: str = Field(min_length=1, pattern=r"^\S+$")
    max_tokens: int = Field(default=4096, ge=256)
    reasoning: ReasoningSettings | None = None
    calls_per_turn: int = Field(default=12, ge=1, le=100)
    calls_per_episode: int = Field(default=120, ge=1, le=2000)
    turn_timeout_seconds: int = Field(default=180, ge=5, le=1800)

    @model_validator(mode="after")
    def validate_reasoning_budget(self) -> Self:
        if (
            self.reasoning is not None
            and self.reasoning.max_tokens is not None
            and self.reasoning.max_tokens >= self.max_tokens
        ):
            raise ValueError("Reasoning tokens must leave room within the total completion budget")
        return self


class Treatment(Settings):
    public_messaging: bool = True
    private_chat: bool = False
    private_history: bool = False
    private_communication_prohibited: bool = True
    memory: bool = False


class Case(Settings):
    document: Path
    reference_claim: str | None = None
    expected_verdict: Verdict | None = None


class Experiment(Settings):
    name: str = Field(default="discovery", pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    episodes: int = Field(default=1, ge=1, le=1000)
    jury_size: Literal[3, 5, 7] = 3
    opportunities_per_phase: int = Field(default=2, ge=1, le=20)
    seed: int = 0
    model: ModelSettings
    treatment: Treatment = Treatment()
    case: Case
    parameters: ProtocolParameters = ProtocolParameters(
        beta_wei="1000000",
        gamma_bps=1000,
        posting_duration_secs=3600,
        challenge_duration_secs=3600,
        commit_duration_secs=3600,
        reveal_duration_secs=3600,
    )

    @model_validator(mode="after")
    def validate_protocol(self) -> Self:
        p = self.parameters
        if p.winner_bps + p.juror_bps + p.protocol_bps != 10000:
            raise ValueError("Payout shares must sum to 10000 basis points")
        if int(p.beta_wei) >= 2**128 or int(p.beta_wei) * p.gamma_bps // 10000 < 1:
            raise ValueError("Bond must fit uint128 and produce a positive juror bond")
        if self.case.expected_verdict and not self.case.reference_claim:
            raise ValueError("An expected verdict needs an exact reference claim")
        return self

    @property
    def actor_ids(self) -> tuple[str, ...]:
        return ("creator", "challenger", *(f"juror-{i}" for i in range(1, self.jury_size + 1)))


def load_experiment(path: Path, *, model_name: str | None = None) -> Experiment:
    data = tomllib.loads(path.read_text())
    if model_name is not None:
        model = data.get("model", {})
        if not isinstance(model, dict):
            raise ValueError("Model settings must be a TOML table")
        data = {**data, "model": {**model, "name": model_name}}
    experiment = Experiment.model_validate(data)
    document = (path.resolve().parent / experiment.case.document).resolve()
    if not document.is_file() or document.stat().st_size > 65536:
        raise ValueError("Case document must exist and fit within 64 KiB")
    document.read_text(encoding="utf-8")
    return experiment.model_copy(
        update={"case": experiment.case.model_copy(update={"document": document})}
    )
