use std::time::{SystemTime, UNIX_EPOCH};

use alloy::primitives::keccak256;
use rusqlite::{Connection, OptionalExtension, Row, Transaction, TransactionBehavior, params};
use serde::{Serialize, de::DeserializeOwned};

use super::{Store, StoreError};
use crate::chat::{
    ChatActor, ChatActorUsage, ChatAuditEvent, ChatAuditKind, ChatAuditReport, ChatMessage,
    ChatPage, ChatRecord, ChatView, CreateChat, MessagePage, SendMessage,
};

impl Store {
    pub(crate) fn create_chat(
        &self,
        actor: &ChatActor,
        episode_id: &str,
        request: &CreateChat,
        key: &str,
    ) -> Result<ChatView, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let scope = format!("create:{episode_id}:{}", actor.operator);
        let digest = digest(request)?;
        if let Some(existing) = cached(&transaction, &scope, actor, key, &digest)? {
            return Ok(existing);
        }
        let view = ChatView {
            chat_id: uuid::Uuid::new_v4().to_string(),
            episode_id: episode_id.into(),
            participant_ids: request.participant_ids.clone(),
            history_enabled: request.history_enabled,
            created_at_ms: now_ms()?,
        };
        transaction.execute("INSERT INTO chats(id,episode_id,first_id,second_id,history_enabled,communication_prohibited,created_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7)",
            params![view.chat_id, episode_id, view.participant_ids[0], view.participant_ids[1], view.history_enabled,
                request.communication_prohibited, view.created_at_ms])?;
        cache(&transaction, &scope, actor, key, &digest, &view)?;
        let record = ChatRecord {
            view: view.clone(),
            prohibited: request.communication_prohibited,
        };
        let event = chat_event(actor, &record, ChatAuditKind::ChatCreated)?;
        commit_event(transaction, event)?;
        Ok(view)
    }

    pub(crate) fn send_chat_message(
        &self,
        actor: &ChatActor,
        chat_id: &str,
        request: &SendMessage,
        key: &str,
    ) -> Result<ChatMessage, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let chat = required_chat(&transaction, chat_id)?;
        if !chat.allows(actor, false) {
            commit_event(
                transaction,
                chat_event(actor, &chat, ChatAuditKind::AccessDenied)?,
            )?;
            return Err(StoreError::AccessDenied);
        }
        let scope = format!("send:{chat_id}");
        let digest = digest(request)?;
        if let Some(existing) = cached(&transaction, &scope, actor, key, &digest)? {
            return Ok(existing);
        }
        let sequence: u64 = transaction.query_row(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM chat_messages WHERE chat_id=?1",
            [chat_id],
            |row| row.get(0),
        )?;
        let recipient_id = if actor.id == chat.view.participant_ids[0] {
            &chat.view.participant_ids[1]
        } else {
            &chat.view.participant_ids[0]
        };
        let message = ChatMessage {
            message_id: uuid::Uuid::new_v4().to_string(),
            sequence,
            sender_id: actor.id.clone(),
            recipient_id: recipient_id.clone(),
            content: request.content.clone(),
            content_hash: keccak256(request.content.as_bytes()).to_string(),
            created_at_ms: now_ms()?,
        };
        transaction.execute("INSERT INTO chat_messages(chat_id,sequence,id,sender_id,recipient_id,content,content_hash,created_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
            params![chat_id, sequence, message.message_id, actor.id, recipient_id, message.content, message.content_hash, message.created_at_ms])?;
        cache(&transaction, &scope, actor, key, &digest, &message)?;
        let mut event = chat_event(actor, &chat, ChatAuditKind::MessageSent)?;
        event.recipient_id = Some(message.recipient_id.clone());
        event.message_sequence = Some(sequence);
        event.message_hash = Some(message.content_hash.clone());
        event.message_bytes = Some(message.content.len() as u64);
        event.policy_violation = chat.prohibited;
        commit_event(transaction, event)?;
        Ok(message)
    }

    pub(crate) fn read_chat_messages(
        &self,
        actor: &ChatActor,
        chat_id: &str,
        after: u64,
        limit: u16,
        transcript: bool,
    ) -> Result<MessagePage, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let chat = required_chat(&transaction, chat_id)?;
        if !chat.allows(actor, transcript) {
            commit_event(
                transaction,
                chat_event(actor, &chat, ChatAuditKind::AccessDenied)?,
            )?;
            return Err(StoreError::AccessDenied);
        }
        let sql = if chat.view.history_enabled || transcript {
            "SELECT id,sequence,sender_id,recipient_id,content,content_hash,created_at_ms FROM chat_messages WHERE chat_id=?1 AND sequence>?2 ORDER BY sequence LIMIT ?3"
        } else {
            "SELECT id,sequence,sender_id,recipient_id,content,content_hash,created_at_ms FROM chat_messages WHERE chat_id=?1 AND sequence>?2 ORDER BY sequence DESC LIMIT 1"
        };
        let mut statement = transaction.prepare(sql)?;
        let mut messages: Vec<ChatMessage> = if chat.view.history_enabled || transcript {
            statement
                .query_map(
                    params![chat_id, after, u32::from(limit) + 1],
                    decode_message,
                )?
                .collect::<rusqlite::Result<_>>()?
        } else {
            statement
                .query_map(params![chat_id, after], decode_message)?
                .collect::<rusqlite::Result<_>>()?
        };
        drop(statement);
        let has_more = messages.len() > usize::from(limit);
        messages.truncate(usize::from(limit));
        let next_after = messages.last().map_or(after, |message| message.sequence);
        let mut event = chat_event(
            actor,
            &chat,
            if transcript {
                ChatAuditKind::TranscriptRead
            } else {
                ChatAuditKind::MessagesRead
            },
        )?;
        event.returned_sequences = messages.iter().map(|message| message.sequence).collect();
        event.policy_violation = !transcript && chat.prohibited && !messages.is_empty();
        commit_event(transaction, event)?;
        Ok(MessagePage {
            chat_id: chat_id.into(),
            messages,
            next_after,
            has_more,
        })
    }

    pub(crate) fn list_chats(
        &self,
        actor: &ChatActor,
        episode_id: &str,
        after: Option<&str>,
        limit: u16,
    ) -> Result<ChatPage, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut statement = transaction.prepare("SELECT id,episode_id,first_id,second_id,history_enabled,created_at_ms,communication_prohibited FROM chats WHERE episode_id=?1 AND id>?2 AND (?3 OR first_id=?4 OR second_id=?4) ORDER BY id LIMIT ?5")?;
        let mut chats: Vec<ChatView> = statement
            .query_map(
                params![
                    episode_id,
                    after.unwrap_or(""),
                    actor.operator,
                    actor.id,
                    u32::from(limit) + 1
                ],
                decode_chat,
            )?
            .map(|row| row.map(|chat| chat.view))
            .collect::<rusqlite::Result<_>>()?;
        drop(statement);
        let has_more = chats.len() > usize::from(limit);
        chats.truncate(usize::from(limit));
        let next_after = chats.last().map(|chat| chat.chat_id.clone());
        commit_event(
            transaction,
            episode_event(actor, episode_id, ChatAuditKind::ChatsListed)?,
        )?;
        Ok(ChatPage {
            chats,
            next_after,
            has_more,
        })
    }

    pub(crate) fn chat_denied(
        &self,
        episode_id: &str,
        chat_id: Option<&str>,
        actor: &ChatActor,
    ) -> Result<(), StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction_with_behavior(TransactionBehavior::Immediate)?;
        let mut event = episode_event(actor, episode_id, ChatAuditKind::AccessDenied)?;
        event.chat_id = chat_id.map(str::to_owned);
        commit_event(transaction, event)
    }

    pub(crate) fn chat_audit(
        &self,
        episode_id: &str,
        after: u64,
        limit: u16,
    ) -> Result<ChatAuditReport, StoreError> {
        let mut connection = self.connection()?;
        let transaction = connection.transaction()?;
        let chat_count: u64 = transaction.query_row(
            "SELECT COUNT(*) FROM chats WHERE episode_id=?1",
            [episode_id],
            |row| row.get(0),
        )?;
        let message_count: u64 = transaction.query_row("SELECT COUNT(*) FROM chat_messages m JOIN chats c ON c.id=m.chat_id WHERE c.episode_id=?1", [episode_id], |row| row.get(0))?;
        let chat_used = transaction.query_row(
            "SELECT EXISTS(SELECT 1 FROM chat_audit WHERE episode_id=?1 AND actor_is_operator=0)",
            [episode_id],
            |row| row.get(0),
        )?;
        let prohibited_communication_used = transaction.query_row("SELECT EXISTS(SELECT 1 FROM chat_audit WHERE episode_id=?1 AND kind='message_sent' AND policy_violation=1)", [episode_id], |row| row.get(0))?;
        let actors = {
            let mut statement = transaction.prepare("SELECT actor_id,SUM(kind='chat_created'),SUM(kind='message_sent'),SUM(kind='messages_read'),SUM(CASE WHEN kind='messages_read' THEN json_array_length(json_extract(metadata_json,'$.returned_sequences')) ELSE 0 END),SUM(kind='access_denied'),SUM(kind='message_sent' AND policy_violation=1),SUM(kind='messages_read' AND policy_violation=1) FROM chat_audit WHERE episode_id=?1 AND actor_is_operator=0 GROUP BY actor_id ORDER BY actor_id")?;
            statement
                .query_map([episode_id], |row| {
                    Ok(ChatActorUsage {
                        actor_id: row.get(0)?,
                        created_chats: row.get(1)?,
                        sent_messages: row.get(2)?,
                        read_requests: row.get(3)?,
                        messages_returned: row.get(4)?,
                        denied_requests: row.get(5)?,
                        prohibited_sent_messages: row.get(6)?,
                        prohibited_read_requests: row.get(7)?,
                    })
                })?
                .collect::<rusqlite::Result<Vec<_>>>()?
        };
        let mut events = {
            let mut statement = transaction.prepare("SELECT sequence,metadata_json FROM chat_audit WHERE episode_id=?1 AND sequence>?2 ORDER BY sequence LIMIT ?3")?;
            let rows = statement
                .query_map(params![episode_id, after, u32::from(limit) + 1], |row| {
                    Ok((row.get::<_, u64>(0)?, row.get::<_, String>(1)?))
                })?;
            rows.map(|row| {
                let (sequence, json) = row?;
                let mut event: ChatAuditEvent = decode(&json)?;
                event.sequence = sequence;
                Ok(event)
            })
            .collect::<Result<Vec<_>, StoreError>>()?
        };
        let has_more = events.len() > usize::from(limit);
        events.truncate(usize::from(limit));
        let next_after = events.last().map_or(after, |event| event.sequence);
        transaction.commit()?;
        Ok(ChatAuditReport {
            episode_id: episode_id.into(),
            chat_used,
            communication_used: message_count > 0,
            prohibited_communication_used,
            chat_count,
            message_count,
            actors,
            events,
            next_after,
            has_more,
        })
    }
}

fn required_chat(connection: &Connection, id: &str) -> Result<ChatRecord, StoreError> {
    connection.query_row("SELECT id,episode_id,first_id,second_id,history_enabled,created_at_ms,communication_prohibited FROM chats WHERE id=?1", [id], decode_chat)
        .optional()?.ok_or_else(|| StoreError::NotFound("chat".into()))
}

fn decode_chat(row: &Row<'_>) -> rusqlite::Result<ChatRecord> {
    Ok(ChatRecord {
        view: ChatView {
            chat_id: row.get(0)?,
            episode_id: row.get(1)?,
            participant_ids: [row.get(2)?, row.get(3)?],
            history_enabled: row.get(4)?,
            created_at_ms: row.get(5)?,
        },
        prohibited: row.get(6)?,
    })
}

fn decode_message(row: &Row<'_>) -> rusqlite::Result<ChatMessage> {
    Ok(ChatMessage {
        message_id: row.get(0)?,
        sequence: row.get(1)?,
        sender_id: row.get(2)?,
        recipient_id: row.get(3)?,
        content: row.get(4)?,
        content_hash: row.get(5)?,
        created_at_ms: row.get(6)?,
    })
}

fn episode_event(
    actor: &ChatActor,
    episode_id: &str,
    kind: ChatAuditKind,
) -> Result<ChatAuditEvent, StoreError> {
    Ok(ChatAuditEvent {
        sequence: 0,
        episode_id: episode_id.into(),
        chat_id: None,
        actor_id: actor.id.clone(),
        actor_is_operator: actor.operator,
        kind,
        communication_prohibited: false,
        policy_violation: false,
        recipient_id: None,
        message_sequence: None,
        message_hash: None,
        message_bytes: None,
        returned_sequences: Vec::new(),
        created_at_ms: now_ms()?,
    })
}

fn chat_event(
    actor: &ChatActor,
    chat: &ChatRecord,
    kind: ChatAuditKind,
) -> Result<ChatAuditEvent, StoreError> {
    let mut event = episode_event(actor, &chat.view.episode_id, kind)?;
    event.chat_id = Some(chat.view.chat_id.clone());
    event.communication_prohibited = chat.prohibited;
    Ok(event)
}

fn commit_event(transaction: Transaction<'_>, event: ChatAuditEvent) -> Result<(), StoreError> {
    transaction.execute("INSERT INTO chat_audit(episode_id,chat_id,actor_id,actor_is_operator,kind,policy_violation,metadata_json) VALUES(?1,?2,?3,?4,?5,?6,?7)",
        params![event.episode_id,event.chat_id,event.actor_id,event.actor_is_operator,event.kind.as_str(),event.policy_violation,encode(&event)?])?;
    let audit_sequence = transaction.last_insert_rowid();
    transaction.commit()?;
    tracing::info!(event="chat.audit.recorded", kind=event.kind.as_str(), episode_id=%event.episode_id,
        chat_id=event.chat_id.as_deref().unwrap_or(""), actor_id=%event.actor_id, operator=event.actor_is_operator,
        audit_sequence, policy_violation=event.policy_violation);
    Ok(())
}

fn cached<T: DeserializeOwned>(
    transaction: &Transaction<'_>,
    scope: &str,
    actor: &ChatActor,
    key: &str,
    digest: &str,
) -> Result<Option<T>, StoreError> {
    let existing = transaction.query_row("SELECT request_digest,response_json FROM chat_requests WHERE scope=?1 AND actor_id=?2 AND idempotency_key=?3", params![scope,actor.id,key],
        |row| Ok((row.get::<_,String>(0)?,row.get::<_,String>(1)?))).optional()?;
    match existing {
        Some((previous, response)) if previous == digest => Ok(Some(decode(&response)?)),
        Some(_) => Err(StoreError::Conflict(
            "chat idempotency payload changed".into(),
        )),
        None => Ok(None),
    }
}

fn cache<T: Serialize>(
    transaction: &Transaction<'_>,
    scope: &str,
    actor: &ChatActor,
    key: &str,
    digest: &str,
    response: &T,
) -> Result<(), StoreError> {
    transaction.execute("INSERT INTO chat_requests(scope,actor_id,idempotency_key,request_digest,response_json) VALUES(?1,?2,?3,?4,?5)", params![scope,actor.id,key,digest,encode(response)?])?;
    Ok(())
}

fn digest<T: Serialize>(request: &T) -> Result<String, StoreError> {
    let bytes = serde_jcs::to_vec(request)
        .map_err(|_| StoreError::InvalidRecord("invalid chat request".into()))?;
    Ok(keccak256(bytes).to_string())
}

fn encode<T: Serialize>(value: &T) -> Result<String, StoreError> {
    serde_json::to_string(value)
        .map_err(|_| StoreError::InvalidRecord("invalid chat record".into()))
}

fn decode<T: DeserializeOwned>(value: &str) -> Result<T, StoreError> {
    serde_json::from_str(value).map_err(|_| StoreError::InvalidRecord("invalid chat record".into()))
}

fn now_ms() -> Result<u64, StoreError> {
    let value = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| StoreError::InvalidRecord("clock precedes Unix epoch".into()))?
        .as_millis();
    let value = i64::try_from(value)
        .map_err(|_| StoreError::InvalidRecord("clock exceeds SQLite range".into()))?;
    Ok(value as u64)
}
