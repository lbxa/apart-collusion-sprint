//! Off-chain experimental communication, separate from contract game authority.

mod types;
pub use types::*;

use crate::{
    game::{GameError, RegisterEpisode, validate_key},
    store::Store,
};
use std::sync::Arc;

#[derive(Clone)]
pub struct ChatService {
    store: Arc<Store>,
    operator_id: String,
}

impl ChatService {
    pub fn new(store: Arc<Store>, operator_id: String) -> Self {
        Self { store, operator_id }
    }

    fn actor(&self, principal: ChatPrincipal) -> ChatActor {
        match principal {
            ChatPrincipal::Operator => ChatActor {
                id: self.operator_id.clone(),
                operator: true,
            },
            ChatPrincipal::Participant(id) => ChatActor {
                id,
                operator: false,
            },
        }
    }

    // SQLite may wait on another connection. Keep its blocking work off the
    // async runtime and independent of the game's chain-operation mutex.
    async fn blocking<T, F>(&self, action: F) -> Result<T, GameError>
    where
        T: Send + 'static,
        F: FnOnce(&Store) -> Result<T, GameError> + Send + 'static,
    {
        let store = self.store.clone();
        tokio::task::spawn_blocking(move || action(&store))
            .await
            .map_err(|_| GameError::Internal("chat storage task failed".into()))?
    }

    pub async fn create(
        &self,
        principal: ChatPrincipal,
        episode_id: String,
        request: CreateChat,
        key: String,
    ) -> Result<ChatView, GameError> {
        validate_key(&key)?;
        let actor = self.actor(principal);
        self.blocking(move |store| {
            let config = episode(store, &episode_id)?;
            if request.participant_ids[0] == request.participant_ids[1]
                || !request
                    .participant_ids
                    .iter()
                    .all(|id| assigned(&config, id))
            {
                return Err(GameError::Validation(
                    "a chat requires two distinct participants assigned to this episode".into(),
                ));
            }
            if !actor.operator
                && (!request.participant_ids.contains(&actor.id)
                    || !request.communication_prohibited)
            {
                store.chat_denied(&episode_id, None, &actor)?;
                return Err(GameError::Forbidden(
                    "participants may create only their own prohibited-communication chats".into(),
                ));
            }
            Ok(store.create_chat(&actor, &episode_id, &request, &key)?)
        })
        .await
    }

    pub async fn list(
        &self,
        principal: ChatPrincipal,
        episode_id: String,
        query: ChatListQuery,
    ) -> Result<ChatPage, GameError> {
        let limit = query.limit.unwrap_or(50);
        if !(1..=100).contains(&limit) || query.after.as_ref().is_some_and(|id| id.len() > 128) {
            return Err(GameError::Validation(
                "invalid chat pagination; limit must be 1–100".into(),
            ));
        }
        let actor = self.actor(principal);
        self.blocking(move |store| {
            let config = episode(store, &episode_id)?;
            if !actor.operator && !assigned(&config, &actor.id) {
                store.chat_denied(&episode_id, None, &actor)?;
                return Err(GameError::Forbidden(
                    "participant is not assigned to this episode".into(),
                ));
            }
            Ok(store.list_chats(&actor, &episode_id, query.after.as_deref(), limit)?)
        })
        .await
    }

    pub async fn send(
        &self,
        principal: ChatPrincipal,
        chat_id: String,
        request: SendMessage,
        key: String,
    ) -> Result<ChatMessage, GameError> {
        validate_key(&key)?;
        if request.content.len() > 16 * 1024 || request.content.trim().is_empty() {
            return Err(GameError::Validation(
                "message must contain 1–16384 UTF-8 bytes and not be entirely whitespace".into(),
            ));
        }
        let actor = self.actor(principal);
        self.blocking(move |store| Ok(store.send_chat_message(&actor, &chat_id, &request, &key)?))
            .await
    }

    pub async fn messages(
        &self,
        principal: ChatPrincipal,
        chat_id: String,
        query: ChatQuery,
        transcript: bool,
    ) -> Result<MessagePage, GameError> {
        let limit = page_limit(query)?;
        let actor = self.actor(principal);
        self.blocking(move |store| {
            Ok(store.read_chat_messages(&actor, &chat_id, query.after, limit, transcript)?)
        })
        .await
    }

    pub async fn audit(
        &self,
        principal: ChatPrincipal,
        episode_id: String,
        query: ChatQuery,
    ) -> Result<ChatAuditReport, GameError> {
        let limit = page_limit(query)?;
        let actor = self.actor(principal);
        self.blocking(move |store| {
            episode(store, &episode_id)?;
            if !actor.operator {
                store.chat_denied(&episode_id, None, &actor)?;
                return Err(GameError::Forbidden(
                    "chat audit requires an operator credential".into(),
                ));
            }
            Ok(store.chat_audit(&episode_id, query.after, limit)?)
        })
        .await
    }
}

fn page_limit(query: ChatQuery) -> Result<u16, GameError> {
    query.page_limit().ok_or_else(|| {
        GameError::Validation(
            "invalid chat pagination; limit must be 1–100 and after must fit signed 64-bit storage"
                .into(),
        )
    })
}

fn episode(store: &Store, id: &str) -> Result<RegisterEpisode, GameError> {
    let record = store
        .get_episode(id)?
        .ok_or_else(|| GameError::NotFound("episode".into()))?;
    serde_json::from_str(&record.config_json)
        .map_err(|_| GameError::Internal("invalid episode configuration".into()))
}

fn assigned(config: &RegisterEpisode, actor: &str) -> bool {
    actor == config.creator_id
        || actor == config.challenger_id
        || actor == config.treasury_id
        || config.juror_ids.iter().any(|id| id == actor)
}
