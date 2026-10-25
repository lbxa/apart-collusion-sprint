pub mod types;
pub use types::*;
mod validation;
pub(crate) use validation::validate_key;
pub use validation::{artifact_hash, configuration_hash, validate_registration};
mod events;
mod execution;
mod reads;

use crate::chain::ChainClient;
use crate::store::Store;
use std::sync::Arc;
use tokio::sync::Mutex;

#[derive(Clone)]
pub struct GameService {
    inner: Arc<Mutex<GameInner>>,
    operator_id: String,
    chats: crate::chat::ChatService,
    forum: crate::forum::ForumService,
}

struct GameInner {
    chain: ChainClient,
    store: Arc<Store>,
}

impl GameService {
    pub fn new(chain: ChainClient, store: Store, operator_id: String) -> Result<Self, GameError> {
        let operator_address = chain
            .address(&operator_id)
            .map_err(|_| GameError::Validation("operator signer is not configured".into()))?;
        if operator_address != chain.operator_address() {
            return Err(GameError::Validation(
                "configured operator signer does not match the contract operator".into(),
            ));
        }
        let identity = serde_json::to_string(chain.identity())
            .map_err(|_| GameError::Internal("deployment serialization failed".into()))?;
        store.bind_deployment(&identity)?;
        let store = Arc::new(store);
        let chats = crate::chat::ChatService::new(store.clone(), operator_id.clone());
        let forum = crate::forum::ForumService::new(store.clone(), operator_id.clone());
        Ok(Self {
            inner: Arc::new(Mutex::new(GameInner { chain, store })),
            operator_id,
            chats,
            forum,
        })
    }
    pub fn operator_id(&self) -> &str {
        &self.operator_id
    }
    pub fn chats(&self) -> &crate::chat::ChatService {
        &self.chats
    }
    pub fn forum(&self) -> &crate::forum::ForumService {
        &self.forum
    }
    pub async fn identity(&self) -> DeploymentView {
        reads::deployment_view(self.inner.lock().await.chain.identity())
    }
    pub async fn participants(&self) -> Vec<ParticipantView> {
        self.inner
            .lock()
            .await
            .chain
            .participants()
            .into_iter()
            .map(|(actor_id, address)| ParticipantView {
                actor_id,
                address: address.to_string(),
            })
            .collect()
    }
    pub async fn register(
        &self,
        request: RegisterEpisode,
        key: &str,
    ) -> Result<OperationView, GameError> {
        validation::validate_key(key)?;
        let mut inner = self.inner.lock().await;
        validate_registration(&request, &inner.chain.participants())?;
        let intent = execution::StoredIntent::Register {
            request: Box::new(request.clone()),
        };
        let operation = inner.reserve(
            &format!("register:{}", self.operator_id),
            key,
            &request.episode_id,
            &self.operator_id,
            "register",
            &intent,
        )?;
        inner.execute(operation, &self.operator_id).await
    }
    pub async fn act(
        &self,
        episode_id: &str,
        actor_id: &str,
        action: GameAction,
        key: &str,
    ) -> Result<OperationView, GameError> {
        validation::validate_key(key)?;
        let mut inner = self.inner.lock().await;
        let (configuration, _) = inner.verified_episode(episode_id).await?;
        validation::authorize_action(&configuration, &self.operator_id, actor_id, &action)?;
        match &action {
            GameAction::PostClaim { content } => {
                artifact_hash(content)?;
            }
            GameAction::Challenge { evidence } => {
                artifact_hash(evidence)?;
            }
            GameAction::CommitVote { assessment, .. } => {
                artifact_hash(assessment)?;
            }
            _ => {}
        }
        let kind = action.kind();
        let operation = inner.reserve(
            &format!("{kind}:{episode_id}:{actor_id}"),
            key,
            episode_id,
            actor_id,
            kind,
            &execution::StoredIntent::Action { action },
        )?;
        inner.execute(operation, &self.operator_id).await
    }
    pub async fn episode(&self, episode_id: &str) -> Result<EpisodeView, GameError> {
        self.inner.lock().await.read_episode(episode_id).await
    }
    pub async fn settlement(&self, episode_id: &str) -> Result<SettlementView, GameError> {
        self.inner.lock().await.read_settlement(episode_id).await
    }
    pub async fn balances(&self, episode_id: &str) -> Result<BalancesView, GameError> {
        self.inner.lock().await.read_balances(episode_id).await
    }
    pub async fn operation(&self, operation_id: &str) -> Result<OperationView, GameError> {
        let mut inner = self.inner.lock().await;
        let operation = inner.stored_operation(operation_id)?;
        let operation = inner.observe(operation).await?;
        execution::operation_view(&operation)
    }
    pub async fn reconcile(&self, operation_id: &str) -> Result<OperationView, GameError> {
        let mut inner = self.inner.lock().await;
        let operation = inner.stored_operation(operation_id)?;
        inner.execute(operation, &self.operator_id).await
    }
    pub async fn recover_pending(&self) -> Result<Vec<OperationView>, GameError> {
        let mut inner = self.inner.lock().await;
        inner.recheck_canonical_evidence().await?;
        let mut outcomes = Vec::new();
        for operation in inner.store.pending_operations()? {
            match inner.execute(operation.clone(), &self.operator_id).await {
                Ok(view) => {
                    tracing::info!(event = "game.operation.recovered", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, status = %view.status);
                    outcomes.push(view);
                }
                Err(_) => {
                    let view = execution::operation_view(&inner.stored_operation(&operation.id)?)?;
                    tracing::warn!(event = "game.operation.recovery_deferred", operation_id = %operation.id, episode_id = %operation.episode_id, actor_id = %operation.actor_id, status = %view.status);
                    outcomes.push(view);
                }
            }
        }
        Ok(outcomes)
    }
    pub async fn replay_events(&self, from_block: u64, to_block: u64) -> Result<usize, GameError> {
        self.inner
            .lock()
            .await
            .replay_events(from_block, to_block)
            .await
    }
    pub async fn export_events(&self, from_block: u64, to_block: u64) -> Result<String, GameError> {
        self.inner
            .lock()
            .await
            .export_events(from_block, to_block)
            .await
    }
}

impl From<crate::store::StoreError> for GameError {
    fn from(error: crate::store::StoreError) -> Self {
        use crate::store::StoreError;
        match error {
            StoreError::Conflict(_) | StoreError::InvalidState(_) => Self::Conflict(
                "immutable record or operation state conflicts with this request".into(),
            ),
            StoreError::NotFound(_) => Self::NotFound("record".into()),
            StoreError::AccessDenied => Self::Forbidden("chat access denied".into()),
            _ => Self::Internal("local records are unavailable".into()),
        }
    }
}

impl From<crate::chain::ChainError> for GameError {
    fn from(error: crate::chain::ChainError) -> Self {
        use crate::chain::ChainError;
        match error {
            ChainError::UnknownEpisode => {
                Self::NotFound("episode is not currently registered on chain".into())
            }
            ChainError::UnknownActor(_) => {
                Self::Forbidden("signer is not configured for this actor".into())
            }
            ChainError::Rejected(_) => Self::Rejected(
                "contract rejected the action in the current phase or with these parameters".into(),
            ),
            ChainError::InsufficientFunds => {
                Self::Unavailable("signer cannot cover its bond and gas budget".into())
            }
            ChainError::BudgetExceeded => Self::Unavailable(
                "transaction exceeds the service's configured gas or fee budget".into(),
            ),
            ChainError::OutstandingTransaction => {
                Self::Conflict("signer has an unresolved transaction; reconcile it first".into())
            }
            ChainError::Reorganized => {
                Self::Unavailable("receipt block changed; reconciliation is required".into())
            }
            ChainError::Unavailable(_) => Self::Unavailable("chain RPC request failed".into()),
            _ => Self::Internal("deployment identity or chain configuration is invalid".into()),
        }
    }
}

#[derive(Debug, thiserror::Error)]
pub enum GameError {
    #[error("invalid request: {0}")]
    Validation(String),
    #[error("not found: {0}")]
    NotFound(String),
    #[error("forbidden: {0}")]
    Forbidden(String),
    #[error("conflict: {0}")]
    Conflict(String),
    #[error("temporarily unavailable: {0}")]
    Unavailable(String),
    #[error("action rejected: {0}")]
    Rejected(String),
    #[error("internal service error: {0}")]
    Internal(String),
}
