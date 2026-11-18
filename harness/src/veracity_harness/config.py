"""Validated experimental inputs; no game strategy lives in configuration."""

import json
import re
import tomllib
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from game_api.generated import ProtocolParameters, Verdict


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
    provider: Literal["openrouter", "cloudflare"] = "openrouter"
    max_tokens: int = Field(default=4096, ge=256)
    reasoning: ReasoningSettings | None = None
    calls_per_turn: int = Field(default=12, ge=1, le=100)
    calls_per_episode: int = Field(default=120, ge=1, le=2000)
    turn_timeout_seconds: int = Field(default=180, ge=5, le=1800)
    # Workers AI: about 20 requests a minute per account and model; kept just below.
    requests_per_minute: int = Field(default=18, ge=1, le=10000)
    sampling_seed: int | None = Field(default=None, ge=0, le=2**31 - 1)
    text_input_token_ceiling: int | None = Field(default=None, ge=8192, le=1048576)

    @model_validator(mode="after")
    def validate_reasoning_budget(self) -> Self:
        if (
            self.reasoning is not None
            and self.reasoning.max_tokens is not None
            and self.reasoning.max_tokens >= self.max_tokens
        ):
            raise ValueError("Reasoning tokens must leave room within the total completion budget")
        if (
            self.provider == "cloudflare"
            and self.reasoning is not None
            and self.reasoning.model_dump(exclude_none=True).keys() - {"effort"}
        ):
            raise ValueError("Cloudflare Workers AI accepts only a reasoning effort")
        return self


class Treatment(Settings):
    public_messaging: bool = True
    private_chat: bool = False
    private_history: bool = False
    private_communication_prohibited: bool = True
    # Preserve interface/instructions while withholding message-read delivery.
    # Attempted sends still reach the engine and remain in operator transcripts.
    message_delivery: Literal["normal", "suppressed"] = "normal"
    memory: bool = False
    # A writable cache mounted in every sandbox that is not described as a channel.
    shared_store: bool = False
    # Jurors are anonymous to the creator and challenger: per-case labels, and no
    # private chat between a party and a juror.
    anonymous_jury: bool = False
    # Accounts may move withdrawal credit to another participant in the current case.
    # The route appears in the account's API schema; no brief or guide describes it.
    transfers: bool = False


class Case(Settings):
    document: Path
    reference_claim: str | None = None
    expected_verdict: Verdict | None = None
    # The scripted challenge's evidence for a false claim in the account history.
    evidence: str | None = None
    # A JSON list of vouchers served one at a time by the gateway's records service.
    records: Path | None = None


class Experiment(Settings):
    name: str = Field(default="discovery", pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    episodes: int = Field(default=1, ge=1, le=1000)
    jury_size: Literal[3, 5, 7, 9, 11, 13, 15] = 3
    opportunities_per_phase: int = Field(default=2, ge=1, le=20)
    seed: int = 0
    model: ModelSettings
    treatment: Treatment = Treatment()
    case: Case | None = None
    # One case per episode, in order; otherwise every episode uses `case`.
    schedule: list[Case] = Field(default_factory=list)
    # A scripted publisher posts each case's reference claim instead of a model.
    creator: Literal["agent", "scripted"] = "agent"
    # A scripted challenger files each case's prepared evidence.
    challenger: Literal["agent", "scripted"] = "agent"
    # Finish deterministic setup before notifying evaluated jurors. This prevents
    # a juror observing a challenge and committing before a seeded offer exists.
    scripted_setup_first: bool = False
    # The party handed an impossible assignment to win at all costs: the creator must
    # get its statement (the reference claim) upheld, or the challenger must get the
    # published claim rejected. Its recruiting is prompted by the mandate; whether
    # jurors cooperate is what the condition measures.
    mandate: Literal["none", "creator", "challenger"] = "none"
    # A scripted party that posts a fixed offer to the jury on the forum when voting
    # opens: the controlled counterpart of a mandated model that may or may not recruit.
    offer_by: Literal["creator", "challenger"] | None = None
    offer: str | None = Field(default=None, min_length=1)
    offer_payment_wei: str | None = Field(default=None, pattern=r"^[1-9][0-9]*$")
    framing: Literal["hidden", "evaluation"] = "hidden"
    # payoff: the account keeps its earnings; operator: run for a client firm;
    # principal: run for a client firm whose plan expects growing earnings.
    # quota: run for a client firm whose monthly plan sets a revenue target.
    objective: Literal["payoff", "operator", "principal", "quota"] = "payoff"
    # Role -> monthly net revenue target in wei; roles earn very different amounts.
    revenue_targets_wei: dict[Literal["creator", "challenger", "juror"], str] = Field(
        default_factory=dict
    )
    # episodic: a fresh chain per case. continuous: one chain for the session with
    # its own accounts, a forward-moving clock, and readable earlier cases.
    network: Literal["episodic", "continuous"] = "episodic"
    # stepped: the harness jumps the chain clock between rounds. realtime: deadlines
    # arrive on the host clock that participants' shells show.
    clock: Literal["stepped", "realtime"] = "stepped"
    # roles: accounts are named for their roles. neutral: participants see stable
    # opaque names; the engine and audit logs keep the role ids.
    account_names: Literal["roles", "neutral"] = "roles"
    # Cases the account handled under a scripted policy before the session starts.
    history: list[Case] = Field(default_factory=list)
    constitution: Literal["enumerated", "principles"] = "enumerated"
    awareness_probe: bool = False
    # Actor id -> model name, for mixed lineups; other model settings are shared.
    lineup: dict[str, str] = Field(default_factory=dict)
    # Distinct records each account may retrieve per case from the records service.
    lookup_allowance: int | None = Field(default=None, ge=1, le=1000)
    # A juror played by a scripted policy that proposes dividing the inspection.
    scripted_peer: str | None = None
    # A scripted peer may inspect less than the account allowance; evaluated
    # jurors retain the full allowance, so honest individual inspection can be feasible.
    scripted_peer_inspection_count: int | None = Field(default=None, ge=1, le=1000)
    peer_offer: str | None = Field(default=None, min_length=1)
    # Several scripted jurors, each posting its own message and committing `peer_verdict`
    # before evaluated jurors are notified: the swarm form of `scripted_peer`/`peer_offer`.
    peer_offers: dict[str, Annotated[str, Field(min_length=1)]] = Field(default_factory=dict)
    peer_verdict: Verdict | None = None
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
        if (self.case is None) == (not self.schedule):
            raise ValueError("Choose a case or a schedule")
        if self.schedule and len(self.schedule) != self.episodes:
            raise ValueError("The schedule needs exactly one case per episode")
        cases = self.schedule or [self.case]
        if any(case.expected_verdict and not case.reference_claim for case in cases):
            raise ValueError("An expected verdict needs an exact reference claim")
        if self.mandate != "none" and (
            self.mandate in self.scripted_actors or not all(case.reference_claim for case in cases)
        ):
            raise ValueError("A mandate needs a model party and a statement per case")
        if (self.offer_by is None) != (self.offer is None):
            raise ValueError("A scripted offer needs both the offering party and its text")
        if self.offer_by is not None and self.offer_by not in self.scripted_actors:
            raise ValueError("A scripted offer comes from a scripted party")
        if self.scripted_setup_first and (
            self.creator != "scripted" or self.challenger != "scripted"
        ):
            raise ValueError("Scripted setup first needs both parties scripted")
        if self.offer_payment_wei is not None and (
            self.offer_by is None or not self.treatment.transfers
        ):
            raise ValueError("Paid scripted offers need an offering party and transfers")
        if self.mandate == "challenger" and not all(case.evidence for case in cases):
            raise ValueError("A challenger mandate needs the client's challenge for every case")
        if self.challenger == "scripted" and not all(case.evidence for case in cases):
            raise ValueError("A scripted challenger needs evidence for every case")
        if self.creator == "scripted" and not all(case.reference_claim for case in cases):
            raise ValueError("A scripted publisher needs a reference claim for every case")
        if (self.lookup_allowance is None) != (not any(case.records for case in cases)):
            raise ValueError("Voucher records and a lookup allowance go together")
        if self.lookup_allowance is not None and not all(case.records for case in cases):
            raise ValueError("Every case needs voucher records when the service is on")
        if self.scripted_peer_inspection_count is not None and (
            self.scripted_peer is None
            or self.lookup_allowance is None
            or self.scripted_peer_inspection_count > self.lookup_allowance
        ):
            raise ValueError(
                "A scripted peer inspection count needs the records peer and fits its allowance"
            )
        if self.peer_offers and (self.scripted_peer is not None or self.peer_offer is not None):
            raise ValueError("Configure scripted juror peers one way: peer_offers or scripted_peer")
        if self.peer_offers and self.peer_verdict is None:
            raise ValueError("Scripted juror peers need a peer verdict")
        if self.peer_offers and self.lookup_allowance is not None:
            raise ValueError("Scripted juror peers with messages run without voucher records")
        if not set(self.peer_offers) <= {a for a in self.actor_ids if a.startswith("juror-")}:
            raise ValueError("Each scripted juror peer must be a juror on the roster")
        if not self.peer_offers and (self.peer_offer is None) != (self.peer_verdict is None):
            raise ValueError("A peer offer needs both text and a peer verdict")
        if self.peer_offer is not None and (
            self.scripted_peer is None or self.lookup_allowance is not None
        ):
            raise ValueError("A peer offer needs a scripted peer without voucher records")
        if self.scripted_peer is not None and (
            not self.scripted_peer.startswith("juror-") or self.scripted_peer not in self.actor_ids
        ):
            raise ValueError("A scripted peer must be a juror on the roster")
        if (
            self.scripted_peer is not None
            and self.peer_offer is None
            and (self.lookup_allowance is None or not all(case.expected_verdict for case in cases))
        ):
            raise ValueError("A scripted juror peer needs the records service and verdicts")
        played = {
            actor.split("-", 1)[0] for actor in self.actor_ids if actor not in self.scripted_actors
        }
        if self.objective == "quota" and not played <= self.revenue_targets_wei.keys():
            raise ValueError("The quota objective needs a revenue target for every played role")
        if self.objective != "quota" and self.revenue_targets_wei:
            raise ValueError("Only the quota objective takes revenue targets")
        if not all(re.fullmatch(r"[1-9][0-9]*", v) for v in self.revenue_targets_wei.values()):
            raise ValueError("Revenue targets are positive integers in wei")
        if self.clock == "realtime" and self.network != "continuous":
            raise ValueError("A realtime clock needs a continuous network")
        if self.history and self.network != "continuous":
            raise ValueError("Account history needs a continuous network")
        if not all(case.reference_claim and case.expected_verdict for case in self.history):
            raise ValueError("Each history case needs a reference claim and expected verdict")
        if any(
            case.expected_verdict == "CHALLENGER_SUPPORTED" and not case.evidence
            for case in self.history
        ):
            raise ValueError("A false claim in the account history needs challenge evidence")
        if not self.lineup.keys() <= set(self.actor_ids):
            raise ValueError("A lineup names only actors on the case roster")
        if self.scripted_actors & self.lineup.keys():
            raise ValueError("A scripted actor plays without a model; no lineup entry applies")
        for name in self.lineup.values():
            ModelSettings.model_validate({**self.model.model_dump(), "name": name})
        return self

    def model_for(self, actor: str) -> ModelSettings:
        if actor not in self.lineup:
            return self.model
        return self.model.model_copy(update={"name": self.lineup[actor]})

    @property
    def model_names(self) -> set[str]:
        """Every model that plays an actor, each priced and recorded once."""
        played = [actor for actor in self.actor_ids if actor not in self.scripted_actors]
        return {self.model_for(actor).name for actor in played}

    @property
    def peer_jurors(self) -> tuple[str, ...]:
        """Jurors played by scripted peer policies, in roster order."""
        peers = set(self.peer_offers) | ({self.scripted_peer} if self.scripted_peer else set())
        return tuple(actor for actor in self.actor_ids if actor in peers)

    def peer_message(self, actor: str) -> str | None:
        """The message a scripted peer juror posts, if it posts one."""
        if actor == self.scripted_peer:
            return self.peer_offer
        return self.peer_offers.get(actor)

    @property
    def scripted_actors(self) -> set[str]:
        """Actors played by deterministic policies rather than models."""
        return (
            ({"creator"} if self.creator == "scripted" else set())
            | ({"challenger"} if self.challenger == "scripted" else set())
            | set(self.peer_jurors)
        )

    def case_for(self, index: int) -> Case:
        return self.schedule[index] if self.schedule else self.case

    @property
    def actor_ids(self) -> tuple[str, ...]:
        return ("creator", "challenger", *(f"juror-{i}" for i in range(1, self.jury_size + 1)))


def load_experiment(
    path: Path,
    *,
    model_name: str | None = None,
    seed: int | None = None,
    provider: str | None = None,
) -> Experiment:
    data = tomllib.loads(path.read_text())
    if seed is not None:
        data = {**data, "seed": seed}
    overrides = {
        key: value
        for key, value in (("name", model_name), ("provider", provider))
        if value is not None
    }
    if overrides:
        model = data.get("model", {})
        if not isinstance(model, dict):
            raise ValueError("Model settings must be a TOML table")
        data = {**data, "model": {**model, **overrides}}
    experiment = Experiment.model_validate(data)

    def resolved(case: Case) -> Case:
        document = (path.resolve().parent / case.document).resolve()
        if not document.is_file() or document.stat().st_size > 65536:
            raise ValueError("Case document must exist and fit within 64 KiB")
        document.read_text(encoding="utf-8")
        records = None
        if case.records is not None:
            records = (path.resolve().parent / case.records).resolve()
            if not records.is_file() or records.stat().st_size > 1_048_576:
                raise ValueError("Voucher records must exist and fit within 1 MiB")
            rows = json.loads(records.read_text(encoding="utf-8"))
            if not rows or not all(isinstance(row, dict) and "id" in row for row in rows):
                raise ValueError("Voucher records must be a list of objects with ids")
        return case.model_copy(update={"document": document, "records": records})

    return experiment.model_copy(
        update={
            "case": experiment.case and resolved(experiment.case),
            "schedule": [resolved(case) for case in experiment.schedule],
            "history": [resolved(case) for case in experiment.history],
        }
    )
