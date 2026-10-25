//! Persistent episode-wide communication. Contract rules remain authoritative.

mod types;
pub use types::*;

use std::sync::Arc;

use crate::{
    chat::ChatPrincipal,
    game::{GameError, RegisterEpisode, validate_key},
    store::Store,
};

#[derive(Clone)]
pub struct ForumService {
    store: Arc<Store>,
    operator_id: String,
}

impl ForumService {
    pub fn new(store: Arc<Store>, operator_id: String) -> Self {
        Self { store, operator_id }
    }

    fn actor(&self, principal: ChatPrincipal) -> ForumActor {
        match principal {
            ChatPrincipal::Operator => ForumActor {
                id: self.operator_id.clone(),
                operator: true,
            },
            ChatPrincipal::Participant(id) => ForumActor {
                id,
                operator: false,
            },
        }
    }

    // Independent of the game's chain-operation mutex, matching private chat.
    async fn blocking<T, F>(&self, action: F) -> Result<T, GameError>
    where
        T: Send + 'static,
        F: FnOnce(&Store) -> Result<T, GameError> + Send + 'static,
    {
        let store = self.store.clone();
        tokio::task::spawn_blocking(move || action(&store))
            .await
            .map_err(|_| GameError::Internal("forum storage task failed".into()))?
    }

    pub async fn send(
        &self,
        principal: ChatPrincipal,
        episode_id: String,
        request: ForumSendMessage,
        key: String,
    ) -> Result<ForumMessage, GameError> {
        validate_key(&key)?;
        if request.content.len() > 16 * 1024
            || request.content.trim().is_empty()
            || request.round_num == Some(0)
        {
            return Err(GameError::Validation("forum message requires 1–16384 UTF-8 bytes, non-whitespace text, and a positive optional round".into()));
        }
        let actor = self.actor(principal);
        self.blocking(move |store| {
            authorize(store, &episode_id, &actor, false)?;
            Ok(store.send_forum_message(&actor, &episode_id, &request, &key)?)
        })
        .await
    }

    pub async fn messages(
        &self,
        principal: ChatPrincipal,
        episode_id: String,
        query: ForumQuery,
        transcript: bool,
    ) -> Result<ForumMessagePage, GameError> {
        let limit = page_limit(query)?;
        let actor = self.actor(principal);
        self.blocking(move |store| {
            authorize(store, &episode_id, &actor, transcript)?;
            Ok(store.read_forum_messages(&actor, &episode_id, query.after, limit, transcript)?)
        })
        .await
    }

    pub async fn audit(
        &self,
        principal: ChatPrincipal,
        episode_id: String,
        query: ForumQuery,
    ) -> Result<ForumAuditReport, GameError> {
        let limit = page_limit(query)?;
        let actor = self.actor(principal);
        self.blocking(move |store| {
            authorize(store, &episode_id, &actor, true)?;
            Ok(store.forum_audit(&episode_id, query.after, limit)?)
        })
        .await
    }
}

fn page_limit(query: ForumQuery) -> Result<u16, GameError> {
    query.page_limit().ok_or_else(|| GameError::Validation("invalid forum pagination; limit must be 1–100 and after must fit signed 64-bit storage".into()))
}

fn authorize(
    store: &Store,
    episode_id: &str,
    actor: &ForumActor,
    operator_only: bool,
) -> Result<(), GameError> {
    let record = store
        .get_episode(episode_id)?
        .ok_or_else(|| GameError::NotFound("episode".into()))?;
    let config: RegisterEpisode = serde_json::from_str(&record.config_json)
        .map_err(|_| GameError::Internal("invalid episode configuration".into()))?;
    let assigned = actor.id == config.creator_id
        || actor.id == config.challenger_id
        || actor.id == config.treasury_id
        || config.juror_ids.contains(&actor.id);
    let allowed = if operator_only {
        actor.operator
    } else {
        !actor.operator && assigned
    };
    if allowed {
        return Ok(());
    }
    store.forum_denied(episode_id, actor)?;
    Err(GameError::Forbidden(
        if operator_only {
            "forum transcript and audit require an operator credential"
        } else {
            "forum communication requires a participant assigned to this episode"
        }
        .into(),
    ))
}
