//! Durable game records and transaction outbox. Financial state remains on-chain.

use std::{
    fmt,
    path::Path,
    sync::{Mutex, MutexGuard},
    time::Duration,
};

use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
mod chat;
mod forum;

#[derive(Debug, thiserror::Error)]
pub enum StoreError {
    #[error("operation conflicts with an immutable record: {0}")]
    Conflict(String),
    #[error("invalid operation state: {0}")]
    InvalidState(String),
    #[error("record not found: {0}")]
    NotFound(String),
    #[error("chat access denied")]
    AccessDenied,
    #[error("invalid stored record: {0}")]
    InvalidRecord(String),
    #[error("SQLite error: {0}")]
    Database(#[from] rusqlite::Error),
    #[error("filesystem error: {0}")]
    Io(#[from] std::io::Error),
    #[error("store lock was poisoned")]
    Poisoned,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperationStatus {
    Accepted,
    Prepared,
    Submitted,
    Included,
    Confirmed,
    Reverted,
    Failed,
}

impl OperationStatus {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Accepted => "accepted",
            Self::Prepared => "prepared",
            Self::Submitted => "submitted",
            Self::Included => "included",
            Self::Confirmed => "confirmed",
            Self::Reverted => "reverted",
            Self::Failed => "failed",
        }
    }

    fn from_stored(value: &str) -> rusqlite::Result<Self> {
        match value {
            "accepted" => Ok(Self::Accepted),
            "prepared" => Ok(Self::Prepared),
            "submitted" => Ok(Self::Submitted),
            "included" => Ok(Self::Included),
            "confirmed" => Ok(Self::Confirmed),
            "reverted" => Ok(Self::Reverted),
            "failed" => Ok(Self::Failed),
            _ => Err(rusqlite::Error::InvalidQuery),
        }
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct PreparedTransactionRecord {
    pub sender: String,
    pub nonce: u64,
    pub tx_hash: String,
    pub raw_transaction: Vec<u8>,
}

impl fmt::Debug for PreparedTransactionRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedTransactionRecord")
            .field("sender", &self.sender)
            .field("nonce", &self.nonce)
            .field("tx_hash", &self.tx_hash)
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReceiptRecord {
    pub chain_id: u64,
    pub contract_address: String,
    pub transaction_hash: String,
    pub block_number: u64,
    pub block_hash: String,
    pub gas_used: String,
    pub effective_gas_price: String,
    pub receipt_json: String,
}

impl ReceiptRecord {
    fn has_same_inclusion(&self, other: &Self) -> bool {
        self.chain_id == other.chain_id
            && self.contract_address == other.contract_address
            && self.transaction_hash == other.transaction_hash
            && self.block_number == other.block_number
            && self.block_hash == other.block_hash
            && self.gas_used == other.gas_used
            && self.effective_gas_price == other.effective_gas_price
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct StoredOperation {
    pub id: String,
    pub scope: String,
    pub key: String,
    pub request_digest: String,
    pub episode_id: String,
    pub actor_id: String,
    pub kind: String,
    pub request_json: String,
    pub status: OperationStatus,
    pub prepared: Option<PreparedTransactionRecord>,
    pub receipt: Option<ReceiptRecord>,
    pub error: Option<String>,
}

impl fmt::Debug for StoredOperation {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("StoredOperation")
            .field("id", &self.id)
            .field("kind", &self.kind)
            .field("status", &self.status)
            .finish_non_exhaustive()
    }
}

#[derive(Debug)]
pub enum Reservation {
    Created(StoredOperation),
    Existing(StoredOperation),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoredEpisode {
    pub id: String,
    pub onchain_id: String,
    pub configuration_hash: String,
    pub config_json: String,
}

#[derive(Clone, Eq, PartialEq)]
pub struct RevealMaterial {
    pub verdict: u8,
    pub assessment_hash: String,
    pub salt: [u8; 32],
    pub assessment_utf8: String,
}

impl fmt::Debug for RevealMaterial {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RevealMaterial")
            .finish_non_exhaustive()
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ChainEventRecord {
    pub chain_id: u64,
    pub contract_address: String,
    pub block_number: u64,
    pub block_hash: String,
    pub transaction_hash: String,
    pub log_index: u64,
    pub payload_json: String,
}

pub struct Store {
    connection: Mutex<Connection>,
}

const OPERATION_QUERY: &str = "SELECT o.id,o.scope,o.idempotency_key,o.request_digest,o.episode_id,
    o.actor_id,o.kind,o.request_json,o.status,o.error,
    s.sender,s.nonce,s.transaction_hash,s.raw_transaction,
    r.chain_id,r.contract_address,r.transaction_hash,r.block_number,r.block_hash,
    r.gas_used,r.effective_gas_price,r.receipt_json
    FROM operations o LEFT JOIN signed_transactions s ON s.operation_id=o.id
    LEFT JOIN receipts r ON r.operation_id=o.id";

impl Store {
    pub fn open(path: impl AsRef<Path>) -> Result<Self, StoreError> {
        let path = path.as_ref();
        if path != Path::new(":memory:") {
            if let Some(parent) = path
                .parent()
                .filter(|parent| !parent.as_os_str().is_empty())
            {
                std::fs::create_dir_all(parent)?;
            }
            let mut options = std::fs::OpenOptions::new();
            options.create(true).append(true);
            #[cfg(unix)]
            {
                use std::os::unix::fs::{OpenOptionsExt, PermissionsExt};
                options.mode(0o600);
                let file = options.open(path)?;
                file.set_permissions(std::fs::Permissions::from_mode(0o600))?;
            }
            #[cfg(not(unix))]
            {
                options.open(path)?;
            }
        }
        let mut connection = Connection::open(path)?;
        connection.busy_timeout(Duration::from_secs(5))?;
        connection.pragma_update(None, "journal_mode", "WAL")?;
        connection.pragma_update(None, "foreign_keys", "ON")?;
        // Check the version under the same write lock as every migration, so
        // concurrent openers cannot act on a stale version or partial schema.
        let migration = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let schema_version: u32 =
            migration.pragma_query_value(None, "user_version", |row| row.get(0))?;
        if schema_version > 3 {
            return Err(StoreError::InvalidRecord(
                "database schema is newer than this service".into(),
            ));
        }
        if schema_version == 0 {
            migration.execute_batch(include_str!("schema.sql"))?;
        }
        if schema_version < 2 {
            migration.execute_batch(include_str!("chat-schema.sql"))?;
        }
        if schema_version < 3 {
            migration.execute_batch(include_str!("forum-schema.sql"))?;
        }
        migration.commit()?;
        Ok(Self {
            connection: Mutex::new(connection),
        })
    }

    fn connection(&self) -> Result<MutexGuard<'_, Connection>, StoreError> {
        self.connection.lock().map_err(|_| StoreError::Poisoned)
    }

    pub fn bind_deployment(&self, identity_json: &str) -> Result<(), StoreError> {
        validate_json(identity_json)?;
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute("INSERT INTO deployment(singleton,identity_json) VALUES(1,?1) ON CONFLICT(singleton) DO NOTHING", [identity_json])?;
        let current: String = transaction.query_row(
            "SELECT identity_json FROM deployment WHERE singleton=1",
            [],
            |row| row.get(0),
        )?;
        if current != identity_json {
            return Err(StoreError::Conflict("deployment identity".into()));
        }
        transaction.commit()?;
        Ok(())
    }

    pub fn deployment(&self) -> Result<Option<String>, StoreError> {
        Ok(self
            .connection()?
            .query_row(
                "SELECT identity_json FROM deployment WHERE singleton=1",
                [],
                |row| row.get(0),
            )
            .optional()?)
    }
    #[allow(clippy::too_many_arguments)]
    pub fn reserve(
        &self,
        scope: &str,
        key: &str,
        digest: &str,
        episode_id: &str,
        actor_id: &str,
        kind: &str,
        request_json: &str,
    ) -> Result<Reservation, StoreError> {
        validate_json(request_json)?;
        if [scope, key, digest, episode_id, actor_id, kind]
            .iter()
            .any(|value| value.is_empty())
        {
            return Err(StoreError::InvalidRecord(
                "operation identity fields cannot be empty".into(),
            ));
        }
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let existing_id = transaction
            .query_row(
                "SELECT id FROM operations WHERE scope=?1 AND idempotency_key=?2",
                params![scope, key],
                |row| row.get::<_, String>(0),
            )
            .optional()?;
        if let Some(id) = existing_id {
            let existing = required_operation(&transaction, &id)?;
            if existing.request_digest != digest
                || existing.episode_id != episode_id
                || existing.actor_id != actor_id
                || existing.kind != kind
                || existing.request_json != request_json
            {
                return Err(StoreError::Conflict(
                    "idempotency key has another request".into(),
                ));
            }
            transaction.commit()?;
            return Ok(Reservation::Existing(existing));
        }
        let id = uuid::Uuid::new_v4().to_string();
        transaction.execute("INSERT INTO operations(id,scope,idempotency_key,request_digest,episode_id,actor_id,kind,request_json,status) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,'accepted')", params![id,scope,key,digest,episode_id,actor_id,kind,request_json])?;
        let created = required_operation(&transaction, &id)?;
        transaction.commit()?;
        Ok(Reservation::Created(created))
    }

    pub fn get_operation(&self, id: &str) -> Result<Option<StoredOperation>, StoreError> {
        let connection = self.connection()?;
        read_operation(&connection, id)
    }

    pub fn pending_operations(&self) -> Result<Vec<StoredOperation>, StoreError> {
        let connection = self.connection()?;
        let mut statement = connection.prepare(&format!("{OPERATION_QUERY} WHERE o.status IN ('accepted','prepared','submitted','included') ORDER BY o.rowid"))?;
        Ok(statement
            .query_map([], decode_operation)?
            .collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn receipt_operations(&self) -> Result<Vec<StoredOperation>, StoreError> {
        let connection = self.connection()?;
        let mut statement = connection.prepare(&format!(
            "{OPERATION_QUERY} WHERE r.operation_id IS NOT NULL ORDER BY o.rowid"
        ))?;
        Ok(statement
            .query_map([], decode_operation)?
            .collect::<rusqlite::Result<Vec<_>>>()?)
    }

    /// Internal recovery records, including private request bodies. Export DTOs
    /// must explicitly select public audit fields instead of serializing these.
    pub fn all_operations(&self) -> Result<Vec<StoredOperation>, StoreError> {
        let connection = self.connection()?;
        let mut statement = connection.prepare(&format!("{OPERATION_QUERY} ORDER BY o.rowid"))?;
        Ok(statement
            .query_map([], decode_operation)?
            .collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn prepare_operation(
        &self,
        id: &str,
        prepared: &PreparedTransactionRecord,
    ) -> Result<StoredOperation, StoreError> {
        if prepared.raw_transaction.is_empty() {
            return Err(StoreError::InvalidRecord(
                "signed transaction cannot be empty".into(),
            ));
        }
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = required_operation(&transaction, id)?;
        if let Some(previous) = &current.prepared {
            if previous != prepared {
                return Err(StoreError::Conflict("signed transaction identity".into()));
            }
            transaction.commit()?;
            return Ok(current);
        }
        if current.status != OperationStatus::Accepted {
            return Err(StoreError::InvalidState(current.status.as_str().into()));
        }
        if let Err(error) = transaction.execute("INSERT INTO signed_transactions(operation_id,sender,nonce,transaction_hash,raw_transaction) VALUES(?1,?2,?3,?4,?5)", params![id,prepared.sender,prepared.nonce.to_string(),prepared.tx_hash,prepared.raw_transaction]) {
            if matches!(error, rusqlite::Error::SqliteFailure(ref cause, _) if cause.code == rusqlite::ErrorCode::ConstraintViolation) {
                return Err(StoreError::Conflict("signed sender nonce or transaction already belongs to another operation".into()));
            }
            return Err(error.into());
        }
        transaction.execute(
            "UPDATE operations SET status='prepared',error=NULL WHERE id=?1",
            [id],
        )?;
        let updated = required_operation(&transaction, id)?;
        transaction.commit()?;
        Ok(updated)
    }

    pub fn mark_submitted(&self, id: &str) -> Result<StoredOperation, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = required_operation(&transaction, id)?;
        if current.status != OperationStatus::Prepared
            && current.status != OperationStatus::Submitted
        {
            return Err(StoreError::InvalidState(current.status.as_str().into()));
        }
        transaction.execute(
            "UPDATE operations SET status='submitted',error=NULL WHERE id=?1",
            [id],
        )?;
        let updated = required_operation(&transaction, id)?;
        transaction.commit()?;
        Ok(updated)
    }

    pub fn record_receipt(
        &self,
        id: &str,
        receipt: &ReceiptRecord,
        status: OperationStatus,
    ) -> Result<StoredOperation, StoreError> {
        validate_json(&receipt.receipt_json)?;
        let chain_id = sqlite_integer(receipt.chain_id)?;
        let block_number = sqlite_integer(receipt.block_number)?;
        if !matches!(
            status,
            OperationStatus::Included | OperationStatus::Confirmed | OperationStatus::Reverted
        ) {
            return Err(StoreError::InvalidState(
                "receipt requires an included, confirmed, or reverted outcome".into(),
            ));
        }
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = required_operation(&transaction, id)?;
        if current
            .prepared
            .as_ref()
            .map(|prepared| prepared.tx_hash.as_str())
            != Some(receipt.transaction_hash.as_str())
        {
            return Err(StoreError::Conflict(
                "receipt does not match signed transaction".into(),
            ));
        }
        if matches!(
            current.status,
            OperationStatus::Accepted | OperationStatus::Failed
        ) || matches!(
            current.status,
            OperationStatus::Confirmed | OperationStatus::Reverted
        ) && current.status != status
        {
            return Err(StoreError::InvalidState(current.status.as_str().into()));
        }
        if current
            .receipt
            .as_ref()
            .is_some_and(|previous| !previous.has_same_inclusion(receipt))
        {
            return Err(StoreError::Conflict(
                "receipt changed without a canonical rewind".into(),
            ));
        }
        transaction.execute("INSERT INTO receipts(operation_id,chain_id,contract_address,transaction_hash,block_number,block_hash,gas_used,effective_gas_price,receipt_json) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9) ON CONFLICT(operation_id) DO UPDATE SET receipt_json=excluded.receipt_json", params![id,chain_id,receipt.contract_address,receipt.transaction_hash,block_number,receipt.block_hash,receipt.gas_used,receipt.effective_gas_price,receipt.receipt_json])?;
        transaction.execute(
            "UPDATE operations SET status=?2,error=NULL WHERE id=?1",
            params![id, status.as_str()],
        )?;
        let updated = required_operation(&transaction, id)?;
        transaction.commit()?;
        Ok(updated)
    }

    /// Records a definitive rejection before signing. Failed commitment cleanup
    /// is atomic with this audit update; other recoverable or signed commitments
    /// keep their reveal material. Uncertain RPC outcomes belong in `record_error`.
    pub fn mark_failed(&self, id: &str, error: &str) -> Result<StoredOperation, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = required_operation(&transaction, id)?;
        if !matches!(
            current.status,
            OperationStatus::Accepted | OperationStatus::Failed
        ) {
            return Err(StoreError::InvalidState(
                "a signed transaction must be reconciled, not discarded".into(),
            ));
        }
        transaction.execute(
            "UPDATE operations SET status='failed',error=?2 WHERE id=?1",
            params![id, error],
        )?;
        if current.kind == "commit_vote"
            && !has_retained_commitment(&transaction, &current.episode_id, &current.actor_id)?
        {
            transaction.execute(
                "DELETE FROM reveal_material WHERE episode_id=?1 AND actor_id=?2",
                params![current.episode_id, current.actor_id],
            )?;
        }
        let updated = required_operation(&transaction, id)?;
        transaction.commit()?;
        Ok(updated)
    }

    pub fn record_error(&self, id: &str, error: &str) -> Result<StoredOperation, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        required_operation(&transaction, id)?;
        transaction.execute(
            "UPDATE operations SET error=?2 WHERE id=?1",
            params![id, error],
        )?;
        let updated = required_operation(&transaction, id)?;
        transaction.commit()?;
        Ok(updated)
    }

    pub fn insert_episode(
        &self,
        id: &str,
        onchain_id: &str,
        configuration_hash: &str,
        config_json: &str,
    ) -> Result<(), StoreError> {
        validate_json(config_json)?;
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let current = transaction.query_row("SELECT id,onchain_id,configuration_hash,config_json FROM episodes WHERE id=?1 OR onchain_id=?2",params![id,onchain_id],decode_episode).optional()?;
        let expected = StoredEpisode {
            id: id.into(),
            onchain_id: onchain_id.into(),
            configuration_hash: configuration_hash.into(),
            config_json: config_json.into(),
        };
        if let Some(previous) = current {
            if previous != expected {
                return Err(StoreError::Conflict("episode configuration".into()));
            }
        } else {
            transaction.execute("INSERT INTO episodes(id,onchain_id,configuration_hash,config_json) VALUES(?1,?2,?3,?4)",params![id,onchain_id,configuration_hash,config_json])?;
        }
        transaction.commit()?;
        Ok(())
    }

    pub fn get_episode(&self, id: &str) -> Result<Option<StoredEpisode>, StoreError> {
        Ok(self
            .connection()?
            .query_row(
                "SELECT id,onchain_id,configuration_hash,config_json FROM episodes WHERE id=?1",
                [id],
                decode_episode,
            )
            .optional()?)
    }

    pub fn put_reveal_material(
        &self,
        episode_id: &str,
        actor_id: &str,
        material: &RevealMaterial,
    ) -> Result<(), StoreError> {
        if material.verdict > 1 {
            return Err(StoreError::InvalidRecord("unknown verdict".into()));
        }
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let previous = read_reveal(&transaction, episode_id, actor_id)?;
        if let Some(previous) = previous {
            if previous != *material {
                return Err(StoreError::Conflict("reveal material".into()));
            }
        } else {
            transaction.execute("INSERT INTO reveal_material(episode_id,actor_id,verdict,assessment_hash,salt,assessment_utf8) VALUES(?1,?2,?3,?4,?5,?6)",params![episode_id,actor_id,material.verdict,material.assessment_hash,material.salt.as_slice(),material.assessment_utf8])?;
        }
        transaction.commit()?;
        Ok(())
    }

    pub fn get_reveal_material(
        &self,
        episode_id: &str,
        actor_id: &str,
    ) -> Result<Option<RevealMaterial>, StoreError> {
        let connection = self.connection()?;
        read_reveal(&connection, episode_id, actor_id)
    }

    pub fn store_artifact(&self, hash: &str, utf8: &str) -> Result<(), StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute(
            "INSERT INTO artifacts(hash,utf8) VALUES(?1,?2) ON CONFLICT(hash) DO NOTHING",
            params![hash, utf8],
        )?;
        let previous: String =
            transaction.query_row("SELECT utf8 FROM artifacts WHERE hash=?1", [hash], |row| {
                row.get(0)
            })?;
        if previous != utf8 {
            return Err(StoreError::Conflict("artifact bytes for hash".into()));
        }
        transaction.commit()?;
        Ok(())
    }

    pub fn artifact(&self, hash: &str) -> Result<Option<String>, StoreError> {
        Ok(self
            .connection()?
            .query_row("SELECT utf8 FROM artifacts WHERE hash=?1", [hash], |row| {
                row.get(0)
            })
            .optional()?)
    }

    pub fn insert_chain_event(&self, event: &ChainEventRecord) -> Result<bool, StoreError> {
        validate_json(&event.payload_json)?;
        let chain_id = sqlite_integer(event.chain_id)?;
        let block_number = sqlite_integer(event.block_number)?;
        let log_index = sqlite_integer(event.log_index)?;
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let previous = transaction.query_row("SELECT chain_id,contract_address,block_number,block_hash,transaction_hash,log_index,payload_json FROM chain_events WHERE chain_id=?1 AND contract_address=?2 AND block_hash=?3 AND transaction_hash=?4 AND log_index=?5",params![chain_id,event.contract_address,event.block_hash,event.transaction_hash,log_index],decode_event).optional()?;
        if let Some(previous) = previous {
            if previous != *event {
                return Err(StoreError::Conflict("chain event identity".into()));
            }
            transaction.commit()?;
            return Ok(false);
        }
        transaction.execute("INSERT INTO chain_events(chain_id,contract_address,block_number,block_hash,transaction_hash,log_index,payload_json) VALUES(?1,?2,?3,?4,?5,?6,?7)",params![chain_id,event.contract_address,block_number,event.block_hash,event.transaction_hash,log_index,event.payload_json])?;
        transaction.commit()?;
        Ok(true)
    }

    pub fn chain_events(
        &self,
        chain_id: u64,
        contract: &str,
        from_block: u64,
        to_block: u64,
    ) -> Result<Vec<ChainEventRecord>, StoreError> {
        if from_block > to_block {
            return Err(StoreError::InvalidRecord(
                "block range starts after it ends".into(),
            ));
        }
        let Ok(from_block) = i64::try_from(from_block) else {
            return Ok(Vec::new());
        };
        let to_block = i64::try_from(to_block).unwrap_or(i64::MAX);
        let connection = self.connection()?;
        let mut statement = connection.prepare("SELECT chain_id,contract_address,block_number,block_hash,transaction_hash,log_index,payload_json FROM chain_events WHERE chain_id=?1 AND contract_address=?2 AND block_number>=?3 AND block_number<=?4 ORDER BY block_number,log_index,transaction_hash,block_hash")?;
        Ok(statement
            .query_map(
                params![sqlite_integer(chain_id)?, contract, from_block, to_block],
                decode_event,
            )?
            .collect::<rusqlite::Result<Vec<_>>>()?)
    }

    pub fn rewind_chain(
        &self,
        chain_id: u64,
        contract: &str,
        from_block: u64,
    ) -> Result<(), StoreError> {
        let chain_id = sqlite_integer(chain_id)?;
        let from_block = sqlite_integer(from_block)?;
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        transaction.execute("UPDATE operations SET status='submitted',error=NULL WHERE id IN (SELECT operation_id FROM receipts WHERE chain_id=?1 AND contract_address=?2 AND block_number>=?3)",params![chain_id,contract,from_block])?;
        transaction.execute(
            "DELETE FROM receipts WHERE chain_id=?1 AND contract_address=?2 AND block_number>=?3",
            params![chain_id, contract, from_block],
        )?;
        transaction.execute("DELETE FROM chain_events WHERE chain_id=?1 AND contract_address=?2 AND block_number>=?3",params![chain_id,contract,from_block])?;
        transaction.commit()?;
        Ok(())
    }
}

fn sqlite_integer(value: u64) -> Result<i64, StoreError> {
    i64::try_from(value).map_err(|_| {
        StoreError::InvalidRecord("chain evidence integer exceeds SQLite range".into())
    })
}

fn validate_json(value: &str) -> Result<(), StoreError> {
    serde_json::from_str::<serde_json::Value>(value)
        .map(|_| ())
        .map_err(|_| StoreError::InvalidRecord("expected valid JSON".into()))
}

fn has_retained_commitment(
    connection: &Connection,
    episode_id: &str,
    actor_id: &str,
) -> rusqlite::Result<bool> {
    connection.query_row(
        "SELECT EXISTS(SELECT 1 FROM operations o LEFT JOIN signed_transactions s ON s.operation_id=o.id WHERE o.episode_id=?1 AND o.actor_id=?2 AND o.kind='commit_vote' AND (o.status<>'failed' OR s.operation_id IS NOT NULL))",
        params![episode_id,actor_id],
        |row| row.get(0),
    )
}

fn read_operation(
    connection: &Connection,
    id: &str,
) -> Result<Option<StoredOperation>, StoreError> {
    Ok(connection
        .query_row(
            &format!("{OPERATION_QUERY} WHERE o.id=?1"),
            [id],
            decode_operation,
        )
        .optional()?)
}

fn required_operation(connection: &Connection, id: &str) -> Result<StoredOperation, StoreError> {
    read_operation(connection, id)?.ok_or_else(|| StoreError::NotFound(id.into()))
}

fn decode_operation(row: &rusqlite::Row<'_>) -> rusqlite::Result<StoredOperation> {
    let prepared = if let Some(sender) = row.get::<_, Option<String>>(10)? {
        let nonce: String = row.get(11)?;
        Some(PreparedTransactionRecord {
            sender,
            nonce: nonce.parse().map_err(|error| {
                rusqlite::Error::FromSqlConversionFailure(
                    11,
                    rusqlite::types::Type::Text,
                    Box::new(error),
                )
            })?,
            tx_hash: row.get(12)?,
            raw_transaction: row.get(13)?,
        })
    } else {
        None
    };
    let receipt = if let Some(chain_id) = row.get::<_, Option<u64>>(14)? {
        Some(ReceiptRecord {
            chain_id,
            contract_address: row.get(15)?,
            transaction_hash: row.get(16)?,
            block_number: row.get(17)?,
            block_hash: row.get(18)?,
            gas_used: row.get(19)?,
            effective_gas_price: row.get(20)?,
            receipt_json: row.get(21)?,
        })
    } else {
        None
    };
    Ok(StoredOperation {
        id: row.get(0)?,
        scope: row.get(1)?,
        key: row.get(2)?,
        request_digest: row.get(3)?,
        episode_id: row.get(4)?,
        actor_id: row.get(5)?,
        kind: row.get(6)?,
        request_json: row.get(7)?,
        status: OperationStatus::from_stored(&row.get::<_, String>(8)?)?,
        error: row.get(9)?,
        prepared,
        receipt,
    })
}

fn decode_episode(row: &rusqlite::Row<'_>) -> rusqlite::Result<StoredEpisode> {
    Ok(StoredEpisode {
        id: row.get(0)?,
        onchain_id: row.get(1)?,
        configuration_hash: row.get(2)?,
        config_json: row.get(3)?,
    })
}

fn read_reveal(
    connection: &Connection,
    episode_id: &str,
    actor_id: &str,
) -> Result<Option<RevealMaterial>, StoreError> {
    Ok(connection.query_row("SELECT verdict,assessment_hash,salt,assessment_utf8 FROM reveal_material WHERE episode_id=?1 AND actor_id=?2",params![episode_id,actor_id],|row| {
        let salt: Vec<u8> = row.get(2)?;
        let salt = salt.try_into().map_err(|_|rusqlite::Error::InvalidColumnType(2,"salt".into(),rusqlite::types::Type::Blob))?;
        Ok(RevealMaterial { verdict:row.get(0)?,assessment_hash:row.get(1)?,salt,assessment_utf8:row.get(3)? })
    }).optional()?)
}

fn decode_event(row: &rusqlite::Row<'_>) -> rusqlite::Result<ChainEventRecord> {
    Ok(ChainEventRecord {
        chain_id: row.get(0)?,
        contract_address: row.get(1)?,
        block_number: row.get(2)?,
        block_hash: row.get(3)?,
        transaction_hash: row.get(4)?,
        log_index: row.get(5)?,
        payload_json: row.get(6)?,
    })
}
