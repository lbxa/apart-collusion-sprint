use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use utoipa::ToSchema;
use utoipa::openapi::schema::{ObjectBuilder, Type};

fn decimal_amount() -> ObjectBuilder {
    ObjectBuilder::new()
        .schema_type(Type::String)
        .pattern(Some("^(0|[1-9][0-9]*)$"))
}

fn amount_map() -> ObjectBuilder {
    ObjectBuilder::new()
        .schema_type(Type::Object)
        .additional_properties(Some(decimal_amount()))
}

fn phase_name() -> ObjectBuilder {
    ObjectBuilder::new()
        .schema_type(Type::String)
        .enum_values(Some([
            "REGISTERED",
            "OPEN",
            "COMMIT",
            "REVEAL",
            "SETTLED_CREATOR",
            "SETTLED_CHALLENGER",
            "ABORTED",
            "EXPIRED_UNCHALLENGED",
            "EXPIRED_UNFUNDED",
        ]))
}

fn operation_status() -> ObjectBuilder {
    ObjectBuilder::new()
        .schema_type(Type::String)
        .enum_values(Some([
            "accepted",
            "prepared",
            "submitted",
            "included",
            "confirmed",
            "reverted",
            "failed",
        ]))
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ProtocolParameters {
    /// Native currency base units as a canonical decimal integer, never a float.
    #[schema(pattern = "^[1-9][0-9]*$")]
    pub beta_wei: String,
    #[schema(minimum = 1, maximum = 9999)]
    pub gamma_bps: u16,
    #[serde(default = "default_winner_bps")]
    #[schema(default = 6000, minimum = 0, maximum = 10000)]
    pub winner_bps: u16,
    #[serde(default = "default_juror_bps")]
    #[schema(default = 3000, minimum = 0, maximum = 10000)]
    pub juror_bps: u16,
    #[serde(default = "default_protocol_bps")]
    #[schema(default = 1000, minimum = 0, maximum = 10000)]
    pub protocol_bps: u16,
    #[schema(minimum = 1, maximum = 9007199254740991u64)]
    pub posting_duration_secs: u64,
    #[schema(minimum = 1, maximum = 9007199254740991u64)]
    pub challenge_duration_secs: u64,
    #[schema(minimum = 1, maximum = 9007199254740991u64)]
    pub commit_duration_secs: u64,
    #[schema(minimum = 1, maximum = 9007199254740991u64)]
    pub reveal_duration_secs: u64,
}

const fn default_winner_bps() -> u16 {
    6000
}
const fn default_juror_bps() -> u16 {
    3000
}
const fn default_protocol_bps() -> u16 {
    1000
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct RegisterEpisode {
    pub episode_id: String,
    /// Optional legacy correlation tag; the engine does not manage experiments.
    #[serde(default)]
    #[schema(default = "")]
    pub experiment_id: String,
    /// Optional legacy correlation tag; scenarios are managed by the caller.
    #[serde(default)]
    #[schema(default = "")]
    pub scenario_id: String,
    pub creator_id: String,
    pub challenger_id: String,
    pub juror_ids: Vec<String>,
    pub treasury_id: String,
    pub parameters: ProtocolParameters,
    /// Optional opaque public metadata; never used for protocol decisions.
    #[serde(default)]
    #[schema(default = json!({}))]
    pub provenance: BTreeMap<String, String>,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Verdict {
    CreatorSupported,
    ChallengerSupported,
}

impl Verdict {
    pub const fn as_u8(self) -> u8 {
        match self {
            Self::CreatorSupported => 0,
            Self::ChallengerSupported => 1,
        }
    }
}

/// A private command; do not log this value or export stored command bodies.
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum GameAction {
    PostClaim {
        content: String,
    },
    Challenge {
        evidence: String,
    },
    CommitVote {
        verdict: Verdict,
        assessment: String,
    },
    RevealVote {},
    Settle {},
    Expire {},
    Withdraw {},
}

impl GameAction {
    pub const fn kind(&self) -> &'static str {
        match self {
            Self::PostClaim { .. } => "post_claim",
            Self::Challenge { .. } => "challenge",
            Self::CommitVote { .. } => "commit_vote",
            Self::RevealVote { .. } => "reveal_vote",
            Self::Settle { .. } => "settle",
            Self::Expire { .. } => "expire",
            Self::Withdraw { .. } => "withdraw",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct DeploymentView {
    pub chain_id: u64,
    pub contract_address: String,
    pub code_hash: String,
    pub abi_version: u64,
    pub confirmation_depth: u64,
    pub finality_policy: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct ParticipantView {
    pub actor_id: String,
    pub address: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct ReceiptView {
    pub transaction_hash: String,
    pub success: bool,
    pub block_number: u64,
    pub block_hash: String,
    #[schema(schema_with = decimal_amount)]
    pub gas_used: String,
    #[schema(schema_with = decimal_amount)]
    pub effective_gas_price: String,
    pub confirmations: u64,
    pub confirmed: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct TransactionView {
    pub transaction_hash: String,
    pub sender: String,
    pub nonce: u64,
    #[schema(required = true)]
    pub receipt: Option<ReceiptView>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct OperationView {
    pub operation_id: String,
    pub episode_id: String,
    pub actor_id: String,
    pub kind: String,
    #[schema(schema_with = operation_status)]
    pub status: String,
    #[schema(required = true)]
    pub transaction: Option<TransactionView>,
    #[schema(required = true)]
    pub error: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct JurorView {
    pub actor_id: String,
    #[schema(required = true)]
    pub commitment: Option<String>,
    pub revealed: bool,
    /// Absent until a valid reveal is included on-chain.
    #[schema(required = true)]
    pub verdict: Option<Verdict>,
    #[schema(required = true)]
    pub assessment_hash: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct EpisodeView {
    pub episode_id: String,
    pub onchain_episode_id: String,
    pub configuration_hash: String,
    pub configuration: RegisterEpisode,
    #[schema(schema_with = phase_name)]
    pub phase: String,
    pub posting_deadline: u64,
    pub challenge_deadline: u64,
    pub commit_deadline: u64,
    pub reveal_deadline: u64,
    #[schema(required = true)]
    pub content_hash: Option<String>,
    #[schema(required = true)]
    pub evidence_hash: Option<String>,
    #[schema(required = true)]
    pub content: Option<String>,
    #[schema(required = true)]
    pub evidence: Option<String>,
    pub jurors: Vec<JurorView>,
    pub creator_votes: u8,
    pub challenger_votes: u8,
    pub required_votes: usize,
    #[schema(schema_with = decimal_amount)]
    pub juror_bond_wei: String,
    #[schema(schema_with = decimal_amount)]
    pub locked_liability_wei: String,
    #[schema(schema_with = decimal_amount)]
    pub total_deposited_wei: String,
    #[schema(schema_with = decimal_amount)]
    pub total_credited_wei: String,
    pub deployment: DeploymentView,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct SettlementView {
    pub episode_id: String,
    #[schema(schema_with = phase_name)]
    pub outcome: String,
    pub final_votes: BTreeMap<String, Verdict>,
    #[schema(required = true)]
    pub winner_id: Option<String>,
    #[schema(schema_with = decimal_amount)]
    pub winner_payout: String,
    #[schema(schema_with = amount_map)]
    pub juror_payouts: BTreeMap<String, String>,
    /// Protocol share plus division dust, excluding forfeited juror bonds.
    #[schema(schema_with = decimal_amount)]
    pub protocol_fee: String,
    #[schema(schema_with = amount_map)]
    pub forfeited_bonds: BTreeMap<String, String>,
    /// Party refunds only; valid juror bond refunds are in juror_payouts.
    #[schema(schema_with = amount_map)]
    pub refunds: BTreeMap<String, String>,
    #[schema(schema_with = decimal_amount)]
    pub total_deposited: String,
    #[schema(schema_with = decimal_amount)]
    pub total_credited: String,
    pub deployment: DeploymentView,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct BalancesView {
    pub episode_id: String,
    /// Historical settlement entitlements belonging to this episode.
    #[schema(schema_with = amount_map)]
    pub entitlements: BTreeMap<String, String>,
    /// Current global contract credits, potentially spanning several episodes.
    #[schema(schema_with = amount_map)]
    pub withdrawal_credits: BTreeMap<String, String>,
}
