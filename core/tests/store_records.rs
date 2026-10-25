use std::sync::{Arc, Barrier};

use tempfile::TempDir;
use veracity_game_service::store::{
    ChainEventRecord, OperationStatus, PreparedTransactionRecord, ReceiptRecord, Reservation,
    RevealMaterial, Store, StoreError,
};

fn database() -> (TempDir, Store) {
    let directory = tempfile::tempdir().unwrap();
    let store = Store::open(directory.path().join("game.sqlite")).unwrap();
    (directory, store)
}

fn reserve(store: &Store, key: &str) -> String {
    match store
        .reserve(
            "creator:claim",
            key,
            "digest",
            "episode",
            "creator",
            "claim",
            "{}",
        )
        .unwrap()
    {
        Reservation::Created(operation) => operation.id,
        Reservation::Existing(_) => panic!("expected a new operation"),
    }
}

fn prepared() -> PreparedTransactionRecord {
    PreparedTransactionRecord {
        sender: "0xcreator".into(),
        nonce: 17,
        tx_hash: "0xtransaction".into(),
        raw_transaction: vec![2, 4, 6, 8],
    }
}

fn receipt() -> ReceiptRecord {
    ReceiptRecord {
        chain_id: 31337,
        contract_address: "0xcontract".into(),
        transaction_hash: "0xtransaction".into(),
        block_number: 20,
        block_hash: "0xblock".into(),
        gas_used: "21000".into(),
        effective_gas_price: "1000000000".into(),
        receipt_json: "{\"status\":\"0x1\"}".into(),
    }
}

#[test]
fn same_key_and_body_reuses_one_durable_operation() {
    let (_directory, store) = database();
    let id = reserve(&store, "key");
    let repeated = store
        .reserve(
            "creator:claim",
            "key",
            "digest",
            "episode",
            "creator",
            "claim",
            "{}",
        )
        .unwrap();
    let Reservation::Existing(operation) = repeated else {
        panic!("retry allocated another operation");
    };
    assert_eq!(operation.id, id);
    assert_eq!(operation.status, OperationStatus::Accepted);
    assert_eq!(store.pending_operations().unwrap().len(), 1);
}

#[test]
fn conflicting_idempotency_payload_is_rejected_and_scope_is_independent() {
    let (_directory, store) = database();
    reserve(&store, "key");
    assert!(matches!(
        store.reserve(
            "creator:claim",
            "key",
            "changed",
            "episode",
            "creator",
            "claim",
            "{}"
        ),
        Err(StoreError::Conflict(_))
    ));
    assert!(matches!(
        store.reserve(
            "challenger:challenge",
            "key",
            "digest",
            "episode",
            "challenger",
            "challenge",
            "{}"
        ),
        Ok(Reservation::Created(_))
    ));
}

#[test]
fn separate_connections_atomically_reserve_one_operation() {
    let (directory, _store) = database();
    let path = directory.path().join("game.sqlite");
    let first = Store::open(&path).unwrap();
    let second = Store::open(&path).unwrap();
    let barrier = Arc::new(Barrier::new(2));
    let handles = [first, second].map(|store| {
        let barrier = Arc::clone(&barrier);
        std::thread::spawn(move || {
            barrier.wait();
            store.reserve(
                "scope", "key", "digest", "episode", "creator", "claim", "{}",
            )
        })
    });
    let results = handles.map(|handle| handle.join().unwrap().unwrap());
    assert_eq!(
        results
            .iter()
            .filter(|value| matches!(value, Reservation::Created(_)))
            .count(),
        1
    );
    assert_eq!(
        results
            .iter()
            .filter(|value| matches!(value, Reservation::Existing(_)))
            .count(),
        1
    );
}

#[test]
fn reveal_material_and_signed_transaction_survive_reopening() {
    let (directory, store) = database();
    let id = reserve(&store, "key");
    let secret = RevealMaterial {
        verdict: 0,
        assessment_hash: "0xassessment".into(),
        salt: [91; 32],
        assessment_utf8: "Evidence: café\n".into(),
    };
    store
        .put_reveal_material("episode", "juror", &secret)
        .unwrap();
    store.prepare_operation(&id, &prepared()).unwrap();
    drop(store);
    let reopened = Store::open(directory.path().join("game.sqlite")).unwrap();
    assert_eq!(
        reopened.get_reveal_material("episode", "juror").unwrap(),
        Some(secret)
    );
    let operation = reopened.get_operation(&id).unwrap().unwrap();
    assert_eq!(operation.status, OperationStatus::Prepared);
    assert_eq!(operation.prepared, Some(prepared()));
    assert_eq!(operation.request_json, "{}");
}

#[test]
fn revealed_secret_cannot_be_replaced_by_another_request() {
    let (_directory, store) = database();
    let secret = RevealMaterial {
        verdict: 1,
        assessment_hash: "0xassessment".into(),
        salt: [73; 32],
        assessment_utf8: "assessment\n".into(),
    };
    store
        .put_reveal_material("episode", "juror", &secret)
        .unwrap();
    store
        .put_reveal_material("episode", "juror", &secret)
        .unwrap();
    let mut changed = secret.clone();
    changed.salt = [74; 32];
    assert!(matches!(
        store.put_reveal_material("episode", "juror", &changed),
        Err(StoreError::Conflict(_))
    ));
    assert_eq!(
        store.get_reveal_material("episode", "juror").unwrap(),
        Some(secret)
    );
}

#[test]
fn transaction_identity_is_immutable_after_preparation() {
    let (_directory, store) = database();
    let id = reserve(&store, "key");
    store.prepare_operation(&id, &prepared()).unwrap();
    store.prepare_operation(&id, &prepared()).unwrap();
    let mut changed = prepared();
    changed.nonce += 1;
    assert!(matches!(
        store.prepare_operation(&id, &changed),
        Err(StoreError::Conflict(_))
    ));
    assert!(matches!(
        store.mark_failed(&id, "uncertain broadcast"),
        Err(StoreError::InvalidState(_))
    ));
    store.record_error(&id, "RPC unavailable").unwrap();
    let operation = store.get_operation(&id).unwrap().unwrap();
    assert_eq!(operation.status, OperationStatus::Prepared);
    assert_eq!(operation.prepared, Some(prepared()));
    assert_eq!(operation.error.as_deref(), Some("RPC unavailable"));
}

#[test]
fn receipt_recovery_can_skip_missing_submitted_marker_but_not_transaction_identity() {
    let (_directory, store) = database();
    let id = reserve(&store, "key");
    store.prepare_operation(&id, &prepared()).unwrap();
    store
        .record_receipt(&id, &receipt(), OperationStatus::Included)
        .unwrap();
    store
        .record_receipt(&id, &receipt(), OperationStatus::Confirmed)
        .unwrap();
    assert!(store.pending_operations().unwrap().is_empty());
    let mut changed = receipt();
    changed.transaction_hash = "0xother".into();
    assert!(matches!(
        store.record_receipt(&id, &changed, OperationStatus::Confirmed),
        Err(StoreError::Conflict(_))
    ));
    assert!(matches!(
        store.record_receipt(&id, &receipt(), OperationStatus::Included),
        Err(StoreError::InvalidState(_))
    ));
    assert_eq!(
        store.get_operation(&id).unwrap().unwrap().receipt,
        Some(receipt())
    );
}

#[test]
fn confirmations_can_advance_without_replacing_consensus_identity() {
    let (_directory, store) = database();
    let id = reserve(&store, "key");
    store.prepare_operation(&id, &prepared()).unwrap();
    let mut observed = receipt();
    observed.receipt_json = "{\"confirmations\":1}".into();
    store
        .record_receipt(&id, &observed, OperationStatus::Included)
        .unwrap();
    observed.receipt_json = "{\"confirmations\":2}".into();
    store
        .record_receipt(&id, &observed, OperationStatus::Confirmed)
        .unwrap();
    assert_eq!(
        store.get_operation(&id).unwrap().unwrap().receipt,
        Some(observed)
    );
}

#[test]
fn pending_operations_include_recoverable_states_and_exclude_terminal_outcomes() {
    let (_directory, store) = database();
    let accepted = reserve(&store, "accepted");
    let pending = reserve(&store, "pending");
    store.prepare_operation(&pending, &prepared()).unwrap();
    store.mark_submitted(&pending).unwrap();
    let failed = reserve(&store, "failed");
    store.mark_failed(&failed, "validation rejected").unwrap();
    let reverted = reserve(&store, "reverted");
    let mut reverted_transaction = prepared();
    reverted_transaction.nonce += 1;
    reverted_transaction.tx_hash = "0xreverted".into();
    let mut reverted_receipt = receipt();
    reverted_receipt.transaction_hash = "0xreverted".into();
    store
        .prepare_operation(&reverted, &reverted_transaction)
        .unwrap();
    store
        .record_receipt(&reverted, &reverted_receipt, OperationStatus::Reverted)
        .unwrap();
    let ids: Vec<_> = store
        .pending_operations()
        .unwrap()
        .into_iter()
        .map(|operation| operation.id)
        .collect();
    assert_eq!(ids, vec![accepted, pending]);
}

#[test]
fn immutable_episode_configuration_and_artifact_bytes_survive_reopening() {
    let (directory, store) = database();
    store
        .insert_episode("episode", "0xonchain", "0xconfig", "{\"jury\":3}")
        .unwrap();
    store
        .insert_episode("episode", "0xonchain", "0xconfig", "{\"jury\":3}")
        .unwrap();
    assert!(matches!(
        store.insert_episode("episode", "0xonchain", "0xnew", "{}"),
        Err(StoreError::Conflict(_))
    ));
    store.store_artifact("0xartifact", "  café\n").unwrap();
    store.store_artifact("0xartifact", "  café\n").unwrap();
    assert!(matches!(
        store.store_artifact("0xartifact", "café\n"),
        Err(StoreError::Conflict(_))
    ));
    drop(store);
    let reopened = Store::open(directory.path().join("game.sqlite")).unwrap();
    assert_eq!(
        reopened
            .get_episode("episode")
            .unwrap()
            .unwrap()
            .configuration_hash,
        "0xconfig"
    );
    assert_eq!(
        reopened.artifact("0xartifact").unwrap().as_deref(),
        Some("  café\n")
    );
}

fn event(block_number: u64, block_hash: &str, log_index: u64) -> ChainEventRecord {
    ChainEventRecord {
        chain_id: 31337,
        contract_address: "0xcontract".into(),
        block_number,
        block_hash: block_hash.into(),
        transaction_hash: "0xtransaction".into(),
        log_index,
        payload_json: "{\"event\":\"credited\"}".into(),
    }
}

#[test]
fn chain_event_identity_deduplicates_and_reorg_rewinds_receipts() {
    let (_directory, store) = database();
    let before = event(19, "0xbefore", 0);
    let orphan = event(20, "0xblock", 1);
    assert!(store.insert_chain_event(&before).unwrap());
    assert!(!store.insert_chain_event(&before).unwrap());
    assert!(store.insert_chain_event(&orphan).unwrap());
    let mut foreign = orphan.clone();
    foreign.chain_id = 80002;
    assert!(store.insert_chain_event(&foreign).unwrap());
    let id = reserve(&store, "key");
    store.prepare_operation(&id, &prepared()).unwrap();
    store
        .record_receipt(&id, &receipt(), OperationStatus::Confirmed)
        .unwrap();
    store.rewind_chain(31337, "0xcontract", 20).unwrap();
    assert_eq!(
        store
            .chain_events(31337, "0xcontract", 0, u64::MAX)
            .unwrap(),
        vec![before]
    );
    assert_eq!(
        store
            .chain_events(80002, "0xcontract", 0, u64::MAX)
            .unwrap(),
        vec![foreign]
    );
    let recovered = store.get_operation(&id).unwrap().unwrap();
    assert_eq!(recovered.status, OperationStatus::Submitted);
    assert!(recovered.receipt.is_none());
    assert_eq!(recovered.prepared, Some(prepared()));
}

#[cfg(unix)]
#[test]
fn persistent_database_is_private_to_its_owner() {
    use std::os::unix::fs::PermissionsExt;
    let (directory, _store) = database();
    let permissions = std::fs::metadata(directory.path().join("game.sqlite"))
        .unwrap()
        .permissions();
    assert_eq!(permissions.mode() & 0o777, 0o600);
}

#[test]
fn deployment_identity_is_immutable_across_restarts() {
    let (directory, store) = database();
    store
        .bind_deployment("{\"chain_id\":31337,\"contract\":\"0xfirst\"}")
        .unwrap();
    store
        .bind_deployment("{\"chain_id\":31337,\"contract\":\"0xfirst\"}")
        .unwrap();
    assert!(matches!(
        store.bind_deployment("{\"chain_id\":31337,\"contract\":\"0xother\"}"),
        Err(StoreError::Conflict(_))
    ));
    drop(store);
    let reopened = Store::open(directory.path().join("game.sqlite")).unwrap();
    assert_eq!(
        reopened.deployment().unwrap().as_deref(),
        Some("{\"chain_id\":31337,\"contract\":\"0xfirst\"}")
    );
}

#[test]
fn separate_operations_cannot_reserve_the_same_signed_sender_nonce() {
    let (_directory, store) = database();
    let first = reserve(&store, "first");
    let second = reserve(&store, "second");
    store.prepare_operation(&first, &prepared()).unwrap();
    assert!(matches!(
        store.prepare_operation(&second, &prepared()),
        Err(StoreError::Conflict(_))
    ));
    assert_eq!(
        store.get_operation(&second).unwrap().unwrap().status,
        OperationStatus::Accepted
    );
}

#[test]
fn debug_output_redacts_unrevealed_material_and_request_body() {
    let (_directory, store) = database();
    let operation = store
        .reserve(
            "scope",
            "key",
            "digest",
            "episode",
            "juror",
            "commit",
            "{\"assessment\":\"private reasoning\"}",
        )
        .unwrap();
    let Reservation::Created(operation) = operation else {
        panic!("new operation expected");
    };
    assert!(!format!("{operation:?}").contains("private reasoning"));
    let secret = RevealMaterial {
        verdict: 1,
        assessment_hash: "hash".into(),
        salt: [77; 32],
        assessment_utf8: "private assessment".into(),
    };
    assert!(!format!("{secret:?}").contains("private assessment"));
}

#[test]
fn receipt_recovery_queries_include_terminal_receipts_and_preserve_order() {
    let (_directory, store) = database();
    let accepted = reserve(&store, "accepted");
    let confirmed = reserve(&store, "confirmed");
    store.prepare_operation(&confirmed, &prepared()).unwrap();
    store
        .record_receipt(&confirmed, &receipt(), OperationStatus::Confirmed)
        .unwrap();
    let reverted = reserve(&store, "reverted");
    let mut second_transaction = prepared();
    second_transaction.nonce += 1;
    second_transaction.tx_hash = "0xreverted".into();
    let mut second_receipt = receipt();
    second_receipt.transaction_hash = "0xreverted".into();
    store
        .prepare_operation(&reverted, &second_transaction)
        .unwrap();
    store
        .record_receipt(&reverted, &second_receipt, OperationStatus::Reverted)
        .unwrap();
    let receipts = store.receipt_operations().unwrap();
    assert_eq!(
        receipts
            .iter()
            .map(|operation| operation.id.clone())
            .collect::<Vec<_>>(),
        vec![confirmed.clone(), reverted.clone()]
    );
    assert!(receipts.iter().all(|operation| operation.receipt.is_some()));
    let all = store.all_operations().unwrap();
    assert_eq!(
        all.iter()
            .map(|operation| operation.id.clone())
            .collect::<Vec<_>>(),
        vec![accepted, confirmed, reverted]
    );
    assert!(
        receipts
            .iter()
            .all(|operation| !format!("{operation:?}").contains("request_json"))
    );
}

#[test]
fn replay_query_limits_chain_contract_and_inclusive_block_range() {
    let (_directory, store) = database();
    let first = event(10, "0xblock10", 2);
    let earlier_log = event(10, "0xblock10", 0);
    let next = event(11, "0xblock11", 0);
    let outside = event(12, "0xblock12", 0);
    let mut another_contract = event(10, "0xblock10", 1);
    another_contract.contract_address = "0xother".into();
    let mut another_chain = event(10, "0xblock10", 1);
    another_chain.chain_id = 80002;
    for value in [
        &next,
        &first,
        &outside,
        &another_contract,
        &earlier_log,
        &another_chain,
    ] {
        store.insert_chain_event(value).unwrap();
    }
    assert_eq!(
        store.chain_events(31337, "0xcontract", 10, 11).unwrap(),
        vec![earlier_log, first, next]
    );
    assert!(
        store
            .chain_events(31337, "0xcontract", 13, 20)
            .unwrap()
            .is_empty()
    );
    assert!(matches!(
        store.chain_events(31337, "0xcontract", 12, 10),
        Err(StoreError::InvalidRecord(_))
    ));
}

fn reserve_commit(store: &Store, key: &str) -> String {
    let reservation = store
        .reserve(
            "juror:commit_vote",
            key,
            "digest",
            "episode",
            "juror",
            "commit_vote",
            "{}",
        )
        .unwrap();
    let Reservation::Created(operation) = reservation else {
        panic!("new commit expected");
    };
    operation.id
}

fn material() -> RevealMaterial {
    RevealMaterial {
        verdict: 0,
        assessment_hash: "0xassessment".into(),
        salt: [93; 32],
        assessment_utf8: "private assessment".into(),
    }
}

#[test]
fn definitively_failed_unsigned_commit_can_discard_unanchored_material() {
    let (directory, store) = database();
    let operation = reserve_commit(&store, "failed");
    store
        .put_reveal_material("episode", "juror", &material())
        .unwrap();
    store
        .mark_failed(&operation, "preparation rejected the wrong phase")
        .unwrap();
    store
        .mark_failed(&operation, "preparation rejected the wrong phase")
        .unwrap();
    assert!(
        store
            .get_reveal_material("episode", "juror")
            .unwrap()
            .is_none()
    );
    drop(store);
    let reopened = Store::open(directory.path().join("game.sqlite")).unwrap();
    let mut corrected = material();
    corrected.verdict = 1;
    corrected.salt = [94; 32];
    reserve_commit(&reopened, "corrected");
    reopened
        .put_reveal_material("episode", "juror", &corrected)
        .unwrap();
    assert_eq!(
        reopened.get_reveal_material("episode", "juror").unwrap(),
        Some(corrected)
    );
}

#[test]
fn uncertain_or_signed_commit_material_cannot_be_lost() {
    let (directory, store) = database();
    let operation = reserve_commit(&store, "pending");
    store
        .put_reveal_material("episode", "juror", &material())
        .unwrap();
    store
        .record_error(
            &operation,
            "RPC unavailable; preparation not conclusively rejected",
        )
        .unwrap();
    assert_eq!(
        store.get_reveal_material("episode", "juror").unwrap(),
        Some(material())
    );
    store.prepare_operation(&operation, &prepared()).unwrap();
    assert!(matches!(
        store.mark_failed(&operation, "signed transaction outcome is uncertain"),
        Err(StoreError::InvalidState(_))
    ));
    store.mark_submitted(&operation).unwrap();
    assert!(matches!(
        store.mark_failed(&operation, "broadcast outcome is uncertain"),
        Err(StoreError::InvalidState(_))
    ));
    drop(store);
    let reopened = Store::open(directory.path().join("game.sqlite")).unwrap();
    assert!(matches!(
        reopened.mark_failed(&operation, "broadcast outcome is uncertain after restart"),
        Err(StoreError::InvalidState(_))
    ));
    assert_eq!(
        reopened.get_reveal_material("episode", "juror").unwrap(),
        Some(material())
    );
}

#[test]
fn failed_duplicate_commit_cannot_delete_another_signed_commit_secret() {
    let (_directory, store) = database();
    let signed = reserve_commit(&store, "signed");
    store
        .put_reveal_material("episode", "juror", &material())
        .unwrap();
    store.prepare_operation(&signed, &prepared()).unwrap();
    let failed = reserve_commit(&store, "failed");
    store
        .mark_failed(&failed, "duplicate commitment rejected")
        .unwrap();
    store
        .mark_failed(&failed, "duplicate commitment rejected")
        .unwrap();
    assert_eq!(
        store.get_reveal_material("episode", "juror").unwrap(),
        Some(material())
    );
}

#[test]
fn failed_non_commit_action_cannot_delete_reveal_material() {
    let (_directory, store) = database();
    let operation = reserve(&store, "failed-claim");
    store
        .put_reveal_material("episode", "juror", &material())
        .unwrap();
    store.mark_failed(&operation, "claim rejected").unwrap();
    assert_eq!(
        store.get_reveal_material("episode", "juror").unwrap(),
        Some(material())
    );
}

#[test]
fn failed_old_request_cannot_delete_a_newer_recoverable_commit_secret() {
    let (_directory, store) = database();
    let failed = reserve_commit(&store, "failed");
    store.mark_failed(&failed, "preparation rejected").unwrap();
    reserve_commit(&store, "recoverable");
    store
        .put_reveal_material("episode", "juror", &material())
        .unwrap();
    store.mark_failed(&failed, "preparation rejected").unwrap();
    assert_eq!(
        store.get_reveal_material("episode", "juror").unwrap(),
        Some(material())
    );
}

#[test]
fn failure_record_and_unowned_secret_cleanup_commit_atomically() {
    let (directory, store) = database();
    let operation = reserve_commit(&store, "failed");
    store
        .put_reveal_material("episode", "juror", &material())
        .unwrap();
    store.mark_failed(&operation, "contract_rejected").unwrap();
    drop(store);
    let reopened = Store::open(directory.path().join("game.sqlite")).unwrap();
    assert!(
        reopened
            .get_reveal_material("episode", "juror")
            .unwrap()
            .is_none()
    );
    let retained_audit = reopened.get_operation(&operation).unwrap().unwrap();
    assert_eq!(retained_audit.status, OperationStatus::Failed);
    assert_eq!(retained_audit.error.as_deref(), Some("contract_rejected"));
    assert_eq!(retained_audit.request_json, "{}");
}
