//! Explicit local development and external deployment configuration.

use clap::{ArgGroup, Parser};
use serde::Deserialize;
use std::{collections::BTreeSet, net::SocketAddr, path::PathBuf};

use alloy::primitives::{Address, B256};

#[derive(Debug, Parser)]
#[command(name = "veracity-game-service", version, about = "Veracity game API")]
#[command(group(ArgGroup::new("mode").required(true).args(["local", "config"])))]
pub struct Cli {
    /// Start an isolated Anvil chain with development-only API credentials.
    #[arg(long)]
    pub local: bool,
    /// Attach to an explicitly identified deployed contract.
    #[arg(long)]
    pub config: Option<PathBuf>,
    #[arg(long, default_value = "127.0.0.1:8080")]
    pub bind: SocketAddr,
    /// SQLite path; local mode defaults to an ephemeral database.
    #[arg(long)]
    pub database: Option<PathBuf>,
    #[arg(long, default_value = "contracts/artifacts/Veracity.json")]
    pub artifact: PathBuf,
    /// Derive local accounts from this seed instead of Anvil's well-known defaults.
    #[arg(long)]
    pub local_key_seed: Option<u64>,
    /// Unix timestamp of the local chain's genesis block.
    #[arg(long)]
    pub local_genesis_timestamp: Option<u64>,
}

impl Cli {
    pub fn validate(&self) -> Result<(), String> {
        if !self.local && (self.local_key_seed.is_some() || self.local_genesis_timestamp.is_some())
        {
            return Err("local chain options require --local".into());
        }
        if self.local && !self.bind.ip().is_loopback() {
            return Err("local development credentials require a loopback listener".into());
        }
        if self.local
            && self
                .database
                .as_ref()
                .is_some_and(|path| path.metadata().is_ok_and(|metadata| metadata.len() > 0))
        {
            return Err("local mode creates a fresh chain; use a new database or --config to resume an existing deployment".into());
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct DeploymentConfig {
    pub rpc_url: String,
    pub expected_chain_id: u64,
    pub contract_address: String,
    pub expected_code_hash: String,
    pub confirmation_depth: u64,
    pub max_gas_limit: u64,
    pub max_fee_per_gas_wei: String,
    pub operator_id: String,
    pub operator_token_env: String,
    pub participants: Vec<ParticipantConfig>,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ParticipantConfig {
    pub id: String,
    pub private_key_env: String,
    pub token_env: String,
}

impl DeploymentConfig {
    pub fn validate(&self) -> Result<(), String> {
        if !matches!(self.expected_chain_id, 31337 | 80002) {
            return Err("only explicitly configured Anvil (31337) and Amoy (80002) deployments are supported".into());
        }
        let endpoint = url::Url::parse(&self.rpc_url).map_err(|_| "invalid RPC URL".to_owned())?;
        if !matches!(endpoint.scheme(), "http" | "https") || endpoint.host_str().is_none() {
            return Err("RPC URL must use HTTP or HTTPS and include a host".into());
        }
        if !self
            .contract_address
            .parse::<Address>()
            .is_ok_and(|value| !value.is_zero())
            || !self
                .expected_code_hash
                .parse::<B256>()
                .is_ok_and(|value| !value.is_zero())
        {
            return Err(
                "a nonzero contract address and exact runtime code hash are required".into(),
            );
        }
        if self.confirmation_depth == 0
            || self.max_gas_limit == 0
            || !self
                .max_fee_per_gas_wei
                .parse::<u128>()
                .is_ok_and(|value| value > 0)
        {
            return Err(
                "confirmation depth and transaction budgets must be positive integers".into(),
            );
        }
        let mut participant_ids = BTreeSet::new();
        for participant in &self.participants {
            if participant.id.is_empty() || !participant_ids.insert(&participant.id) {
                return Err("participant IDs must be nonempty and unique".into());
            }
            for reference in [&participant.private_key_env, &participant.token_env] {
                validate_environment_reference(reference)?;
            }
        }
        if !participant_ids.contains(&self.operator_id) {
            return Err("operator_id must name a configured signer".into());
        }
        validate_environment_reference(&self.operator_token_env)?;
        Ok(())
    }
}

fn validate_environment_reference(reference: &str) -> Result<(), String> {
    if reference.is_empty()
        || reference
            .bytes()
            .any(|byte| !(byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_'))
        || reference.as_bytes()[0].is_ascii_digit()
    {
        return Err("secrets must reference uppercase environment variable names".into());
    }
    Ok(())
}
