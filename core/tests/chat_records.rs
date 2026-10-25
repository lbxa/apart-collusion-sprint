use std::sync::Arc;

use rusqlite::Connection;
use veracity_game_service::{
    chat::{ChatPrincipal, ChatQuery, ChatService, CreateChat, SendMessage},
    store::Store,
};

fn participant(id: &str) -> ChatPrincipal {
    ChatPrincipal::Participant(id.into())
}

fn seed(store: &Store) {
    let config = include_str!("../../examples/episode.json");
    store
        .insert_episode("trial-001", "0xtest", "0xconfiguration", config)
        .unwrap();
}

fn request() -> CreateChat {
    CreateChat {
        participant_ids: ["creator".into(), "juror-1".into()],
        history_enabled: true,
        communication_prohibited: true,
    }
}

#[test]
fn failed_initial_migration_does_not_leave_partial_game_tables_or_change_version() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("database.sqlite");
    let connection = Connection::open(&path).unwrap();
    connection
        .execute_batch("CREATE TABLE chat_audit(existing TEXT);")
        .unwrap();
    assert!(Store::open(&path).is_err());
    let version: u32 = connection
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    assert_eq!(
        version, 0,
        "failed initialization must roll back all schema changes"
    );
    let count: u32 = connection
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='episodes'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(count, 0);
}

#[test]
fn version_one_game_records_survive_upgrade_and_future_versions_are_rejected() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("database.sqlite");
    let connection = Connection::open(&path).unwrap();
    connection
        .execute_batch(include_str!("../src/store/schema.sql"))
        .unwrap();
    connection
        .execute(
            "INSERT INTO artifacts(hash,utf8) VALUES('existing','preserve exactly')",
            [],
        )
        .unwrap();
    drop(connection);
    let store = Store::open(&path).unwrap();
    seed(&store);
    drop(store);
    let connection = Connection::open(&path).unwrap();
    let version: u32 = connection
        .pragma_query_value(None, "user_version", |row| row.get(0))
        .unwrap();
    assert_eq!(version, 3);
    let content: String = connection
        .query_row(
            "SELECT utf8 FROM artifacts WHERE hash='existing'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(content, "preserve exactly");
    connection.pragma_update(None, "user_version", 4).unwrap();
    assert!(Store::open(&path).is_err());
    assert_eq!(
        connection
            .pragma_query_value::<u32, _>(None, "user_version", |row| row.get(0))
            .unwrap(),
        4
    );
}

#[tokio::test]
async fn audit_failure_rolls_back_message_and_idempotency_record_then_retry_recovers() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("database.sqlite");
    let store = Arc::new(Store::open(&path).unwrap());
    seed(&store);
    let service = ChatService::new(store, "treasury".into());
    let chat = service
        .create(
            participant("creator"),
            "trial-001".into(),
            request(),
            "create".into(),
        )
        .await
        .unwrap();
    let control = Connection::open(&path).unwrap();
    control.execute_batch("CREATE TRIGGER reject_chat_send BEFORE INSERT ON chat_audit WHEN NEW.kind='message_sent' BEGIN SELECT RAISE(ABORT,'injected audit failure'); END;").unwrap();
    let message = SendMessage {
        content: "private exact content".into(),
    };
    assert!(
        service
            .send(
                participant("creator"),
                chat.chat_id.clone(),
                message.clone(),
                "send".into()
            )
            .await
            .is_err()
    );
    for table in ["chat_messages", "chat_requests WHERE scope LIKE 'send:%'"] {
        // Fixed test-owned SQL fragments, never external input.
        let count: u32 = control
            .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                row.get(0)
            })
            .unwrap();
        assert_eq!(count, 0);
    }
    control
        .execute_batch("DROP TRIGGER reject_chat_send;")
        .unwrap();
    let saved = service
        .send(
            participant("creator"),
            chat.chat_id.clone(),
            message,
            "send".into(),
        )
        .await
        .unwrap();
    assert_eq!(saved.sequence, 1);
    control.execute_batch("CREATE TRIGGER reject_chat_read BEFORE INSERT ON chat_audit WHEN NEW.kind='messages_read' BEGIN SELECT RAISE(ABORT,'injected audit failure'); END;").unwrap();
    assert!(
        service
            .messages(
                participant("juror-1"),
                chat.chat_id.clone(),
                ChatQuery::default(),
                false
            )
            .await
            .is_err()
    );
    control
        .execute_batch("DROP TRIGGER reject_chat_read;")
        .unwrap();
    let page = service
        .messages(
            participant("juror-1"),
            chat.chat_id,
            ChatQuery::default(),
            false,
        )
        .await
        .unwrap();
    assert_eq!(page.messages[0].content, "private exact content");
    let report = service
        .audit(
            ChatPrincipal::Operator,
            "trial-001".into(),
            ChatQuery::default(),
        )
        .await
        .unwrap();
    assert_eq!(report.message_count, 1);
    assert_eq!(
        report
            .actors
            .iter()
            .find(|actor| actor.actor_id == "juror-1")
            .unwrap()
            .read_requests,
        1
    );
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn independent_connections_deduplicate_racing_sends_and_scope_keys_by_sender() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("database.sqlite");
    let store = Arc::new(Store::open(&path).unwrap());
    seed(&store);
    let first = ChatService::new(store, "treasury".into());
    let second = ChatService::new(Arc::new(Store::open(&path).unwrap()), "treasury".into());
    let (a, b) = tokio::join!(
        first.create(
            participant("creator"),
            "trial-001".into(),
            request(),
            "create".into()
        ),
        second.create(
            participant("creator"),
            "trial-001".into(),
            request(),
            "create".into()
        )
    );
    let chat = a.unwrap();
    assert_eq!(chat.chat_id, b.unwrap().chat_id);
    let mut tasks = tokio::task::JoinSet::new();
    for index in 0..12 {
        let service = if index % 2 == 0 {
            first.clone()
        } else {
            second.clone()
        };
        let id = chat.chat_id.clone();
        tasks.spawn(async move {
            service
                .send(
                    participant("creator"),
                    id,
                    SendMessage {
                        content: "one logical message".into(),
                    },
                    "same-key".into(),
                )
                .await
                .unwrap()
                .message_id
        });
    }
    let expected = tasks.join_next().await.unwrap().unwrap();
    while let Some(result) = tasks.join_next().await {
        assert_eq!(result.unwrap(), expected);
    }
    let reply = second
        .send(
            participant("juror-1"),
            chat.chat_id,
            SendMessage {
                content: "other sender".into(),
            },
            "same-key".into(),
        )
        .await
        .unwrap();
    assert_eq!(reply.sequence, 2);
    let report = first
        .audit(
            ChatPrincipal::Operator,
            "trial-001".into(),
            ChatQuery::default(),
        )
        .await
        .unwrap();
    assert_eq!(report.chat_count, 1);
    assert_eq!(report.message_count, 2);
    assert_eq!(
        report
            .events
            .iter()
            .filter(|event| event.kind == veracity_game_service::chat::ChatAuditKind::MessageSent)
            .count(),
        2
    );
}
