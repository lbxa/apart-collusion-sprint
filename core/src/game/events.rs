use std::collections::{BTreeMap, BTreeSet};

use alloy::primitives::B256;

use super::{GameError, GameInner};
use crate::{
    chain::{LogEvidence, ReceiptEvidence},
    store::ChainEventRecord,
};

fn validate_range(from: u64, to: u64) -> Result<(), GameError> {
    if to < from || to - from >= 10000 {
        return Err(GameError::Validation(
            "event range must be inclusive and contain at most 10000 blocks".into(),
        ));
    }
    Ok(())
}

impl GameInner {
    /// Check previously collected evidence, including confirmed receipts and
    /// blocks above the latest head after an Anvil revert or reorganisation.
    pub(super) async fn recheck_canonical_evidence(&mut self) -> Result<(), GameError> {
        let identity = self.chain.identity().clone();
        let contract = identity.contract_address.to_string();
        let mut blocks: BTreeMap<u64, BTreeSet<String>> = BTreeMap::new();
        for record in self
            .store
            .chain_events(identity.chain_id, &contract, 0, u64::MAX)?
        {
            blocks
                .entry(record.block_number)
                .or_default()
                .insert(record.block_hash);
        }
        for operation in self.store.receipt_operations()? {
            if let Some(record) = operation.receipt {
                blocks
                    .entry(record.block_number)
                    .or_default()
                    .insert(record.block_hash);
            }
        }
        for (height, hashes) in blocks {
            let canonical = self.chain.canonical_block_hash(height).await?;
            let expected = hashes
                .into_iter()
                .map(|hash| {
                    hash.parse::<B256>()
                        .map_err(|_| GameError::Internal("stored block hash is invalid".into()))
                })
                .collect::<Result<Vec<_>, _>>()?;
            if expected
                .into_iter()
                .any(|expected| canonical != Some(expected))
            {
                self.store
                    .rewind_chain(identity.chain_id, &contract, height)?;
                tracing::warn!(
                    event = "game.chain.rewind",
                    chain_id = identity.chain_id,
                    from_block = height
                );
                break;
            }
        }
        // Receipt persistence is the durable boundary. If a process stopped
        // between that transaction and event insertion, rebuild the public
        // event rows from the canonical receipt, including terminal operations.
        for operation in self.store.receipt_operations()? {
            if let Some(record) = operation.receipt {
                let receipt: ReceiptEvidence =
                    serde_json::from_str(&record.receipt_json).map_err(|_| {
                        GameError::Internal("stored receipt evidence is invalid".into())
                    })?;
                if receipt.block_number != record.block_number
                    || receipt.block_hash.to_string() != record.block_hash
                    || receipt.transaction_hash.to_string() != record.transaction_hash
                {
                    return Err(GameError::Internal(
                        "stored receipt identity is inconsistent".into(),
                    ));
                }
                for log in &receipt.logs {
                    if log.block_number != receipt.block_number
                        || log.block_hash != receipt.block_hash
                        || log.transaction_hash != receipt.transaction_hash
                    {
                        return Err(GameError::Internal(
                            "stored receipt log identity is inconsistent".into(),
                        ));
                    }
                    self.persist_log(log)?;
                }
            }
        }
        Ok(())
    }

    pub(super) async fn replay_events(&mut self, from: u64, to: u64) -> Result<usize, GameError> {
        validate_range(from, to)?;
        self.recheck_canonical_evidence().await?;
        let mut inserted = 0;
        for log in self.chain.logs(from, to).await? {
            if self.persist_log(&log)? {
                inserted += 1;
            }
        }
        tracing::info!(
            event = "game.chain.replayed",
            from_block = from,
            to_block = to,
            inserted
        );
        Ok(inserted)
    }

    pub(super) fn persist_log(&self, log: &LogEvidence) -> Result<bool, GameError> {
        if log.chain_id != self.chain.identity().chain_id
            || log.contract_address != self.chain.identity().contract_address
        {
            return Err(GameError::Internal(
                "event identity does not match the configured deployment".into(),
            ));
        }
        let record = ChainEventRecord {
            chain_id: log.chain_id,
            contract_address: log.contract_address.to_string(),
            block_number: log.block_number,
            block_hash: log.block_hash.to_string(),
            transaction_hash: log.transaction_hash.to_string(),
            log_index: log.log_index,
            payload_json: serde_json::to_string(&log)
                .map_err(|_| GameError::Internal("event serialization failed".into()))?,
        };
        Ok(self.store.insert_chain_event(&record)?)
    }

    pub(super) async fn export_events(&mut self, from: u64, to: u64) -> Result<String, GameError> {
        validate_range(from, to)?;
        self.recheck_canonical_evidence().await?;
        let identity = self.chain.identity();
        let mut output = String::new();
        for record in self.store.chain_events(
            identity.chain_id,
            &identity.contract_address.to_string(),
            from,
            to,
        )? {
            // Deserialize the public log schema instead of exporting arbitrary
            // stored JSON, private commands, or reveal-material rows.
            let log: LogEvidence = serde_json::from_str(&record.payload_json)
                .map_err(|_| GameError::Internal("stored event evidence is invalid".into()))?;
            if log.chain_id != identity.chain_id
                || log.contract_address != identity.contract_address
            {
                return Err(GameError::Internal(
                    "stored event identity is invalid".into(),
                ));
            }
            output.push_str(
                &serde_json::to_string(&log)
                    .map_err(|_| GameError::Internal("event export failed".into()))?,
            );
            output.push('\n');
        }
        Ok(output)
    }
}
