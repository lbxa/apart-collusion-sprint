use alloy::primitives::{Address, B256, Bytes, U256};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Clone, Debug)]
pub struct ChainConfig {
    pub rpc_url: String,
    pub expected_chain_id: u64,
    pub contract_address: Address,
    pub expected_code_hash: B256,
    pub confirmation_depth: u64,
    pub max_gas_limit: u64,
    pub max_fee_per_gas: u128,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct DeploymentIdentity {
    pub chain_id: u64,
    pub contract_address: Address,
    pub code_hash: B256,
    pub abi_version: u64,
    pub confirmation_depth: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ContractConfig {
    pub creator: Address,
    pub challenger: Address,
    pub jurors: Vec<Address>,
    pub treasury: Address,
    pub configuration_hash: B256,
    pub beta: U256,
    pub gamma_bps: u16,
    pub winner_bps: u16,
    pub juror_bps: u16,
    pub protocol_bps: u16,
    pub posting_duration: u64,
    pub challenge_duration: u64,
    pub commit_duration: u64,
    pub reveal_duration: u64,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum State {
    Unknown,
    Registered,
    Open,
    Commit,
    Reveal,
    SettledCreator,
    SettledChallenger,
    Aborted,
    ExpiredUnchallenged,
    ExpiredUnfunded,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct EpisodeSnapshot {
    pub config: ContractConfig,
    pub content_hash: B256,
    pub evidence_hash: B256,
    pub posting_deadline: u64,
    pub challenge_deadline: u64,
    pub commit_deadline: u64,
    pub reveal_deadline: u64,
    pub state: State,
    pub creator_votes: u8,
    pub challenger_votes: u8,
    pub juror_bond: U256,
    pub locked_liability: U256,
    pub total_deposited: U256,
    pub total_credited: U256,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct JurorSnapshot {
    pub commitment: B256,
    pub assessment_hash: B256,
    pub revealed: bool,
    pub verdict: u8,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct SettlementSnapshot {
    pub outcome: State,
    pub winner: Address,
    pub winner_payout: U256,
    pub juror_reward: U256,
    pub protocol_fee: U256,
    pub forfeited_bonds: U256,
}

/// Private command input. In particular, never log or export reveal material.
pub enum ChainAction {
    Register {
        episode_id: B256,
        config: ContractConfig,
    },
    PostClaim {
        episode_id: B256,
        content_hash: B256,
    },
    Challenge {
        episode_id: B256,
        evidence_hash: B256,
    },
    CommitVote {
        episode_id: B256,
        commitment: B256,
    },
    RevealVote {
        episode_id: B256,
        verdict: u8,
        assessment_hash: B256,
        salt: B256,
    },
    Settle {
        episode_id: B256,
    },
    Expire {
        episode_id: B256,
    },
    Withdraw,
}

/// Persist this record before calling `broadcast`; retries reuse these exact bytes.
#[derive(Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PreparedTransaction {
    pub sender: Address,
    pub nonce: u64,
    pub tx_hash: B256,
    pub raw: Bytes,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct LogEvidence {
    pub chain_id: u64,
    pub contract_address: Address,
    pub block_number: u64,
    pub block_hash: B256,
    pub transaction_hash: B256,
    pub log_index: u64,
    pub topics: Vec<B256>,
    pub data: Bytes,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq)]
pub struct ReceiptEvidence {
    pub transaction_hash: B256,
    pub success: bool,
    pub block_number: u64,
    pub block_hash: B256,
    pub gas_used: u64,
    pub effective_gas_price: u128,
    pub confirmations: u64,
    pub confirmed: bool,
    pub logs: Vec<LogEvidence>,
}

#[derive(Debug, Error)]
pub enum ChainError {
    #[error("invalid chain configuration: {0}")]
    Configuration(String),
    #[error("only explicitly configured Anvil (31337) and Amoy (80002) are supported")]
    UnsupportedChain,
    #[error("deployment identity does not match the configured chain, code hash, or ABI")]
    IdentityMismatch,
    #[error("no isolated signer is configured for participant {0}")]
    UnknownActor(String),
    #[error("contract rejected the action: {0}")]
    Rejected(String),
    #[error("the authoritative contract has no registered episode with this identifier")]
    UnknownEpisode,
    #[error("chain RPC unavailable: {0}")]
    Unavailable(String),
    #[error("participant balance cannot cover the bond and configured transaction gas")]
    InsufficientFunds,
    #[error("estimated transaction exceeds the configured gas or fee budget")]
    BudgetExceeded,
    #[error("this signer has an unresolved prepared transaction")]
    OutstandingTransaction,
    #[error("receipt block is no longer canonical")]
    Reorganized,
}
