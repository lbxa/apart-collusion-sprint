mod support;

use axum::{
    body::Body,
    http::{Method, Request, StatusCode},
};
use http_body_util::BodyExt;
use serde_json::{Value, json};
use support::{Fixture, registration};
use tower::ServiceExt;

#[tokio::test]
async fn a_game_can_be_created_without_experiment_harness_metadata() {
    let fixture = Fixture::new().await;
    let body: Value = serde_json::from_str(include_str!("../../examples/episode.json")).unwrap();
    assert!(body.get("experiment_id").is_none());
    assert!(body.get("scenario_id").is_none());
    let (status, operation) = fixture
        .request(
            Method::POST,
            "/v1/episodes",
            Some("operator"),
            Some("game-only-registration"),
            body,
        )
        .await;
    assert_eq!(status, StatusCode::CREATED);
    assert_eq!(operation["episode_id"], "trial-001");
    assert_eq!(operation["status"], "confirmed");
}

#[tokio::test]
async fn authenticates_commands_and_binds_the_actor_to_its_credential() {
    let fixture = Fixture::new().await;
    let request = serde_json::to_value(registration("auth-test", 3, "1000")).unwrap();
    for (actor, status) in [
        (None, StatusCode::UNAUTHORIZED),
        (Some("unknown"), StatusCode::UNAUTHORIZED),
        (Some("creator"), StatusCode::FORBIDDEN),
    ] {
        let (actual, body) = fixture
            .request(
                Method::POST,
                "/v1/episodes",
                actor,
                Some("registration"),
                request.clone(),
            )
            .await;
        assert_eq!(actual, status, "{body}");
        assert!(body["error"]["code"].is_string());
    }
    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/episodes",
            Some("operator"),
            None,
            request,
        )
        .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["error"]["code"], "INVALID_IDEMPOTENCY_KEY");

    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/anything/commitments",
            Some("operator"),
            Some("vote"),
            json!({"verdict":"CREATOR_SUPPORTED","assessment":"assessment"}),
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
}

#[tokio::test]
async fn rejects_float_money_unknown_fields_malformed_json_and_oversized_bodies() {
    let fixture = Fixture::new().await;
    let mut request = serde_json::to_value(registration("invalid-input", 3, "1000")).unwrap();
    request["parameters"]["beta_wei"] = json!(10.0);
    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/episodes",
            Some("operator"),
            Some("float-money"),
            request,
        )
        .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["error"]["code"], "INVALID_REQUEST");

    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/episodes/anything/commitments",
            Some("juror-1"),
            Some("smuggle-actor"),
            json!({"actor_id":"juror-2","verdict":"CREATOR_SUPPORTED","assessment":"assessment"}),
        )
        .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    assert_eq!(body["error"]["code"], "INVALID_REQUEST");

    let response = fixture
        .app
        .clone()
        .oneshot(
            Request::builder()
                .method(Method::POST)
                .uri("/v1/episodes")
                .header("Authorization", "Bearer test-operator")
                .header("Idempotency-Key", "malformed")
                .header("Content-Type", "application/json")
                .body(Body::from("{not-json"))
                .unwrap(),
        )
        .await
        .unwrap();
    assert_eq!(response.status(), StatusCode::UNPROCESSABLE_ENTITY);
    let body: Value =
        serde_json::from_slice(&response.into_body().collect().await.unwrap().to_bytes()).unwrap();
    assert_eq!(body["error"]["code"], "INVALID_REQUEST");

    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/episodes/anything/claims",
            Some("creator"),
            Some("large"),
            json!({"content":"x".repeat(150_000)}),
        )
        .await;
    assert_eq!(status, StatusCode::PAYLOAD_TOO_LARGE);
    assert_eq!(body["error"]["code"], "BODY_TOO_LARGE");
}

#[tokio::test]
async fn exposes_versioned_docs_and_consistent_route_errors() {
    let fixture = Fixture::new().await;
    let (status, body) = fixture
        .request(Method::GET, "/v1/openapi.json", None, None, Value::Null)
        .await;
    assert_eq!(status, StatusCode::OK);
    assert!(body["paths"].get("/v1/episodes").is_some());

    let (status, body) = fixture
        .request(Method::GET, "/v2/episodes", None, None, Value::Null)
        .await;
    assert_eq!(status, StatusCode::NOT_FOUND);
    assert_eq!(body["error"]["code"], "NOT_FOUND");
    let (status, body) = fixture
        .request(Method::DELETE, "/v1/episodes", None, None, Value::Null)
        .await;
    assert_eq!(status, StatusCode::METHOD_NOT_ALLOWED);
    assert_eq!(body["error"]["code"], "METHOD_NOT_ALLOWED");
}

#[tokio::test]
async fn bounds_public_chain_exports_and_requires_operator_replay() {
    let fixture = Fixture::new().await;
    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/chain/replay",
            Some("creator"),
            Some("replay"),
            json!({"from_block":0,"to_block":10}),
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN, "{body}");
    for request in [
        json!({"from_block":10,"to_block":0}),
        json!({"from_block":0,"to_block":10000}),
    ] {
        let (status, body) = fixture
            .request(
                Method::POST,
                "/v1/chain/replay",
                Some("operator"),
                Some("invalid-replay"),
                request,
            )
            .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
    }
    for uri in [
        "/v1/chain/events?from_block=10&to_block=0",
        "/v1/chain/events?from_block=0&to_block=10000",
        "/v1/chain/events?from_block=not-a-number&to_block=2",
    ] {
        let (status, body) = fixture
            .request(Method::GET, uri, None, None, Value::Null)
            .await;
        assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY, "{body}");
        assert_eq!(body["error"]["code"], "INVALID_REQUEST");
    }
}

#[tokio::test]
async fn replay_needs_no_command_key_and_repeats_without_duplicate_events_or_transactions() {
    let fixture = Fixture::new().await;
    fixture.register("replay-without-key", 3, "1000").await;
    let head = fixture.rpc("eth_blockNumber", json!([])).await;
    let head = u64::from_str_radix(head.as_str().unwrap().trim_start_matches("0x"), 16).unwrap();
    let nonce = fixture.nonce("treasury").await;
    let range = json!({"from_block":0,"to_block":head});
    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/chain/replay",
            Some("operator"),
            None,
            range.clone(),
        )
        .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    let first_export = fixture.service.export_events(0, head).await.unwrap();
    assert!(!first_export.is_empty());

    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/chain/replay",
            Some("operator"),
            None,
            range,
        )
        .await;
    assert_eq!(status, StatusCode::OK, "{body}");
    assert_eq!(body["events_recorded"], 0);
    assert_eq!(
        fixture.service.export_events(0, head).await.unwrap(),
        first_export
    );
    assert_eq!(
        fixture.nonce("treasury").await,
        nonce,
        "Evidence replay must not broadcast a transaction."
    );
}
