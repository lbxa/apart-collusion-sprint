use axum::{
    Json, Router,
    extract::{
        Path, Query, Request, State,
        rejection::{JsonRejection, PathRejection, QueryRejection},
    },
    http::{HeaderMap, HeaderValue, StatusCode, header},
    middleware::{self, Next},
    response::{IntoResponse, Response},
    routing::get,
};

use super::{
    auth::{Principal, authenticate},
    error::ApiError,
    routes::{AppState, idempotency_key, request_json, resource_id},
};
use crate::{
    chat::ChatPrincipal,
    forum::{ForumAuditReport, ForumMessage, ForumMessagePage, ForumQuery, ForumSendMessage},
};

pub(super) fn router() -> Router<AppState> {
    Router::new()
        .route(
            "/v1/episodes/{id}/forum/messages",
            get(get_forum_messages).post(send_forum_message),
        )
        .route(
            "/v1/episodes/{id}/forum/transcript",
            get(get_forum_transcript),
        )
        .route("/v1/episodes/{id}/forum-audit", get(get_forum_audit))
        .route_layer(middleware::from_fn(no_cache))
}

async fn no_cache(request: Request, next: Next) -> Response {
    let mut response = next.run(request).await;
    response
        .headers_mut()
        .insert(header::CACHE_CONTROL, HeaderValue::from_static("no-store"));
    response
        .headers_mut()
        .insert(header::VARY, HeaderValue::from_static("Authorization"));
    response
}

fn principal(headers: &HeaderMap, state: &AppState) -> Result<ChatPrincipal, ApiError> {
    match authenticate(headers, &state.auth) {
        Some(Principal::Operator) => Ok(ChatPrincipal::Operator),
        Some(Principal::Participant(id)) => Ok(ChatPrincipal::Participant(id)),
        None => Err(ApiError::new(
            StatusCode::UNAUTHORIZED,
            "UNAUTHORIZED",
            "A valid bearer credential is required.",
        )),
    }
}

fn query(value: Result<Query<ForumQuery>, QueryRejection>) -> Result<ForumQuery, ApiError> {
    value.map(|Query(value)| value).map_err(|_| {
        ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_REQUEST",
            "Forum pagination query is invalid.",
        )
    })
}

#[utoipa::path(post,path="/v1/episodes/{id}/forum/messages",tag="public forum",request_body=ForumSendMessage,
    description="Append exact UTF-8 to the episode-wide forum as the authenticated assigned participant. round_num is an optional caller-supplied annotation. Retried requests return the original message without duplicate audit events.",
    params(("id"=String,Path),("Idempotency-Key"=String,Header)),security(("bearerAuth"=[])),
    responses((status=201,body=ForumMessage),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=409,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn send_forum_message(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<ForumSendMessage>, JsonRejection>,
) -> Result<Response, ApiError> {
    let actor = principal(&headers, &state)?;
    let key = idempotency_key(&headers)?.to_owned();
    let message = state
        .service
        .forum()
        .send(actor, resource_id(id)?, request_json(body)?, key)
        .await?;
    Ok((StatusCode::CREATED, Json(message)).into_response())
}

#[utoipa::path(get,path="/v1/episodes/{id}/forum/messages",tag="public forum",
    description="Assigned participants read full chronological forum history. Every read is audited with exact returned sequence numbers. Operators use the separate transcript route.",
    params(("id"=String,Path),("after"=Option<u64>,Query),("limit"=Option<u16>,Query,description="1–100, default 50")),security(("bearerAuth"=[])),
    responses((status=200,body=ForumMessagePage),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn get_forum_messages(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    pagination: Result<Query<ForumQuery>, QueryRejection>,
) -> Result<Json<ForumMessagePage>, ApiError> {
    let actor = principal(&headers, &state)?;
    Ok(Json(
        state
            .service
            .forum()
            .messages(actor, resource_id(id)?, query(pagination)?, false)
            .await?,
    ))
}

#[utoipa::path(get,path="/v1/episodes/{id}/forum/transcript",tag="forum audit",
    description="Operator-only retained forum transcript. Access is audited separately and never counts as participant use.",
    params(("id"=String,Path),("after"=Option<u64>,Query),("limit"=Option<u16>,Query,description="1–100, default 50")),security(("bearerAuth"=[])),
    responses((status=200,body=ForumMessagePage),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn get_forum_transcript(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    pagination: Result<Query<ForumQuery>, QueryRejection>,
) -> Result<Json<ForumMessagePage>, ApiError> {
    let actor = principal(&headers, &state)?;
    Ok(Json(
        state
            .service
            .forum()
            .messages(actor, resource_id(id)?, query(pagination)?, true)
            .await?,
    ))
}

#[utoipa::path(get,path="/v1/episodes/{id}/forum-audit",tag="forum audit",
    description="Operator-only metadata events and all-time forum usage. Bodies are omitted; totals are independent of event pagination. Audit reads create no events.",
    params(("id"=String,Path),("after"=Option<u64>,Query),("limit"=Option<u16>,Query,description="1–100, default 50")),security(("bearerAuth"=[])),
    responses((status=200,body=ForumAuditReport),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn get_forum_audit(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    pagination: Result<Query<ForumQuery>, QueryRejection>,
) -> Result<Json<ForumAuditReport>, ApiError> {
    let actor = principal(&headers, &state)?;
    Ok(Json(
        state
            .service
            .forum()
            .audit(actor, resource_id(id)?, query(pagination)?)
            .await?,
    ))
}
