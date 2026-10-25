use alloy::primitives::{Address, B256, b256};
use serde::Deserialize;
use veracity_game_service::chain::{ChainClient, ChainConfig, ChainError, commitment_hash};

#[test]
fn commitment_uses_standard_abi_and_every_domain_field() {
    #[derive(Deserialize)]
    struct Vector {
        chain_id: String,
        contract_address: Address,
        episode_id: B256,
        juror_address: Address,
        verdict: u8,
        assessment_hash: B256,
        salt: B256,
        expected_commitment: B256,
    }
    let fixture: Vector =
        serde_json::from_str(include_str!("../../contracts/fixtures/commitment.json")).unwrap();
    let chain_id = fixture.chain_id.parse().unwrap();
    let contract = fixture.contract_address;
    let episode = fixture.episode_id;
    let juror = fixture.juror_address;
    let assessment = fixture.assessment_hash;
    let salt = fixture.salt;
    let verdict = fixture.verdict;
    let hash = commitment_hash(
        chain_id, contract, episode, juror, verdict, assessment, salt,
    );
    assert_eq!(hash, fixture.expected_commitment);
    for changed in [
        commitment_hash(80002, contract, episode, juror, verdict, assessment, salt),
        commitment_hash(
            chain_id,
            Address::ZERO,
            episode,
            juror,
            verdict,
            assessment,
            salt,
        ),
        commitment_hash(
            chain_id,
            contract,
            B256::ZERO,
            juror,
            verdict,
            assessment,
            salt,
        ),
        commitment_hash(
            chain_id,
            contract,
            episode,
            Address::ZERO,
            verdict,
            assessment,
            salt,
        ),
        commitment_hash(chain_id, contract, episode, juror, 1, assessment, salt),
        commitment_hash(
            chain_id,
            contract,
            episode,
            juror,
            verdict,
            B256::ZERO,
            salt,
        ),
        commitment_hash(
            chain_id,
            contract,
            episode,
            juror,
            verdict,
            assessment,
            B256::ZERO,
        ),
    ] {
        assert_ne!(hash, changed);
    }
}

#[tokio::test]
async fn rejects_mainnet_before_attempting_any_rpc() {
    let config = ChainConfig {
        rpc_url: "http://127.0.0.1:1".into(),
        expected_chain_id: 1,
        contract_address: Address::ZERO,
        expected_code_hash: b256!(
            "0000000000000000000000000000000000000000000000000000000000000001"
        ),
        confirmation_depth: 1,
        max_gas_limit: 1_000_000,
        max_fee_per_gas: 100_000_000_000,
    };
    assert!(matches!(
        ChainClient::connect(config, Default::default()).await,
        Err(ChainError::UnsupportedChain)
    ));
}
