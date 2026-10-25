use std::{collections::BTreeMap, path::PathBuf};

use alloy::{
    network::{EthereumWallet, TransactionBuilder},
    node_bindings::{Anvil, AnvilInstance},
    primitives::{Address, B256, U256},
    providers::{DynProvider, Provider, ProviderBuilder, ext::AnvilApi},
    rpc::types::TransactionRequest,
    signers::local::PrivateKeySigner,
};
use veracity_game_service::chain::{
    ChainAction, ChainClient, ChainConfig, ChainError, ContractConfig, DeploymentIdentity,
    PreparedTransaction, State,
};

struct Fixture {
    _anvil: AnvilInstance,
    client: ChainClient,
    rpc: DynProvider,
    config: ChainConfig,
    signers: BTreeMap<String, PrivateKeySigner>,
}

impl Fixture {
    async fn new() -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .parent()
            .unwrap()
            .to_path_buf();
        let anvil = Anvil::new()
            .path(root.join(".tools/bin/anvil"))
            .chain_id(31337)
            .try_spawn()
            .expect("install the pinned Anvil with scripts/install-foundry.sh");
        let signers = anvil
            .keys()
            .iter()
            .enumerate()
            .map(|(index, key)| {
                (
                    format!("actor-{index}"),
                    PrivateKeySigner::from(key.clone()),
                )
            })
            .collect::<BTreeMap<_, _>>();
        let identity = ChainClient::deploy(
            &anvil.endpoint(),
            signers["actor-9"].clone(),
            &root.join("contracts/artifacts/Veracity.json"),
        )
        .await
        .unwrap();
        let config = config(&anvil.endpoint(), &identity);
        let client = ChainClient::connect(config.clone(), signers.clone())
            .await
            .unwrap();
        let rpc = ProviderBuilder::new()
            .connect_http(anvil.endpoint_url())
            .erased();
        Self {
            _anvil: anvil,
            client,
            rpc,
            config,
            signers,
        }
    }

    fn episode_config(&self) -> ContractConfig {
        ContractConfig {
            creator: self.client.address("actor-0").unwrap(),
            challenger: self.client.address("actor-1").unwrap(),
            jurors: (2..5)
                .map(|i| self.client.address(&format!("actor-{i}")).unwrap())
                .collect(),
            treasury: self.client.address("actor-9").unwrap(),
            configuration_hash: B256::repeat_byte(0xaa),
            beta: U256::from(1000),
            gamma_bps: 1000,
            winner_bps: 6000,
            juror_bps: 3000,
            protocol_bps: 1000,
            posting_duration: 3600,
            challenge_duration: 3600,
            commit_duration: 3600,
            reveal_duration: 3600,
        }
    }

    async fn register(&mut self, id: B256) {
        let config = self.episode_config();
        let prepared = self
            .client
            .prepare(
                "actor-9",
                ChainAction::Register {
                    episode_id: id,
                    config,
                },
            )
            .await
            .unwrap();
        self.client.broadcast(&prepared).await.unwrap();
        included(&self.client, &prepared).await;
    }
}

fn config(url: &str, identity: &DeploymentIdentity) -> ChainConfig {
    ChainConfig {
        rpc_url: url.into(),
        expected_chain_id: identity.chain_id,
        contract_address: identity.contract_address,
        expected_code_hash: identity.code_hash,
        confirmation_depth: 1,
        max_gas_limit: 10_000_000,
        max_fee_per_gas: 100_000_000_000,
    }
}

async fn included(client: &ChainClient, prepared: &PreparedTransaction) {
    for _ in 0..100 {
        if let Some(receipt) = client.receipt(prepared.tx_hash).await.unwrap() {
            assert!(receipt.success);
            return;
        }
        tokio::time::sleep(std::time::Duration::from_millis(10)).await;
    }
    panic!("local transaction was not included");
}

#[tokio::test]
async fn preparation_is_durable_before_broadcast_and_retry_reuses_the_same_transaction() {
    let mut fixture = Fixture::new().await;
    let sender = fixture.client.address("actor-9").unwrap();
    let before = fixture.client.nonce(sender).await.unwrap();
    let episode_id = B256::repeat_byte(1);
    let config = fixture.episode_config();
    let prepared = fixture
        .client
        .prepare(
            "actor-9",
            ChainAction::Register {
                episode_id,
                config: config.clone(),
            },
        )
        .await
        .unwrap();
    assert_eq!(prepared.nonce, before);
    assert_eq!(fixture.client.nonce(sender).await.unwrap(), before);
    assert!(
        fixture
            .client
            .receipt(prepared.tx_hash)
            .await
            .unwrap()
            .is_none()
    );
    assert!(matches!(
        fixture
            .client
            .prepare(
                "actor-9",
                ChainAction::Register {
                    episode_id: B256::repeat_byte(2),
                    config
                }
            )
            .await,
        Err(ChainError::OutstandingTransaction)
    ));

    let persisted = serde_json::to_vec(&prepared).unwrap();
    let restored: PreparedTransaction = serde_json::from_slice(&persisted).unwrap();
    assert_eq!(
        fixture.client.broadcast(&restored).await.unwrap(),
        prepared.tx_hash
    );
    included(&fixture.client, &restored).await;
    assert_eq!(
        fixture.client.broadcast(&restored).await.unwrap(),
        prepared.tx_hash
    );
    assert_eq!(fixture.client.nonce(sender).await.unwrap(), before + 1);
    let episode = fixture.client.episode(episode_id).await.unwrap();
    assert_eq!(episode.state, State::Registered);
    let receipt = fixture
        .client
        .receipt(prepared.tx_hash)
        .await
        .unwrap()
        .unwrap();
    assert!(receipt.confirmed);
    assert!(receipt.logs.iter().all(|log| log.chain_id == 31337
        && log.transaction_hash == prepared.tx_hash
        && log.block_hash == receipt.block_hash));
    assert!(!receipt.logs.is_empty());
}

#[tokio::test]
async fn startup_checks_code_chain_and_confirmation_policy() {
    let fixture = Fixture::new().await;
    let mut wrong = fixture.config.clone();
    wrong.expected_code_hash = B256::ZERO;
    assert!(matches!(
        ChainClient::connect(wrong, fixture.signers.clone()).await,
        Err(ChainError::IdentityMismatch)
    ));
    let mut wrong = fixture.config.clone();
    wrong.expected_chain_id = 80002;
    assert!(matches!(
        ChainClient::connect(wrong, fixture.signers.clone()).await,
        Err(ChainError::IdentityMismatch)
    ));
    let mut wrong = fixture.config.clone();
    wrong.confirmation_depth = 0;
    assert!(matches!(
        ChainClient::connect(wrong, fixture.signers.clone()).await,
        Err(ChainError::Configuration(_))
    ));
    let mut wrong = fixture.config.clone();
    wrong.contract_address = Address::ZERO;
    assert!(matches!(
        ChainClient::connect(wrong, fixture.signers).await,
        Err(ChainError::IdentityMismatch)
    ));
}

#[tokio::test]
async fn startup_pins_the_authoritative_operator_address() {
    let fixture = Fixture::new().await;
    assert_eq!(
        fixture.client.operator_address(),
        fixture.client.address("actor-9").unwrap()
    );
}

#[tokio::test]
async fn refuses_a_party_action_when_the_wallet_cannot_cover_its_bond() {
    let mut fixture = Fixture::new().await;
    let id = B256::repeat_byte(3);
    fixture.register(id).await;
    let creator = fixture.client.address("actor-0").unwrap();
    fixture
        .rpc
        .anvil_set_balance(creator, U256::ZERO)
        .await
        .unwrap();
    let result = fixture
        .client
        .prepare(
            "actor-0",
            ChainAction::PostClaim {
                episode_id: id,
                content_hash: B256::repeat_byte(4),
            },
        )
        .await;
    assert!(matches!(result, Err(ChainError::InsufficientFunds)));
}

#[tokio::test]
async fn gas_budget_and_contract_rejections_are_distinct() {
    let mut fixture = Fixture::new().await;
    let mut limited = fixture.config.clone();
    limited.max_gas_limit = 1;
    let mut limited = ChainClient::connect(limited, fixture.signers.clone())
        .await
        .unwrap();
    assert!(matches!(
        limited
            .prepare(
                "actor-9",
                ChainAction::Register {
                    episode_id: B256::repeat_byte(5),
                    config: fixture.episode_config()
                }
            )
            .await,
        Err(ChainError::BudgetExceeded)
    ));
    let id = B256::repeat_byte(6);
    fixture.register(id).await;
    assert!(matches!(
        fixture
            .client
            .prepare(
                "actor-1",
                ChainAction::Challenge {
                    episode_id: id,
                    evidence_hash: B256::repeat_byte(7)
                }
            )
            .await,
        Err(ChainError::Rejected(_))
    ));
}

#[tokio::test]
async fn removed_receipts_are_not_reported_as_confirmed_after_a_reorganisation() {
    let mut fixture = Fixture::new().await;
    let snapshot: U256 = fixture
        .rpc
        .raw_request("evm_snapshot".into(), ())
        .await
        .unwrap();
    let prepared = fixture
        .client
        .prepare(
            "actor-9",
            ChainAction::Register {
                episode_id: B256::repeat_byte(8),
                config: fixture.episode_config(),
            },
        )
        .await
        .unwrap();
    fixture.client.broadcast(&prepared).await.unwrap();
    included(&fixture.client, &prepared).await;
    let evidence = fixture
        .client
        .receipt(prepared.tx_hash)
        .await
        .unwrap()
        .unwrap();
    let reverted: bool = fixture
        .rpc
        .raw_request("evm_revert".into(), (snapshot,))
        .await
        .unwrap();
    assert!(reverted);
    assert!(
        fixture
            .client
            .receipt(prepared.tx_hash)
            .await
            .unwrap()
            .is_none()
    );
    assert_ne!(
        fixture
            .client
            .canonical_block_hash(evidence.block_number)
            .await
            .unwrap(),
        Some(evidence.block_hash)
    );
}

#[tokio::test]
async fn registration_events_can_be_replayed_and_deduplicated_by_canonical_identity() {
    let mut fixture = Fixture::new().await;
    fixture.register(B256::repeat_byte(9)).await;
    let head = fixture.client.block_number().await.unwrap();
    let first = fixture.client.logs(0, head).await.unwrap();
    assert!(
        !first.is_empty(),
        "catch-up must return the registration event"
    );
    let second = fixture.client.logs(0, head).await.unwrap();
    assert_eq!(first, second);
    let identities = first
        .iter()
        .chain(second.iter())
        .map(|log| {
            (
                log.chain_id,
                log.contract_address,
                log.block_hash,
                log.transaction_hash,
                log.log_index,
            )
        })
        .collect::<std::collections::HashSet<_>>();
    assert_eq!(identities.len(), first.len());
    assert!(first.iter().all(
        |log| log.contract_address == fixture.config.contract_address && log.block_number <= head
    ));
    assert!(matches!(
        fixture.client.logs(10, 9).await,
        Err(ChainError::Configuration(_))
    ));
    assert!(matches!(
        fixture.client.logs(0, 10_000).await,
        Err(ChainError::Configuration(_))
    ));
}

#[tokio::test]
async fn unknown_transaction_with_consumed_nonce_requires_reconciliation_not_replacement() {
    let mut fixture = Fixture::new().await;
    let prepared = fixture
        .client
        .prepare(
            "actor-9",
            ChainAction::Register {
                episode_id: B256::repeat_byte(10),
                config: fixture.episode_config(),
            },
        )
        .await
        .unwrap();
    let other = ProviderBuilder::new()
        .wallet(EthereumWallet::from(fixture.signers["actor-9"].clone()))
        .connect_http(fixture._anvil.endpoint_url());
    other
        .send_transaction(
            TransactionRequest::default()
                .with_to(fixture.client.address("actor-0").unwrap())
                .with_value(U256::from(1)),
        )
        .await
        .unwrap()
        .get_receipt()
        .await
        .unwrap();
    let nonce = fixture.client.nonce(prepared.sender).await.unwrap();
    assert_eq!(nonce, prepared.nonce + 1);
    assert!(matches!(
        fixture.client.broadcast(&prepared).await,
        Err(ChainError::OutstandingTransaction)
    ));
    assert!(
        fixture
            .client
            .receipt(prepared.tx_hash)
            .await
            .unwrap()
            .is_none()
    );
    assert_eq!(fixture.client.nonce(prepared.sender).await.unwrap(), nonce);
}

#[tokio::test]
async fn abandoned_unbroadcast_transaction_does_not_poison_the_signer() {
    let mut fixture = Fixture::new().await;
    let action = || ChainAction::Register {
        episode_id: B256::repeat_byte(11),
        config: fixture.episode_config(),
    };
    let prepared = fixture.client.prepare("actor-9", action()).await.unwrap();
    fixture.client.abandon_unbroadcast(&prepared);
    let replacement = fixture
        .client
        .prepare(
            "actor-9",
            ChainAction::Register {
                episode_id: B256::repeat_byte(12),
                config: fixture.episode_config(),
            },
        )
        .await;
    assert!(
        replacement.is_ok(),
        "an unbroadcast failed persistence attempt must release its nonce reservation"
    );
    assert_eq!(replacement.unwrap().nonce, prepared.nonce);
    assert!(
        fixture
            .client
            .receipt(prepared.tx_hash)
            .await
            .unwrap()
            .is_none()
    );
}

#[tokio::test]
async fn slow_rpc_is_bounded_by_the_configured_request_timeout() {
    use axum::{Json, Router, routing::post};
    use std::time::Duration;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
    let address = listener.local_addr().unwrap();
    let server = tokio::spawn(async move {
        let app = Router::new().route(
            "/",
            post(|| async {
                std::future::pending::<()>().await;
                Json(serde_json::json!({"jsonrpc":"2.0", "id":0, "result":"0x7a69"}))
            }),
        );
        axum::serve(listener, app).await.unwrap();
    });
    let identity = DeploymentIdentity {
        chain_id: 31337,
        contract_address: Address::repeat_byte(1),
        code_hash: B256::repeat_byte(2),
        abi_version: 1,
        confirmation_depth: 1,
    };
    let result = tokio::time::timeout(
        Duration::from_secs(1),
        ChainClient::connect_with_rpc_timeout(
            config(&format!("http://{address}"), &identity),
            Default::default(),
            Duration::from_millis(100),
        ),
    )
    .await;
    server.abort();
    assert!(
        matches!(result, Ok(Err(ChainError::Unavailable(_)))),
        "a stalled RPC must return Unavailable within the configured bound"
    );
}

#[tokio::test]
async fn transient_errors_have_bounded_retries_but_semantic_errors_never_retry() {
    use axum::{
        Json, Router, extract::State, http::StatusCode, response::IntoResponse, routing::post,
    };
    use std::sync::{
        Arc,
        atomic::{AtomicUsize, Ordering},
    };
    use std::time::Duration;
    #[derive(Clone)]
    struct ResponsePolicy {
        status: StatusCode,
        rpc_code: Option<i64>,
        attempts: Arc<AtomicUsize>,
    }
    #[derive(serde::Deserialize)]
    struct Request {
        id: serde_json::Value,
    }
    async fn rpc(
        State(policy): State<ResponsePolicy>,
        Json(request): Json<Request>,
    ) -> axum::response::Response {
        let attempts = policy.attempts;
        attempts.fetch_add(1, Ordering::SeqCst);
        let body = match policy.rpc_code {
            Some(code) => {
                serde_json::json!({"jsonrpc":"2.0", "id":request.id, "error":{"code":code,"message":"injected failure"}})
            }
            None => serde_json::json!({"error":"injected HTTP failure"}),
        };
        (policy.status, Json(body)).into_response()
    }
    for (name, status, rpc_code, expected_attempts) in [
        ("HTTP429", StatusCode::TOO_MANY_REQUESTS, None, 4),
        ("HTTP503", StatusCode::SERVICE_UNAVAILABLE, None, 4),
        ("RPC429", StatusCode::OK, Some(429), 4),
        ("RPC-32005", StatusCode::OK, Some(-32005), 4),
        ("semantic revert", StatusCode::OK, Some(3), 1),
        ("invalid params", StatusCode::OK, Some(-32602), 1),
    ] {
        let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let attempts = Arc::new(AtomicUsize::new(0));
        let app = Router::new()
            .route("/", post(rpc))
            .with_state(ResponsePolicy {
                status,
                rpc_code,
                attempts: attempts.clone(),
            });
        let server = tokio::spawn(async move { axum::serve(listener, app).await.unwrap() });
        let identity = DeploymentIdentity {
            chain_id: 31337,
            contract_address: Address::repeat_byte(1),
            code_hash: B256::repeat_byte(2),
            abi_version: 1,
            confirmation_depth: 1,
        };
        let result = tokio::time::timeout(
            Duration::from_secs(6),
            ChainClient::connect_with_rpc_timeout(
                config(&format!("http://{address}"), &identity),
                Default::default(),
                Duration::from_millis(100),
            ),
        )
        .await;
        server.abort();
        assert!(
            matches!(result, Ok(Err(ChainError::Unavailable(_)))),
            "{name}"
        );
        assert_eq!(attempts.load(Ordering::SeqCst), expected_attempts, "{name}");
    }
}

#[tokio::test]
async fn only_the_exact_unknown_episode_error_is_classified_as_absence() {
    let mut fixture = Fixture::new().await;
    assert!(matches!(
        fixture.client.episode(B256::repeat_byte(13)).await,
        Err(ChainError::UnknownEpisode)
    ));
    let id = B256::repeat_byte(14);
    fixture.register(id).await;
    assert!(matches!(
        fixture
            .client
            .prepare(
                "actor-1",
                ChainAction::Challenge {
                    episode_id: id,
                    evidence_hash: B256::repeat_byte(15)
                }
            )
            .await,
        Err(ChainError::Rejected(_))
    ));
}
