CREATE TABLE forum_messages (
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    id TEXT NOT NULL UNIQUE,
    sender_id TEXT NOT NULL,
    content TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    round_num INTEGER CHECK (round_num IS NULL OR round_num BETWEEN 1 AND 4294967295),
    created_at_ms INTEGER NOT NULL CHECK (created_at_ms >= 0),
    PRIMARY KEY(episode_id, sequence)
);
CREATE TABLE forum_requests (
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    response_json TEXT NOT NULL CHECK (json_valid(response_json)),
    PRIMARY KEY(episode_id, actor_id, idempotency_key)
);
CREATE TABLE forum_audit (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id TEXT NOT NULL REFERENCES episodes(id),
    actor_id TEXT NOT NULL,
    actor_is_operator INTEGER NOT NULL CHECK (actor_is_operator IN (0,1)),
    kind TEXT NOT NULL CHECK (kind IN ('message_sent','messages_read','transcript_read','access_denied')),
    metadata_json TEXT NOT NULL CHECK (json_valid(metadata_json))
);
CREATE INDEX forum_audit_episode ON forum_audit(episode_id, sequence);
CREATE INDEX forum_audit_actor ON forum_audit(episode_id, actor_id, kind);
PRAGMA user_version = 3;
