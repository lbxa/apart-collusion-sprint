mod support;

use axum::http::{Method, StatusCode};
use serde_json::{Value, json};
use support::{Fixture, registration};
use tower::ServiceExt;

async fn game() -> Fixture {
    let fixture = Fixture::new().await;
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes",
            Some("operator"),
            Some("register"),
            serde_json::to_value(registration("chat-game", 3, "1000")).unwrap(),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    fixture
}

async fn create(fixture: &Fixture, history: bool) -> String {
    let (status, chat) = fixture
        .request(
            Method::POST,
            "/v1/episodes/chat-game/chats",
            Some("creator"),
            Some("create-chat"),
            json!({
                "participant_ids": ["creator", "juror-1"], "history_enabled": history,
            }),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED, "{chat}");
    assert_eq!(chat["history_enabled"], history);
    chat["chat_id"].as_str().unwrap().to_owned()
}

async fn send(fixture: &Fixture, chat: &str, actor: &str, key: &str, content: &str) -> Value {
    let (status, message) = fixture
        .request(
            Method::POST,
            &format!("/v1/chats/{chat}/messages"),
            Some(actor),
            Some(key),
            json!({"content":content}),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED, "{message}");
    assert_eq!(message["sender_id"], actor);
    assert_eq!(message["content"], content);
    message
}

async fn read(fixture: &Fixture, chat: &str, actor: &str) -> Value {
    let (status, page) = fixture
        .request(
            Method::GET,
            &format!("/v1/chats/{chat}/messages"),
            Some(actor),
            None,
            json!(null),
        )
        .await;
    assert_eq!(status, StatusCode::OK, "{page}");
    page
}

#[tokio::test]
async fn history_is_two_way_bounded_and_only_visible_to_the_pair() {
    let fixture = game().await;
    let chat = create(&fixture, true).await;
    let first = send(&fixture, &chat, "creator", "one", "  private café\r\n").await;
    assert_eq!(
        first["content_hash"],
        alloy::primitives::keccak256("  private café\r\n".as_bytes()).to_string()
    );
    let second = send(&fixture, &chat, "juror-1", "two", "reply").await;
    for actor in ["creator", "juror-1"] {
        let page = read(&fixture, &chat, actor).await;
        assert_eq!(page["messages"], json!([first, second]));
    }
    let (status, page) = fixture
        .request(
            Method::GET,
            &format!("/v1/chats/{chat}/messages?after=0&limit=1"),
            Some("creator"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(page["messages"], json!([first]));
    assert_eq!(page["has_more"], true);
    let (status, next) = fixture
        .request(
            Method::GET,
            &format!(
                "/v1/chats/{chat}/messages?after={}&limit=1",
                page["next_after"]
            ),
            Some("creator"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(next["messages"], json!([second]));
    for actor in [None, Some("challenger"), Some("operator")] {
        let (status, denied) = fixture
            .request(
                Method::GET,
                &format!("/v1/chats/{chat}/messages"),
                actor,
                None,
                json!(null),
            )
            .await;
        assert!(matches!(
            status,
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
        ));
        assert!(!denied.to_string().contains("private café"));
    }
}

#[tokio::test]
async fn history_disabled_exposes_only_latest_but_operator_retains_every_message() {
    let mut fixture = game().await;
    let chat = create(&fixture, false).await;
    let first = send(&fixture, &chat, "creator", "one", "old secret").await;
    let second = send(&fixture, &chat, "juror-1", "two", "latest secret").await;
    fixture.restart_service().await;
    for actor in ["creator", "juror-1"] {
        assert_eq!(
            read(&fixture, &chat, actor).await["messages"],
            json!([second])
        );
    }
    let (status, transcript) = fixture
        .request(
            Method::GET,
            &format!("/v1/chats/{chat}/transcript"),
            Some("operator"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(transcript["messages"], json!([first, second]));
    let (status, _) = fixture
        .request(
            Method::GET,
            &format!("/v1/chats/{chat}/transcript"),
            Some("creator"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn audit_identifies_prohibited_senders_readers_and_denied_access_without_content() {
    let fixture = game().await;
    let (status, empty) = fixture
        .request(
            Method::GET,
            "/v1/episodes/chat-game/chat-audit",
            Some("operator"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(empty["communication_used"], false);
    let chat = create(&fixture, true).await;
    send(
        &fixture,
        &chat,
        "creator",
        "secret",
        "never in audit metadata",
    )
    .await;
    read(&fixture, &chat, "juror-1").await;
    let (status, _) = fixture
        .request(
            Method::GET,
            &format!("/v1/chats/{chat}/messages"),
            Some("challenger"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    let (status, audit) = fixture
        .request(
            Method::GET,
            "/v1/episodes/chat-game/chat-audit",
            Some("operator"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(audit["chat_used"], true);
    assert_eq!(audit["communication_used"], true);
    assert_eq!(audit["prohibited_communication_used"], true);
    assert_eq!(audit["message_count"], 1);
    let actors = audit["actors"].as_array().unwrap();
    assert!(
        actors
            .iter()
            .any(|a| a["actor_id"] == "creator" && a["sent_messages"] == 1)
    );
    assert!(
        actors
            .iter()
            .any(|a| a["actor_id"] == "juror-1" && a["read_requests"] == 1)
    );
    assert!(
        actors
            .iter()
            .any(|a| a["actor_id"] == "challenger" && a["denied_requests"] == 1)
    );
    assert!(!audit.to_string().contains("never in audit metadata"));
    assert!(
        audit["events"]
            .as_array()
            .unwrap()
            .iter()
            .any(|e| e["kind"] == "message_sent" && e["policy_violation"] == true)
    );
    assert!(
        audit["events"]
            .as_array()
            .unwrap()
            .iter()
            .any(|event| event["kind"] == "messages_read"
                && event["actor_id"] == "juror-1"
                && event["returned_sequences"] == json!([1]))
    );
    let (_, end) = fixture
        .request(
            Method::GET,
            &format!(
                "/v1/episodes/chat-game/chat-audit?after={}&limit=1",
                audit["next_after"]
            ),
            Some("operator"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(end["events"], json!([]));
    assert_eq!(end["message_count"], 1);
    assert_eq!(end["prohibited_communication_used"], true);
    for actor in [None, Some("juror-1")] {
        let (status, _) = fixture
            .request(
                Method::GET,
                "/v1/episodes/chat-game/chat-audit",
                actor,
                None,
                json!(null),
            )
            .await;
        assert!(matches!(
            status,
            StatusCode::UNAUTHORIZED | StatusCode::FORBIDDEN
        ));
    }
    let (status, public) = fixture
        .request(
            Method::GET,
            "/v1/episodes/chat-game",
            None,
            None,
            json!(null),
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert!(!public.to_string().contains("never in audit metadata"));
    assert!(public.get("chats").is_none());
}

#[tokio::test]
async fn create_and_send_retries_cannot_duplicate_messages_or_rewrite_settings() {
    let fixture = game().await;
    let chat = create(&fixture, false).await;
    assert_eq!(create(&fixture, false).await, chat);
    let first = send(&fixture, &chat, "creator", "message", "original").await;
    assert_eq!(
        send(&fixture, &chat, "creator", "message", "original").await,
        first
    );
    for (path, body, key) in [
        (
            format!("/v1/chats/{chat}/messages"),
            json!({"content":"changed"}),
            "message",
        ),
        (
            "/v1/episodes/chat-game/chats".into(),
            json!({"participant_ids":["creator","juror-1"],"history_enabled":true}),
            "create-chat",
        ),
    ] {
        let (status, _) = fixture
            .request(Method::POST, &path, Some("creator"), Some(key), body)
            .await;
        assert_eq!(status, StatusCode::CONFLICT);
    }
    let (_, audit) = fixture
        .request(
            Method::GET,
            "/v1/episodes/chat-game/chat-audit",
            Some("operator"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(audit["chat_count"], 1);
    assert_eq!(audit["message_count"], 1);
}

#[tokio::test]
async fn participants_cannot_impersonate_others_or_clear_the_prohibition_flag() {
    let fixture = game().await;
    for body in [
        json!({"participant_ids":["challenger","juror-1"],"history_enabled":true}),
        json!({"participant_ids":["creator","juror-1"],"communication_prohibited":false}),
    ] {
        let (status, _) = fixture
            .request(
                Method::POST,
                "/v1/episodes/chat-game/chats",
                Some("creator"),
                Some("bad-create"),
                body,
            )
            .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
    }
    for participants in [json!(["creator", "creator"]), json!(["creator", "juror-7"])] {
        let (status, _) = fixture
            .request(
                Method::POST,
                "/v1/episodes/chat-game/chats",
                Some("creator"),
                Some("bad-roster"),
                json!({"participant_ids":participants}),
            )
            .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    }
    let (status, allowed) = fixture
        .request(
            Method::POST,
            "/v1/episodes/chat-game/chats",
            Some("operator"),
            Some("allowed-control"),
            json!({
                "participant_ids":["creator","juror-1"], "communication_prohibited":false,
            }),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    let chat = allowed["chat_id"].as_str().unwrap();
    send(&fixture, chat, "creator", "allowed", "control message").await;
    let (_, audit) = fixture
        .request(
            Method::GET,
            "/v1/episodes/chat-game/chat-audit",
            Some("operator"),
            None,
            json!(null),
        )
        .await;
    assert_eq!(audit["communication_used"], true);
    assert_eq!(audit["prohibited_communication_used"], false);
}

#[tokio::test]
async fn chat_discovery_is_private_and_invalid_queries_and_messages_fail_closed() {
    let fixture = game().await;
    let chat = create(&fixture, true).await;
    for (actor, count) in [("creator", 1), ("juror-1", 1), ("challenger", 0)] {
        let (status, page) = fixture
            .request(
                Method::GET,
                "/v1/episodes/chat-game/chats",
                Some(actor),
                None,
                json!(null),
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(page["chats"].as_array().unwrap().len(), count);
    }
    for query in [
        "limit=0",
        "limit=101",
        "after=18446744073709551615",
        "unrecognized=true",
    ] {
        let (status, _) = fixture
            .request(
                Method::GET,
                &format!("/v1/chats/{chat}/messages?{query}"),
                Some("creator"),
                None,
                json!(null),
            )
            .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    }
    for content in [" ".to_owned(), "x".repeat(16 * 1024 + 1)] {
        let (status, _) = fixture
            .request(
                Method::POST,
                &format!("/v1/chats/{chat}/messages"),
                Some("creator"),
                Some("invalid"),
                json!({"content":content}),
            )
            .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    }
    let (status, _) = fixture
        .request(
            Method::POST,
            &format!("/v1/chats/{chat}/messages"),
            Some("challenger"),
            Some("attack"),
            json!({"content":"not a member"}),
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    let (status, _) = fixture
        .request(
            Method::POST,
            &format!("/v1/chats/{chat}/messages"),
            Some("creator"),
            None,
            json!({"content":"no key"}),
        )
        .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
}

#[tokio::test]
async fn any_pair_of_episode_roles_can_chat_without_transactions_or_phase_changes() {
    let fixture = game().await;
    let nonce = fixture.nonce("treasury").await;
    for (index, pair) in [
        ["creator", "challenger"],
        ["juror-1", "juror-2"],
        ["treasury", "juror-3"],
    ]
    .iter()
    .enumerate()
    {
        let (status, chat) = fixture
            .request(
                Method::POST,
                "/v1/episodes/chat-game/chats",
                Some(pair[0]),
                Some(&format!("pair-{index}")),
                json!({"participant_ids":pair}),
            )
            .await;
        assert_eq!(status, StatusCode::CREATED, "{chat}");
        let id = chat["chat_id"].as_str().unwrap();
        send(&fixture, id, pair[0], "one", "role-neutral message").await;
        assert_eq!(
            read(&fixture, id, pair[1]).await["messages"][0]["recipient_id"],
            pair[1]
        );
    }
    assert_eq!(fixture.nonce("treasury").await, nonce);
    let (_, episode) = fixture
        .request(
            Method::GET,
            "/v1/episodes/chat-game",
            None,
            None,
            json!(null),
        )
        .await;
    assert_eq!(episode["phase"], "REGISTERED");
}

#[tokio::test]
async fn private_responses_disable_caching_and_openapi_documents_credentials_and_history() {
    let fixture = game().await;
    let chat = create(&fixture, false).await;
    let response = fixture
        .app
        .clone()
        .oneshot(
            axum::http::Request::builder()
                .uri(format!("/v1/chats/{chat}/messages"))
                .header("Authorization", "Bearer test-creator")
                .body(axum::body::Body::empty())
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::OK);
    assert_eq!(response.headers()["cache-control"], "no-store");
    assert_eq!(response.headers()["vary"], "Authorization");
    let document = serde_json::to_value(veracity_game_service::api::openapi()).unwrap();
    for (path, method) in [
        ("/v1/episodes/{id}/chats", "post"),
        ("/v1/episodes/{id}/chats", "get"),
        ("/v1/chats/{id}/messages", "post"),
        ("/v1/chats/{id}/messages", "get"),
        ("/v1/chats/{id}/transcript", "get"),
        ("/v1/episodes/{id}/chat-audit", "get"),
    ] {
        let operation = &document["paths"][path][method];
        assert!(operation.is_object(), "{method} {path}");
        assert!(operation["security"][0]["bearerAuth"].is_array());
    }
}
