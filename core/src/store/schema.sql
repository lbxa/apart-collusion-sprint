CREATE TABLE IF NOT EXISTS deployment (
    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
    identity_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    onchain_id TEXT NOT NULL UNIQUE,
    configuration_hash TEXT NOT NULL,
    config_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    episode_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    request_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('accepted','prepared','submitted','included','confirmed','reverted','failed')),
    error TEXT,
    UNIQUE(scope, idempotency_key)
);
CREATE TABLE IF NOT EXISTS signed_transactions (
    operation_id TEXT PRIMARY KEY REFERENCES operations(id),
    sender TEXT NOT NULL,
    nonce TEXT NOT NULL,
    transaction_hash TEXT NOT NULL UNIQUE,
    raw_transaction BLOB NOT NULL CHECK (length(raw_transaction) > 0),
    UNIQUE(sender, nonce)
);
CREATE TABLE IF NOT EXISTS receipts (
    operation_id TEXT PRIMARY KEY REFERENCES operations(id),
    chain_id INTEGER NOT NULL CHECK (chain_id >= 0),
    contract_address TEXT NOT NULL,
    transaction_hash TEXT NOT NULL,
    block_number INTEGER NOT NULL CHECK (block_number >= 0),
    block_hash TEXT NOT NULL,
    gas_used TEXT NOT NULL,
    effective_gas_price TEXT NOT NULL,
    receipt_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS reveal_material (
    episode_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    verdict INTEGER NOT NULL CHECK (verdict IN (0,1)),
    assessment_hash TEXT NOT NULL,
    salt BLOB NOT NULL CHECK (length(salt) = 32),
    assessment_utf8 TEXT NOT NULL,
    PRIMARY KEY (episode_id, actor_id)
);
CREATE TABLE IF NOT EXISTS artifacts (
    hash TEXT PRIMARY KEY,
    utf8 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chain_events (
    chain_id INTEGER NOT NULL CHECK (chain_id >= 0),
    contract_address TEXT NOT NULL,
    block_number INTEGER NOT NULL CHECK (block_number >= 0),
    block_hash TEXT NOT NULL,
    transaction_hash TEXT NOT NULL,
    log_index INTEGER NOT NULL CHECK (log_index >= 0),
    payload_json TEXT NOT NULL,
    PRIMARY KEY (chain_id, contract_address, block_hash, transaction_hash, log_index)
);
PRAGMA user_version = 1;
