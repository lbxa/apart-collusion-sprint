mod support;

use alloy::primitives::U256;
use axum::http::{Method, StatusCode};
use serde_json::{Value, json};
use support::{Fixture, registration};
use veracity_game_service::game::{
    BalancesView, EpisodeView, GameAction, OperationView, SettlementView, Verdict,
};
use veracity_game_service::{chain::LogEvidence, store::ChainEventRecord};
use veracity_game_service::{game::GameService, store::Store};

#[tokio::test]
async fn rust_game_registration_is_confirmed_by_the_authoritative_local_contract() {
    let fixture = Fixture::new().await;
    let operation = fixture
        .service
        .register(registration("rust-service", 3, "100"), "rust-service")
        .await
        .unwrap();
    assert_eq!(operation.status, "confirmed");
    let episode = fixture.service.episode("rust-service").await.unwrap();
    assert_eq!(episode.phase, "REGISTERED");
    assert_eq!(episode.required_votes, 2);
    assert_eq!(episode.total_deposited_wei, "0");
    assert!(operation.transaction.unwrap().receipt.unwrap().success);
}

#[tokio::test]
async fn startup_rejects_a_signer_that_is_not_the_contract_operator() {
    let fixture = Fixture::new().await;
    let directory = tempfile::tempdir().unwrap();
    let result = GameService::new(
        fixture.chain_client().await,
        Store::open(directory.path().join("wrong-operator.sqlite")).unwrap(),
        "creator".into(),
    );
    assert!(
        result.is_err(),
        "creator signer must not be accepted as the deployment operator"
    );
}

#[tokio::test]
async fn a_fresh_record_store_cannot_replace_an_existing_onchain_episode_configuration() {
    let fixture = Fixture::new().await;
    fixture.register("existing-onchain", 3, "100").await;
    let directory = tempfile::tempdir().unwrap();
    let database = directory.path().join("fresh.sqlite");
    let fresh = GameService::new(
        fixture.chain_client().await,
        Store::open(&database).unwrap(),
        "treasury".into(),
    )
    .unwrap();
    let attempted_replacement = registration("existing-onchain", 5, "200");
    assert!(
        fresh
            .register(attempted_replacement, "attempted-replacement")
            .await
            .is_err()
    );
    assert!(
        Store::open(&database)
            .unwrap()
            .get_episode("existing-onchain")
            .unwrap()
            .is_none(),
        "rejected pre-existing episode registration must not insert a local replacement record"
    );
    assert!(
        fresh.episode("existing-onchain").await.is_err(),
        "a rejected replacement must not publish local jury5/chain jury3 as one episode"
    );
    assert!(
        fresh
            .act(
                "existing-onchain",
                "creator",
                GameAction::PostClaim {
                    content: "Do not act using a mismatched local configuration.\n".into(),
                },
                "mismatched-claim"
            )
            .await
            .is_err()
    );
    let original: EpisodeView = fixture.get("/v1/episodes/existing-onchain").await;
    assert_eq!(original.required_votes, 2);
    assert_eq!(original.configuration.parameters.beta_wei, "100");
    assert_eq!(original.total_deposited_wei, "0");
}

#[tokio::test]
async fn both_winners_pay_minority_revealers_conserve_rounding_dust_and_withdraw() {
    let fixture = Fixture::new().await;
    for (id, winning_verdict, winner_id, outcome) in [
        (
            "creator-wins",
            "CREATOR_SUPPORTED",
            "creator",
            "SETTLED_CREATOR",
        ),
        (
            "challenger-wins",
            "CHALLENGER_SUPPORTED",
            "challenger",
            "SETTLED_CHALLENGER",
        ),
    ] {
        fixture.open_dispute(id, 5, "107").await;
        for i in 1..=5 {
            let verdict = if i <= 3 {
                winning_verdict
            } else if winning_verdict == "CREATOR_SUPPORTED" {
                "CHALLENGER_SUPPORTED"
            } else {
                "CREATOR_SUPPORTED"
            };
            fixture
                .mutate(
                    &format!("/v1/episodes/{id}/commitments"),
                    &format!("juror-{i}"),
                    &format!("commit-{id}-{i}"),
                    json!({"verdict":verdict,"assessment":format!("private-assessment-{i}\n")}),
                )
                .await;
        }
        let committed: EpisodeView = fixture.get(&format!("/v1/episodes/{id}")).await;
        assert_eq!(committed.phase, "COMMIT");
        assert_eq!(committed.required_votes, 3);
        assert!(
            committed
                .jurors
                .iter()
                .all(|juror| juror.verdict.is_none() && juror.assessment_hash.is_none())
        );
        assert!(
            !serde_json::to_string(&committed)
                .unwrap()
                .contains("private-assessment")
        );
        fixture.advance_to(committed.commit_deadline).await;
        for i in 1..=5 {
            fixture
                .mutate(
                    &format!("/v1/episodes/{id}/reveals"),
                    &format!("juror-{i}"),
                    &format!("reveal-{id}-{i}"),
                    json!({}),
                )
                .await;
        }
        fixture.advance_to(committed.reveal_deadline).await;
        fixture
            .mutate(
                &format!("/v1/episodes/{id}/settle"),
                "operator",
                &format!("settle-{id}"),
                json!({}),
            )
            .await;
        let settlement: SettlementView =
            fixture.get(&format!("/v1/episodes/{id}/settlement")).await;
        assert_eq!(settlement.outcome, outcome);
        assert_eq!(settlement.winner_id.as_deref(), Some(winner_id));
        assert_eq!(settlement.winner_payout, "172");
        assert_eq!(settlement.protocol_fee, "12");
        assert_eq!(settlement.juror_payouts.len(), 5);
        assert!(
            settlement
                .juror_payouts
                .values()
                .all(|amount| amount == "16")
        );
        assert_eq!(settlement.final_votes.len(), 5);
        assert_eq!(settlement.total_deposited, "264");
        assert_eq!(settlement.total_credited, settlement.total_deposited);
        assert!(settlement.forfeited_bonds.is_empty());
        assert!(settlement.refunds.is_empty());

        let balances: BalancesView = fixture.get(&format!("/v1/episodes/{id}/balances")).await;
        assert_eq!(balances.entitlements[winner_id], "172");
        let credit_before = fixture.chain_credit(winner_id).await;
        assert!(credit_before >= U256::from(172));
        let (status, _) = fixture
            .request(
                Method::POST,
                &format!("/v1/episodes/{id}/settle"),
                Some("operator"),
                Some(&format!("second-settle-{id}")),
                json!({}),
            )
            .await;
        assert_eq!(status, StatusCode::CONFLICT);
        assert_eq!(fixture.chain_credit(winner_id).await, credit_before);
        fixture
            .mutate(
                &format!("/v1/episodes/{id}/withdrawals"),
                winner_id,
                &format!("withdraw-{id}"),
                json!({}),
            )
            .await;
        assert_eq!(fixture.chain_credit(winner_id).await, U256::ZERO);
        let balances: BalancesView = fixture.get(&format!("/v1/episodes/{id}/balances")).await;
        assert_eq!(balances.entitlements[winner_id], "172");
        assert_eq!(balances.withdrawal_credits[winner_id], "0");
    }
}

#[tokio::test]
async fn full_jury_threshold_does_not_shrink_for_absent_or_withholding_jurors() {
    let fixture = Fixture::new().await;
    for jury_size in [3, 5, 7] {
        let id = format!("abort-jury-{jury_size}");
        fixture.open_dispute(&id, jury_size, "100").await;
        let threshold = jury_size / 2 + 1;
        for i in 1..=threshold {
            fixture
                .mutate(
                    &format!("/v1/episodes/{id}/commitments"),
                    &format!("juror-{i}"),
                    &format!("commit-{id}-{i}"),
                    json!({"verdict":"CREATOR_SUPPORTED","assessment":"assessment\n"}),
                )
                .await;
        }
        let state: EpisodeView = fixture.get(&format!("/v1/episodes/{id}")).await;
        assert_eq!(state.required_votes, threshold);
        fixture.advance_to(state.commit_deadline).await;
        for i in 1..threshold {
            fixture
                .mutate(
                    &format!("/v1/episodes/{id}/reveals"),
                    &format!("juror-{i}"),
                    &format!("reveal-{id}-{i}"),
                    json!({}),
                )
                .await;
        }
        fixture.advance_to(state.reveal_deadline).await;
        fixture
            .mutate(
                &format!("/v1/episodes/{id}/settle"),
                "operator",
                &format!("settle-{id}"),
                json!({}),
            )
            .await;
        let settlement: SettlementView =
            fixture.get(&format!("/v1/episodes/{id}/settlement")).await;
        assert_eq!(settlement.outcome, "ABORTED");
        assert_eq!(settlement.winner_id, None);
        assert_eq!(settlement.winner_payout, "0");
        assert_eq!(settlement.protocol_fee, "0");
        assert_eq!(settlement.refunds["creator"], "100");
        assert_eq!(settlement.refunds["challenger"], "100");
        assert_eq!(settlement.juror_payouts.len(), threshold - 1);
        assert!(
            settlement
                .juror_payouts
                .values()
                .all(|amount| amount == "10")
        );
        assert_eq!(settlement.forfeited_bonds.len(), 1);
        assert_eq!(
            settlement.forfeited_bonds[&format!("juror-{threshold}")],
            "10"
        );
        assert_eq!(settlement.total_credited, settlement.total_deposited);
        assert!(
            !settlement
                .forfeited_bonds
                .contains_key(&format!("juror-{jury_size}"))
        );
    }
}

#[tokio::test]
async fn expiry_distinguishes_unfunded_from_unchallenged_at_exact_deadlines() {
    let fixture = Fixture::new().await;
    fixture.register("unfunded", 3, "100").await;
    let state: EpisodeView = fixture.get("/v1/episodes/unfunded").await;
    fixture.advance_to(state.posting_deadline).await;
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/unfunded/claims",
            Some("creator"),
            Some("late-claim"),
            json!({"content":"Too late\n"}),
        )
        .await;
    assert_eq!(status, StatusCode::CONFLICT);
    fixture
        .mutate(
            "/v1/episodes/unfunded/expire",
            "operator",
            "expire-unfunded",
            json!({}),
        )
        .await;
    let outcome: SettlementView = fixture.get("/v1/episodes/unfunded/settlement").await;
    assert_eq!(outcome.outcome, "EXPIRED_UNFUNDED");
    assert_eq!(outcome.total_deposited, "0");
    assert!(outcome.refunds.is_empty());

    fixture.register("unchallenged", 3, "100").await;
    fixture
        .mutate(
            "/v1/episodes/unchallenged/claims",
            "creator",
            "post-unchallenged",
            json!({"content":"Nobody challenged this claim.\n"}),
        )
        .await;
    let state: EpisodeView = fixture.get("/v1/episodes/unchallenged").await;
    fixture.advance_to(state.challenge_deadline).await;
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/unchallenged/challenges",
            Some("challenger"),
            Some("late-challenge"),
            json!({"evidence":"Too late\n"}),
        )
        .await;
    assert_eq!(status, StatusCode::CONFLICT);
    fixture
        .mutate(
            "/v1/episodes/unchallenged/expire",
            "operator",
            "expire-unchallenged",
            json!({}),
        )
        .await;
    let outcome: SettlementView = fixture.get("/v1/episodes/unchallenged/settlement").await;
    assert_eq!(outcome.outcome, "EXPIRED_UNCHALLENGED");
    assert_eq!(outcome.refunds["creator"], "100");
    assert_eq!(outcome.winner_id, None);
    assert_eq!(outcome.protocol_fee, "0");
    assert!(outcome.final_votes.is_empty());
    fixture
        .mutate(
            "/v1/episodes/unchallenged/withdrawals",
            "creator",
            "withdraw-expiry",
            json!({}),
        )
        .await;
    assert_eq!(fixture.chain_credit("creator").await, U256::ZERO);
}

#[tokio::test]
async fn restart_retains_reveal_secret_and_idempotency_without_another_bond() {
    let mut fixture = Fixture::new().await;
    fixture.open_dispute("restart", 3, "100").await;
    let commit_request =
        json!({"verdict":"CHALLENGER_SUPPORTED","assessment":"secret-before-reveal\n"});
    let commit = fixture
        .mutate(
            "/v1/episodes/restart/commitments",
            "juror-1",
            "durable-commit",
            &commit_request,
        )
        .await;
    let public_commit = serde_json::to_string(&commit).unwrap();
    assert!(!public_commit.contains("secret-before-reveal"));
    assert!(!public_commit.contains("CHALLENGER_SUPPORTED"));
    assert!(!public_commit.contains("salt"));
    let nonce = fixture.nonce("juror-1").await;
    fixture.restart_service().await;
    let repeated = fixture
        .mutate(
            "/v1/episodes/restart/commitments",
            "juror-1",
            "durable-commit",
            &commit_request,
        )
        .await;
    assert_eq!(repeated, commit);
    assert_eq!(fixture.nonce("juror-1").await, nonce);
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/restart/commitments",
            Some("juror-1"),
            Some("durable-commit"),
            json!({"verdict":"CREATOR_SUPPORTED","assessment":"different\n"}),
        )
        .await;
    assert_eq!(status, StatusCode::CONFLICT);
    let state: EpisodeView = fixture.get("/v1/episodes/restart").await;
    assert_eq!(state.total_deposited_wei, "210");
    assert!(state.jurors.iter().all(|juror| juror.verdict.is_none()));
    fixture.advance_to(state.commit_deadline).await;
    fixture
        .mutate(
            "/v1/episodes/restart/reveals",
            "juror-1",
            "reveal-after-restart",
            json!({}),
        )
        .await;
    let state: EpisodeView = fixture.get("/v1/episodes/restart").await;
    assert_eq!(state.jurors[0].verdict, Some(Verdict::ChallengerSupported));
    assert_eq!(state.challenger_votes, 1);
}

#[tokio::test]
async fn pending_commit_survives_restart_and_reconciles_the_same_signed_transaction() {
    let mut fixture = Fixture::new().await;
    fixture.open_dispute("pending-restart", 3, "100").await;
    fixture.rpc("evm_setAutomine", json!([false])).await;
    let request = json!({"verdict":"CREATOR_SUPPORTED","assessment":"recoverable secret\n"});
    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/episodes/pending-restart/commitments",
            Some("juror-1"),
            Some("pending-commit"),
            request.clone(),
        )
        .await;
    assert_eq!(status, StatusCode::ACCEPTED, "pending response: {body}");
    let first: OperationView = serde_json::from_value(body).unwrap();
    assert!(matches!(
        first.status.as_str(),
        "prepared" | "submitted" | "included"
    ));
    let transaction = first
        .transaction
        .as_ref()
        .expect("signed transaction identity is durable");
    let nonce = fixture.nonce("juror-1").await;
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/pending-restart/commitments",
            Some("juror-1"),
            Some("pending-choice-replacement"),
            json!({"verdict":"CHALLENGER_SUPPORTED","assessment":"replacement must fail\n"}),
        )
        .await;
    assert_eq!(status, StatusCode::CONFLICT);
    fixture.restart_service().await;
    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/episodes/pending-restart/commitments",
            Some("juror-1"),
            Some("pending-commit"),
            request,
        )
        .await;
    assert_eq!(
        status,
        StatusCode::ACCEPTED,
        "duplicate pending response: {body}"
    );
    let repeated: OperationView = serde_json::from_value(body).unwrap();
    assert_eq!(repeated.operation_id, first.operation_id);
    assert_eq!(
        repeated.transaction.as_ref().unwrap().transaction_hash,
        transaction.transaction_hash
    );
    assert_eq!(fixture.nonce("juror-1").await, nonce);
    fixture.rpc("evm_mine", json!([])).await;
    fixture.rpc("evm_setAutomine", json!([true])).await;
    let confirmed = fixture
        .service
        .recover_pending()
        .await
        .unwrap()
        .into_iter()
        .find(|operation| operation.operation_id == first.operation_id)
        .expect("startup recovery must revisit the persisted pending transaction");
    assert_eq!(confirmed.status, "confirmed");
    assert_eq!(
        confirmed.transaction.unwrap().transaction_hash,
        transaction.transaction_hash
    );
    assert_eq!(fixture.nonce("juror-1").await, nonce);
    let state: EpisodeView = fixture.get("/v1/episodes/pending-restart").await;
    assert_eq!(state.total_deposited_wei, "210");
    fixture.advance_to(state.commit_deadline).await;
    fixture
        .mutate(
            "/v1/episodes/pending-restart/reveals",
            "juror-1",
            "pending-reveal",
            json!({}),
        )
        .await;
    let state: EpisodeView = fixture.get("/v1/episodes/pending-restart").await;
    assert_eq!(state.creator_votes, 1);
}

#[tokio::test]
async fn a_timely_request_included_after_the_deadline_is_recorded_as_reverted_without_a_phantom_bond()
 {
    let fixture = Fixture::new().await;
    fixture.open_dispute("late-inclusion", 3, "100").await;
    let before: EpisodeView = fixture.get("/v1/episodes/late-inclusion").await;
    fixture.rpc("evm_setAutomine", json!([false])).await;
    let (status, body) = fixture
        .request(
            Method::POST,
            "/v1/episodes/late-inclusion/commitments",
            Some("juror-1"),
            Some("late-inclusion-commit"),
            json!({"verdict":"CREATOR_SUPPORTED","assessment":"Chosen before the deadline\n"}),
        )
        .await;
    assert_eq!(status, StatusCode::ACCEPTED);
    let pending: OperationView = serde_json::from_value(body).unwrap();
    fixture.advance_to(before.commit_deadline).await;
    fixture.rpc("evm_setAutomine", json!([true])).await;
    let (status, body) = fixture
        .request(
            Method::POST,
            &format!("/v1/operations/{}/reconcile", pending.operation_id),
            Some("operator"),
            Some("reconcile-late-inclusion"),
            json!({}),
        )
        .await;
    assert_eq!(
        status,
        StatusCode::OK,
        "reconcile reverted transaction: {body}"
    );
    let reverted: OperationView = serde_json::from_value(body).unwrap();
    assert_eq!(reverted.status, "reverted");
    assert_eq!(reverted.kind, "commit_vote");
    let receipt = reverted.transaction.unwrap().receipt.unwrap();
    assert!(!receipt.success);
    assert!(receipt.block_number > 0);
    let state: EpisodeView = fixture.get("/v1/episodes/late-inclusion").await;
    assert_eq!(state.total_deposited_wei, "200");
    assert_eq!(state.jurors[0].commitment, None);
    fixture.advance_to(state.reveal_deadline).await;
    fixture
        .mutate(
            "/v1/episodes/late-inclusion/settle",
            "operator",
            "settle-late-inclusion",
            json!({}),
        )
        .await;
    let settlement: SettlementView = fixture.get("/v1/episodes/late-inclusion/settlement").await;
    assert_eq!(settlement.outcome, "ABORTED");
    assert!(settlement.forfeited_bonds.is_empty());
    assert_eq!(settlement.total_credited, "200");
}

#[tokio::test]
async fn a_rejected_unsigned_early_commit_does_not_freeze_a_jurors_later_choice() {
    let fixture = Fixture::new().await;
    fixture.register("early-commit", 3, "100").await;
    fixture
        .mutate(
            "/v1/episodes/early-commit/claims",
            "creator",
            "early-claim",
            json!({"content":"A claim.\n"}),
        )
        .await;
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/early-commit/commitments",
            Some("juror-1"),
            Some("too-early-commit"),
            json!({"verdict":"CREATOR_SUPPORTED","assessment":"An early assessment\n"}),
        )
        .await;
    assert_eq!(status, StatusCode::CONFLICT);
    let state: EpisodeView = fixture.get("/v1/episodes/early-commit").await;
    assert_eq!(state.total_deposited_wei, "100");
    assert_eq!(state.jurors[0].commitment, None);
    fixture
        .mutate(
            "/v1/episodes/early-commit/challenges",
            "challenger",
            "early-challenge",
            json!({"evidence":"New evidence changes the juror's assessment.\n"}),
        )
        .await;
    fixture
        .mutate(
            "/v1/episodes/early-commit/commitments",
            "juror-1",
            "valid-later-commit",
            json!({"verdict":"CHALLENGER_SUPPORTED","assessment":"A revised assessment\n"}),
        )
        .await;
    let state: EpisodeView = fixture.get("/v1/episodes/early-commit").await;
    fixture.advance_to(state.commit_deadline).await;
    fixture
        .mutate(
            "/v1/episodes/early-commit/reveals",
            "juror-1",
            "valid-later-reveal",
            json!({}),
        )
        .await;
    let state: EpisodeView = fixture.get("/v1/episodes/early-commit").await;
    assert_eq!(state.jurors[0].verdict, Some(Verdict::ChallengerSupported));
}

#[tokio::test]
async fn auth_and_schema_prevent_actor_impersonation_and_float_money() {
    let fixture = Fixture::new().await;
    let body = serde_json::to_value(registration("auth", 3, "100")).unwrap();
    for actor in [None, Some("not-configured")] {
        let (status, _) = fixture
            .request(
                Method::POST,
                "/v1/episodes",
                actor,
                Some("auth"),
                body.clone(),
            )
            .await;
        assert_eq!(status, StatusCode::UNAUTHORIZED);
    }
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes",
            Some("creator"),
            Some("auth"),
            body.clone(),
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes",
            Some("operator"),
            None,
            body.clone(),
        )
        .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);
    let mut float_money = body;
    float_money["parameters"]["beta_wei"] = json!(10.0);
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes",
            Some("operator"),
            Some("float-money"),
            float_money,
        )
        .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);

    fixture.register("auth", 3, "100").await;
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/auth/claims",
            Some("challenger"),
            Some("impersonated-claim"),
            json!({"content":"A claim\n"}),
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN);
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/auth/claims",
            Some("creator"),
            Some("actor-in-body"),
            json!({"content":"A claim\n","actor_id":"challenger"}),
        )
        .await;
    assert_eq!(status, StatusCode::UNPROCESSABLE_ENTITY);

    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/auth/claims",
            Some("operator"),
            Some("operator-cannot-impersonate-creator"),
            json!({"content":"A claim\n"}),
        )
        .await;
    assert_eq!(status, StatusCode::FORBIDDEN);

    let specification: Value = fixture.get("/v1/openapi.json").await;
    assert!(specification["paths"]["/v1/episodes"].is_object());
    assert!(specification["paths"]["/v1/episodes/{id}/commitments"].is_object());
    assert!(specification["components"]["securitySchemes"].is_object());
    let state: EpisodeView = fixture.get("/v1/episodes/auth").await;
    assert_eq!(state.phase, "REGISTERED");
    assert_eq!(state.total_deposited_wei, "0");
}

#[tokio::test]
async fn registration_retry_returns_one_operation_and_rejects_changed_payload() {
    let fixture = Fixture::new().await;
    let request = registration("register-retry", 3, "100");
    let (first, repeated) = tokio::join!(
        fixture.mutate("/v1/episodes", "operator", "same-register", &request),
        fixture.mutate("/v1/episodes", "operator", "same-register", &request),
    );
    assert_eq!(first, repeated);
    let stored: OperationView = fixture
        .get(&format!("/v1/operations/{}", first.operation_id))
        .await;
    assert_eq!(stored, first);
    let mut changed = request;
    changed.parameters.beta_wei = "200".into();
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes",
            Some("operator"),
            Some("same-register"),
            serde_json::to_value(changed).unwrap(),
        )
        .await;
    assert_eq!(status, StatusCode::CONFLICT);
}

#[tokio::test]
async fn event_replay_deduplicates_and_exports_public_chain_evidence_without_vote_secrets() {
    let fixture = Fixture::new().await;
    fixture.open_dispute("event-export", 3, "100").await;
    let commit = fixture
        .mutate(
            "/v1/episodes/event-export/commitments",
            "juror-1",
            "export-commit",
            json!({"verdict":"CHALLENGER_SUPPORTED","assessment":"never-export-this-assessment\n"}),
        )
        .await;
    let head = commit.transaction.unwrap().receipt.unwrap().block_number;
    // Receipts may already have recorded these events, but replay must remain stable.
    fixture.service.replay_events(0, head).await.unwrap();
    assert_eq!(fixture.service.replay_events(0, head).await.unwrap(), 0);
    let export = fixture.service.export_events(0, head).await.unwrap();
    let rows: Vec<Value> = export
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert!(!rows.is_empty());
    assert!(rows.iter().all(|row| row["chain_id"] == 31337));
    assert!(
        rows.iter()
            .all(|row| row["contract_address"].as_str().is_some())
    );
    assert!(rows.iter().all(|row| row["block_hash"].as_str().is_some()));
    assert!(
        rows.iter()
            .all(|row| row["transaction_hash"].as_str().is_some())
    );
    assert!(rows.iter().all(|row| row["log_index"].as_u64().is_some()));
    assert!(!export.contains("never-export-this-assessment"));
    assert!(!export.contains("CHALLENGER_SUPPORTED"));
    assert!(!export.contains("salt"));
    assert!(!export.contains("raw_transaction"));
    assert_eq!(
        fixture.service.export_events(0, head).await.unwrap(),
        export
    );
}

#[tokio::test]
async fn replay_rewinds_orphaned_chain_evidence_after_a_local_reorganisation() {
    let fixture = Fixture::new().await;
    fixture.register("reorg", 3, "100").await;
    let snapshot = fixture.rpc("evm_snapshot", json!([])).await;
    let claim = fixture
        .mutate(
            "/v1/episodes/reorg/claims",
            "creator",
            "orphaned-claim",
            json!({"content":"This block will be orphaned.\n"}),
        )
        .await;
    let orphaned_block = claim.transaction.unwrap().receipt.unwrap().block_number;
    fixture
        .service
        .replay_events(0, orphaned_block)
        .await
        .unwrap();
    let before = fixture
        .service
        .export_events(0, orphaned_block)
        .await
        .unwrap();
    assert!(
        before
            .lines()
            .map(|line| serde_json::from_str::<Value>(line).unwrap())
            .any(|row| row["block_number"].as_u64() == Some(orphaned_block))
    );
    assert_eq!(
        fixture.rpc("evm_revert", json!([snapshot])).await,
        json!(true)
    );
    fixture
        .service
        .replay_events(0, orphaned_block - 1)
        .await
        .unwrap();
    let after = fixture
        .service
        .export_events(0, orphaned_block)
        .await
        .unwrap();
    assert!(
        after
            .lines()
            .map(|line| serde_json::from_str::<Value>(line).unwrap())
            .all(|row| row["block_number"].as_u64().unwrap() < orphaned_block)
    );
    let state: EpisodeView = fixture.get("/v1/episodes/reorg").await;
    assert_eq!(state.phase, "REGISTERED");
    assert_eq!(state.total_deposited_wei, "0");
    assert_eq!(state.content_hash, None);
}

#[tokio::test]
async fn startup_rebuilds_missing_event_rows_from_durable_confirmed_receipts() {
    let mut fixture = Fixture::new().await;
    let registration = fixture.register("receipt-crash-window", 3, "100").await;
    let block = registration
        .transaction
        .unwrap()
        .receipt
        .unwrap()
        .block_number;
    let before = fixture.service.export_events(0, block).await.unwrap();
    assert!(!before.is_empty());
    rusqlite::Connection::open(&fixture.database)
        .unwrap()
        .execute("DELETE FROM chain_events", [])
        .unwrap();
    fixture.restart_service().await;
    assert_eq!(
        fixture.service.export_events(0, block).await.unwrap(),
        before,
        "a crash between receipt persistence and event projection must not permanently lose evidence"
    );
}

#[tokio::test]
async fn canonical_evidence_at_the_same_height_cannot_hide_an_orphaned_event() {
    let fixture = Fixture::new().await;
    let registration = fixture.register("mixed-fork-evidence", 3, "100").await;
    let block = registration
        .transaction
        .unwrap()
        .receipt
        .unwrap()
        .block_number;
    let client = fixture.chain_client().await;
    let identity = client.identity();
    let store = Store::open(&fixture.database).unwrap();
    let events = store
        .chain_events(31337, &identity.contract_address.to_string(), block, block)
        .unwrap();
    let canonical = events.first().unwrap();
    let mut orphaned_log: LogEvidence = serde_json::from_str(&canonical.payload_json).unwrap();
    let orphaned_hash = alloy::primitives::B256::from(U256::from(1));
    assert_ne!(orphaned_log.block_hash, orphaned_hash);
    orphaned_log.block_hash = orphaned_hash;
    store
        .insert_chain_event(&ChainEventRecord {
            block_hash: orphaned_hash.to_string(),
            payload_json: serde_json::to_string(&orphaned_log).unwrap(),
            ..canonical.clone()
        })
        .unwrap();
    fixture.service.replay_events(0, block).await.unwrap();
    let export = fixture.service.export_events(0, block).await.unwrap();
    let rows: Vec<Value> = export
        .lines()
        .map(|line| serde_json::from_str(line).unwrap())
        .collect();
    assert_eq!(rows.len(), events.len());
    assert!(
        rows.iter()
            .all(|row| row["block_hash"] != orphaned_hash.to_string()),
        "every stored hash at a height must be checked, even if canonical evidence also exists"
    );
}

#[tokio::test]
async fn failed_prepared_transaction_persistence_releases_only_the_unbroadcast_nonce_reservation() {
    let fixture = Fixture::new().await;
    fixture.register("prepare-write-failure", 3, "100").await;
    let fault = rusqlite::Connection::open(&fixture.database).unwrap();
    fault.execute_batch("CREATE TRIGGER reject_prepared BEFORE UPDATE OF status ON operations WHEN NEW.status='prepared' BEGIN SELECT RAISE(ABORT,'injected prepare persistence failure'); END;").unwrap();
    let before = fixture.nonce("creator").await;
    let (status, _) = fixture
        .request(
            Method::POST,
            "/v1/episodes/prepare-write-failure/claims",
            Some("creator"),
            Some("failed-prepare-write"),
            json!({"content":"A valid claim.\n"}),
        )
        .await;
    assert_eq!(status, StatusCode::INTERNAL_SERVER_ERROR);
    assert_eq!(fixture.nonce("creator").await, before);
    fault
        .execute_batch("DROP TRIGGER reject_prepared;")
        .unwrap();
    fixture
        .mutate(
            "/v1/episodes/prepare-write-failure/claims",
            "creator",
            "recovered-prepare-write",
            json!({"content":"A valid claim.\n"}),
        )
        .await;
    assert_eq!(fixture.nonce("creator").await, before + 1);
    let state: EpisodeView = fixture.get("/v1/episodes/prepare-write-failure").await;
    assert_eq!(state.phase, "OPEN");
    assert_eq!(state.total_deposited_wei, "100");
}

#[tokio::test]
async fn a_temporary_transaction_budget_failure_retains_the_original_ballot_for_recovery() {
    let mut fixture = Fixture::new().await;
    fixture.open_dispute("retryable-budget", 3, "100").await;
    fixture.set_transaction_budget(1, 100_000_000_000).await;
    let nonce = fixture.nonce("juror-1").await;
    let (status, body) = fixture.request(Method::POST, "/v1/episodes/retryable-budget/commitments",
        Some("juror-1"), Some("budget-blocked-commit"),
        json!({"verdict":"CREATOR_SUPPORTED","assessment":"The original ballot must survive.\n"})).await;
    assert_eq!(
        status,
        StatusCode::SERVICE_UNAVAILABLE,
        "retryable budget response: {body}"
    );
    assert_eq!(fixture.nonce("juror-1").await, nonce);
    let store = Store::open(&fixture.database).unwrap();
    let operation = store
        .pending_operations()
        .unwrap()
        .into_iter()
        .find(|operation| {
            operation.episode_id == "retryable-budget" && operation.actor_id == "juror-1"
        })
        .expect("a gas budget issue must retain an accepted, recoverable operation");
    assert_eq!(
        operation.status,
        veracity_game_service::store::OperationStatus::Accepted
    );
    assert_eq!(operation.error.as_deref(), Some("budget_exceeded"));
    assert!(operation.prepared.is_none());
    let material = store
        .get_reveal_material("retryable-budget", "juror-1")
        .unwrap()
        .expect("pre-broadcast budget failures must retain the chosen ballot and salt");
    assert_eq!(material.verdict, 0);
    let (status, _) = fixture.request(Method::POST, "/v1/episodes/retryable-budget/commitments",
        Some("juror-1"), Some("different-budget-ballot"),
        json!({"verdict":"CHALLENGER_SUPPORTED","assessment":"A replacement ballot must be rejected.\n"})).await;
    assert_eq!(status, StatusCode::CONFLICT);
    fixture
        .set_transaction_budget(3_000_000, 100_000_000_000)
        .await;
    let recovered = fixture.service.operation(&operation.id).await.unwrap();
    assert_eq!(recovered.status, "confirmed");
    assert_eq!(fixture.nonce("juror-1").await, nonce + 1);
    let restored = store
        .get_reveal_material("retryable-budget", "juror-1")
        .unwrap()
        .unwrap();
    assert!(restored.salt == material.salt);
    assert_eq!(restored.verdict, material.verdict);
    assert_eq!(restored.assessment_hash, material.assessment_hash);
    let state: EpisodeView = fixture.get("/v1/episodes/retryable-budget").await;
    assert_eq!(state.total_deposited_wei, "210");
    fixture.advance_to(state.commit_deadline).await;
    fixture
        .mutate(
            "/v1/episodes/retryable-budget/reveals",
            "juror-1",
            "reveal-recovered-budget",
            json!({}),
        )
        .await;
    let state: EpisodeView = fixture.get("/v1/episodes/retryable-budget").await;
    assert_eq!(state.jurors[0].verdict, Some(Verdict::CreatorSupported));
}
