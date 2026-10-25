use std::{collections::BTreeMap, future::Future, path::Path, time::Duration};

use alloy::{
    eips::eip2718::Encodable2718,
    network::{EthereumWallet, TransactionBuilder},
    primitives::{Address, B256, Bytes, U256, keccak256},
    providers::{DynProvider, Provider, ProviderBuilder},
    rpc::types::{BlockNumberOrTag, Filter, Log, TransactionRequest},
    signers::local::PrivateKeySigner,
    sol_types::{SolError, SolType, SolValue},
    transports::http::reqwest::Client as HttpClient,
    transports::{TransportError, TransportErrorKind},
};
use backon::{ExponentialBuilder, Retryable};
use serde::Deserialize;

use super::types::*;

mod bindings {
    alloy::sol!(
        #![sol(rpc)]
        "../contracts/src/Veracity.sol"
    );
}

/// One adapter owns the configured signers. Hold the application's operation
/// mutex across preparation, durable persistence, and broadcast. The mutable
/// preparation API and in-flight reservation prevent concurrent nonce reuse.
pub struct ChainClient {
    provider: DynProvider,
    config: ChainConfig,
    identity: DeploymentIdentity,
    operator_address: Address,
    signers: BTreeMap<String, PrivateKeySigner>,
    in_flight: BTreeMap<Address, (u64, B256)>,
}

pub fn commitment_hash(
    chain_id: u64,
    contract: Address,
    episode: B256,
    juror: Address,
    verdict: u8,
    assessment_hash: B256,
    salt: B256,
) -> B256 {
    type Commitment = alloy::sol!((uint256, address, bytes32, address, uint8, bytes32, bytes32));
    keccak256(Commitment::abi_encode(&(
        U256::from(chain_id),
        contract,
        episode,
        juror,
        verdict,
        assessment_hash,
        salt,
    )))
}

impl ChainClient {
    /// Use ten-second HTTP requests and a three-second connection timeout.
    pub async fn connect(
        config: ChainConfig,
        signers: BTreeMap<String, PrivateKeySigner>,
    ) -> Result<Self, ChainError> {
        Self::connect_with_rpc_timeout(config, signers, Duration::from_secs(10)).await
    }

    #[tracing::instrument(name = "chain.connect", skip_all, err)]
    pub async fn connect_with_rpc_timeout(
        config: ChainConfig,
        signers: BTreeMap<String, PrivateKeySigner>,
        timeout: Duration,
    ) -> Result<Self, ChainError> {
        if !matches!(config.expected_chain_id, 31337 | 80002) {
            return Err(ChainError::UnsupportedChain);
        }
        if config.confirmation_depth == 0
            || config.max_gas_limit == 0
            || config.max_fee_per_gas == 0
        {
            return Err(ChainError::Configuration(
                "confirmation depth and transaction budgets must be positive".into(),
            ));
        }
        let provider = ProviderBuilder::new()
            .connect_reqwest(
                rpc_http_client(timeout)?,
                config
                    .rpc_url
                    .parse()
                    .map_err(|_| ChainError::Configuration("invalid RPC URL".into()))?,
            )
            .erased();
        let chain_id = retry_rpc(|| async { provider.get_chain_id().await }, transient_rpc)
            .await
            .map_err(unavailable)?;
        if chain_id != config.expected_chain_id {
            return Err(ChainError::IdentityMismatch);
        }
        let code = retry_rpc(
            || async { provider.get_code_at(config.contract_address).await },
            transient_rpc,
        )
        .await
        .map_err(unavailable)?;
        if code.is_empty() || keccak256(&code) != config.expected_code_hash {
            return Err(ChainError::IdentityMismatch);
        }
        let contract = bindings::Veracity::new(config.contract_address, &provider);
        let abi = retry_rpc(
            || async { contract.ABI_VERSION().call().await },
            transient_contract,
        )
        .await
        .map_err(identity_call_error)?;
        if abi != U256::from(1) {
            return Err(ChainError::IdentityMismatch);
        }
        let operator_address = retry_rpc(
            || async { contract.operator().call().await },
            transient_contract,
        )
        .await
        .map_err(identity_call_error)?;
        if operator_address == Address::ZERO {
            return Err(ChainError::IdentityMismatch);
        }
        let identity = DeploymentIdentity {
            chain_id,
            contract_address: config.contract_address,
            code_hash: config.expected_code_hash,
            abi_version: 1,
            confirmation_depth: config.confirmation_depth,
        };
        tracing::info!(event = "chain.connected", chain_id, contract_address = %config.contract_address, abi_version = 1_u64, "Deployment identity verified");
        Ok(Self {
            provider,
            config,
            identity,
            operator_address,
            signers,
            in_flight: BTreeMap::new(),
        })
    }

    pub fn identity(&self) -> &DeploymentIdentity {
        &self.identity
    }

    pub fn operator_address(&self) -> Address {
        self.operator_address
    }

    pub fn address(&self, actor_id: &str) -> Result<Address, ChainError> {
        self.signers
            .get(actor_id)
            .map(|signer| signer.address())
            .ok_or_else(|| ChainError::UnknownActor(actor_id.into()))
    }

    pub fn participants(&self) -> BTreeMap<String, Address> {
        self.signers
            .iter()
            .map(|(id, signer)| (id.clone(), signer.address()))
            .collect()
    }

    pub async fn timestamp(&self) -> Result<u64, ChainError> {
        let block = retry_rpc(
            || async {
                self.provider
                    .get_block_by_number(BlockNumberOrTag::Latest)
                    .await
            },
            transient_rpc,
        )
        .await
        .map_err(unavailable)?
        .ok_or_else(|| ChainError::Unavailable("latest block is unavailable".into()))?;
        Ok(block.header.timestamp)
    }

    pub async fn block_number(&self) -> Result<u64, ChainError> {
        retry_rpc(
            || async { self.provider.get_block_number().await },
            transient_rpc,
        )
        .await
        .map_err(unavailable)
    }

    /// Replay one bounded, inclusive range. Callers page in ranges of at most
    /// 10,000 blocks and retain block hashes to rewind after a reorganisation.
    pub async fn logs(
        &self,
        from_block: u64,
        to_block: u64,
    ) -> Result<Vec<LogEvidence>, ChainError> {
        if to_block < from_block || to_block - from_block >= 10_000 {
            return Err(ChainError::Configuration(
                "log ranges must include between one and 10000 blocks".into(),
            ));
        }
        let end_hash = self.canonical_block_hash(to_block).await?.ok_or_else(|| {
            ChainError::Unavailable("requested log range is not included yet".into())
        })?;
        let filter = Filter::new()
            .address(self.config.contract_address)
            .from_block(from_block)
            .to_block(to_block);
        let logs = retry_rpc(
            || async { self.provider.get_logs(&filter).await },
            transient_rpc,
        )
        .await
        .map_err(unavailable)?;
        if self.canonical_block_hash(to_block).await? != Some(end_hash) {
            return Err(ChainError::Reorganized);
        }
        logs.iter()
            .filter(|log| log.address() == self.config.contract_address)
            .map(|log| {
                let evidence = self.log_evidence(log)?;
                if evidence.block_number < from_block || evidence.block_number > to_block {
                    return Err(ChainError::Unavailable(
                        "RPC returned a log outside the requested range".into(),
                    ));
                }
                Ok(evidence)
            })
            .collect()
    }

    pub async fn nonce(&self, sender: Address) -> Result<u64, ChainError> {
        retry_rpc(
            || async { self.provider.get_transaction_count(sender).pending().await },
            transient_rpc,
        )
        .await
        .map_err(unavailable)
    }

    pub async fn balance(&self, sender: Address) -> Result<U256, ChainError> {
        retry_rpc(
            || async { self.provider.get_balance(sender).await },
            transient_rpc,
        )
        .await
        .map_err(unavailable)
    }

    pub async fn episode(&self, episode_id: B256) -> Result<EpisodeSnapshot, ChainError> {
        let contract = bindings::Veracity::new(self.config.contract_address, &self.provider);
        let view = retry_rpc(
            || async { contract.getEpisode(episode_id).call().await },
            transient_contract,
        )
        .await
        .map_err(contract_error)?;
        Ok(EpisodeSnapshot {
            config: from_contract_config(view.config),
            content_hash: view.contentHash,
            evidence_hash: view.evidenceHash,
            posting_deadline: view.postingDeadline,
            challenge_deadline: view.challengeDeadline,
            commit_deadline: view.commitDeadline,
            reveal_deadline: view.revealDeadline,
            state: from_contract_state(view.state)?,
            creator_votes: view.creatorVotes,
            challenger_votes: view.challengerVotes,
            juror_bond: view.jurorBond,
            locked_liability: view.lockedLiability,
            total_deposited: view.totalDeposited,
            total_credited: view.totalCredited,
        })
    }

    pub async fn juror(
        &self,
        episode_id: B256,
        address: Address,
    ) -> Result<JurorSnapshot, ChainError> {
        let contract = bindings::Veracity::new(self.config.contract_address, &self.provider);
        let view = retry_rpc(
            || async { contract.getJuror(episode_id, address).call().await },
            transient_contract,
        )
        .await
        .map_err(contract_error)?;
        Ok(JurorSnapshot {
            commitment: view.commitment,
            assessment_hash: view.assessmentHash,
            revealed: view.revealed,
            verdict: view.verdict,
        })
    }

    pub async fn settlement(&self, episode_id: B256) -> Result<SettlementSnapshot, ChainError> {
        let contract = bindings::Veracity::new(self.config.contract_address, &self.provider);
        let view = retry_rpc(
            || async { contract.getSettlement(episode_id).call().await },
            transient_contract,
        )
        .await
        .map_err(contract_error)?;
        Ok(SettlementSnapshot {
            outcome: from_contract_state(view.outcome)?,
            winner: view.winner,
            winner_payout: view.winnerPayout,
            juror_reward: view.jurorReward,
            protocol_fee: view.protocolFee,
            forfeited_bonds: view.forfeitedBonds,
        })
    }

    pub async fn credits(&self, address: Address) -> Result<U256, ChainError> {
        let contract = bindings::Veracity::new(self.config.contract_address, &self.provider);
        retry_rpc(
            || async { contract.credits(address).call().await },
            transient_contract,
        )
        .await
        .map_err(contract_error)
    }

    pub async fn entitlement(
        &self,
        episode_id: B256,
        address: Address,
    ) -> Result<U256, ChainError> {
        let contract = bindings::Veracity::new(self.config.contract_address, &self.provider);
        retry_rpc(
            || async { contract.entitlement(episode_id, address).call().await },
            transient_contract,
        )
        .await
        .map_err(contract_error)
    }

    pub async fn phase(&self, episode_id: B256) -> Result<State, ChainError> {
        let contract = bindings::Veracity::new(self.config.contract_address, &self.provider);
        let state = retry_rpc(
            || async { contract.phase(episode_id).call().await },
            transient_contract,
        )
        .await
        .map_err(contract_error)?;
        from_contract_state(state)
    }

    #[tracing::instrument(name = "chain.prepare", skip_all, fields(actor_id), err)]
    pub async fn prepare(
        &mut self,
        actor_id: &str,
        action: ChainAction,
    ) -> Result<PreparedTransaction, ChainError> {
        let sender = self.address(actor_id)?;
        let nonce = self.nonce(sender).await?;
        if self
            .in_flight
            .get(&sender)
            .is_some_and(|(reserved, _)| *reserved >= nonce)
        {
            return Err(ChainError::OutstandingTransaction);
        }
        let contract = bindings::Veracity::new(self.config.contract_address, &self.provider);
        let (data, value) = match action {
            ChainAction::Register { episode_id, config } => (
                contract
                    .registerEpisode(episode_id, into_contract_config(config))
                    .calldata()
                    .clone(),
                U256::ZERO,
            ),
            ChainAction::PostClaim {
                episode_id,
                content_hash,
            } => (
                contract
                    .postClaim(episode_id, content_hash)
                    .calldata()
                    .clone(),
                self.episode(episode_id).await?.config.beta,
            ),
            ChainAction::Challenge {
                episode_id,
                evidence_hash,
            } => (
                contract
                    .challenge(episode_id, evidence_hash)
                    .calldata()
                    .clone(),
                self.episode(episode_id).await?.config.beta,
            ),
            ChainAction::CommitVote {
                episode_id,
                commitment,
            } => (
                contract
                    .commitVote(episode_id, commitment)
                    .calldata()
                    .clone(),
                self.episode(episode_id).await?.juror_bond,
            ),
            ChainAction::RevealVote {
                episode_id,
                verdict,
                assessment_hash,
                salt,
            } => (
                contract
                    .revealVote(episode_id, verdict, assessment_hash, salt)
                    .calldata()
                    .clone(),
                U256::ZERO,
            ),
            ChainAction::Settle { episode_id } => {
                (contract.settle(episode_id).calldata().clone(), U256::ZERO)
            }
            ChainAction::Expire { episode_id } => {
                (contract.expire(episode_id).calldata().clone(), U256::ZERO)
            }
            ChainAction::Withdraw => (contract.withdraw().calldata().clone(), U256::ZERO),
        };
        let mut request = TransactionRequest::default()
            .with_from(sender)
            .with_to(self.config.contract_address)
            .with_value(value)
            .with_input(data)
            .with_chain_id(self.identity.chain_id)
            .with_nonce(nonce);
        let balance = self.balance(sender).await?;
        if balance <= value {
            return Err(ChainError::InsufficientFunds);
        }
        let estimated_gas = retry_rpc(
            || async { self.provider.estimate_gas(request.clone()).await },
            transient_rpc,
        )
        .await
        .map_err(rpc_action_error)?;
        let gas_limit = estimated_gas
            .checked_add(estimated_gas / 5)
            .ok_or(ChainError::BudgetExceeded)?;
        let fees = retry_rpc(
            || async { self.provider.estimate_eip1559_fees().await },
            transient_rpc,
        )
        .await
        .map_err(unavailable)?;
        if gas_limit > self.config.max_gas_limit
            || fees.max_fee_per_gas > self.config.max_fee_per_gas
        {
            return Err(ChainError::BudgetExceeded);
        }
        let gas_budget = U256::from(gas_limit) * U256::from(fees.max_fee_per_gas);
        let required = value
            .checked_add(gas_budget)
            .ok_or(ChainError::BudgetExceeded)?;
        if balance < required {
            return Err(ChainError::InsufficientFunds);
        }
        request = request
            .with_gas_limit(gas_limit)
            .with_max_fee_per_gas(fees.max_fee_per_gas)
            .with_max_priority_fee_per_gas(fees.max_priority_fee_per_gas);
        let signer = self
            .signers
            .get(actor_id)
            .ok_or_else(|| ChainError::UnknownActor(actor_id.into()))?;
        let wallet = EthereumWallet::from(signer.clone());
        let signed = request
            .build(&wallet)
            .await
            .map_err(|_| ChainError::Configuration("transaction signing failed".into()))?;
        let prepared = PreparedTransaction {
            sender,
            nonce,
            tx_hash: *signed.tx_hash(),
            raw: signed.encoded_2718().into(),
        };
        self.in_flight.insert(sender, (nonce, prepared.tx_hash));
        tracing::info!(event = "chain.prepared", %sender, nonce, transaction_hash = %prepared.tx_hash, "Transaction prepared for durable storage before broadcast");
        Ok(prepared)
    }

    #[tracing::instrument(name = "chain.broadcast", skip_all, fields(sender = %transaction.sender, transaction_hash = %transaction.tx_hash, nonce = transaction.nonce), err)]
    pub async fn broadcast(&self, transaction: &PreparedTransaction) -> Result<B256, ChainError> {
        if keccak256(&transaction.raw) != transaction.tx_hash {
            return Err(ChainError::Configuration(
                "stored transaction bytes do not match their hash".into(),
            ));
        }
        match retry_rpc(
            || async { self.provider.send_raw_transaction(&transaction.raw).await },
            transient_rpc,
        )
        .await
        {
            Ok(pending) if *pending.tx_hash() == transaction.tx_hash => {
                tracing::info!(event = "chain.submitted", transaction_hash = %transaction.tx_hash, "Exact signed transaction submitted");
                Ok(transaction.tx_hash)
            }
            Ok(_) => Err(ChainError::IdentityMismatch),
            Err(error) => {
                tracing::warn!(event = "chain.broadcast_uncertain", transaction_hash = %transaction.tx_hash, sender = %transaction.sender, nonce = transaction.nonce, "Broadcast result uncertain; reconciling hash and nonce");
                // A lost response or an already-known transaction is not a reason
                // to sign another nonce. Reconcile the exact persisted hash.
                if retry_rpc(
                    || async {
                        self.provider
                            .get_transaction_by_hash(transaction.tx_hash)
                            .await
                    },
                    transient_rpc,
                )
                .await
                .map_err(unavailable)?
                .is_some()
                {
                    Ok(transaction.tx_hash)
                } else if self.nonce(transaction.sender).await? > transaction.nonce {
                    Err(ChainError::OutstandingTransaction)
                } else {
                    Err(unavailable(error))
                }
            }
        }
    }

    /// Release only a matching reservation after local persistence failed,
    /// before any broadcast attempt. Never use this after an uncertain send.
    pub fn abandon_unbroadcast(&mut self, transaction: &PreparedTransaction) {
        if self.in_flight.get(&transaction.sender)
            == Some(&(transaction.nonce, transaction.tx_hash))
        {
            self.in_flight.remove(&transaction.sender);
            tracing::warn!(event = "chain.unbroadcast_abandoned", transaction_hash = %transaction.tx_hash, sender = %transaction.sender, nonce = transaction.nonce, "Unbroadcast nonce reservation released after failed persistence");
        }
    }

    pub async fn canonical_block_hash(&self, number: u64) -> Result<Option<B256>, ChainError> {
        Ok(retry_rpc(
            || async { self.provider.get_block_by_number(number.into()).await },
            transient_rpc,
        )
        .await
        .map_err(unavailable)?
        .map(|block| block.header.hash))
    }

    #[tracing::instrument(name = "chain.receipt", skip_all, fields(%transaction_hash), err)]
    pub async fn receipt(
        &self,
        transaction_hash: B256,
    ) -> Result<Option<ReceiptEvidence>, ChainError> {
        let Some(receipt) = retry_rpc(
            || async {
                self.provider
                    .get_transaction_receipt(transaction_hash)
                    .await
            },
            transient_rpc,
        )
        .await
        .map_err(unavailable)?
        else {
            return Ok(None);
        };
        let block_number = receipt
            .block_number
            .ok_or_else(|| ChainError::Unavailable("receipt has no included block".into()))?;
        let block_hash = receipt
            .block_hash
            .ok_or_else(|| ChainError::Unavailable("receipt has no included block hash".into()))?;
        if self.canonical_block_hash(block_number).await? != Some(block_hash) {
            tracing::warn!(event = "chain.receipt_orphaned", %transaction_hash, block_number, %block_hash, "Receipt block is no longer canonical");
            return Err(ChainError::Reorganized);
        }
        let height = self.block_number().await?;
        let confirmations = height.saturating_sub(block_number).saturating_add(1);
        tracing::debug!(event = "chain.receipt_observed", %transaction_hash, block_number, %block_hash, success = receipt.status(), confirmations, confirmed = confirmations >= self.identity.confirmation_depth, "Receipt inclusion observed");
        let logs = receipt
            .inner
            .logs()
            .iter()
            .filter(|log| log.address() == self.config.contract_address)
            .map(|log| self.log_evidence(log))
            .collect::<Result<Vec<_>, ChainError>>()?;
        Ok(Some(ReceiptEvidence {
            transaction_hash,
            success: receipt.status(),
            block_number,
            block_hash,
            gas_used: receipt.gas_used,
            effective_gas_price: receipt.effective_gas_price,
            confirmations,
            confirmed: confirmations >= self.identity.confirmation_depth,
            logs,
        }))
    }

    fn log_evidence(&self, log: &Log) -> Result<LogEvidence, ChainError> {
        if log.removed {
            return Err(ChainError::Reorganized);
        }
        Ok(LogEvidence {
            chain_id: self.identity.chain_id,
            contract_address: log.address(),
            block_number: log
                .block_number
                .ok_or_else(|| ChainError::Unavailable("included log lacks block number".into()))?,
            block_hash: log
                .block_hash
                .ok_or_else(|| ChainError::Unavailable("included log lacks block hash".into()))?,
            transaction_hash: log.transaction_hash.ok_or_else(|| {
                ChainError::Unavailable("included log lacks transaction hash".into())
            })?,
            log_index: log
                .log_index
                .ok_or_else(|| ChainError::Unavailable("included log lacks log index".into()))?,
            topics: log.topics().to_vec(),
            data: log.data().data.clone(),
        })
    }

    /// Deploy only when explicitly invoked by bootstrap code. Normal service
    /// startup connects to a pinned address/code hash instead of redeploying.
    pub async fn deploy(
        rpc_url: &str,
        operator: PrivateKeySigner,
        artifact_path: &Path,
    ) -> Result<DeploymentIdentity, ChainError> {
        #[derive(Deserialize)]
        struct Artifact {
            bytecode: Bytecode,
        }
        #[derive(Deserialize)]
        struct Bytecode {
            object: String,
        }

        let provider = ProviderBuilder::new()
            .wallet(operator.clone())
            .connect_reqwest(
                rpc_http_client(Duration::from_secs(10))?,
                rpc_url
                    .parse()
                    .map_err(|_| ChainError::Configuration("invalid RPC URL".into()))?,
            );
        let chain_id = provider.get_chain_id().await.map_err(unavailable)?;
        if !matches!(chain_id, 31337 | 80002) {
            return Err(ChainError::UnsupportedChain);
        }
        let artifact: Artifact =
            serde_json::from_slice(&std::fs::read(artifact_path).map_err(|_| {
                ChainError::Configuration("contract artifact cannot be read".into())
            })?)
            .map_err(|_| {
                ChainError::Configuration("contract artifact bytecode is invalid".into())
            })?;
        let mut bytecode = artifact
            .bytecode
            .object
            .parse::<Bytes>()
            .map_err(|_| ChainError::Configuration("contract artifact bytecode is not hex".into()))?
            .to_vec();
        bytecode.extend(operator.address().abi_encode());
        let request = TransactionRequest::default()
            .with_deploy_code(bytecode)
            .with_from(operator.address())
            .with_chain_id(chain_id);
        let receipt = provider
            .send_transaction(request)
            .await
            .map_err(unavailable)?
            .with_timeout(Some(Duration::from_secs(30)))
            .get_receipt()
            .await
            .map_err(unavailable)?;
        if !receipt.status() {
            return Err(ChainError::Rejected("deployment reverted".into()));
        }
        let contract_address = receipt.contract_address.ok_or_else(|| {
            ChainError::Unavailable("deployment receipt has no contract address".into())
        })?;
        let code = provider
            .get_code_at(contract_address)
            .await
            .map_err(unavailable)?;
        Ok(DeploymentIdentity {
            chain_id,
            contract_address,
            code_hash: keccak256(&code),
            abi_version: 1,
            confirmation_depth: 1,
        })
    }
}

fn rpc_http_client(timeout: Duration) -> Result<HttpClient, ChainError> {
    if timeout.is_zero() || timeout > Duration::from_secs(60) {
        return Err(ChainError::Configuration(
            "RPC timeout must be positive and at most sixty seconds".into(),
        ));
    }
    HttpClient::builder()
        .timeout(timeout)
        .connect_timeout(timeout.min(Duration::from_secs(3)))
        .build()
        .map_err(|_| {
            ChainError::Configuration("HTTP timeout policy could not be configured".into())
        })
}

/// Retry only classified transport throttling/disconnection. Each attempt has
/// the HTTP timeout above. This closure must never sign or allocate a nonce;
/// a write closure may only rebroadcast the exact already-persisted bytes.
async fn retry_rpc<T, E, F, Fut>(operation: F, is_transient: fn(&E) -> bool) -> Result<T, E>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = Result<T, E>>,
{
    operation
        .retry(
            ExponentialBuilder::default()
                .with_min_delay(Duration::from_millis(100))
                // BackON adds jitter after its base cap, so a one-second base
                // keeps the actual jittered delay below two seconds.
                .with_max_delay(Duration::from_secs(1))
                .with_max_times(3)
                .with_total_delay(Some(Duration::from_secs(5)))
                .with_jitter(),
        )
        .when(is_transient)
        .notify(|_, delay| {
            tracing::warn!(
                event = "chain.rpc_retry",
                backoff_ms = delay.as_millis() as u64,
                "Transient RPC retry scheduled"
            )
        })
        .await
}

fn transient_rpc(error: &TransportError) -> bool {
    if error
        .as_error_resp()
        .is_some_and(|response| matches!(response.code, 429 | -32005))
    {
        return true;
    }
    match error.as_transport_err() {
        Some(TransportErrorKind::BackendGone) => true,
        Some(TransportErrorKind::HttpError(http)) => matches!(http.status, 429 | 503),
        _ => false,
    }
}

fn transient_contract(error: &alloy::contract::Error) -> bool {
    match error {
        alloy::contract::Error::TransportError(error) => transient_rpc(error),
        _ => false,
    }
}

fn unavailable(_: impl std::fmt::Display) -> ChainError {
    // Transport errors may include entire requests. Do not return calldata or
    // credentials to HTTP clients, and never log their raw debug representation.
    ChainError::Unavailable("RPC request did not complete successfully".into())
}

fn contract_error(error: alloy::contract::Error) -> ChainError {
    if let Some(data) = error.as_revert_data() {
        if bindings::Veracity::UnknownEpisode::abi_decode_validate(&data).is_ok() {
            return ChainError::UnknownEpisode;
        }
        ChainError::Rejected("contract call reverted".into())
    } else {
        unavailable(error)
    }
}

fn identity_call_error(error: alloy::contract::Error) -> ChainError {
    if matches!(&error, alloy::contract::Error::TransportError(_))
        && error.as_revert_data().is_none()
    {
        unavailable(error)
    } else {
        ChainError::IdentityMismatch
    }
}

fn rpc_action_error(error: alloy::transports::TransportError) -> ChainError {
    if error.as_error_resp().is_some_and(|response| {
        response.code == 3 || response.message.starts_with("execution reverted")
    }) {
        ChainError::Rejected("transaction would revert".into())
    } else {
        unavailable(error)
    }
}

fn into_contract_config(config: ContractConfig) -> bindings::Veracity::Config {
    bindings::Veracity::Config {
        creator: config.creator,
        challenger: config.challenger,
        jurors: config.jurors,
        treasury: config.treasury,
        configurationHash: config.configuration_hash,
        beta: config.beta,
        gammaBps: config.gamma_bps,
        winnerBps: config.winner_bps,
        jurorBps: config.juror_bps,
        protocolBps: config.protocol_bps,
        postingDuration: config.posting_duration,
        challengeDuration: config.challenge_duration,
        commitDuration: config.commit_duration,
        revealDuration: config.reveal_duration,
    }
}

fn from_contract_config(config: bindings::Veracity::Config) -> ContractConfig {
    ContractConfig {
        creator: config.creator,
        challenger: config.challenger,
        jurors: config.jurors,
        treasury: config.treasury,
        configuration_hash: config.configurationHash,
        beta: config.beta,
        gamma_bps: config.gammaBps,
        winner_bps: config.winnerBps,
        juror_bps: config.jurorBps,
        protocol_bps: config.protocolBps,
        posting_duration: config.postingDuration,
        challenge_duration: config.challengeDuration,
        commit_duration: config.commitDuration,
        reveal_duration: config.revealDuration,
    }
}

fn from_contract_state(state: bindings::Veracity::State) -> Result<State, ChainError> {
    match state as u8 {
        0 => Ok(State::Unknown),
        1 => Ok(State::Registered),
        2 => Ok(State::Open),
        3 => Ok(State::Commit),
        4 => Ok(State::Reveal),
        5 => Ok(State::SettledCreator),
        6 => Ok(State::SettledChallenger),
        7 => Ok(State::Aborted),
        8 => Ok(State::ExpiredUnchallenged),
        9 => Ok(State::ExpiredUnfunded),
        _ => Err(ChainError::IdentityMismatch),
    }
}
