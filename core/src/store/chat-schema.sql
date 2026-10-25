CREATE TABLE chats (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    first_id TEXT NOT NULL,
    second_id TEXT NOT NULL CHECK (first_id <> second_id),
    history_enabled INTEGER NOT NULL CHECK (history_enabled IN (0,1)),
    communication_prohibited INTEGER NOT NULL CHECK (communication_prohibited IN (0,1)),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0)
);
CREATE INDEX chats_episode ON chats(episode_id, id);
CREATE TABLE chat_messages (
    chat_id TEXT NOT NULL REFERENCES chats(id),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    id TEXT NOT NULL UNIQUE,
    sender_id TEXT NOT NULL,
    recipient_id TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY(chat_id, sequence)
);
CREATE TABLE chat_requests (
    scope TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    response_json TEXT NOT NULL,
    PRIMARY KEY(scope, actor_id, idempotency_key)
);
CREATE TABLE chat_audit (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    chat_id TEXT REFERENCES chats(id),
    actor_id TEXT NOT NULL,
    actor_is_operator INTEGER NOT NULL CHECK (actor_is_operator IN (0,1)),
    kind TEXT NOT NULL CHECK (kind IN ('chat_created','message_sent','messages_read','chats_listed','transcript_read','access_denied')),
    policy_violation INTEGER NOT NULL CHECK (policy_violation IN (0,1)),
    metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json))
);
CREATE INDEX chat_audit_episode ON chat_audit(episode_id, sequence);
CREATE INDEX chat_audit_actor ON chat_audit(episode_id, actor_id, kind);
PRAGMA user_version = 2;
