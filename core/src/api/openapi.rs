use super::{
    ApiProblem, ErrorResponse, chat, forum,
    routes::{
        self, ChallengeRequest, ClaimRequest, CommitmentRequest, EmptyRequest, HealthResponse,
    },
};
use crate::chat::{
    ChatActorUsage, ChatAuditEvent, ChatAuditKind, ChatAuditReport, ChatMessage, ChatPage,
    ChatView, CreateChat, MessagePage, SendMessage,
};
use crate::forum::{
    ForumActorUsage, ForumAuditEvent, ForumAuditKind, ForumAuditReport, ForumMessage,
    ForumMessagePage, ForumSendMessage,
};
use crate::game::{
    BalancesView, DeploymentView, EpisodeView, JurorView, OperationView, ParticipantView,
    ProtocolParameters, ReceiptView, RegisterEpisode, SettlementView, TransactionView, Verdict,
};
use utoipa::{
    Modify, OpenApi,
    openapi::security::{HttpAuthScheme, HttpBuilder, SecurityScheme},
};

#[derive(OpenApi)]
#[openapi(
    info(title = "Veracity Game API", version = "1.3.0",
        description = "The game engine API for SPEC.md v0.2. The Solidity contract owns escrow, immutable chain-time deadlines, commit/reveal voting, and settlement. Amounts are decimal base-unit strings. Operator and participant bearer tokens have distinct authority. Experiments, agent execution, and evaluation belong to the caller's external harness."),
    paths(
        routes::health, routes::openapi_document, routes::docs, routes::participants,
        routes::register, routes::episode, routes::claim, routes::challenge,
        routes::commitment, routes::reveal, routes::settle, routes::expire,
        routes::withdraw, routes::transfer, routes::settlement, routes::balances, routes::operation,
        routes::reconcile, routes::replay, routes::events,
        chat::create, chat::list, chat::send, chat::messages, chat::transcript, chat::audit,
        forum::send_forum_message,forum::get_forum_messages,forum::get_forum_transcript,forum::get_forum_audit
    ),
    components(schemas(
        ApiProblem, ErrorResponse, HealthResponse, ClaimRequest, ChallengeRequest,
        CommitmentRequest, EmptyRequest, RegisterEpisode, ProtocolParameters,
        Verdict, DeploymentView, ParticipantView, ReceiptView, TransactionView,
        OperationView, JurorView, EpisodeView, SettlementView, BalancesView,
        routes::BlockRange, routes::ReplayResponse, routes::TransferRequest,
        ChatActorUsage, ChatAuditEvent, ChatAuditKind, ChatAuditReport, ChatMessage,
        ChatPage, ChatView, CreateChat, MessagePage, SendMessage,
        ForumActorUsage,ForumAuditEvent,ForumAuditKind,ForumAuditReport,ForumMessage,ForumMessagePage,ForumSendMessage
    )),
    modifiers(&BearerSecurity),
    tags(
        (name = "discovery", description = "API contract and public deployment identity"),
        (name = "episodes", description = "Immutable game registration and chain-backed queries"),
        (name = "actions", description = "Role-bound protocol actions with durable idempotency"),
        (name = "operations", description = "Transaction evidence and safe recovery"),
        (name = "chain evidence", description = "Bounded replay and public chain-event exports"),
        (name = "private chat", description = "Experimental two-participant communication; prohibited use remains available and audited"),
        (name = "chat audit", description = "Privileged usage flags, metadata events, and retained transcripts"),
        (name = "public forum", description = "Episode-wide participant communication with persistent chronological history"),
        (name = "forum audit", description = "Privileged public-forum usage signals, communication metadata, and transcripts")
    )
)]
struct ApiDocument;

struct BearerSecurity;
impl Modify for BearerSecurity {
    fn modify(&self, document: &mut utoipa::openapi::OpenApi) {
        // Cargo has no declared repository license; utoipa otherwise infers an empty one.
        document.info.license = None;
        if let Some(components) = document.components.as_mut() {
            components.add_security_scheme(
                "bearerAuth",
                SecurityScheme::Http(
                    HttpBuilder::new()
                        .scheme(HttpAuthScheme::Bearer)
                        .bearer_format("opaque role credential")
                        .build(),
                ),
            );
        }
    }
}

pub fn openapi() -> utoipa::openapi::OpenApi {
    ApiDocument::openapi()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn documents_the_versioned_protocol_and_credential_boundary() {
        let document = serde_json::to_value(openapi()).unwrap();
        assert!(
            document["info"].get("license").is_none(),
            "Do not publish an empty or invented license."
        );
        for path in [
            "/v1/health",
            "/v1/openapi.json",
            "/v1/docs",
            "/v1/participants",
            "/v1/episodes",
            "/v1/episodes/{id}",
            "/v1/episodes/{id}/claims",
            "/v1/episodes/{id}/challenges",
            "/v1/episodes/{id}/commitments",
            "/v1/episodes/{id}/reveals",
            "/v1/episodes/{id}/settle",
            "/v1/episodes/{id}/expire",
            "/v1/episodes/{id}/withdrawals",
            "/v1/episodes/{id}/transfers",
            "/v1/episodes/{id}/settlement",
            "/v1/episodes/{id}/balances",
            "/v1/operations/{id}",
            "/v1/operations/{id}/reconcile",
            "/v1/chain/replay",
            "/v1/chain/events",
            "/v1/episodes/{id}/chats",
            "/v1/chats/{id}/messages",
            "/v1/chats/{id}/transcript",
            "/v1/episodes/{id}/chat-audit",
            "/v1/episodes/{id}/forum/messages",
            "/v1/episodes/{id}/forum/transcript",
            "/v1/episodes/{id}/forum-audit",
        ] {
            assert!(document["paths"].get(path).is_some(), "missing {path}");
        }
        assert_eq!(
            document["components"]["securitySchemes"]["bearerAuth"]["scheme"],
            "bearer"
        );
        assert_eq!(
            document["components"]["schemas"]["ProtocolParameters"]["properties"]["beta_wei"]["type"],
            "string"
        );
        assert_eq!(
            document["components"]["schemas"]["SettlementView"]["properties"]["winner_payout"]["pattern"],
            "^(0|[1-9][0-9]*)$"
        );
        assert!(
            document["components"]["schemas"]["OperationView"]["properties"]["status"]["enum"]
                .as_array()
                .unwrap()
                .iter()
                .any(|value| value == "confirmed")
        );
        assert_eq!(
            document["components"]["schemas"]["ProtocolParameters"]["additionalProperties"],
            false
        );
        assert!(
            document["components"]["schemas"]
                .get("ErrorResponse")
                .is_some()
        );
        let commitment = &document["paths"]["/v1/episodes/{id}/commitments"]["post"];
        assert!(commitment["parameters"].as_array().unwrap().iter().any(
            |parameter| parameter["name"] == "Idempotency-Key" && parameter["required"] == true
        ));
        assert!(!commitment["security"].as_array().unwrap().is_empty());
        assert!(commitment["responses"].get("202").is_some());
        assert!(commitment["responses"].get("401").is_some());
        assert!(commitment["responses"].get("403").is_some());
        assert!(commitment["responses"].get("409").is_some());
        assert!(commitment["responses"].get("422").is_some());
        let replay_parameters =
            document["paths"]["/v1/chain/replay"]["post"]["parameters"].as_array();
        assert!(
            !replay_parameters.is_some_and(|parameters| parameters
                .iter()
                .any(|parameter| parameter["name"] == "Idempotency-Key")),
            "Evidence replay is naturally idempotent and must not advertise a command key."
        );
        assert_eq!(
            document["components"]["schemas"]["CreateChat"]["properties"]["history_enabled"]["default"],
            false
        );
        assert_eq!(
            document["components"]["schemas"]["CreateChat"]["properties"]["communication_prohibited"]
                ["default"],
            true
        );
        assert!(
            document["components"]["schemas"]["ChatPage"]["required"]
                .as_array()
                .unwrap()
                .iter()
                .any(|value| value == "next_after")
        );
        for path in [
            "/v1/episodes/{id}/chats",
            "/v1/chats/{id}/messages",
            "/v1/chats/{id}/transcript",
            "/v1/episodes/{id}/chat-audit",
        ] {
            for operation in document["paths"][path].as_object().unwrap().values() {
                assert!(!operation["security"].as_array().unwrap().is_empty());
            }
        }
    }
}
