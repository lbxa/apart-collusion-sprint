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
use crate::chat::{
    ChatAuditReport, ChatListQuery, ChatMessage, ChatPage, ChatPrincipal, ChatQuery, ChatView,
    CreateChat, MessagePage, SendMessage,
};

pub(super) fn router() -> Router<AppState> {
    Router::new()
        .route("/v1/episodes/{id}/chats", get(list).post(create))
        .route("/v1/chats/{id}/messages", get(messages).post(send))
        .route("/v1/chats/{id}/transcript", get(transcript))
        .route("/v1/episodes/{id}/chat-audit", get(audit))
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

fn query<T>(value: Result<Query<T>, QueryRejection>) -> Result<T, ApiError> {
    value.map(|Query(value)| value).map_err(|_| {
        ApiError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "INVALID_REQUEST",
            "Chat pagination query is invalid.",
        )
    })
}

#[utoipa::path(post, path="/v1/episodes/{id}/chats", tag="private chat", request_body=CreateChat,
    description="Create an immutable two-participant chat. Participants must include themselves and cannot set communication_prohibited=false. The operator may provision permitted controls. History defaults to latest-only; private operator audit always retains all messages.",
    params(("id"=String,Path),("Idempotency-Key"=String,Header)), security(("bearerAuth"=[])),
    responses((status=201,body=ChatView),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=409,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn create(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<CreateChat>, JsonRejection>,
) -> Result<Response, ApiError> {
    let actor = principal(&headers, &state)?;
    let key = idempotency_key(&headers)?.to_owned();
    let chat = state
        .service
        .chats()
        .create(actor, resource_id(id)?, request_json(body)?, key)
        .await?;
    Ok((StatusCode::CREATED, Json(chat)).into_response())
}

#[utoipa::path(get, path="/v1/episodes/{id}/chats", tag="private chat",
    description="List only the caller's chats; the operator sees all episode chats. IDs form an opaque stable lexicographic cursor. Listing is audited.",
    params(("id"=String,Path),("after"=Option<String>,Query),("limit"=Option<u16>,Query,description="1–100, default 50")), security(("bearerAuth"=[])),
    responses((status=200,body=ChatPage),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn list(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    pagination: Result<Query<ChatListQuery>, QueryRejection>,
) -> Result<Json<ChatPage>, ApiError> {
    let actor = principal(&headers, &state)?;
    Ok(Json(
        state
            .service
            .chats()
            .list(actor, resource_id(id)?, query(pagination)?)
            .await?,
    ))
}

#[utoipa::path(post, path="/v1/chats/{id}/messages", tag="private chat", request_body=SendMessage,
    description="Send exact UTF-8 as the authenticated participant. Prohibited communication is delivered and flagged. A retry reuses the original message and send audit event.",
    params(("id"=String,Path),("Idempotency-Key"=String,Header)), security(("bearerAuth"=[])),
    responses((status=201,body=ChatMessage),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=409,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn send(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    body: Result<Json<SendMessage>, JsonRejection>,
) -> Result<Response, ApiError> {
    let actor = principal(&headers, &state)?;
    let key = idempotency_key(&headers)?.to_owned();
    let message = state
        .service
        .chats()
        .send(actor, resource_id(id)?, request_json(body)?, key)
        .await?;
    Ok((StatusCode::CREATED, Json(message)).into_response())
}

#[utoipa::path(get, path="/v1/chats/{id}/messages", tag="private chat",
    description="Either member reads chronological history when enabled, otherwise only the latest chat message. after is an exclusive message-sequence cursor. Repeated reads are permitted and individually audited, including exact returned sequence numbers. Operators must use the transcript endpoint.",
    params(("id"=String,Path),("after"=Option<u64>,Query),("limit"=Option<u16>,Query,description="1–100, default 50")), security(("bearerAuth"=[])),
    responses((status=200,body=MessagePage),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn messages(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    pagination: Result<Query<ChatQuery>, QueryRejection>,
) -> Result<Json<MessagePage>, ApiError> {
    let actor = principal(&headers, &state)?;
    Ok(Json(
        state
            .service
            .chats()
            .messages(actor, resource_id(id)?, query(pagination)?, false)
            .await?,
    ))
}

#[utoipa::path(get, path="/v1/chats/{id}/transcript", tag="chat audit",
    description="Operator-only full private transcript regardless of participant history setting. Access is audited and never marks the operator as an agent communicator.",
    params(("id"=String,Path),("after"=Option<u64>,Query),("limit"=Option<u16>,Query,description="1–100, default 50")), security(("bearerAuth"=[])),
    responses((status=200,body=MessagePage),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn transcript(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    pagination: Result<Query<ChatQuery>, QueryRejection>,
) -> Result<Json<MessagePage>, ApiError> {
    let actor = principal(&headers, &state)?;
    Ok(Json(
        state
            .service
            .chats()
            .messages(actor, resource_id(id)?, query(pagination)?, true)
            .await?,
    ))
}

#[utoipa::path(get, path="/v1/episodes/{id}/chat-audit", tag="chat audit",
    description="Operator-only all-time usage flags and per-participant totals, plus a bounded metadata event page. Event after is exclusive; totals are independent of the cursor. Contains no message bodies. Audit-report inspection does not itself append events.",
    params(("id"=String,Path),("after"=Option<u64>,Query),("limit"=Option<u16>,Query,description="1–100, default 50")), security(("bearerAuth"=[])),
    responses((status=200,body=ChatAuditReport),(status=401,body=super::ErrorResponse),(status=403,body=super::ErrorResponse),(status=404,body=super::ErrorResponse),(status=422,body=super::ErrorResponse),(status=500,body=super::ErrorResponse)))]
pub(super) async fn audit(
    State(state): State<AppState>,
    id: Result<Path<String>, PathRejection>,
    headers: HeaderMap,
    pagination: Result<Query<ChatQuery>, QueryRejection>,
) -> Result<Json<ChatAuditReport>, ApiError> {
    let actor = principal(&headers, &state)?;
    Ok(Json(
        state
            .service
            .chats()
            .audit(actor, resource_id(id)?, query(pagination)?)
            .await?,
    ))
}
