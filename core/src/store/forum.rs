use std::time::{SystemTime, UNIX_EPOCH};

use alloy::primitives::keccak256;
use rusqlite::{OptionalExtension, Row, Transaction, TransactionBehavior, params};
use serde::{Serialize, de::DeserializeOwned};

use super::{Store, StoreError};
use crate::forum::{
    ForumActor, ForumActorUsage, ForumAuditEvent, ForumAuditKind, ForumAuditReport, ForumMessage,
    ForumMessagePage, ForumSendMessage,
};

impl Store {
    pub(crate) fn send_forum_message(
        &self,
        actor: &ForumActor,
        episode_id: &str,
        request: &ForumSendMessage,
        key: &str,
    ) -> Result<ForumMessage, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let request_bytes = serde_jcs::to_vec(request)
            .map_err(|_| StoreError::InvalidRecord("invalid forum request".into()))?;
        let digest = keccak256(request_bytes).to_string();
        let existing = transaction
            .query_row(
                "SELECT request_digest, response_json FROM forum_requests
             WHERE episode_id=?1 AND actor_id=?2 AND idempotency_key=?3",
                params![episode_id, actor.id, key],
                |row| Ok((row.get::<_, String>(0)?, row.get::<_, String>(1)?)),
            )
            .optional()?;
        if let Some((previous, response)) = existing {
            return if previous == digest {
                decode(&response)
            } else {
                Err(StoreError::Conflict(
                    "forum idempotency payload changed".into(),
                ))
            };
        }
        let sequence = transaction.query_row(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM forum_messages WHERE episode_id=?1",
            [episode_id],
            |row| row.get(0),
        )?;
        let message = ForumMessage {
            message_id: uuid::Uuid::new_v4().to_string(),
            sequence,
            sender_id: actor.id.clone(),
            content: request.content.clone(),
            content_hash: keccak256(request.content.as_bytes()).to_string(),
            round_num: request.round_num,
            created_at_ms: now_ms()?,
        };
        transaction.execute(
            "INSERT INTO forum_messages(
                episode_id, sequence, id, sender_id, content, content_hash, round_num, created_at_ms
             ) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
            params![
                episode_id,
                message.sequence,
                message.message_id,
                message.sender_id,
                message.content,
                message.content_hash,
                message.round_num,
                message.created_at_ms
            ],
        )?;
        transaction.execute(
            "INSERT INTO forum_requests(
                episode_id, actor_id, idempotency_key, request_digest, response_json
             ) VALUES(?1,?2,?3,?4,?5)",
            params![episode_id, actor.id, key, digest, encode(&message)?],
        )?;
        let mut event = event(actor, episode_id, ForumAuditKind::MessageSent)?;
        event.message_sequence = Some(message.sequence);
        event.message_hash = Some(message.content_hash.clone());
        event.message_bytes = Some(message.content.len() as u64);
        event.round_num = message.round_num;
        commit_event(transaction, event)?;
        Ok(message)
    }

    pub(crate) fn read_forum_messages(
        &self,
        actor: &ForumActor,
        episode_id: &str,
        after: u64,
        limit: u16,
        transcript: bool,
    ) -> Result<ForumMessagePage, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut messages = {
            let mut statement = transaction.prepare(
                "SELECT id, sequence, sender_id, content, content_hash, round_num, created_at_ms
                 FROM forum_messages WHERE episode_id=?1 AND sequence>?2
                 ORDER BY sequence LIMIT ?3",
            )?;
            statement
                .query_map(
                    params![episode_id, after, u32::from(limit) + 1],
                    decode_message,
                )?
                .collect::<rusqlite::Result<Vec<_>>>()?
        };
        let has_more = messages.len() > usize::from(limit);
        messages.truncate(usize::from(limit));
        let next_after = messages.last().map_or(after, |message| message.sequence);
        let mut event = event(
            actor,
            episode_id,
            if transcript {
                ForumAuditKind::TranscriptRead
            } else {
                ForumAuditKind::MessagesRead
            },
        )?;
        event.returned_sequences = messages.iter().map(|message| message.sequence).collect();
        commit_event(transaction, event)?;
        Ok(ForumMessagePage {
            episode_id: episode_id.into(),
            messages,
            next_after,
            has_more,
        })
    }

    pub(crate) fn forum_denied(
        &self,
        episode_id: &str,
        actor: &ForumActor,
    ) -> Result<(), StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        commit_event(
            transaction,
            event(actor, episode_id, ForumAuditKind::AccessDenied)?,
        )
    }

    pub(crate) fn forum_audit(
        &self,
        episode_id: &str,
        after: u64,
        limit: u16,
    ) -> Result<ForumAuditReport, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction()?;
        let (
            message_count,
            total_message_bytes,
            active_sender_count,
            first_message_at_ms,
            last_message_at_ms,
        ): (u64, u64, u64, Option<u64>, Option<u64>) = transaction.query_row(
            "SELECT COUNT(*), COALESCE(SUM(length(CAST(content AS BLOB))),0),
                    COUNT(DISTINCT sender_id), MIN(created_at_ms), MAX(created_at_ms)
             FROM forum_messages WHERE episode_id=?1",
            [episode_id],
            |row| {
                Ok((
                    row.get(0)?,
                    row.get(1)?,
                    row.get(2)?,
                    row.get(3)?,
                    row.get(4)?,
                ))
            },
        )?;
        let forum_used = transaction.query_row(
            "SELECT EXISTS(SELECT 1 FROM forum_audit WHERE episode_id=?1 AND actor_is_operator=0)",
            [episode_id],
            |row| row.get(0),
        )?;
        let actors = {
            let mut statement = transaction.prepare(
                "SELECT actor_id,
                        SUM(kind='message_sent'),
                        SUM(kind='messages_read'),
                        SUM(CASE WHEN kind='messages_read'
                            THEN json_array_length(json_extract(metadata_json,'$.returned_sequences'))
                            ELSE 0 END),
                        SUM(kind='access_denied'),
                        SUM(CASE WHEN kind='message_sent'
                            THEN json_extract(metadata_json,'$.message_bytes') ELSE 0 END)
                 FROM forum_audit WHERE episode_id=?1 AND actor_is_operator=0
                 GROUP BY actor_id ORDER BY actor_id",
            )?;
            statement
                .query_map([episode_id], |row| {
                    Ok(ForumActorUsage {
                        actor_id: row.get(0)?,
                        sent_messages: row.get(1)?,
                        read_requests: row.get(2)?,
                        messages_returned: row.get(3)?,
                        denied_requests: row.get(4)?,
                        sent_bytes: row.get(5)?,
                    })
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?
        };
        let mut events = {
            let mut statement = transaction.prepare(
                "SELECT sequence, metadata_json FROM forum_audit
                 WHERE episode_id=?1 AND sequence>?2 ORDER BY sequence LIMIT ?3",
            )?;
            statement
                .query_map(params![episode_id, after, u32::from(limit) + 1], |row| {
                    Ok((row.get::<_, u64>(0)?, row.get::<_, String>(1)?))
                })?
                .map(|row| {
                    let (sequence, json) = row?;
                    let mut event: ForumAuditEvent = decode(&json)?;
                    event.sequence = sequence;
                    Ok(event)
                })
                .collect::<Result<Vec<_>, StoreError>>()?
        };
        let has_more = events.len() > usize::from(limit);
        events.truncate(usize::from(limit));
        let next_after = events.last().map_or(after, |event| event.sequence);
        transaction.commit()?;
        Ok(ForumAuditReport {
            episode_id: episode_id.into(),
            forum_used,
            communication_used: message_count > 0,
            message_count,
            total_message_bytes,
            active_sender_count,
            first_message_at_ms,
            last_message_at_ms,
            actors,
            events,
            next_after,
            has_more,
        })
    }
}

fn decode_message(row: &Row<'_>) -> rusqlite::Result<ForumMessage> {
    Ok(ForumMessage {
        message_id: row.get(0)?,
        sequence: row.get(1)?,
        sender_id: row.get(2)?,
        content: row.get(3)?,
        content_hash: row.get(4)?,
        round_num: row.get(5)?,
        created_at_ms: row.get(6)?,
    })
}

fn event(
    actor: &ForumActor,
    episode_id: &str,
    kind: ForumAuditKind,
) -> Result<ForumAuditEvent, StoreError> {
    Ok(ForumAuditEvent {
        sequence: 0,
        episode_id: episode_id.into(),
        actor_id: actor.id.clone(),
        actor_is_operator: actor.operator,
        kind,
        message_sequence: None,
        message_hash: None,
        message_bytes: None,
        round_num: None,
        returned_sequences: Vec::new(),
        created_at_ms: now_ms()?,
    })
}

fn commit_event(transaction: Transaction<'_>, event: ForumAuditEvent) -> Result<(), StoreError> {
    transaction.execute(
        "INSERT INTO forum_audit(episode_id, actor_id, actor_is_operator, kind, metadata_json)
         VALUES(?1,?2,?3,?4,?5)",
        params![
            event.episode_id,
            event.actor_id,
            event.actor_is_operator,
            event.kind.as_str(),
            encode(&event)?
        ],
    )?;
    let audit_sequence = transaction.last_insert_rowid();
    transaction.commit()?;
    tracing::info!(
        event="forum.audit.recorded",kind=event.kind.as_str(),episode_id=%event.episode_id,
        actor_id=%event.actor_id,operator=event.actor_is_operator,audit_sequence,
        message_sequence=event.message_sequence,message_bytes=event.message_bytes,
        round_num=event.round_num,returned_messages=event.returned_sequences.len()
    );
    Ok(())
}

fn encode<T: Serialize>(value: &T) -> Result<String, StoreError> {
    serde_json::to_string(value)
        .map_err(|_| StoreError::InvalidRecord("invalid forum record".into()))
}

fn decode<T: DeserializeOwned>(value: &str) -> Result<T, StoreError> {
    serde_json::from_str(value)
        .map_err(|_| StoreError::InvalidRecord("invalid forum record".into()))
}

fn now_ms() -> Result<u64, StoreError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| StoreError::InvalidRecord("clock precedes Unix epoch".into()))?
        .as_millis();
    i64::try_from(millis)
        .map(|value| value as u64)
        .map_err(|_| StoreError::InvalidRecord("clock exceeds SQLite range".into()))
}
