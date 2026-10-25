"""Validated wire types for the Rust engine's versioned API.

Financial strings stay exact here; conversion to harness display units happens
only after validation. Keep these fields aligned with core/src/game/types.rs.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Money = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)$")]
Vote = Literal["CREATOR_SUPPORTED", "CHALLENGER_SUPPORTED"]
EnginePhase = Literal[
    "REGISTERED", "OPEN", "COMMIT", "REVEAL", "SETTLED_CREATOR",
    "SETTLED_CHALLENGER", "ABORTED", "EXPIRED_UNCHALLENGED", "EXPIRED_UNFUNDED",
]


class WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True,
                              hide_input_in_errors=True)


class Deployment(WireModel):
    chain_id: int
    contract_address: str
    code_hash: str
    abi_version: int
    confirmation_depth: int
    finality_policy: str


class Startup(WireModel):
    api_url: str
    rpc_url: str
    deployment: Deployment


class Health(WireModel):
    status: Literal["ok"]
    api_version: Literal["v1"]
    deployment: Deployment


class Receipt(WireModel):
    transaction_hash: str
    success: bool
    block_number: int
    block_hash: str
    gas_used: Money
    effective_gas_price: Money
    confirmations: int
    confirmed: bool


class Transaction(WireModel):
    transaction_hash: str
    sender: str
    nonce: int
    receipt: Receipt | None


class Operation(WireModel):
    operation_id: str
    episode_id: str
    actor_id: str
    kind: str
    status: Literal["accepted", "prepared", "submitted", "included",
                    "confirmed", "reverted", "failed"]
    transaction: Transaction | None
    error: str | None


class Juror(WireModel):
    actor_id: str
    commitment: str | None
    revealed: bool
    verdict: Vote | None
    assessment_hash: str | None


class Parameters(WireModel):
    beta_wei: Money
    gamma_bps: int
    winner_bps: int
    juror_bps: int
    protocol_bps: int
    posting_duration_secs: int
    challenge_duration_secs: int
    commit_duration_secs: int
    reveal_duration_secs: int


class Registration(WireModel):
    episode_id: str
    experiment_id: str
    scenario_id: str
    creator_id: str
    challenger_id: str
    juror_ids: list[str]
    treasury_id: str
    parameters: Parameters
    provenance: dict[str, str]


class Episode(WireModel):
    episode_id: str
    onchain_episode_id: str
    configuration_hash: str
    configuration: Registration
    phase: EnginePhase
    posting_deadline: int
    challenge_deadline: int
    commit_deadline: int
    reveal_deadline: int
    content_hash: str | None
    evidence_hash: str | None
    content: str | None
    evidence: str | None
    jurors: list[Juror]
    creator_votes: int
    challenger_votes: int
    required_votes: int
    juror_bond_wei: Money
    locked_liability_wei: Money
    total_deposited_wei: Money
    total_credited_wei: Money
    deployment: Deployment


class Settlement(WireModel):
    episode_id: str
    outcome: EnginePhase
    final_votes: dict[str, Vote]
    winner_id: str | None
    winner_payout: Money
    juror_payouts: dict[str, Money]
    protocol_fee: Money
    forfeited_bonds: dict[str, Money]
    refunds: dict[str, Money]
    total_deposited: Money
    total_credited: Money
    deployment: Deployment


class Balances(WireModel):
    episode_id: str
    entitlements: dict[str, Money]
    withdrawal_credits: dict[str, Money]
