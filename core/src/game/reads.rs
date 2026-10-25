use alloy::primitives::{Address, B256, U256, keccak256};
use std::collections::BTreeMap;

use super::{
    BalancesView, DeploymentView, EpisodeView, GameError, GameInner, JurorView, RegisterEpisode,
    SettlementView, Verdict,
};
use crate::chain::{DeploymentIdentity, EpisodeSnapshot, State};

pub(super) fn deployment_view(identity: &DeploymentIdentity) -> DeploymentView {
    DeploymentView {
        chain_id: identity.chain_id,
        contract_address: identity.contract_address.to_string(),
        code_hash: identity.code_hash.to_string(),
        abi_version: identity.abi_version,
        confirmation_depth: identity.confirmation_depth,
        finality_policy: "confirmation_depth".into(),
    }
}

pub(super) fn state_name(state: State) -> &'static str {
    match state {
        State::Unknown => "UNKNOWN",
        State::Registered => "REGISTERED",
        State::Open => "OPEN",
        State::Commit => "COMMIT",
        State::Reveal => "REVEAL",
        State::SettledCreator => "SETTLED_CREATOR",
        State::SettledChallenger => "SETTLED_CHALLENGER",
        State::Aborted => "ABORTED",
        State::ExpiredUnchallenged => "EXPIRED_UNCHALLENGED",
        State::ExpiredUnfunded => "EXPIRED_UNFUNDED",
    }
}

pub(super) fn revealed_verdict(value: u8) -> Result<Verdict, GameError> {
    match value {
        0 => Ok(Verdict::CreatorSupported),
        1 => Ok(Verdict::ChallengerSupported),
        _ => Err(GameError::Internal(
            "contract returned an invalid revealed verdict".into(),
        )),
    }
}

fn nonzero_hash(hash: B256) -> Option<String> {
    (hash != B256::ZERO).then(|| hash.to_string())
}

impl GameInner {
    pub(super) fn episode_configuration(
        &self,
        episode_id: &str,
    ) -> Result<RegisterEpisode, GameError> {
        let stored = self
            .store
            .get_episode(episode_id)?
            .ok_or_else(|| GameError::NotFound("episode".into()))?;
        serde_json::from_str(&stored.config_json)
            .map_err(|_| GameError::Internal("stored configuration is invalid".into()))
    }

    /// Actor IDs are meaningful only when every immutable local rule matches
    /// the authoritative contract configuration they claim to describe.
    pub(super) async fn verified_episode(
        &self,
        episode_id: &str,
    ) -> Result<(RegisterEpisode, EpisodeSnapshot), GameError> {
        let configuration = self.episode_configuration(episode_id)?;
        let snapshot = self.chain.episode(keccak256(episode_id.as_bytes())).await?;
        let expected = super::validate_registration(&configuration, &self.chain.participants())
            .map_err(|_| {
                GameError::Conflict(
                    "local episode configuration no longer matches the configured participants"
                        .into(),
                )
            })?;
        if snapshot.config != expected {
            return Err(GameError::Conflict(
                "local episode configuration does not match the authoritative contract".into(),
            ));
        }
        Ok((configuration, snapshot))
    }

    pub(super) async fn read_episode(&self, episode_id: &str) -> Result<EpisodeView, GameError> {
        let (configuration, snapshot) = self.verified_episode(episode_id).await?;
        let onchain_id = keccak256(episode_id.as_bytes());
        let mut jurors = Vec::with_capacity(configuration.juror_ids.len());
        for actor_id in &configuration.juror_ids {
            let vote = self
                .chain
                .juror(onchain_id, self.chain.address(actor_id)?)
                .await?;
            jurors.push(JurorView {
                actor_id: actor_id.clone(),
                commitment: nonzero_hash(vote.commitment),
                revealed: vote.revealed,
                verdict: if vote.revealed {
                    Some(revealed_verdict(vote.verdict)?)
                } else {
                    None
                },
                assessment_hash: if vote.revealed {
                    nonzero_hash(vote.assessment_hash)
                } else {
                    None
                },
            });
        }
        let content_hash = nonzero_hash(snapshot.content_hash);
        let evidence_hash = nonzero_hash(snapshot.evidence_hash);
        let content = content_hash
            .as_ref()
            .map(|hash| self.store.artifact(hash))
            .transpose()?
            .flatten();
        let evidence = evidence_hash
            .as_ref()
            .map(|hash| self.store.artifact(hash))
            .transpose()?
            .flatten();
        Ok(EpisodeView {
            episode_id: episode_id.into(),
            onchain_episode_id: onchain_id.to_string(),
            configuration_hash: snapshot.config.configuration_hash.to_string(),
            phase: state_name(snapshot.state).into(),
            posting_deadline: snapshot.posting_deadline,
            challenge_deadline: snapshot.challenge_deadline,
            commit_deadline: snapshot.commit_deadline,
            reveal_deadline: snapshot.reveal_deadline,
            content_hash,
            evidence_hash,
            content,
            evidence,
            jurors,
            creator_votes: snapshot.creator_votes,
            challenger_votes: snapshot.challenger_votes,
            required_votes: configuration.juror_ids.len() / 2 + 1,
            juror_bond_wei: snapshot.juror_bond.to_string(),
            locked_liability_wei: snapshot.locked_liability.to_string(),
            total_deposited_wei: snapshot.total_deposited.to_string(),
            total_credited_wei: snapshot.total_credited.to_string(),
            configuration,
            deployment: deployment_view(self.chain.identity()),
        })
    }

    pub(super) async fn read_settlement(
        &self,
        episode_id: &str,
    ) -> Result<SettlementView, GameError> {
        let (configuration, episode) = self.verified_episode(episode_id).await?;
        let onchain_id = keccak256(episode_id.as_bytes());
        if !matches!(
            episode.state,
            State::SettledCreator
                | State::SettledChallenger
                | State::Aborted
                | State::ExpiredUnchallenged
                | State::ExpiredUnfunded
        ) {
            return Err(GameError::Conflict(
                "episode has no terminal settlement yet".into(),
            ));
        }
        let settlement = self.chain.settlement(onchain_id).await?;
        let mut final_votes = BTreeMap::new();
        let mut juror_payouts = BTreeMap::new();
        let mut forfeited_bonds = BTreeMap::new();
        for actor_id in &configuration.juror_ids {
            let address = self.chain.address(actor_id)?;
            let vote = self.chain.juror(onchain_id, address).await?;
            if vote.revealed {
                final_votes.insert(actor_id.clone(), revealed_verdict(vote.verdict)?);
                juror_payouts.insert(
                    actor_id.clone(),
                    self.chain
                        .entitlement(onchain_id, address)
                        .await?
                        .to_string(),
                );
            } else if vote.commitment != B256::ZERO {
                forfeited_bonds.insert(actor_id.clone(), episode.juror_bond.to_string());
            }
        }
        let winner_id = if settlement.winner == Address::ZERO {
            None
        } else {
            [
                configuration.creator_id.clone(),
                configuration.challenger_id.clone(),
            ]
            .into_iter()
            .find(|actor_id| self.chain.address(actor_id).ok() == Some(settlement.winner))
        };
        let mut refunds = BTreeMap::new();
        if matches!(episode.state, State::Aborted | State::ExpiredUnchallenged) {
            for actor_id in [&configuration.creator_id, &configuration.challenger_id] {
                let entitlement = self
                    .chain
                    .entitlement(onchain_id, self.chain.address(actor_id)?)
                    .await?;
                if entitlement > U256::ZERO {
                    refunds.insert(actor_id.clone(), entitlement.to_string());
                }
            }
        }
        Ok(SettlementView {
            episode_id: episode_id.into(),
            outcome: state_name(settlement.outcome).into(),
            final_votes,
            winner_id,
            winner_payout: settlement.winner_payout.to_string(),
            juror_payouts,
            protocol_fee: settlement.protocol_fee.to_string(),
            forfeited_bonds,
            refunds,
            total_deposited: episode.total_deposited.to_string(),
            total_credited: episode.total_credited.to_string(),
            deployment: deployment_view(self.chain.identity()),
        })
    }

    pub(super) async fn read_balances(&self, episode_id: &str) -> Result<BalancesView, GameError> {
        let (configuration, _) = self.verified_episode(episode_id).await?;
        let onchain_id = keccak256(episode_id.as_bytes());
        let mut entitlements = BTreeMap::new();
        let mut withdrawal_credits = BTreeMap::new();
        for actor_id in [
            &configuration.creator_id,
            &configuration.challenger_id,
            &configuration.treasury_id,
        ]
        .into_iter()
        .chain(configuration.juror_ids.iter())
        {
            let address = self.chain.address(actor_id)?;
            entitlements.insert(
                actor_id.clone(),
                self.chain
                    .entitlement(onchain_id, address)
                    .await?
                    .to_string(),
            );
            withdrawal_credits.insert(
                actor_id.clone(),
                self.chain.credits(address).await?.to_string(),
            );
        }
        Ok(BalancesView {
            episode_id: episode_id.into(),
            entitlements,
            withdrawal_credits,
        })
    }
}
