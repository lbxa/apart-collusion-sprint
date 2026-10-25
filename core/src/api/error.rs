use axum::{
    Json,
    http::{StatusCode, header},
    response::{IntoResponse, Response},
};
use serde::Serialize;
use utoipa::ToSchema;

use crate::game::GameError;

#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct ErrorResponse {
    pub error: ApiProblem,
}

#[derive(Clone, Debug, Serialize, ToSchema)]
pub struct ApiProblem {
    pub code: String,
    pub message: String,
}

pub(super) struct ApiError {
    pub status: StatusCode,
    pub code: &'static str,
    pub message: String,
}

impl ApiError {
    pub fn new(status: StatusCode, code: &'static str, message: impl Into<String>) -> Self {
        Self {
            status,
            code,
            message: message.into(),
        }
    }
}

impl From<GameError> for ApiError {
    fn from(error: GameError) -> Self {
        match error {
            GameError::Validation(message) => {
                Self::new(StatusCode::UNPROCESSABLE_ENTITY, "INVALID_REQUEST", message)
            }
            GameError::NotFound(message) => Self::new(StatusCode::NOT_FOUND, "NOT_FOUND", message),
            GameError::Forbidden(message) => Self::new(StatusCode::FORBIDDEN, "FORBIDDEN", message),
            GameError::Conflict(message) => Self::new(StatusCode::CONFLICT, "CONFLICT", message),
            GameError::Rejected(_) => Self::new(
                StatusCode::CONFLICT,
                "ACTION_REJECTED",
                "The contract rejected this action. Check the episode phase and assigned role.",
            ),
            GameError::Unavailable(_) => Self::new(
                StatusCode::SERVICE_UNAVAILABLE,
                "CHAIN_UNAVAILABLE",
                "The chain service is temporarily unavailable. Inspect and reconcile the existing operation before retrying.",
            ),
            GameError::Internal(_) => Self::new(
                StatusCode::INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
                "The request could not be completed.",
            ),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        let mut response = (
            self.status,
            Json(ErrorResponse {
                error: ApiProblem {
                    code: self.code.into(),
                    message: self.message,
                },
            }),
        )
            .into_response();
        if self.status == StatusCode::UNAUTHORIZED {
            response.headers_mut().insert(
                header::WWW_AUTHENTICATE,
                axum::http::HeaderValue::from_static("Bearer"),
            );
        }
        response
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn maps_domain_failures_without_leaking_infrastructure_details() {
        let cases = [
            (
                GameError::Validation("invalid bond".into()),
                StatusCode::UNPROCESSABLE_ENTITY,
                "INVALID_REQUEST",
            ),
            (
                GameError::NotFound("episode".into()),
                StatusCode::NOT_FOUND,
                "NOT_FOUND",
            ),
            (
                GameError::Forbidden("wrong role".into()),
                StatusCode::FORBIDDEN,
                "FORBIDDEN",
            ),
            (
                GameError::Conflict("duplicate".into()),
                StatusCode::CONFLICT,
                "CONFLICT",
            ),
            (
                GameError::Rejected("late vote".into()),
                StatusCode::CONFLICT,
                "ACTION_REJECTED",
            ),
            (
                GameError::Unavailable("https://user:password@private.rpc".into()),
                StatusCode::SERVICE_UNAVAILABLE,
                "CHAIN_UNAVAILABLE",
            ),
            (
                GameError::Internal("secret internal data".into()),
                StatusCode::INTERNAL_SERVER_ERROR,
                "INTERNAL_ERROR",
            ),
        ];
        for (error, status, code) in cases {
            let response = ApiError::from(error);
            assert_eq!(response.status, status);
            assert_eq!(response.code, code);
            assert!(!response.message.contains("password"));
            assert!(!response.message.contains("secret"));
        }
    }
}
