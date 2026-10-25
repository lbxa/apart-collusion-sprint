//! Versioned HTTP boundary for the contract-backed game service.

mod auth;
mod chat;
mod error;
mod forum;
mod openapi;
mod routes;

pub use auth::{AuthConfig, AuthConfigError};
pub use error::{ApiProblem, ErrorResponse};
pub use openapi::openapi;
pub use routes::{HealthResponse, router};
