use std::collections::BTreeMap;

use alloy::primitives::{Address, U256, keccak256};
use veracity_game_service::game::{
    ProtocolParameters, RegisterEpisode, artifact_hash, configuration_hash, validate_registration,
};

fn registration() -> RegisterEpisode {
    RegisterEpisode {
        episode_id: "trial-1".into(),
        experiment_id: String::new(),
        scenario_id: String::new(),
        creator_id: "creator".into(),
        challenger_id: "challenger".into(),
        juror_ids: vec!["juror-1".into(), "juror-2".into(), "juror-3".into()],
        treasury_id: "treasury".into(),
        parameters: ProtocolParameters {
            beta_wei: "10000".into(),
            gamma_bps: 1000,
            winner_bps: 6000,
            juror_bps: 3000,
            protocol_bps: 1000,
            posting_duration_secs: 30,
            challenge_duration_secs: 30,
            commit_duration_secs: 30,
            reveal_duration_secs: 30,
        },
        provenance: BTreeMap::new(),
    }
}

fn roster() -> BTreeMap<String, Address> {
    [
        "creator",
        "challenger",
        "juror-1",
        "juror-2",
        "juror-3",
        "treasury",
    ]
    .into_iter()
    .enumerate()
    .map(|(index, id)| {
        (
            id.to_owned(),
            Address::from_word(U256::from(index + 1).into()),
        )
    })
    .collect()
}

#[test]
fn validates_symmetric_integer_bonds_and_frozen_roster() {
    let config = validate_registration(&registration(), &roster()).unwrap();
    assert_eq!(config.beta, U256::from(10000));
    assert_eq!(config.jurors.len(), 3);
    assert_eq!(config.gamma_bps, 1000);
}

#[test]
fn game_registration_does_not_require_experiment_or_scenario_metadata() {
    let mut body = serde_json::to_value(registration()).unwrap();
    for field in ["experiment_id", "scenario_id", "provenance"] {
        body.as_object_mut().unwrap().remove(field);
    }
    let request: RegisterEpisode = serde_json::from_value(body).unwrap();
    let config = validate_registration(&request, &roster()).unwrap();
    assert_eq!(config.beta, U256::from(10000));
    assert_eq!(config.jurors.len(), 3);
}

#[test]
fn optional_legacy_tags_preserve_existing_stored_configuration_hashes() {
    let mut legacy = serde_json::to_value(registration()).unwrap();
    legacy["experiment_id"] = serde_json::json!("existing-experiment");
    legacy["scenario_id"] = serde_json::json!("existing-scenario");
    legacy["provenance"] = serde_json::json!({"dataset_version":"legacy-v1"});
    let original_hash = keccak256(serde_jcs::to_vec(&legacy).unwrap());
    let decoded: RegisterEpisode = serde_json::from_value(legacy.clone()).unwrap();
    assert_eq!(serde_json::to_value(&decoded).unwrap(), legacy);
    assert_eq!(configuration_hash(&decoded).unwrap(), original_hash);
}

#[test]
fn rejects_zero_fractional_noncanonical_or_overflowing_money() {
    for amount in [
        "0",
        "0.5",
        "1e18",
        "-1",
        " 1",
        "01",
        "0x10",
        "115792089237316195423570985008687907853269984665640564039457584007913129639935",
    ] {
        let mut request = registration();
        request.parameters.beta_wei = amount.into();
        assert!(
            validate_registration(&request, &roster()).is_err(),
            "accepted {amount}"
        );
    }
}

#[test]
fn rejects_conflicting_addresses_even_with_different_actor_ids() {
    let mut addresses = roster();
    addresses.insert("challenger".into(), addresses["creator"]);
    assert!(validate_registration(&registration(), &addresses).is_err());
}

#[test]
fn rejects_invalid_threshold_rosters_and_parameters() {
    let mut request = registration();
    request.juror_ids.pop();
    assert!(validate_registration(&request, &roster()).is_err());
    let mut request = registration();
    request.juror_ids[1] = request.juror_ids[0].clone();
    assert!(validate_registration(&request, &roster()).is_err());
    let mut request = registration();
    request.parameters.gamma_bps = 0;
    assert!(validate_registration(&request, &roster()).is_err());
    let mut request = registration();
    request.parameters.protocol_bps = 1001;
    assert!(validate_registration(&request, &roster()).is_err());
    let mut request = registration();
    request.parameters.commit_duration_secs = 0;
    assert!(validate_registration(&request, &roster()).is_err());
    let mut request = registration();
    request.parameters.beta_wei = "1".into();
    assert!(validate_registration(&request, &roster()).is_err());
}

#[test]
fn artifact_hash_anchors_exact_utf8_without_trimming_or_normalization() {
    assert_eq!(artifact_hash("claim\n").unwrap(), keccak256("claim\n"));
    assert_ne!(
        artifact_hash("claim\n").unwrap(),
        artifact_hash("claim").unwrap()
    );
    assert_ne!(
        artifact_hash("é").unwrap(),
        artifact_hash("e\u{301}").unwrap()
    );
    assert!(artifact_hash("claim\r\n").is_err());
}

#[test]
fn canonical_configuration_hash_is_stable_across_metadata_insertion_order() {
    let mut first = registration();
    first.provenance.insert("z".into(), "last".into());
    first.provenance.insert("a".into(), "first".into());
    let mut second = registration();
    second.provenance.insert("a".into(), "first".into());
    second.provenance.insert("z".into(), "last".into());
    assert_eq!(
        configuration_hash(&first).unwrap(),
        configuration_hash(&second).unwrap()
    );
    second.parameters.gamma_bps += 1;
    assert_ne!(
        configuration_hash(&first).unwrap(),
        configuration_hash(&second).unwrap()
    );
}

#[test]
fn money_wire_schema_rejects_json_numbers_and_unknown_actor_fields() {
    let mut json = serde_json::to_value(registration()).unwrap();
    json["parameters"]["beta_wei"] = serde_json::json!(10000.0);
    assert!(serde_json::from_value::<RegisterEpisode>(json).is_err());
    let mut json = serde_json::to_value(registration()).unwrap();
    json["private_key"] = serde_json::json!("forbidden");
    assert!(serde_json::from_value::<RegisterEpisode>(json).is_err());
}

#[test]
fn service_transaction_budget_is_retryable_infrastructure_policy_not_contract_rejection() {
    let error = veracity_game_service::game::GameError::from(
        veracity_game_service::chain::ChainError::BudgetExceeded,
    );
    assert!(
        matches!(
            error,
            veracity_game_service::game::GameError::Unavailable(_)
        ),
        "budget policy must preserve retryable intent rather than report contract rejection"
    );
}
