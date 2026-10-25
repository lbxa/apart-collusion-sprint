use std::collections::{BTreeMap, BTreeSet};

use alloy::primitives::{Address, B256, U256, keccak256};

use super::{GameAction, GameError, RegisterEpisode};
use crate::chain::ContractConfig;

pub const MAX_ARTIFACT_BYTES: usize = 64 * 1024;

pub fn validate_identifier(id: &str) -> Result<(), GameError> {
    if id.is_empty()
        || id.len() > 128
        || !id
            .bytes()
            .all(|value| value.is_ascii_alphanumeric() || matches!(value, b'-' | b'_' | b'.'))
    {
        return Err(GameError::Validation(
            "identifiers must contain 1–128 ASCII letters, digits, '.', '_' or '-'".into(),
        ));
    }
    Ok(())
}

pub fn validate_key(key: &str) -> Result<(), GameError> {
    if key.is_empty() || key.len() > 128 || !key.bytes().all(|value| (0x21..=0x7e).contains(&value))
    {
        return Err(GameError::Validation(
            "Idempotency-Key must contain 1–128 visible ASCII characters".into(),
        ));
    }
    Ok(())
}

pub fn artifact_hash(artifact: &str) -> Result<B256, GameError> {
    if artifact.len() > MAX_ARTIFACT_BYTES {
        return Err(GameError::Validation(
            "artifact exceeds 64 KiB of UTF-8 bytes".into(),
        ));
    }
    if artifact.contains('\r') {
        return Err(GameError::Validation(
            "artifact must use LF line endings; CR is not normalized".into(),
        ));
    }
    Ok(keccak256(artifact.as_bytes()))
}

pub fn configuration_hash(request: &RegisterEpisode) -> Result<B256, GameError> {
    let canonical = serde_jcs::to_vec(request).map_err(|_| {
        GameError::Validation("configuration cannot be encoded as canonical JSON".into())
    })?;
    Ok(keccak256(canonical))
}

pub(super) fn authorize_action(
    request: &RegisterEpisode,
    operator_id: &str,
    actor_id: &str,
    action: &GameAction,
) -> Result<(), GameError> {
    let authorized = match action {
        GameAction::PostClaim { .. } => actor_id == request.creator_id,
        GameAction::Challenge { .. } => actor_id == request.challenger_id,
        GameAction::CommitVote { .. } | GameAction::RevealVote { .. } => {
            request.juror_ids.iter().any(|juror| juror == actor_id)
        }
        GameAction::Settle { .. } | GameAction::Expire { .. } => actor_id == operator_id,
        GameAction::Withdraw { .. } => {
            actor_id == request.creator_id
                || actor_id == request.challenger_id
                || actor_id == request.treasury_id
                || request.juror_ids.iter().any(|juror| juror == actor_id)
        }
    };
    if !authorized {
        return Err(GameError::Forbidden(
            "the authenticated actor cannot perform this episode action".into(),
        ));
    }
    Ok(())
}

pub fn validate_registration(
    request: &RegisterEpisode,
    participants: &BTreeMap<String, Address>,
) -> Result<ContractConfig, GameError> {
    for id in [
        &request.episode_id,
        &request.creator_id,
        &request.challenger_id,
        &request.treasury_id,
    ] {
        validate_identifier(id)?;
    }
    if !matches!(request.juror_ids.len(), 3 | 5 | 7) {
        return Err(GameError::Validation(
            "jury must contain exactly 3, 5, or 7 distinct jurors".into(),
        ));
    }
    let address = |actor: &str| -> Result<Address, GameError> {
        participants
            .get(actor)
            .copied()
            .filter(|address| *address != Address::ZERO)
            .ok_or_else(|| {
                GameError::Validation(format!(
                    "participant {actor} has no configured nonzero signer"
                ))
            })
    };
    let creator = address(&request.creator_id)?;
    let challenger = address(&request.challenger_id)?;
    let treasury = address(&request.treasury_id)?;
    let mut seen = BTreeSet::new();
    for participant in [creator, challenger, treasury] {
        if !seen.insert(participant) {
            return Err(GameError::Validation(
                "party and treasury addresses must be distinct".into(),
            ));
        }
    }
    let mut jurors = Vec::with_capacity(request.juror_ids.len());
    for actor in &request.juror_ids {
        validate_identifier(actor)?;
        let juror = address(actor)?;
        if !seen.insert(juror) {
            return Err(GameError::Validation(
                "juror addresses must be unique and separate from parties and treasury".into(),
            ));
        }
        jurors.push(juror);
    }
    let parameters = &request.parameters;
    if parameters.beta_wei.is_empty()
        || !parameters
            .beta_wei
            .bytes()
            .all(|value| value.is_ascii_digit())
        || parameters.beta_wei.starts_with('0')
    {
        return Err(GameError::Validation(
            "beta_wei must be a positive canonical decimal integer string".into(),
        ));
    }
    let beta: U256 = parameters
        .beta_wei
        .parse()
        .map_err(|_| GameError::Validation("beta_wei exceeds uint256".into()))?;
    if !(1..10000).contains(&parameters.gamma_bps)
        || [
            parameters.winner_bps,
            parameters.juror_bps,
            parameters.protocol_bps,
        ]
        .iter()
        .any(|share| *share > 10000)
        || u32::from(parameters.winner_bps)
            + u32::from(parameters.juror_bps)
            + u32::from(parameters.protocol_bps)
            != 10000
    {
        return Err(GameError::Validation(
            "gamma_bps must be 1–9999 and payout shares must sum to 10000".into(),
        ));
    }
    let overflow =
        || GameError::Validation("bond parameters exceed safe uint256 accounting bounds".into());
    let juror_bond = beta
        .checked_mul(U256::from(parameters.gamma_bps))
        .ok_or_else(overflow)?
        / U256::from(10000);
    if juror_bond.is_zero() {
        return Err(GameError::Validation(
            "derived juror bond must be at least one base unit".into(),
        ));
    }
    beta.checked_mul(U256::from(10000)).ok_or_else(overflow)?;
    beta.checked_mul(U256::from(2))
        .and_then(|parties| {
            juror_bond
                .checked_mul(U256::from(request.juror_ids.len()))
                .and_then(|jury| parties.checked_add(jury))
        })
        .ok_or_else(overflow)?;
    for duration in [
        parameters.posting_duration_secs,
        parameters.challenge_duration_secs,
        parameters.commit_duration_secs,
        parameters.reveal_duration_secs,
    ] {
        if duration == 0 || duration > 9_007_199_254_740_991 {
            return Err(GameError::Validation(
                "phase durations must be positive safe JSON integers".into(),
            ));
        }
    }
    Ok(ContractConfig {
        creator,
        challenger,
        jurors,
        treasury,
        configuration_hash: configuration_hash(request)?,
        beta,
        gamma_bps: parameters.gamma_bps,
        winner_bps: parameters.winner_bps,
        juror_bps: parameters.juror_bps,
        protocol_bps: parameters.protocol_bps,
        posting_duration: parameters.posting_duration_secs,
        challenge_duration: parameters.challenge_duration_secs,
        commit_duration: parameters.commit_duration_secs,
        reveal_duration: parameters.reveal_duration_secs,
    })
}
