use alloy::primitives::{B256, Bytes, keccak256};
use rand::{TryRngCore, rngs::OsRng};
use serde::{Deserialize, Serialize};

use super::{
    GameAction, GameError, GameInner, OperationView, ReceiptView, RegisterEpisode, TransactionView,
    validate_registration,
};
use crate::chain::{
    ChainAction, ChainError, PreparedTransaction, ReceiptEvidence, commitment_hash,
};
use crate::store::{
    OperationStatus, PreparedTransactionRecord, ReceiptRecord, Reservation, RevealMaterial,
    StoredOperation,
};

#[derive(Serialize, Deserialize)]
#[serde(tag = "intent")]
pub(super) enum StoredIntent {
    Register { request: Box<RegisterEpisode> },
    Action { action: GameAction },
}

impl GameInner {
    pub(super) fn stored_operation(&self, id: &str) -> Result<StoredOperation, GameError> {
        self.store
            .get_operation(id)?
            .ok_or_else(|| GameError::NotFound("operation".into()))
    }

    #[allow(clippy::too_many_arguments)]
    pub(super) fn reserve(
        &self,
        scope: &str,
        key: &str,
        episode_id: &str,
        actor_id: &str,
        kind: &str,
        intent: &StoredIntent,
    ) -> Result<StoredOperation, GameError> {
        let json = serde_json::to_string(intent)
            .map_err(|_| GameError::Internal("intent serialization failed".into()))?;
        let canonical = serde_jcs::to_vec(intent).map_err(|_| {
            GameError::Validation("intent cannot be encoded as canonical JSON".into())
        })?;
        let digest = keccak256(canonical).to_string();
        let (operation, reused) = match self
            .store
            .reserve(scope, key, &digest, episode_id, actor_id, kind, &json)?
        {
            Reservation::Created(operation) => (operation, false),
            Reservation::Existing(operation) => (operation, true),
        };
        tracing::info!(event = "game.operation.reserved", operation_id = %operation.id, episode_id, actor_id, kind, reused, status = operation.status.as_str());
        Ok(operation)
    }

    pub(super) async fn execute(
        &mut self,
        mut operation: StoredOperation,
        operator_id: &str,
    ) -> Result<OperationView, GameError> {
        if operation.status == OperationStatus::Failed {
            return Err(GameError::Rejected(operation.error.unwrap_or_else(|| {
                "previous attempt failed before broadcast".into()
            })));
        }
        operation = self.observe(operation).await?;
        if matches!(
            operation.status,
            OperationStatus::Confirmed | OperationStatus::Reverted
        ) {
            return operation_view(&operation);
        }
        if operation.status == OperationStatus::Accepted {
            for pending in self.store.pending_operations()? {
                if pending.id != operation.id
                    && pending.actor_id == operation.actor_id
                    && pending.prepared.is_some()
                {
                    let pending = self.observe(pending).await?;
                    if !matches!(
                        pending.status,
                        OperationStatus::Confirmed | OperationStatus::Reverted
                    ) {
                        self.store
                            .record_error(&operation.id, "signer_has_pending_transaction")?;
                        return Err(GameError::Conflict(
                            "signer has an unresolved transaction; reconcile it first".into(),
                        ));
                    }
                }
            }
            let intent: StoredIntent = serde_json::from_str(&operation.request_json)
                .map_err(|_| GameError::Internal("stored intent is invalid".into()))?;
            let action = match intent {
                StoredIntent::Register { request } => {
                    if operation.actor_id != operator_id {
                        return Err(GameError::Forbidden(
                            "registration requires operator".into(),
                        ));
                    }
                    let config = validate_registration(&request, &self.chain.participants())?;
                    let episode_id = keccak256(request.episode_id.as_bytes());
                    // Distinguish the contract's exact UnknownEpisode error
                    // from every RPC or unrelated revert before staging local
                    // metadata for a genuinely new registration.
                    match self.chain.episode(episode_id).await {
                        Ok(_) => {
                            self.store
                                .mark_failed(&operation.id, "episode_already_registered")?;
                            return Err(GameError::Conflict(
                                "episode ID is already registered on chain".into(),
                            ));
                        }
                        Err(ChainError::UnknownEpisode) => {}
                        Err(error) => return Err(error.into()),
                    }
                    self.store.insert_episode(
                        &request.episode_id,
                        &episode_id.to_string(),
                        &config.configuration_hash.to_string(),
                        &serde_json::to_string(&request).map_err(|_| {
                            GameError::Internal("configuration serialization failed".into())
                        })?,
                    )?;
                    ChainAction::Register { episode_id, config }
                }
                StoredIntent::Action { action } => {
                    match self.prepare_action(&operation, operator_id, action).await {
                        Ok(action) => action,
                        Err(error) => {
                            if matches!(
                                error,
                                GameError::Validation(_)
                                    | GameError::Forbidden(_)
                                    | GameError::Conflict(_)
                                    | GameError::Rejected(_)
                            ) {
                                self.store
                                    .mark_failed(&operation.id, "action_validation_failed")?;
                                tracing::warn!(event = "game.operation.failed", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, classification = "action_validation_failed");
                            }
                            return Err(error);
                        }
                    }
                }
            };
            let prepared = match self.chain.prepare(&operation.actor_id, action).await {
                Ok(prepared) => prepared,
                Err(error) => {
                    let preparation_code = if matches!(&error, ChainError::BudgetExceeded) {
                        "budget_exceeded"
                    } else {
                        "preparation_unavailable"
                    };
                    let error: GameError = error.into();
                    if matches!(error, GameError::Rejected(_) | GameError::Forbidden(_)) {
                        self.store.mark_failed(&operation.id, "contract_rejected")?;
                        tracing::warn!(event = "game.operation.failed", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, classification = "contract_rejected");
                    } else {
                        self.store.record_error(&operation.id, preparation_code)?;
                        tracing::warn!(event = "game.operation.preparation_deferred", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, classification = preparation_code);
                    }
                    return Err(error);
                }
            };
            let persisted = self.store.prepare_operation(
                &operation.id,
                &PreparedTransactionRecord {
                    sender: prepared.sender.to_string(),
                    nonce: prepared.nonce,
                    tx_hash: prepared.tx_hash.to_string(),
                    raw_transaction: prepared.raw.to_vec(),
                },
            );
            operation = match persisted {
                Ok(operation) => operation,
                Err(error) => {
                    // No broadcast has occurred. Roll back only this client's
                    // matching in-memory reservation, not durable signed work.
                    self.chain.abandon_unbroadcast(&prepared);
                    return Err(error.into());
                }
            };
            tracing::info!(event = "game.operation.prepared", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, status = operation.status.as_str());
        }
        if let Some(prepared) = &operation.prepared {
            let transaction = prepared_transaction(prepared)?;
            // Never sign a replacement when broadcast status is uncertain.
            if self.chain.receipt(transaction.tx_hash).await?.is_none() {
                let nonce = self.chain.nonce(transaction.sender).await?;
                if nonce > transaction.nonce {
                    self.store
                        .record_error(&operation.id, "nonce_consumed_without_known_receipt")?;
                    return operation_view(&self.stored_operation(&operation.id)?);
                }
                match self.chain.broadcast(&transaction).await {
                    Ok(_) => {
                        operation = self.store.mark_submitted(&operation.id)?;
                        tracing::info!(event = "game.operation.submitted", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, status = operation.status.as_str());
                    }
                    Err(_) => {
                        self.store
                            .record_error(&operation.id, "broadcast_uncertain")?;
                        tracing::warn!(event = "game.operation.broadcast_uncertain", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, classification = "broadcast_uncertain");
                        return operation_view(&self.stored_operation(&operation.id)?);
                    }
                }
            }
            for attempt in 0..4 {
                operation = self.observe(operation).await?;
                if matches!(
                    operation.status,
                    OperationStatus::Confirmed | OperationStatus::Reverted
                ) {
                    break;
                }
                if attempt != 3 {
                    tokio::time::sleep(std::time::Duration::from_millis(25)).await;
                }
            }
        }
        operation_view(&operation)
    }

    async fn prepare_action(
        &self,
        operation: &StoredOperation,
        operator_id: &str,
        action: GameAction,
    ) -> Result<ChainAction, GameError> {
        let (request, _) = self.verified_episode(&operation.episode_id).await?;
        super::validation::authorize_action(&request, operator_id, &operation.actor_id, &action)?;
        let episode_id = keccak256(operation.episode_id.as_bytes());
        match action {
            GameAction::PostClaim { content } => {
                let content_hash = super::artifact_hash(&content)?;
                self.store
                    .store_artifact(&content_hash.to_string(), &content)?;
                Ok(ChainAction::PostClaim {
                    episode_id,
                    content_hash,
                })
            }
            GameAction::Challenge { evidence } => {
                let evidence_hash = super::artifact_hash(&evidence)?;
                self.store
                    .store_artifact(&evidence_hash.to_string(), &evidence)?;
                Ok(ChainAction::Challenge {
                    episode_id,
                    evidence_hash,
                })
            }
            GameAction::CommitVote {
                verdict,
                assessment,
            } => {
                let assessment_hash = super::artifact_hash(&assessment)?;
                let material = match self
                    .store
                    .get_reveal_material(&operation.episode_id, &operation.actor_id)?
                {
                    Some(material) => {
                        if material.verdict != verdict.as_u8()
                            || material.assessment_hash != assessment_hash.to_string()
                            || material.assessment_utf8 != assessment
                        {
                            return Err(GameError::Conflict(
                                "a different commitment intent is already retained for this juror"
                                    .into(),
                            ));
                        }
                        material
                    }
                    None => {
                        let mut salt = [0u8; 32];
                        OsRng.try_fill_bytes(&mut salt).map_err(|_| {
                            GameError::Unavailable("secure entropy source is unavailable".into())
                        })?;
                        let material = RevealMaterial {
                            verdict: verdict.as_u8(),
                            assessment_hash: assessment_hash.to_string(),
                            salt,
                            assessment_utf8: assessment.clone(),
                        };
                        self.store.put_reveal_material(
                            &operation.episode_id,
                            &operation.actor_id,
                            &material,
                        )?;
                        material
                    }
                };
                self.store
                    .store_artifact(&assessment_hash.to_string(), &assessment)?;
                let identity = self.chain.identity();
                let commitment = commitment_hash(
                    identity.chain_id,
                    identity.contract_address,
                    episode_id,
                    self.chain.address(&operation.actor_id)?,
                    material.verdict,
                    assessment_hash,
                    B256::from(material.salt),
                );
                Ok(ChainAction::CommitVote {
                    episode_id,
                    commitment,
                })
            }
            GameAction::RevealVote {} => {
                let material = self
                    .store
                    .get_reveal_material(&operation.episode_id, &operation.actor_id)?
                    .ok_or_else(|| {
                        GameError::Conflict("no retained commitment exists for this juror".into())
                    })?;
                let assessment_hash = material.assessment_hash.parse().map_err(|_| {
                    GameError::Internal("retained assessment hash is invalid".into())
                })?;
                Ok(ChainAction::RevealVote {
                    episode_id,
                    verdict: material.verdict,
                    assessment_hash,
                    salt: B256::from(material.salt),
                })
            }
            GameAction::Settle {} => Ok(ChainAction::Settle { episode_id }),
            GameAction::Expire {} => Ok(ChainAction::Expire { episode_id }),
            GameAction::Withdraw {} => Ok(ChainAction::Withdraw),
            GameAction::TransferCredits {
                recipient_id,
                amount_wei,
            } => Ok(ChainAction::TransferCredits {
                recipient: self.chain.address(&recipient_id)?,
                amount: super::validation::positive_amount("amount_wei", &amount_wei)?,
            }),
        }
    }

    pub(super) async fn observe(
        &mut self,
        mut operation: StoredOperation,
    ) -> Result<StoredOperation, GameError> {
        if let Some(receipt) = &operation.receipt {
            let canonical = self
                .chain
                .canonical_block_hash(receipt.block_number)
                .await?;
            let expected: B256 = receipt
                .block_hash
                .parse()
                .map_err(|_| GameError::Internal("stored block hash is invalid".into()))?;
            if canonical != Some(expected) {
                self.store.rewind_chain(
                    self.chain.identity().chain_id,
                    &self.chain.identity().contract_address.to_string(),
                    receipt.block_number,
                )?;
                tracing::warn!(event = "game.operation.reorg", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, from_block = receipt.block_number);
                operation = self.stored_operation(&operation.id)?;
            }
        }
        if let Some(prepared) = &operation.prepared {
            let tx_hash: B256 = prepared
                .tx_hash
                .parse()
                .map_err(|_| GameError::Internal("stored transaction hash is invalid".into()))?;
            match self.chain.receipt(tx_hash).await {
                Ok(Some(receipt)) => {
                    let status = if !receipt.success {
                        OperationStatus::Reverted
                    } else if receipt.confirmed {
                        OperationStatus::Confirmed
                    } else {
                        OperationStatus::Included
                    };
                    let record = ReceiptRecord {
                        chain_id: self.chain.identity().chain_id,
                        contract_address: self.chain.identity().contract_address.to_string(),
                        transaction_hash: receipt.transaction_hash.to_string(),
                        block_number: receipt.block_number,
                        block_hash: receipt.block_hash.to_string(),
                        gas_used: receipt.gas_used.to_string(),
                        effective_gas_price: receipt.effective_gas_price.to_string(),
                        receipt_json: serde_json::to_string(&receipt).map_err(|_| {
                            GameError::Internal("receipt serialization failed".into())
                        })?,
                    };
                    let previous = operation.status;
                    operation = self.store.record_receipt(&operation.id, &record, status)?;
                    if previous != status {
                        tracing::info!(event = "game.operation.receipt", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, status = operation.status.as_str());
                    }
                    for log in &receipt.logs {
                        self.persist_log(log)?;
                    }
                }
                Ok(None) => {}
                Err(ChainError::Reorganized) => {
                    operation = self
                        .store
                        .record_error(&operation.id, "receipt_reorganization_pending")?;
                }
                Err(_) => {
                    operation = self
                        .store
                        .record_error(&operation.id, "receipt_lookup_unavailable")?;
                }
            }
        }
        Ok(operation)
    }
}

fn prepared_transaction(
    record: &PreparedTransactionRecord,
) -> Result<PreparedTransaction, GameError> {
    Ok(PreparedTransaction {
        sender: record
            .sender
            .parse()
            .map_err(|_| GameError::Internal("stored sender is invalid".into()))?,
        nonce: record.nonce,
        tx_hash: record
            .tx_hash
            .parse()
            .map_err(|_| GameError::Internal("stored transaction hash is invalid".into()))?,
        raw: Bytes::from(record.raw_transaction.clone()),
    })
}

pub(super) fn operation_view(operation: &StoredOperation) -> Result<OperationView, GameError> {
    let receipt: Option<ReceiptEvidence> = operation
        .receipt
        .as_ref()
        .map(|record| serde_json::from_str(&record.receipt_json))
        .transpose()
        .map_err(|_| GameError::Internal("stored receipt is invalid".into()))?;
    Ok(OperationView {
        operation_id: operation.id.clone(),
        episode_id: operation.episode_id.clone(),
        actor_id: operation.actor_id.clone(),
        kind: operation.kind.clone(),
        status: operation.status.as_str().into(),
        transaction: operation.prepared.as_ref().map(|prepared| TransactionView {
            transaction_hash: prepared.tx_hash.clone(),
            sender: prepared.sender.clone(),
            nonce: prepared.nonce,
            receipt: receipt.map(|receipt| ReceiptView {
                transaction_hash: receipt.transaction_hash.to_string(),
                success: receipt.success,
                block_number: receipt.block_number,
                block_hash: receipt.block_hash.to_string(),
                gas_used: receipt.gas_used.to_string(),
                effective_gas_price: receipt.effective_gas_price.to_string(),
                confirmations: receipt.confirmations,
                confirmed: receipt.confirmed,
            }),
        }),
        error: operation.error.as_deref().map(|error| match error {
            "contract_rejected"
            | "episode_already_registered"
            | "action_validation_failed"
            | "preparation_unavailable"
            | "budget_exceeded"
            | "signer_has_pending_transaction"
            | "broadcast_uncertain"
            | "nonce_consumed_without_known_receipt"
            | "receipt_lookup_unavailable"
            | "receipt_reorganization_pending" => error.to_owned(),
            _ => "operation_requires_attention".into(),
        }),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn public_operation_omits_private_intent_and_sanitizes_untrusted_diagnostics() {
        let operation = StoredOperation {
            id: "operation".into(),
            scope: "private".into(),
            key: "private-key".into(),
            request_digest: "digest".into(),
            episode_id: "episode".into(),
            actor_id: "juror-1".into(),
            kind: "commit_vote".into(),
            request_json: "unrevealed-assessment-and-salt".into(),
            status: OperationStatus::Accepted,
            prepared: None,
            receipt: None,
            error: Some("rpc_url_contains_private_api_key".into()),
        };
        let public = serde_json::to_string(&operation_view(&operation).unwrap()).unwrap();
        assert!(!public.contains("unrevealed-assessment"));
        assert!(!public.contains("private-key"));
        assert!(!public.contains("private_api_key"));
    }
}
