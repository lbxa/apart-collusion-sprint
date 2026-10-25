use std::sync::Arc;

use rusqlite::Connection;
use veracity_game_service::{
    chat::{ChatPrincipal, ChatQuery, ChatService},
    forum::{ForumQuery, ForumSendMessage, ForumService},
    store::Store,
};

fn participant(id: &str) -> ChatPrincipal {
    ChatPrincipal::Participant(id.into())
}

fn seed(store: &Store) {
    store
        .insert_episode(
            "trial-001",
            "0xtest",
            "0xconfiguration",
            include_str!("../../examples/episode.json"),
        )
        .unwrap();
}

fn message() -> ForumSendMessage {
    ForumSendMessage {
        content: "public café\r\n".into(),
        round_num: Some(3),
    }
}

#[tokio::test]
async fn version_two_migration_preserves_private_records_and_forum_is_separate() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("game.sqlite");
    let connection = Connection::open(&path).unwrap();
    connection
        .execute_batch(include_str!("../src/store/schema.sql"))
        .unwrap();
    connection
        .execute_batch(include_str!("../src/store/chat-schema.sql"))
        .unwrap();
    connection.execute("INSERT INTO episodes(id,onchain_id,configuration_hash,config_json) VALUES('trial-001','0xtest','0xconfiguration',?1)",[include_str!("../../examples/episode.json")]).unwrap();
    connection.execute_batch("INSERT INTO chats VALUES('old-chat','trial-001','creator','juror-1',1,1,12); INSERT INTO chat_messages VALUES('old-chat',1,'old-message','creator','juror-1','retained private secret','0xprivatehash',13); INSERT INTO chat_requests VALUES('old-scope','creator','old-key','old-digest','{}');").unwrap();
    drop(connection);
    let store = Arc::new(Store::open(&path).unwrap());
    let private = ChatService::new(store.clone(), "treasury".into());
    let forum = ForumService::new(store, "treasury".into());
    let page = private
        .messages(
            participant("juror-1"),
            "old-chat".into(),
            ChatQuery::default(),
            false,
        )
        .await
        .unwrap();
    assert_eq!(page.messages[0].content, "retained private secret");
    let public_page = forum
        .messages(
            participant("juror-1"),
            "trial-001".into(),
            ForumQuery::default(),
            false,
        )
        .await
        .unwrap();
    assert!(public_page.messages.is_empty());
    forum
        .send(
            participant("creator"),
            "trial-001".into(),
            message(),
            "post".into(),
        )
        .await
        .unwrap();
    assert_eq!(
        private
            .messages(
                participant("juror-1"),
                "old-chat".into(),
                ChatQuery::default(),
                false
            )
            .await
            .unwrap()
            .messages
            .len(),
        1
    );
    let connection = Connection::open(&path).unwrap();
    assert_eq!(
        connection
            .pragma_query_value::<u32, _>(None, "user_version", |row| row.get(0))
            .unwrap(),
        3
    );
    let digest: String = connection
        .query_row(
            "SELECT request_digest FROM chat_requests WHERE scope='old-scope'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(digest, "old-digest");
}

#[test]
fn failed_version_two_upgrade_rolls_back_new_tables_and_preserves_version() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("game.sqlite");
    let connection = Connection::open(&path).unwrap();
    connection
        .execute_batch(include_str!("../src/store/schema.sql"))
        .unwrap();
    connection
        .execute_batch(include_str!("../src/store/chat-schema.sql"))
        .unwrap();
    connection
        .execute_batch("CREATE TABLE forum_audit(existing TEXT);")
        .unwrap();
    assert!(Store::open(&path).is_err());
    assert_eq!(
        connection
            .pragma_query_value::<u32, _>(None, "user_version", |row| row.get(0))
            .unwrap(),
        2
    );
    let count: u32 = connection
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='forum_messages'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(count, 0);
    let count: u32 = connection
        .query_row(
            "SELECT COUNT(*) FROM sqlite_master WHERE name='chats'",
            [],
            |row| row.get(0),
        )
        .unwrap();
    assert_eq!(count, 1);
}

#[tokio::test]
async fn failed_audit_atomically_rolls_back_message_and_retry_cache_and_failed_reads_return_nothing()
 {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("game.sqlite");
    let store = Arc::new(Store::open(&path).unwrap());
    seed(&store);
    let service = ForumService::new(store, "treasury".into());
    let control = Connection::open(&path).unwrap();
    control.execute_batch("CREATE TRIGGER reject_forum_send BEFORE INSERT ON forum_audit WHEN NEW.kind='message_sent' BEGIN SELECT RAISE(ABORT,'injected audit failure'); END;").unwrap();
    assert!(
        service
            .send(
                participant("creator"),
                "trial-001".into(),
                message(),
                "send".into()
            )
            .await
            .is_err()
    );
    for table in ["forum_messages", "forum_requests", "forum_audit"] {
        let count: u32 = control
            .query_row(&format!("SELECT COUNT(*) FROM {table}"), [], |row| {
                row.get(0)
            })
            .unwrap();
        assert_eq!(count, 0);
    }
    control
        .execute_batch("DROP TRIGGER reject_forum_send;")
        .unwrap();
    let saved = service
        .send(
            participant("creator"),
            "trial-001".into(),
            message(),
            "send".into(),
        )
        .await
        .unwrap();
    assert_eq!(saved.sequence, 1);
    control.execute_batch("CREATE TRIGGER reject_forum_read BEFORE INSERT ON forum_audit WHEN NEW.kind='messages_read' BEGIN SELECT RAISE(ABORT,'injected audit failure'); END;").unwrap();
    assert!(
        service
            .messages(
                participant("juror-1"),
                "trial-001".into(),
                ForumQuery::default(),
                false
            )
            .await
            .is_err()
    );
    control
        .execute_batch("DROP TRIGGER reject_forum_read;")
        .unwrap();
    let report = service
        .audit(
            ChatPrincipal::Operator,
            "trial-001".into(),
            ForumQuery::default(),
        )
        .await
        .unwrap();
    assert_eq!(report.actors.len(), 1);
    let page = service
        .messages(
            participant("juror-1"),
            "trial-001".into(),
            ForumQuery::default(),
            false,
        )
        .await
        .unwrap();
    assert_eq!(page.messages[0].content, saved.content);
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn independent_connections_serialize_and_deduplicate_racing_posts() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("game.sqlite");
    let first_store = Arc::new(Store::open(&path).unwrap());
    seed(&first_store);
    let first = ForumService::new(first_store, "treasury".into());
    let second = ForumService::new(Arc::new(Store::open(&path).unwrap()), "treasury".into());
    let mut jobs = tokio::task::JoinSet::new();
    for index in 0..20 {
        let service = if index % 2 == 0 {
            first.clone()
        } else {
            second.clone()
        };
        jobs.spawn(async move {
            service
                .send(
                    participant("creator"),
                    "trial-001".into(),
                    message(),
                    format!("key-{}", index / 2),
                )
                .await
                .unwrap()
        });
    }
    while let Some(result) = jobs.join_next().await {
        result.unwrap();
    }
    let report = first
        .audit(
            ChatPrincipal::Operator,
            "trial-001".into(),
            ForumQuery::default(),
        )
        .await
        .unwrap();
    assert_eq!(report.message_count, 10);
    assert_eq!(report.events.len(), 10);
    assert_eq!(report.actors[0].sent_messages, 10);
}
