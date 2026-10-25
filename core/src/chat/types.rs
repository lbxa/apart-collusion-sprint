use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

#[derive(Clone, Debug)]
pub enum ChatPrincipal {
    Operator,
    Participant(String),
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct CreateChat {
    #[schema(min_items = 2, max_items = 2)]
    pub participant_ids: [String; 2],
    #[serde(default)]
    #[schema(default = false)]
    pub history_enabled: bool,
    /// Defaults to prohibited. Only the operator may set this to false.
    #[serde(default = "prohibited")]
    #[schema(default = true)]
    pub communication_prohibited: bool,
}

const fn prohibited() -> bool {
    true
}

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct SendMessage {
    /// Exact UTF-8, 1–16384 bytes and not entirely whitespace.
    pub content: String,
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct ChatView {
    pub chat_id: String,
    pub episode_id: String,
    #[schema(min_items = 2, max_items = 2)]
    pub participant_ids: [String; 2],
    pub history_enabled: bool,
    pub created_at_ms: u64,
}

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct ChatMessage {
    pub message_id: String,
    pub sequence: u64,
    pub sender_id: String,
    pub recipient_id: String,
    pub content: String,
    pub content_hash: String,
    pub created_at_ms: u64,
}

#[derive(Clone, Serialize, Deserialize, ToSchema)]
pub struct MessagePage {
    pub chat_id: String,
    pub messages: Vec<ChatMessage>,
    pub next_after: u64,
    pub has_more: bool,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct ChatPage {
    pub chats: Vec<ChatView>,
    #[schema(required = true)]
    pub next_after: Option<String>,
    pub has_more: bool,
}

#[derive(Clone, Copy, Debug, Default, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ChatQuery {
    #[serde(default)]
    pub after: u64,
    pub limit: Option<u16>,
}

impl ChatQuery {
    pub(crate) fn page_limit(self) -> Option<u16> {
        let limit = self.limit.unwrap_or(50);
        (self.after <= i64::MAX as u64 && (1..=100).contains(&limit)).then_some(limit)
    }
}

#[derive(Clone, Debug, Default, Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ChatListQuery {
    pub after: Option<String>,
    pub limit: Option<u16>,
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum ChatAuditKind {
    ChatCreated,
    MessageSent,
    MessagesRead,
    ChatsListed,
    TranscriptRead,
    AccessDenied,
}

impl ChatAuditKind {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::ChatCreated => "chat_created",
            Self::MessageSent => "message_sent",
            Self::MessagesRead => "messages_read",
            Self::ChatsListed => "chats_listed",
            Self::TranscriptRead => "transcript_read",
            Self::AccessDenied => "access_denied",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct ChatAuditEvent {
    pub sequence: u64,
    pub episode_id: String,
    #[schema(required = true)]
    pub chat_id: Option<String>,
    pub actor_id: String,
    pub actor_is_operator: bool,
    pub kind: ChatAuditKind,
    pub communication_prohibited: bool,
    pub policy_violation: bool,
    #[schema(required = true)]
    pub recipient_id: Option<String>,
    #[schema(required = true)]
    pub message_sequence: Option<u64>,
    #[schema(required = true)]
    pub message_hash: Option<String>,
    #[schema(required = true)]
    pub message_bytes: Option<u64>,
    /// Exact message sequence numbers returned by this read request.
    pub returned_sequences: Vec<u64>,
    pub created_at_ms: u64,
}

#[derive(Clone, Debug, Default, Serialize, Deserialize, ToSchema)]
pub struct ChatActorUsage {
    pub actor_id: String,
    pub created_chats: u64,
    pub sent_messages: u64,
    pub read_requests: u64,
    pub messages_returned: u64,
    pub denied_requests: u64,
    pub prohibited_sent_messages: u64,
    pub prohibited_read_requests: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct ChatAuditReport {
    pub episode_id: String,
    pub chat_used: bool,
    pub communication_used: bool,
    pub prohibited_communication_used: bool,
    pub chat_count: u64,
    pub message_count: u64,
    /// All-time participant totals, independent of event-page pagination.
    pub actors: Vec<ChatActorUsage>,
    pub events: Vec<ChatAuditEvent>,
    pub next_after: u64,
    pub has_more: bool,
}

pub(crate) struct ChatActor {
    pub id: String,
    pub operator: bool,
}

pub(crate) struct ChatRecord {
    pub view: ChatView,
    pub prohibited: bool,
}

impl ChatRecord {
    pub fn allows(&self, actor: &ChatActor, transcript: bool) -> bool {
        if transcript {
            actor.operator
        } else {
            !actor.operator && self.view.participant_ids.contains(&actor.id)
        }
    }
}
