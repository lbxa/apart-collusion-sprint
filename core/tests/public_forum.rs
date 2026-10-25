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
            serde_json::to_value(registration("forum-game", 3, "1000")).unwrap(),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    fixture
}

#[tokio::test]
async fn public_forum_is_persistent_shared_and_audits_exact_observations() {
    let mut fixture = game().await;
    let (status, message) = fixture
        .request(
            Method::POST,
            "/v1/episodes/forum-game/forum/messages",
            Some("creator"),
            Some("post-1"),
            json!({"content":"  public café\r\n", "round_num":1}),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED, "{message}");
    assert_eq!(message["sender_id"], "creator");
    assert_eq!(message["content"], "  public café\r\n");
    assert_eq!(message["round_num"], 1);
    fixture.restart_service().await;
    let (status, page) = fixture
        .request(
            Method::GET,
            "/v1/episodes/forum-game/forum/messages",
            Some("juror-1"),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK, "{page}");
    assert_eq!(page["messages"], json!([message]));
    let (status, audit) = fixture
        .request(
            Method::GET,
            "/v1/episodes/forum-game/forum-audit",
            Some("operator"),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK, "{audit}");
    assert_eq!(audit["forum_used"], true);
    assert_eq!(audit["communication_used"], true);
    assert_eq!(audit["message_count"], 1);
    assert_eq!(audit["events"][1]["returned_sequences"], json!([1]));
    assert!(!audit.to_string().contains("public café"));
}

async fn send(
    fixture: &Fixture,
    actor: &str,
    key: &str,
    content: &str,
    round: Option<u32>,
) -> Value {
    let (status, message) = fixture
        .request(
            Method::POST,
            "/v1/episodes/forum-game/forum/messages",
            Some(actor),
            Some(key),
            json!({"content":content,"round_num":round}),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED, "{message}");
    message
}

async fn audit(fixture: &Fixture, query: &str) -> Value {
    let (status, report) = fixture
        .request(
            Method::GET,
            &format!("/v1/episodes/forum-game/forum-audit{query}"),
            Some("operator"),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK, "{report}");
    report
}

#[tokio::test]
async fn identities_membership_operator_and_episode_boundaries_are_enforced() {
    let fixture = game().await;
    for actor in [
        "creator",
        "challenger",
        "juror-1",
        "juror-2",
        "juror-3",
        "treasury",
    ] {
        send(&fixture, actor, "same-key-for-distinct-actors", actor, None).await;
        let (status, _) = fixture
            .request(
                Method::GET,
                "/v1/episodes/forum-game/forum/messages",
                Some(actor),
                None,
                Value::Null,
            )
            .await;
        assert_eq!(status, StatusCode::OK);
    }
    for actor in [Some("operator"), Some("juror-7"), None] {
        for method in [Method::GET, Method::POST] {
            let (status, response) = fixture
                .request(
                    method,
                    "/v1/episodes/forum-game/forum/messages",
                    actor,
                    Some("denied"),
                    json!({"content":"unauthorized"}),
                )
                .await;
            assert_eq!(
                status,
                if actor.is_none() {
                    StatusCode::UNAUTHORIZED
                } else {
                    StatusCode::FORBIDDEN
                },
                "{response}"
            );
        }
    }
    for path in [
        "/v1/episodes/forum-game/forum/transcript",
        "/v1/episodes/forum-game/forum-audit",
    ] {
        let (status, _) = fixture
            .request(Method::GET, path, Some("creator"), None, Value::Null)
            .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
    }
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/forum-game/forum/messages",
            Some("creator"),
            Some("impersonation"),
            json!({"content":"text", "sender_id":"juror-1"}),
        )
        .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let (status, _) = fixture
        .request(
            Method::GET,
            "/v1/episodes/missing/forum/messages",
            Some("creator"),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    let report = audit(&fixture, "").await;
    assert_eq!(report["message_count"], 6);
    assert_eq!(report["active_sender_count"], 6);
    let denied = report["actors"]
        .as_array()
        .unwrap()
        .iter()
        .find(|actor| actor["actor_id"] == "juror-7")
        .unwrap();
    assert_eq!(denied["denied_requests"], 2);
}

#[tokio::test]
async fn retries_are_exact_and_payload_or_round_changes_conflict() {
    let mut fixture = game().await;
    let message = send(&fixture, "creator", "retry", "café", Some(2)).await;
    assert_eq!(
        send(&fixture, "creator", "retry", "café", Some(2)).await,
        message
    );
    fixture.restart_service().await;
    assert_eq!(
        send(&fixture, "creator", "retry", "café", Some(2)).await,
        message
    );
    for body in [
        json!({"content":"changed","round_num":2}),
        json!({"content":"café","round_num":3}),
    ] {
        let (status, _) = fixture
            .request(
                Method::POST,
                "/v1/episodes/forum-game/forum/messages",
                Some("creator"),
                Some("retry"),
                body,
            )
            .await;
        assert_eq!(status, StatusCode::CONFLICT);
    }
    let report = audit(&fixture, "").await;
    assert_eq!(report["message_count"], 1);
    assert_eq!(report["total_message_bytes"], 5);
    assert_eq!(report["events"].as_array().unwrap().len(), 1);
    assert_eq!(report["events"][0]["message_bytes"], 5);
    assert_eq!(report["events"][0]["round_num"], 2);
    assert_eq!(report["events"][0]["message_hash"], message["content_hash"]);
}

#[tokio::test]
async fn pagination_and_all_time_usage_do_not_depend_on_event_page() {
    let fixture = game().await;
    for index in 1..=3 {
        send(
            &fixture,
            "creator",
            &format!("post-{index}"),
            &format!("message-{index}"),
            Some(index),
        )
        .await;
    }
    let mut seen = Vec::new();
    let mut after = 0;
    loop {
        let (status, page) = fixture
            .request(
                Method::GET,
                &format!("/v1/episodes/forum-game/forum/messages?after={after}&limit=1"),
                Some("juror-1"),
                None,
                Value::Null,
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        seen.extend(
            page["messages"]
                .as_array()
                .unwrap()
                .iter()
                .map(|message| message["sequence"].as_u64().unwrap()),
        );
        after = page["next_after"].as_u64().unwrap();
        if page["has_more"] == false {
            break;
        }
    }
    assert_eq!(seen, [1, 2, 3]);
    let (status, empty) = fixture
        .request(
            Method::GET,
            "/v1/episodes/forum-game/forum/messages?after=999",
            Some("juror-1"),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(empty["next_after"], 999);
    assert_eq!(empty["messages"], json!([]));
    let first = audit(&fixture, "?limit=1").await;
    assert_eq!(first["message_count"], 3);
    assert_eq!(first["actors"][1]["read_requests"], 4);
    assert_eq!(first["actors"][1]["messages_returned"], 3);
    assert_eq!(first["has_more"], true);
    let last = audit(&fixture, "?after=999&limit=1").await;
    assert_eq!(last["events"], json!([]));
    assert_eq!(last["message_count"], first["message_count"]);
    assert_eq!(last["actors"], first["actors"]);
    let repeated = audit(&fixture, "?limit=1").await;
    assert_eq!(repeated, first, "audit reads must not create audit events");
}

#[tokio::test]
async fn evaluator_reads_do_not_mark_participant_use_and_responses_are_not_cached() {
    use axum::{
        body::Body,
        http::{Request, header},
    };
    let fixture = game().await;
    let report = audit(&fixture, "").await;
    assert_eq!(report["forum_used"], false);
    let (status, page) = fixture
        .request(
            Method::GET,
            "/v1/episodes/forum-game/forum/transcript",
            Some("operator"),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(page["messages"], json!([]));
    let report = audit(&fixture, "").await;
    assert_eq!(report["forum_used"], false);
    assert_eq!(report["communication_used"], false);
    assert_eq!(report["actors"], json!([]));
    assert_eq!(report["events"][0]["kind"], "transcript_read");
    for (path, token) in [
        ("/v1/episodes/forum-game/forum/messages", "test-creator"),
        ("/v1/episodes/forum-game/forum/transcript", "test-operator"),
        ("/v1/episodes/forum-game/forum-audit", "test-operator"),
    ] {
        let response = fixture
            .app
            .clone()
            .oneshot(
                Request::builder()
                    .uri(path)
                    .header(header::AUTHORIZATION, format!("Bearer {token}"))
                    .body(Body::empty())
                    .unwrap(),
            )
            .await
            .unwrap();
        assert_eq!(response.headers()[header::CACHE_CONTROL], "no-store");
        assert_eq!(response.headers()[header::VARY], "Authorization");
    }
    let report = audit(&fixture, "").await;
    assert_eq!(
        report["forum_used"], true,
        "an empty participant read counts as use"
    );
    assert_eq!(report["communication_used"], false);
}

#[tokio::test]
async fn validation_rejects_invalid_bytes_rounds_and_cursors_without_side_effects() {
    let fixture = game().await;
    for body in [
        json!({"content":""}),
        json!({"content":" \r\n\t"}),
        json!({"content":"é".repeat(8193)}),
        json!({"content":"text","round_num":0}),
        json!({"content":"text","round_num":-1}),
        json!({"content":"text","round_num":4294967296_u64}),
        json!({"content":"text","unknown":1}),
    ] {
        let (status, response) = fixture
            .request(
                Method::POST,
                "/v1/episodes/forum-game/forum/messages",
                Some("creator"),
                Some("invalid"),
                body,
            )
            .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{response}");
    }
    for query in [
        "?limit=0",
        "?limit=101",
        "?after=9223372036854775808",
        "?after=-1",
        "?bad=true",
    ] {
        let (status, _) = fixture
            .request(
                Method::GET,
                &format!("/v1/episodes/forum-game/forum/messages{query}"),
                Some("creator"),
                None,
                Value::Null,
            )
            .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    }
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/forum-game/forum/messages",
            Some("creator"),
            None,
            json!({"content":"text"}),
        )
        .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(audit(&fixture, "").await["forum_used"], false);
    let boundary = "é".repeat(8192);
    assert_eq!(
        send(&fixture, "creator", "boundary", &boundary, None).await["content"],
        boundary
    );
}

#[tokio::test]
async fn concurrent_posts_have_unique_contiguous_sequences_and_retry_deduplication() {
    let fixture = game().await;
    let mut jobs = Vec::new();
    for index in 0..12 {
        let app = fixture.app.clone();
        jobs.push(tokio::spawn(async move {
            use axum::{body::Body, http::Request};
            app.oneshot(
                Request::builder()
                    .method(Method::POST)
                    .uri("/v1/episodes/forum-game/forum/messages")
                    .header("Authorization", "Bearer test-creator")
                    .header("Content-Type", "application/json")
                    .header("Idempotency-Key", format!("concurrent-{}", index / 2))
                    .body(Body::from(
                        json!({"content":format!("message-{}",index/2)}).to_string(),
                    ))
                    .unwrap(),
            )
            .await
            .unwrap()
            .status()
        }));
    }
    for job in jobs {
        assert_eq!(job.await.unwrap(), StatusCode::CREATED);
    }
    let report = audit(&fixture, "").await;
    assert_eq!(report["message_count"], 6);
    assert_eq!(report["events"].as_array().unwrap().len(), 6);
    let (status, page) = fixture
        .request(
            Method::GET,
            "/v1/episodes/forum-game/forum/messages",
            Some("challenger"),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(
        page["messages"]
            .as_array()
            .unwrap()
            .iter()
            .map(|message| message["sequence"].as_u64().unwrap())
            .collect::<Vec<_>>(),
        [1, 2, 3, 4, 5, 6]
    );
}

#[tokio::test]
async fn separate_episode_rosters_messages_audits_and_private_chat_never_bleed() {
    let fixture = game().await;
    let mut other = registration("other-forum", 3, "1000");
    other.juror_ids = ["juror-4", "juror-5", "juror-6"]
        .map(str::to_owned)
        .to_vec();
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes",
            Some("operator"),
            Some("register-other"),
            serde_json::to_value(other).unwrap(),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    let first = send(
        &fixture,
        "creator",
        "same-episode-key",
        "first episode public",
        None,
    )
    .await;
    let (status, second) = fixture
        .request(
            Method::POST,
            "/v1/episodes/other-forum/forum/messages",
            Some("creator"),
            Some("same-episode-key"),
            json!({"content":"second episode public"}),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(first["sequence"], 1);
    assert_eq!(second["sequence"], 1);
    let (status, chat) = fixture
        .request(
            Method::POST,
            "/v1/episodes/forum-game/chats",
            Some("creator"),
            Some("private-chat"),
            json!({"participant_ids":["creator","juror-1"]}),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    let (status, _) = fixture
        .request(
            Method::POST,
            &format!("/v1/chats/{}/messages", chat["chat_id"].as_str().unwrap()),
            Some("creator"),
            Some("same-episode-key"),
            json!({"content":"private secret never in forum"}),
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    for (episode, member, outsider, expected) in [
        ("forum-game", "juror-1", "juror-4", first),
        ("other-forum", "juror-4", "juror-1", second),
    ] {
        let (status, page) = fixture
            .request(
                Method::GET,
                &format!("/v1/episodes/{episode}/forum/messages"),
                Some(member),
                None,
                Value::Null,
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(page["messages"], json!([expected]));
        assert!(!page.to_string().contains("private secret"));
        let (status, _) = fixture
            .request(
                Method::GET,
                &format!("/v1/episodes/{episode}/forum/messages"),
                Some(outsider),
                None,
                Value::Null,
            )
            .await;
        assert_eq!(status, StatusCode::FORBIDDEN);
        let (status, report) = fixture
            .request(
                Method::GET,
                &format!("/v1/episodes/{episode}/forum-audit"),
                Some("operator"),
                None,
                Value::Null,
            )
            .await;
        assert_eq!(status, StatusCode::OK);
        assert_eq!(report["episode_id"], episode);
        assert_eq!(report["message_count"], 1);
        assert!(
            report["events"]
                .as_array()
                .unwrap()
                .iter()
                .all(|event| event["episode_id"] == episode)
        );
        assert!(!report.to_string().contains("private secret"));
    }
    let (status, private_page) = fixture
        .request(
            Method::GET,
            &format!("/v1/chats/{}/messages", chat["chat_id"].as_str().unwrap()),
            Some("juror-1"),
            None,
            Value::Null,
        )
        .await;
    assert_eq!(status, StatusCode::OK);
    assert_eq!(private_page["messages"].as_array().unwrap().len(), 1);
    assert_eq!(
        private_page["messages"][0]["content"],
        "private secret never in forum"
    );
}
