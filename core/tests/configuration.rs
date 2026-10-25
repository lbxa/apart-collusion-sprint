use clap::Parser;
use veracity_game_service::config::{Cli, DeploymentConfig};

#[test]
fn executable_explains_the_explicit_startup_modes() {
    let output = std::process::Command::new(env!("CARGO_BIN_EXE_veracity-game-service"))
        .arg("--help")
        .output()
        .unwrap();
    assert!(output.status.success());
    let help = String::from_utf8(output.stdout).unwrap();
    assert!(help.contains("--local") && help.contains("--config"));
}

#[test]
fn startup_requires_an_explicit_local_or_deployment_choice() {
    assert!(Cli::try_parse_from(["veracity-game-service"]).is_err());
    assert!(
        Cli::try_parse_from([
            "veracity-game-service",
            "--local",
            "--config",
            "network.toml"
        ])
        .is_err()
    );
    let local = Cli::try_parse_from(["veracity-game-service", "--local"]).unwrap();
    assert!(local.local);
    assert!(local.bind.ip().is_loopback());
    local.validate().unwrap();
}

#[test]
fn local_credentials_cannot_be_exposed_on_a_public_interface() {
    let local = Cli::try_parse_from(["veracity-game-service", "--local", "--bind", "0.0.0.0:8080"])
        .unwrap();
    assert!(local.validate().is_err());
}

#[test]
fn a_fresh_local_chain_cannot_overwrite_an_existing_experiment_database() {
    let directory = tempfile::tempdir().unwrap();
    let database = directory.path().join("game.sqlite");
    let mut local = Cli::try_parse_from(["veracity-game-service", "--local"]).unwrap();
    local.database = Some(database.clone());
    local.validate().unwrap();
    let _store = veracity_game_service::store::Store::open(&database).unwrap();
    assert!(local.validate().is_err());
}

#[test]
fn deployment_configuration_rejects_mainnet_and_empty_identity() {
    let configuration: DeploymentConfig =
        toml::from_str(include_str!("../../configs/server.example.toml")).unwrap();
    configuration.validate().unwrap();
    for chain_id in [1, 137, 0] {
        let mut wrong_chain = configuration.clone();
        wrong_chain.expected_chain_id = chain_id;
        assert!(wrong_chain.validate().is_err());
    }
    let mut wrong_hash = configuration.clone();
    wrong_hash.expected_code_hash = "0x00".into();
    assert!(wrong_hash.validate().is_err());
    let mut wrong_address = configuration.clone();
    wrong_address.contract_address = format!("0x{}", "00".repeat(20));
    assert!(wrong_address.validate().is_err());
    let mut missing_operator = configuration;
    missing_operator.participants.clear();
    assert!(missing_operator.validate().is_err());
}

#[test]
fn deployment_rejects_invalid_rpc_credentials_and_zero_budgets() {
    let configuration: DeploymentConfig =
        toml::from_str(include_str!("../../configs/server.example.toml")).unwrap();
    for endpoint in ["ftp://localhost", "not a URL", "file:///tmp/chain"] {
        let mut invalid = configuration.clone();
        invalid.rpc_url = endpoint.into();
        assert!(invalid.validate().is_err());
    }
    let mut invalid = configuration.clone();
    invalid.confirmation_depth = 0;
    assert!(invalid.validate().is_err());
    let mut invalid = configuration.clone();
    invalid.max_fee_per_gas_wei = "0".into();
    assert!(invalid.validate().is_err());
    let mut invalid = configuration.clone();
    invalid.participants[0].private_key_env = "literal-private-key".into();
    assert!(invalid.validate().is_err());
    let mut invalid = configuration.clone();
    invalid
        .participants
        .push(configuration.participants[0].clone());
    assert!(invalid.validate().is_err());
}

#[test]
fn secrets_are_environment_references_in_toml() {
    let example = include_str!("../../configs/server.example.toml");
    let configuration: DeploymentConfig = toml::from_str(example).unwrap();
    configuration.validate().unwrap();
    assert!(
        configuration
            .participants
            .iter()
            .all(|participant| participant.private_key_env.starts_with("VERACITY_"))
    );
    assert!(format!("{configuration:?}").contains("private_key_env"));
}
