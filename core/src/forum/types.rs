use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
#[serde(deny_unknown_fields)]
pub struct ForumSendMessage {
    /// Exact UTF-8, 1–16384 bytes and not entirely whitespace.
    pub content: String,
    /// Optional caller-supplied deliberation round, not a protocol phase.
    #[serde(default)]
    #[schema(minimum = 1)]
    pub round_num: Option<u32>,
}

#[derive(Clone, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
pub struct ForumMessage {
    pub message_id: String,
    pub sequence: u64,
    pub sender_id: String,
    pub content: String,
    pub content_hash: String,
    #[schema(required = true)]
    pub round_num: Option<u32>,
    pub created_at_ms: u64,
}

#[derive(Clone, Serialize, Deserialize, ToSchema)]
pub struct ForumMessagePage {
    pub episode_id: String,
    pub messages: Vec<ForumMessage>,
    pub next_after: u64,
    pub has_more: bool,
}

#[derive(Clone, Copy, Debug, Default, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ForumQuery {
    #[serde(default)]
    pub after: u64,
    pub limit: Option<u16>,
}

impl ForumQuery {
    pub(crate) fn page_limit(self) -> Option<u16> {
        let limit = self.limit.unwrap_or(50);
        (self.after <= i64::MAX as u64 && (1..=100).contains(&limit)).then_some(limit)
    }
}

#[derive(Clone, Copy, Debug, Serialize, Deserialize, PartialEq, Eq, ToSchema)]
#[serde(rename_all = "snake_case")]
pub enum ForumAuditKind {
    MessageSent,
    MessagesRead,
    TranscriptRead,
    AccessDenied,
}

impl ForumAuditKind {
    pub(crate) const fn as_str(self) -> &'static str {
        match self {
            Self::MessageSent => "message_sent",
            Self::MessagesRead => "messages_read",
            Self::TranscriptRead => "transcript_read",
            Self::AccessDenied => "access_denied",
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct ForumAuditEvent {
    pub sequence: u64,
    pub episode_id: String,
    pub actor_id: String,
    pub actor_is_operator: bool,
    pub kind: ForumAuditKind,
    #[schema(required = true)]
    pub message_sequence: Option<u64>,
    #[schema(required = true)]
    pub message_hash: Option<String>,
    #[schema(required = true)]
    pub message_bytes: Option<u64>,
    #[schema(required = true)]
    pub round_num: Option<u32>,
    /// Exact message sequence numbers prepared for this read response.
    pub returned_sequences: Vec<u64>,
    pub created_at_ms: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct ForumActorUsage {
    pub actor_id: String,
    pub sent_messages: u64,
    pub read_requests: u64,
    pub messages_returned: u64,
    pub denied_requests: u64,
    pub sent_bytes: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize, ToSchema)]
pub struct ForumAuditReport {
    pub episode_id: String,
    /// Includes empty reads and denied participant requests, excludes operator traffic.
    pub forum_used: bool,
    pub communication_used: bool,
    pub message_count: u64,
    pub total_message_bytes: u64,
    pub active_sender_count: u64,
    #[schema(required = true)]
    pub first_message_at_ms: Option<u64>,
    #[schema(required = true)]
    pub last_message_at_ms: Option<u64>,
    /// All-time participant totals, independent of event pagination.
    pub actors: Vec<ForumActorUsage>,
    pub events: Vec<ForumAuditEvent>,
    pub next_after: u64,
    pub has_more: bool,
}

pub(crate) struct ForumActor {
    pub id: String,
    pub operator: bool,
}
