use axum::{
    Json, Router,
    extract::{
        DefaultBodyLimit, MatchedPath, Path, Query, Request, State,
        rejection::{JsonRejection, PathRejection, QueryRejection},
    },
    http::{HeaderMap, StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::{get, post},
};
use serde::{Deserialize, Serialize};
use utoipa::ToSchema;

use super::{
    AuthConfig,
    auth::{Principal, authenticate},
    error::ApiError,
};
use crate::game::{
    BalancesView, DeploymentView, EpisodeView, GameAction, GameService, OperationView,
    ParticipantView, RegisterEpisode, SettlementView, Verdict,
};

#[derive(Clone)]
pub(super) struct AppState {
    pub(super) service: GameService,
    pub(super) auth: AuthConfig,
}

#[derive(Serialize, ToSchema)]
pub struct HealthResponse {
    #[schema(pattern = "^ok$")]
    pub status: &'static str,
    #[schema(pattern = "^v1$")]
    pub api_version: &'static str,
    pub deployment: DeploymentView,
}

#[derive(Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub(super) struct ClaimRequest {
    pub content: String,
}

#[derive(Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub(super) struct ChallengeRequest {
    pub evidence: String,
}

#[derive(Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub(super) struct CommitmentRequest {
    pub verdict: Verdict,
    pub assessment: String,
}

#[derive(Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub(super) struct EmptyRequest {}

#[derive(Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub(super) struct TransferRequest {
    /// Another participant in this episode.
    pub recipient_id: String,
    /// Withdrawal credit to move, in integer base units.
    #[schema(pattern = "^[1-9][0-9]*$")]
    pub amount_wei: String,
}

#[derive(Deserialize, ToSchema)]
#[serde(deny_unknown_fields)]
pub(super) struct BlockRange {
    pub from_block: u64,
    pub to_block: u64,
}

#[derive(Serialize, ToSchema)]
pub(super) struct ReplayResponse {
    pub from_block: u64,
    pub to_block: u64,
    pub events_recorded: usize,
}

/// Construct the versioned API. Call `AuthConfig::validate` before binding.
/// Invalid credential configurations fail closed at the authentication boundary.
pub fn router(service: GameService, auth: AuthConfig) -> Router {
    Router::new()
        .merge(super::chat::router())
        .merge(super::forum::router())
        .route("/v1/health", get(health))
        .route("/v1/openapi.json", get(openapi_document))
        .route("/v1/docs", get(docs))
        .route("/v1/participants", get(participants))
        .route("/v1/episodes", post(register))
        .route("/v1/episodes/{id}", get(episode))
        .route("/v1/episodes/{id}/claims", post(claim))
        .route("/v1/episodes/{id}/challenges", post(challenge))
        .route("/v1/episodes/{id}/commitments", post(commitment))
        .route("/v1/episodes/{id}/reveals", post(reveal))
        .route("/v1/episodes/{id}/settle", post(settle))
        .route("/v1/episodes/{id}/expire", post(expire))
        .route("/v1/episodes/{id}/withdrawals", post(withdraw))
        .route("/v1/episodes/{id}/transfers", post(transfer))
        .route("/v1/episodes/{id}/settlement", get(settlement))
        .route("/v1/episodes/{id}/balances", get(balances))
        .route("/v1/operations/{id}", get(operation))
        .route("/v1/operations/{id}/reconcile", post(reconcile))
        .route("/v1/chain/replay", post(replay))
        .route("/v1/chain/events", get(events))
        .fallback(not_found)
        .method_not_allowed_fallback(method_not_allowed)
        .layer(DefaultBodyLimit::max(128 * 1024))
        .layer(middleware::from_fn(observe_request))
        .with_state(AppState { service, auth })
}

async fn observe_request(request: Request, next: Next) -> Response {
    let method = request.method().clone();
    let route = request
        .extensions()
        .get::<MatchedPath>()
        .map(|path| path.as_str().to_owned())
        .unwrap_or_else(|| "<unmatched>".into());
    let started = std::time::Instant::now();
    let response = next.run(request).await;
    tracing::info!(event = "api.request.completed", method = %method, route = %route,
        status = response.status().as_u16(), elapsed_micros = started.elapsed().as_micros() as u64);
    response
}

fn operator(headers: &HeaderMap, auth: &AuthConfig) -> Result<(), ApiError> {
    match authenticate(headers, auth) {
        Some(Principal::Operator) => Ok(()),
        Some(Principal::Participant(_)) => Err(ApiError::new(
            StatusCode::FORBIDDEN,
            "FORBIDDEN",
            "An operator credential is required.",
        )),
        None => Err(ApiError::new(
            StatusCode::UNAUTHORIZED,
            "UNAUTHORIZED",
            "A valid bearer credential is required.",
        )),
    }
}

fn actor(headers: &HeaderMap, auth: &AuthConfig) -> Result<String, ApiError> {
    match authenticate(headers, auth) {
        Some(Principal::Participant(identity)) => Ok(identity),
        Some(Principal::Operator) => Err(ApiError::new(
            StatusCode::FORBIDDEN,
            "FORBIDDEN",
            "A participant credential is required for this action.",
        )),
        None => Err(ApiError::new(
            StatusCode::UNAUTHORIZED,
            "UNAUTHORIZED",
            "A valid bearer credential is required.",
        )),
    }
}

pub(super) fn idempotency_key(headers: &HeaderMap) -> Result<&str, ApiError> {
    let mut values = headers.get_all("Idempotency-Key").iter();
    let key = values.next().and_then(|value| value.to_str().ok());
    match key {
        Some(key)
            if values.next().is_none()
                && !key.is_empty()
                && key.len() <= 128
                && key.bytes().all(|byte| (0x21..=0x7e).contains(&byte)) =>
        {
            Ok(key)
        }
        _ => Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_IDEMPOTENCY_KEY",
            "Idempotency-Key must contain 1–128 visible ASCII characters without whitespace.",
        )),
    }
}

pub(super) fn request_json<T>(body: Result<Json<T>, JsonRejection>) -> Result<T, ApiError> {
    body.map(|Json(value)| value).map_err(|rejection| {
        if rejection.status() == StatusCode::PAYLOAD_TOO_LARGE {
            ApiError::new(
                StatusCode::PAYLOAD_TOO_LARGE,
                "BODY_TOO_LARGE",
                "The request body exceeds 128 KiB.",
            )
        } else {
            ApiError::new(
                StatusCode::UNPROCESSABLE_ENTITY,
                "INVALID_REQUEST",
                "Request JSON is invalid.",
            )
        }
    })
}

pub(super) fn resource_id(id: Result<Path<String>, PathRejection>) -> Result<String, ApiError> {
    id.map(|Path(value)| value).map_err(|_| {
        ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_REQUEST",
            "The resource path is invalid.",
        )
    })
}

fn operation_response(operation: OperationView, registration: bool) -> Response {
    let status = match operation.status.as_str() {
        "confirmed" if registration => StatusCode::CREATED,
        "confirmed" | "reverted" | "failed" => StatusCode::OK,
        _ => StatusCode::ACCEPTED,
    };
    (status, Json(operation)).into_response()
}

#[utoipa::path(get, path = "/v1/health", tag = "discovery",
    responses((status = 200, description = "Liveness and configured chain identity", body = HealthResponse)))]
pub(super) async fn health(State(state): State<AppState>) -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok",
        api_version: "v1",
        deployment: state.service.identity().await,
    })
}

#[utoipa::path(get, path = "/v1/openapi.json", tag = "discovery",
    responses((status = 200, description = "OpenAPI 3.1 contract", body = Object)))]
pub(super) async fn openapi_document() -> Json<utoipa::openapi::OpenApi> {
    Json(super::openapi())
}

#[utoipa::path(get, path = "/v1/docs", tag = "discovery",
    responses((status = 200, description = "Integration guide", body = String, content_type = "text/markdown")))]
pub(super) async fn docs() -> impl IntoResponse {
    (
        [(header::CONTENT_TYPE, "text/markdown; charset=utf-8")],
        include_str!("../../../docs/api.md"),
    )
}

#[utoipa::path(get, path = "/v1/participants", tag = "discovery",
    responses((status = 200, description = "Configured actor IDs and public addresses", body = [ParticipantView])))]
pub(super) async fn participants(State(state): State<AppState>) -> Json<Vec<ParticipantView>> {
    Json(state.service.participants().await)
}

#[utoipa::path(post, path = "/v1/episodes", tag = "episodes", request_body = RegisterEpisode,
    params(("Idempotency-Key" = String, Header, description = "Unique registration command key")), security(("bearerAuth" = [])),
    responses((status = 201, description = "Registration confirmed", body = OperationView), (status = 202, description = "Registration pending", body = OperationView),
        (status = 401, body = super::ErrorResponse), (status = 403, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse),
        (status = 422, body = super::ErrorResponse), (status = 503, body = super::ErrorResponse)))]
pub(super) async fn register(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Result<Json<RegisterEpisode>, JsonRejection>,
) -> Result<Response, ApiError> {
    operator(&headers, &state.auth)?;
    let key = idempotency_key(&headers)?;
    Ok(operation_response(
        state.service.register(request_json(body)?, key).await?,
        true,
    ))
}

#[utoipa::path(get, path = "/v1/episodes/{id}", tag = "episodes", params(("id" = String, Path, description = "Caller-chosen episode ID")),
    responses((status = 200, body = EpisodeView), (status = 404, body = super::ErrorResponse), (status = 503, body = super::ErrorResponse)))]
pub(super) async fn episode(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
) -> Result<Json<EpisodeView>, ApiError> {
    Ok(Json(state.service.episode(&resource_id(id)?).await?))
}

#[utoipa::path(post, path = "/v1/episodes/{id}/claims", tag = "actions", request_body = ClaimRequest,
    params(("id" = String, Path), ("Idempotency-Key" = String, Header)), security(("bearerAuth" = [])),
    responses((status = 200, body = OperationView), (status = 202, body = OperationView), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse), (status = 422, body = super::ErrorResponse)))]
pub(super) async fn claim(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<ClaimRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    let actor = actor(&headers, &state.auth)?;
    let key = idempotency_key(&headers)?;
    let request = request_json(body)?;
    Ok(operation_response(
        state
            .service
            .act(
                &resource_id(id)?,
                &actor,
                GameAction::PostClaim {
                    content: request.content,
                },
                key,
            )
            .await?,
        false,
    ))
}

#[utoipa::path(post, path = "/v1/episodes/{id}/challenges", tag = "actions", request_body = ChallengeRequest,
    params(("id" = String, Path), ("Idempotency-Key" = String, Header)), security(("bearerAuth" = [])),
    responses((status = 200, body = OperationView), (status = 202, body = OperationView), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse), (status = 422, body = super::ErrorResponse)))]
pub(super) async fn challenge(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<ChallengeRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    let actor = actor(&headers, &state.auth)?;
    let key = idempotency_key(&headers)?;
    let request = request_json(body)?;
    Ok(operation_response(
        state
            .service
            .act(
                &resource_id(id)?,
                &actor,
                GameAction::Challenge {
                    evidence: request.evidence,
                },
                key,
            )
            .await?,
        false,
    ))
}

#[utoipa::path(post, path = "/v1/episodes/{id}/commitments", tag = "actions", request_body = CommitmentRequest,
    description = "Selected juror commits a verdict and assessment and deposits the juror bond. The server generates and persists the secret salt; it is never returned.",
    params(("id" = String, Path), ("Idempotency-Key" = String, Header)), security(("bearerAuth" = [])),
    responses((status = 200, body = OperationView), (status = 202, body = OperationView), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse), (status = 422, body = super::ErrorResponse)))]
pub(super) async fn commitment(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<CommitmentRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    let actor = actor(&headers, &state.auth)?;
    let key = idempotency_key(&headers)?;
    let request = request_json(body)?;
    Ok(operation_response(
        state
            .service
            .act(
                &resource_id(id)?,
                &actor,
                GameAction::CommitVote {
                    verdict: request.verdict,
                    assessment: request.assessment,
                },
                key,
            )
            .await?,
        false,
    ))
}

#[utoipa::path(post, path = "/v1/episodes/{id}/reveals", tag = "actions", request_body = EmptyRequest,
    description = "The same juror reveals previously persisted material during the chain-derived reveal window.",
    params(("id" = String, Path), ("Idempotency-Key" = String, Header)), security(("bearerAuth" = [])),
    responses((status = 200, body = OperationView), (status = 202, body = OperationView), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse), (status = 422, body = super::ErrorResponse)))]
pub(super) async fn reveal(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<EmptyRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    let actor = actor(&headers, &state.auth)?;
    let key = idempotency_key(&headers)?;
    request_json(body)?;
    Ok(operation_response(
        state
            .service
            .act(&resource_id(id)?, &actor, GameAction::RevealVote {}, key)
            .await?,
        false,
    ))
}

#[utoipa::path(post, path = "/v1/episodes/{id}/settle", tag = "actions", request_body = EmptyRequest,
    description = "After the reveal deadline, accrue contract-enforced credits exactly once. No external transfers are made by settlement.",
    params(("id" = String, Path), ("Idempotency-Key" = String, Header)), security(("bearerAuth" = [])),
    responses((status = 200, body = OperationView), (status = 202, body = OperationView), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse), (status = 422, body = super::ErrorResponse)))]
pub(super) async fn settle(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<EmptyRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    operator(&headers, &state.auth)?;
    let key = idempotency_key(&headers)?;
    request_json(body)?;
    Ok(operation_response(
        state
            .service
            .act(
                &resource_id(id)?,
                state.service.operator_id(),
                GameAction::Settle {},
                key,
            )
            .await?,
        false,
    ))
}

#[utoipa::path(post, path = "/v1/episodes/{id}/expire", tag = "actions", request_body = EmptyRequest,
    params(("id" = String, Path), ("Idempotency-Key" = String, Header)), security(("bearerAuth" = [])),
    responses((status = 200, body = OperationView), (status = 202, body = OperationView), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse), (status = 422, body = super::ErrorResponse)))]
pub(super) async fn expire(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<EmptyRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    operator(&headers, &state.auth)?;
    let key = idempotency_key(&headers)?;
    request_json(body)?;
    Ok(operation_response(
        state
            .service
            .act(
                &resource_id(id)?,
                state.service.operator_id(),
                GameAction::Expire {},
                key,
            )
            .await?,
        false,
    ))
}

#[utoipa::path(post, path = "/v1/episodes/{id}/withdrawals", tag = "actions", request_body = EmptyRequest,
    description = "Withdraw only the authenticated participant's entire global credit, which may contain entitlements from multiple episodes.",
    params(("id" = String, Path), ("Idempotency-Key" = String, Header)), security(("bearerAuth" = [])),
    responses((status = 200, body = OperationView), (status = 202, body = OperationView), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse), (status = 422, body = super::ErrorResponse)))]
pub(super) async fn withdraw(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<EmptyRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    let actor = actor(&headers, &state.auth)?;
    let key = idempotency_key(&headers)?;
    request_json(body)?;
    Ok(operation_response(
        state
            .service
            .act(&resource_id(id)?, &actor, GameAction::Withdraw {}, key)
            .await?,
        false,
    ))
}

#[utoipa::path(post, path = "/v1/episodes/{id}/transfers", tag = "actions", request_body = TransferRequest,
    description = "Move part of the authenticated participant's global withdrawal credit to another participant in this episode.",
    params(("id" = String, Path), ("Idempotency-Key" = String, Header)), security(("bearerAuth" = [])),
    responses((status = 200, body = OperationView), (status = 202, body = OperationView), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse), (status = 422, body = super::ErrorResponse)))]
pub(super) async fn transfer(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<TransferRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    let actor = actor(&headers, &state.auth)?;
    let key = idempotency_key(&headers)?;
    let request = request_json(body)?;
    Ok(operation_response(
        state
            .service
            .act(
                &resource_id(id)?,
                &actor,
                GameAction::TransferCredits {
                    recipient_id: request.recipient_id,
                    amount_wei: request.amount_wei,
                },
                key,
            )
            .await?,
        false,
    ))
}

#[utoipa::path(get, path = "/v1/episodes/{id}/settlement", tag = "episodes", params(("id" = String, Path)),
    responses((status = 200, body = SettlementView), (status = 404, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse), (status = 503, body = super::ErrorResponse)))]
pub(super) async fn settlement(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
) -> Result<Json<SettlementView>, ApiError> {
    Ok(Json(state.service.settlement(&resource_id(id)?).await?))
}

#[utoipa::path(get, path = "/v1/episodes/{id}/balances", tag = "episodes", params(("id" = String, Path)),
    responses((status = 200, body = BalancesView), (status = 404, body = super::ErrorResponse), (status = 503, body = super::ErrorResponse)))]
pub(super) async fn balances(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
) -> Result<Json<BalancesView>, ApiError> {
    Ok(Json(state.service.balances(&resource_id(id)?).await?))
}

#[utoipa::path(get, path = "/v1/operations/{id}", tag = "operations", params(("id" = String, Path)),
    responses((status = 200, body = OperationView), (status = 404, body = super::ErrorResponse)))]
pub(super) async fn operation(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
) -> Result<Json<OperationView>, ApiError> {
    Ok(Json(state.service.operation(&resource_id(id)?).await?))
}

#[utoipa::path(post, path = "/v1/operations/{id}/reconcile", tag = "operations", request_body = EmptyRequest,
    description = "Inspect a saved transaction hash/nonce and, when necessary, rebroadcast its exact signed bytes. This never creates a new economic action.",
    params(("id" = String, Path), ("Idempotency-Key" = String, Header)), security(("bearerAuth" = [])),
    responses((status = 200, body = OperationView), (status = 202, body = OperationView), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 404, body = super::ErrorResponse), (status = 409, body = super::ErrorResponse)))]
pub(super) async fn reconcile(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<EmptyRequest>, JsonRejection>,
) -> Result<Response, ApiError> {
    operator(&headers, &state.auth)?;
    idempotency_key(&headers)?;
    request_json(body)?;
    Ok(operation_response(
        state.service.reconcile(&resource_id(id)?).await?,
        false,
    ))
}

async fn not_found() -> ApiError {
    ApiError::new(
        StatusCode::NOT_FOUND,
        "NOT_FOUND",
        "The requested API resource does not exist.",
    )
}
async fn method_not_allowed() -> ApiError {
    ApiError::new(
        StatusCode::METHOD_NOT_ALLOWED,
        "METHOD_NOT_ALLOWED",
        "This method is not supported for the requested resource.",
    )
}

fn block_range(range: BlockRange) -> Result<BlockRange, ApiError> {
    if range
        .to_block
        .checked_sub(range.from_block)
        .is_some_and(|distance| distance < 10_000)
    {
        Ok(range)
    } else {
        Err(ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_REQUEST",
            "A block range must be ordered and contain at most 10,000 blocks, inclusive.",
        ))
    }
}

#[utoipa::path(post, path = "/v1/chain/replay", tag = "chain evidence", request_body = BlockRange,
    description = "Replay a bounded inclusive block range into the deduplicated event stream. At most 10,000 blocks per request. Naturally idempotent by chain-event identity; no Idempotency-Key is needed, and newly recorded counts may differ on repeat.",
    security(("bearerAuth" = [])),
    responses((status = 200, body = ReplayResponse), (status = 401, body = super::ErrorResponse),
        (status = 403, body = super::ErrorResponse), (status = 422, body = super::ErrorResponse), (status = 503, body = super::ErrorResponse)))]
pub(super) async fn replay(
    State(state): State<AppState>,
    headers: HeaderMap,
    body: Result<Json<BlockRange>, JsonRejection>,
) -> Result<Json<ReplayResponse>, ApiError> {
    operator(&headers, &state.auth)?;
    let range = block_range(request_json(body)?)?;
    let events_recorded = state
        .service
        .replay_events(range.from_block, range.to_block)
        .await?;
    Ok(Json(ReplayResponse {
        from_block: range.from_block,
        to_block: range.to_block,
        events_recorded,
    }))
}

#[utoipa::path(get, path = "/v1/chain/events", tag = "chain evidence",
    description = "Stored public chain events as JSON Lines for an inclusive range of at most 10,000 blocks. Excludes private commands and reveal material.",
    params(("from_block" = u64, Query), ("to_block" = u64, Query)),
    responses((status = 200, body = String, content_type = "application/x-ndjson"),
        (status = 422, body = super::ErrorResponse), (status = 503, body = super::ErrorResponse)))]
pub(super) async fn events(
    State(state): State<AppState>,
    query: Result<Query<BlockRange>, QueryRejection>,
) -> Result<Response, ApiError> {
    let Query(range) = query.map_err(|_| {
        ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_REQUEST",
            "The block range query is invalid.",
        )
    })?;
    let range = block_range(range)?;
    let stream = state
        .service
        .export_events(range.from_block, range.to_block)
        .await?;
    Ok((
        [(header::CONTENT_TYPE, "application/x-ndjson; charset=utf-8")],
        stream,
    )
        .into_response())
}
