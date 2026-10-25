use std::collections::{BTreeMap, BTreeSet};

use alloy::primitives::keccak256;
use axum::http::{HeaderMap, header};

/// Server-owned credentials. Never log or serialize this configuration.
#[derive(Clone)]
pub struct AuthConfig {
    pub operator_token: String,
    pub participant_tokens: BTreeMap<String, String>,
}

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum AuthConfigError {
    #[error("API tokens must be nonempty visible ASCII without whitespace")]
    InvalidToken,
    #[error("each API token must identify exactly one principal")]
    DuplicateToken,
    #[error("participant IDs must not be empty")]
    InvalidParticipant,
}

impl AuthConfig {
    /// Validate credentials before starting the HTTP listener.
    pub fn validate(&self) -> Result<(), AuthConfigError> {
        let mut tokens = BTreeSet::new();
        for token in std::iter::once(&self.operator_token).chain(self.participant_tokens.values()) {
            if token.is_empty() || !token.bytes().all(|byte| (0x21..=0x7e).contains(&byte)) {
                return Err(AuthConfigError::InvalidToken);
            }
            if !tokens.insert(keccak256(token.as_bytes())) {
                return Err(AuthConfigError::DuplicateToken);
            }
        }
        if self
            .participant_tokens
            .keys()
            .any(|identity| identity.trim().is_empty())
        {
            return Err(AuthConfigError::InvalidParticipant);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub(super) enum Principal {
    Operator,
    Participant(String),
}

pub(super) fn authenticate(headers: &HeaderMap, auth: &AuthConfig) -> Option<Principal> {
    auth.validate().ok()?;
    let mut values = headers.get_all(header::AUTHORIZATION).iter();
    let value = values.next()?.to_str().ok()?;
    if values.next().is_some() {
        return None;
    }
    let (scheme, token) = value.split_once(' ')?;
    if !scheme.eq_ignore_ascii_case("bearer")
        || token.is_empty()
        || !token.bytes().all(|byte| (0x21..=0x7e).contains(&byte))
    {
        return None;
    }
    // Compare fixed-length digests rather than exposing token-prefix comparisons.
    let digest = keccak256(token.as_bytes());
    if digest == keccak256(auth.operator_token.as_bytes()) {
        return Some(Principal::Operator);
    }
    auth.participant_tokens
        .iter()
        .find_map(|(identity, candidate)| {
            (digest == keccak256(candidate.as_bytes()))
                .then(|| Principal::Participant(identity.clone()))
        })
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::{HeaderValue, header};

    fn config() -> AuthConfig {
        AuthConfig {
            operator_token: "operator-token".into(),
            participant_tokens: BTreeMap::from([
                ("creator".into(), "creator-token".into()),
                ("juror-1".into(), "juror-token".into()),
            ]),
        }
    }

    fn authorization(value: &str) -> HeaderMap {
        let mut headers = HeaderMap::new();
        headers.insert(header::AUTHORIZATION, HeaderValue::from_str(value).unwrap());
        headers
    }

    #[test]
    fn rejects_empty_or_whitespace_credentials() {
        for token in ["", " ", "has space", "has\ttab", "non-ascii-é"] {
            let mut auth = config();
            auth.operator_token = token.into();
            assert_eq!(auth.validate(), Err(AuthConfigError::InvalidToken));
        }
    }

    #[test]
    fn one_token_cannot_authenticate_as_two_principals() {
        let mut auth = config();
        auth.participant_tokens
            .insert("creator".into(), auth.operator_token.clone());
        assert_eq!(auth.validate(), Err(AuthConfigError::DuplicateToken));

        let mut auth = config();
        auth.participant_tokens
            .insert("creator".into(), "juror-token".into());
        assert_eq!(auth.validate(), Err(AuthConfigError::DuplicateToken));
    }

    #[test]
    fn rejects_empty_participant_identity() {
        let mut auth = config();
        auth.participant_tokens
            .insert("".into(), "another-token".into());
        assert_eq!(auth.validate(), Err(AuthConfigError::InvalidParticipant));
    }

    #[test]
    fn bearer_token_binds_the_server_owned_principal() {
        let auth = config();
        assert_eq!(
            authenticate(&authorization("Bearer operator-token"), &auth),
            Some(Principal::Operator)
        );
        assert_eq!(
            authenticate(&authorization("Bearer juror-token"), &auth),
            Some(Principal::Participant("juror-1".into()))
        );
    }

    #[test]
    fn rejects_missing_unknown_ambiguous_or_non_bearer_authorization() {
        let auth = config();
        assert_eq!(authenticate(&HeaderMap::new(), &auth), None);
        for value in [
            "Bearer unknown",
            "Basic operator-token",
            "Bearer",
            "Bearer  operator-token",
            "Bearer operator-token extra",
        ] {
            assert_eq!(authenticate(&authorization(value), &auth), None);
        }
        let mut headers = authorization("Bearer creator-token");
        headers.append(
            header::AUTHORIZATION,
            HeaderValue::from_static("Bearer operator-token"),
        );
        assert_eq!(authenticate(&headers, &auth), None);
    }
}
