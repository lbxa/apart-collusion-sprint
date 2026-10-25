use std::{collections::BTreeMap, io, path::PathBuf};

use alloy::{node_bindings::Anvil, signers::local::PrivateKeySigner};
use clap::Parser;
use veracity_game_service::{
    api::{AuthConfig, router},
    chain::{ChainClient, ChainConfig},
    config::{Cli, DeploymentConfig},
    game::GameService,
    store::Store,
};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();
    cli.validate().map_err(io::Error::other)?;
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .with_writer(std::io::stderr)
        .init();

    // This handle owns the local node process for the listener's lifetime.
    let mut local_node = None;
    let (chain, auth, operator_id, database) = if cli.local {
        let executable = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../.tools/bin/anvil");
        let node = Anvil::at(executable)
            .chain_id(31337)
            .try_spawn()
            .map_err(|_| {
                io::Error::other("cannot start pinned Anvil; run bash scripts/install-foundry.sh")
            })?;
        let actor_ids = [
            "creator",
            "challenger",
            "juror-1",
            "juror-2",
            "juror-3",
            "juror-4",
            "juror-5",
            "juror-6",
            "juror-7",
            "treasury",
        ];
        let signers: BTreeMap<String, PrivateKeySigner> = actor_ids
            .iter()
            .zip(node.keys())
            .map(|(actor, key)| ((*actor).to_owned(), key.clone().into()))
            .collect();
        let deployment =
            ChainClient::deploy(&node.endpoint(), signers["treasury"].clone(), &cli.artifact)
                .await?;
        let chain = ChainClient::connect(
            ChainConfig {
                rpc_url: node.endpoint(),
                expected_chain_id: 31337,
                contract_address: deployment.contract_address,
                expected_code_hash: deployment.code_hash,
                confirmation_depth: 1,
                max_gas_limit: 3_000_000,
                max_fee_per_gas: 100_000_000_000,
            },
            signers,
        )
        .await?;
        let auth = AuthConfig {
            operator_token: "dev-operator".into(),
            participant_tokens: actor_ids
                .into_iter()
                .map(|actor| (actor.to_owned(), format!("dev-{actor}")))
                .collect(),
        };
        let database = cli.database.clone().unwrap_or_else(|| {
            PathBuf::from(".harness/runs")
                .join(uuid::Uuid::new_v4().to_string())
                .join("game.sqlite")
        });
        tracing::info!(event = "game.local.started", rpc_endpoint = %node.endpoint(), "isolated local chain; development credentials only");
        local_node = Some(node);
        (chain, auth, "treasury".to_owned(), database)
    } else {
        let configuration_path = cli
            .config
            .as_ref()
            .ok_or_else(|| io::Error::other("deployment configuration is required"))?;
        let configuration: DeploymentConfig =
            toml::from_str(&std::fs::read_to_string(configuration_path)?)?;
        configuration.validate().map_err(io::Error::other)?;
        let mut signers = BTreeMap::new();
        let mut participant_tokens = BTreeMap::new();
        for participant in &configuration.participants {
            let secret = read_secret(&participant.private_key_env)?;
            let signer: PrivateKeySigner = secret.parse().map_err(|_| {
                io::Error::other(format!("invalid signer in {}", participant.private_key_env))
            })?;
            signers.insert(participant.id.clone(), signer);
            participant_tokens.insert(participant.id.clone(), read_secret(&participant.token_env)?);
        }
        let auth = AuthConfig {
            operator_token: read_secret(&configuration.operator_token_env)?,
            participant_tokens,
        };
        let chain = ChainClient::connect(
            ChainConfig {
                rpc_url: configuration.rpc_url,
                expected_chain_id: configuration.expected_chain_id,
                contract_address: configuration.contract_address.parse()?,
                expected_code_hash: configuration.expected_code_hash.parse()?,
                confirmation_depth: configuration.confirmation_depth,
                max_gas_limit: configuration.max_gas_limit,
                max_fee_per_gas: configuration.max_fee_per_gas_wei.parse()?,
            },
            signers,
        )
        .await?;
        (
            chain,
            auth,
            configuration.operator_id,
            cli.database
                .clone()
                .unwrap_or_else(|| PathBuf::from(".harness/game.sqlite")),
        )
    };

    auth.validate()?;
    if let Some(parent) = database
        .parent()
        .filter(|parent| !parent.as_os_str().is_empty())
    {
        std::fs::create_dir_all(parent)?;
    }
    let service = GameService::new(chain, Store::open(&database)?, operator_id)?;
    service.recover_pending().await?;
    let identity = service.identity().await;
    let listener = tokio::net::TcpListener::bind(cli.bind).await?;
    // Local orchestration discovers exact listeners without scraping log text.
    // Only this mode owns an Anvil node whose clock a harness may control.
    if let Some(node) = local_node.as_ref() {
        println!(
            "{}",
            serde_json::json!({
                "api_url": format!("http://{}", listener.local_addr()?),
                "rpc_url": node.endpoint(),
                "deployment": identity,
            })
        );
    }
    tracing::info!(event = "game.api.listening", address = %listener.local_addr()?, chain_id = identity.chain_id,
        contract_address = %identity.contract_address, database = %database.display(), "Veracity API v1 ready");
    axum::serve(listener, router(service, auth))
        .with_graceful_shutdown(async {
            let _ = tokio::signal::ctrl_c().await;
        })
        .await?;
    drop(local_node);
    Ok(())
}

fn read_secret(reference: &str) -> Result<String, io::Error> {
    std::env::var(reference)
        .map_err(|_| io::Error::other(format!("missing secret environment variable {reference}")))
}
