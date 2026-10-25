#![allow(dead_code)] // Shared fixture methods are used by different integration-test binaries.

use std::{collections::BTreeMap, path::PathBuf};

use alloy::{
    node_bindings::{Anvil, AnvilInstance},
    primitives::U256,
    signers::local::PrivateKeySigner,
};
use axum::{
    Router,
    body::Body,
    http::{Method, Request, StatusCode},
};
use http_body_util::BodyExt;
use serde::{Serialize, de::DeserializeOwned};
use serde_json::{Value, json};
use tempfile::TempDir;
use tower::ServiceExt;
use veracity_game_service::{
    api::{AuthConfig, router},
    chain::{ChainClient, ChainConfig},
    game::{GameService, OperationView, ProtocolParameters, RegisterEpisode},
    store::Store,
};

const ACTORS: [&str; 10] = [
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

/// An actual node, contract, durable SQLite database, and the public HTTP router.
/// Keeping the node handle alive owns its process; dropping this fixture stops it.
pub struct Fixture {
    pub app: Router,
    pub service: GameService,
    pub endpoint: String,
    config: ChainConfig,
    signers: BTreeMap<String, PrivateKeySigner>,
    pub auth: AuthConfig,
    pub database: PathBuf,
    _directory: TempDir,
    _node: AnvilInstance,
}

impl Fixture {
    pub async fn new() -> Self {
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("..");
        let node = Anvil::new()
            .path(root.join(".tools/bin/anvil"))
            .chain_id(31337)
            .try_spawn()
            .expect("install the pinned Foundry tools with bash scripts/install-foundry.sh");
        let endpoint = node.endpoint();
        let signers: BTreeMap<String, PrivateKeySigner> = ACTORS
            .into_iter()
            .zip(node.keys())
            .map(|(id, key)| (id.to_owned(), key.clone().into()))
            .collect();
        let deployment = ChainClient::deploy(
            &endpoint,
            signers["treasury"].clone(),
            &root.join("contracts/artifacts/Veracity.json"),
        )
        .await
        .expect("deploy the actual compiled Veracity contract");
        let config = ChainConfig {
            rpc_url: endpoint.clone(),
            expected_chain_id: 31337,
            contract_address: deployment.contract_address,
            expected_code_hash: deployment.code_hash,
            confirmation_depth: 1,
            max_gas_limit: 3_000_000,
            max_fee_per_gas: 100_000_000_000,
        };
        let auth = AuthConfig {
            operator_token: "test-operator".into(),
            participant_tokens: ACTORS
                .into_iter()
                .map(|id| (id.to_owned(), format!("test-{id}")))
                .collect(),
        };
        let directory = tempfile::tempdir().unwrap();
        let database = directory.path().join("game.sqlite");
        let chain = ChainClient::connect(config.clone(), signers.clone())
            .await
            .unwrap();
        let service =
            GameService::new(chain, Store::open(&database).unwrap(), "treasury".into()).unwrap();
        let app = router(service.clone(), auth.clone());
        Self {
            app,
            service,
            endpoint,
            config,
            signers,
            auth,
            database,
            _directory: directory,
            _node: node,
        }
    }

    pub async fn restart_service(&mut self) {
        let chain = ChainClient::connect(self.config.clone(), self.signers.clone())
            .await
            .unwrap();
        let service = GameService::new(
            chain,
            Store::open(&self.database).unwrap(),
            "treasury".into(),
        )
        .unwrap();
        service.recover_pending().await.unwrap();
        self.app = router(service.clone(), self.auth.clone());
        self.service = service;
    }

    pub async fn set_transaction_budget(&mut self, max_gas_limit: u64, max_fee_per_gas: u128) {
        self.config.max_gas_limit = max_gas_limit;
        self.config.max_fee_per_gas = max_fee_per_gas;
        self.restart_service().await;
    }

    pub async fn rpc(&self, method: &str, params: Value) -> Value {
        let response: Value = reqwest::Client::new()
            .post(&self.endpoint)
            .json(&json!({"jsonrpc":"2.0", "id":1, "method":method, "params":params}))
            .send()
            .await
            .unwrap()
            .json()
            .await
            .unwrap();
        assert!(
            response.get("error").is_none(),
            "local RPC {method}: {response}"
        );
        response
            .get("result")
            .expect("JSON-RPC success result")
            .clone()
    }

    pub async fn advance_to(&self, timestamp: u64) {
        self.rpc("evm_setNextBlockTimestamp", json!([timestamp]))
            .await;
        self.rpc("evm_mine", json!([])).await;
    }

    pub async fn nonce(&self, actor: &str) -> u64 {
        let address = self.signers[actor].address().to_string();
        let quantity = self
            .rpc("eth_getTransactionCount", json!([address, "pending"]))
            .await;
        u64::from_str_radix(quantity.as_str().unwrap().trim_start_matches("0x"), 16).unwrap()
    }

    pub async fn chain_credit(&self, actor: &str) -> U256 {
        let client = self.chain_client().await;
        client.credits(self.signers[actor].address()).await.unwrap()
    }

    pub async fn chain_client(&self) -> ChainClient {
        ChainClient::connect(self.config.clone(), self.signers.clone())
            .await
            .unwrap()
    }

    pub async fn request(
        &self,
        method: Method,
        path: &str,
        actor: Option<&str>,
        key: Option<&str>,
        body: Value,
    ) -> (StatusCode, Value) {
        let mut request = Request::builder()
            .method(method)
            .uri(path)
            .header("Content-Type", "application/json");
        if let Some(actor) = actor {
            let token = if actor == "operator" {
                self.auth.operator_token.clone()
            } else {
                self.auth
                    .participant_tokens
                    .get(actor)
                    .cloned()
                    .unwrap_or_else(|| "unknown-token".into())
            };
            request = request.header("Authorization", format!("Bearer {token}"));
        }
        if let Some(key) = key {
            request = request.header("Idempotency-Key", key);
        }
        let response = self
            .app
            .clone()
            .oneshot(request.body(Body::from(body.to_string())).unwrap())
            .await
            .unwrap();
        let status = response.status();
        let bytes = response.into_body().collect().await.unwrap().to_bytes();
        let value = serde_json::from_slice(&bytes).unwrap_or_else(|_| {
            panic!(
                "{status} {path} did not return JSON: {}",
                String::from_utf8_lossy(&bytes)
            )
        });
        (status, value)
    }

    pub async fn get<T: DeserializeOwned>(&self, path: &str) -> T {
        let (status, body) = self
            .request(Method::GET, path, None, None, Value::Null)
            .await;
        assert_eq!(status, StatusCode::OK, "GET {path}: {body}");
        serde_json::from_value(body).unwrap()
    }

    pub async fn mutate<T: Serialize>(
        &self,
        path: &str,
        actor: &str,
        key: &str,
        request: T,
    ) -> OperationView {
        let (status, body) = self
            .request(
                Method::POST,
                path,
                Some(actor),
                Some(key),
                serde_json::to_value(request).unwrap(),
            )
            .await;
        assert!(
            status == StatusCode::OK
                || status == StatusCode::CREATED
                || status == StatusCode::ACCEPTED,
            "POST {path} as {actor}: {status} {body}"
        );
        let mut operation: OperationView = serde_json::from_value(body).unwrap();
        for _ in 0..20 {
            if matches!(
                operation.status.as_str(),
                "confirmed" | "reverted" | "failed"
            ) {
                break;
            }
            let path = format!("/v1/operations/{}/reconcile", operation.operation_id);
            let (status, body) = self
                .request(
                    Method::POST,
                    &path,
                    Some("operator"),
                    Some(&format!("reconcile-{}", operation.operation_id)),
                    json!({}),
                )
                .await;
            assert!(status.is_success(), "reconcile: {body}");
            operation = serde_json::from_value(body).unwrap();
            tokio::time::sleep(std::time::Duration::from_millis(10)).await;
        }
        assert_eq!(
            operation.status, "confirmed",
            "operation did not confirm: {operation:?}"
        );
        operation
    }

    pub async fn register(&self, id: &str, jury_size: usize, beta: &str) -> OperationView {
        self.mutate(
            "/v1/episodes",
            "operator",
            &format!("register-{id}"),
            registration(id, jury_size, beta),
        )
        .await
    }

    pub async fn open_dispute(&self, id: &str, jury_size: usize, beta: &str) {
        self.register(id, jury_size, beta).await;
        self.mutate(
            &format!("/v1/episodes/{id}/claims"),
            "creator",
            &format!("claim-{id}"),
            json!({"content":"A reproducible claim.\n"}),
        )
        .await;
        self.mutate(
            &format!("/v1/episodes/{id}/challenges"),
            "challenger",
            &format!("challenge-{id}"),
            json!({"evidence":"Counter evidence.\n"}),
        )
        .await;
    }
}

pub fn registration(id: &str, jury_size: usize, beta: &str) -> RegisterEpisode {
    RegisterEpisode {
        episode_id: id.into(),
        experiment_id: String::new(),
        scenario_id: String::new(),
        creator_id: "creator".into(),
        challenger_id: "challenger".into(),
        juror_ids: (1..=jury_size).map(|i| format!("juror-{i}")).collect(),
        treasury_id: "treasury".into(),
        parameters: ProtocolParameters {
            beta_wei: beta.into(),
            gamma_bps: 1000,
            winner_bps: 6000,
            juror_bps: 3000,
            protocol_bps: 1000,
            posting_duration_secs: 1000,
            challenge_duration_secs: 1000,
            commit_duration_secs: 1000,
            reveal_duration_secs: 1000,
        },
        provenance: BTreeMap::new(),
    }
}
