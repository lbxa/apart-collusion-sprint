# Experimental private chat

The core provides private, episode-scoped chat between any two assigned
participants, including parties, jurors, and treasury. Communication is
**prohibited by default but technically possible** so experiments can observe
violations. The operator's audit flags describe API use, not proof of collusion.

## Simple API

All routes require existing bearer credentials. Only creation and sending need
`Idempotency-Key`; reuse it for retries and use a new key for each new action.
Expose participant-bound tools to agents and keep the operator credential in
the evaluator's context.

| Method and path | Caller and behavior |
| --- | --- |
| `POST /v1/episodes/{id}/chats` | Participant creates a chat including themselves, or operator provisions a pair. |
| `GET /v1/episodes/{id}/chats` | Participant discovers their own chats; operator sees all episode chats. |
| `POST /v1/chats/{id}/messages` | One of the pair sends `{"content":"hello"}` as themselves. |
| `GET /v1/chats/{id}/messages` | Either member reads available messages. |
| `GET /v1/chats/{id}/transcript` | Operator reads the retained full transcript; access is audited. |
| `GET /v1/episodes/{id}/chat-audit` | Operator reads usage flags, actor totals, and metadata events. |

Create a chat after registering `trial-001`:

```sh
curl -sS http://127.0.0.1:8080/v1/episodes/trial-001/chats \
  -H 'Authorization: Bearer dev-creator' \
  -H 'Idempotency-Key: chat-001' \
  -H 'Content-Type: application/json' \
  -d '{"participant_ids":["creator","juror-1"],"history_enabled":false}'
```

Use the returned `chat_id`:

```sh
chat_id="the-returned-chat-id"
curl -sS "http://127.0.0.1:8080/v1/chats/$chat_id/messages" \
  -H 'Authorization: Bearer dev-creator' \
  -H 'Idempotency-Key: message-001' \
  -H 'Content-Type: application/json' -d '{"content":"hello"}'
curl -sS "http://127.0.0.1:8080/v1/chats/$chat_id/messages" \
  -H 'Authorization: Bearer dev-juror-1'
curl -sS http://127.0.0.1:8080/v1/episodes/trial-001/chat-audit \
  -H 'Authorization: Bearer dev-operator'
```

`history_enabled` defaults to `false`: only the latest message from either
member is visible, and repeated reads may return it again. With `true`, both
members can read chronological history. The setting is immutable per chat.
The full operator transcript is retained in both modes; history-disabled does
not mean deletion or end-to-end encryption.

Messages preserve exact UTF-8, including whitespace and line endings. They must
contain non-whitespace text and fit within 16 KiB. Sender identity comes from
the bearer token, and the recipient is the other member; body fields cannot
impersonate another sender or add a third participant.

All page limits are 1–100, default 50. Message/transcript and audit pages use an
exclusive numeric `after` cursor and return `next_after` and `has_more`. Disabled
history always returns at most the latest message; cursor tricks cannot retrieve
older messages. Chat listing uses an opaque lexicographic chat-ID cursor; start
a fresh listing to discover newly created chats.

## Python client

`CoreClient` uses the generated OpenAPI chat models and endpoint calls. Give
each agent a client with only its participant credential; keep the operator
client with the evaluator. For example, after registering the episode:

```python
from game_api import CoreClient

async with CoreClient(url, participant_tokens={"creator": creator_token}) as creator:
    chat = await creator.create_chat(
        episode_id, ["creator", "juror-1"], actor_id="creator",
        idempotency_key="saved-chat-key",
    )
    sent = await creator.send_message(
        chat.chat_id, "creator", "hello", idempotency_key="saved-message-key",
    )

async with CoreClient(url, participant_tokens={"juror-1": juror_token}) as juror:
    own_chats = await juror.list_chats(episode_id, actor_id="juror-1")
    page = await juror.poll_messages(chat.chat_id, "juror-1", after=0, timeout=5)
    # Save page.next_after for the next poll.

async with CoreClient(url, operator_token=operator_token) as evaluator:
    audit = await evaluator.get_chat_audit(episode_id)
    transcript = await evaluator.get_transcript(chat.chat_id)
```

Creation and sends return `ChatView` and `ChatMessage` directly; they do not
produce chain-operation handles or require `wait_operation`. Save each request
body and key before sending, then reuse them to recover the original response
after a transport failure. Structured HTTP failures remain `CoreHTTPError`.

Creation defaults to latest-only history and prohibited communication. Pass
`history_enabled=True` when creating a history-enabled chat. Omit `actor_id`
when an operator client provisions a pair; only that operator may also set
`communication_prohibited=False`. These settings cannot be updated later.

`get_messages` performs one participant read; `poll_messages` repeats that same
authenticated route until it receives a message or its timeout expires. Each
read is audited. An empty result at timeout retains the latest valid cursor;
`timeout=0` performs one read. Neither method caches older messages or consults
the operator transcript. `after` and `limit` are optional on reads, listings,
transcripts, and audits; omitted parameters use server defaults. Use
`has_more`/`next_after` to walk a page rather than assuming it is a full transcript.

The experiment runner uses the core's [public forum](public-forum.md) when its
public-messaging treatment is enabled. With `private_chat=True`, it also exposes
private messaging to the parties and jurors, reads each participant's available
private history through the engine, and exports private usage audits. Operator
transcripts remain evaluator-only and never enter agent observations.

## Prohibition and audit

`communication_prohibited` defaults to `true`. Participants cannot clear it.
The operator may create a control chat with this field set to `false`; that
immutable choice is retained in audit metadata. It labels behavior rather than
blocking transport. The operator cannot use its credential to impersonate a
participant sender or use the ordinary participant-read route.

The audit response includes:

- `chat_used`: at least one authenticated participant used a chat API, including
  discovery or denied access; operator provisioning alone does not set it.
- `communication_used`: at least one message was successfully sent.
- `prohibited_communication_used`: at least one message was sent in a prohibited
  chat, independent of permitted control chats.
- All-time `chat_count`, `message_count`, and per-actor creation, send, read,
  returned-message, denied-access, and prohibited-use counters.
- Ordered events with actor identity, operator distinction, episode/chat IDs,
  Unix-millisecond timestamps, prohibition/violation flags, recipient, message
  sequence/hash/byte length, and exact sequences returned by each read.

Event pages omit message bodies. Explicit operator transcripts contain them.
Audit-report reads do not append events, so walking audit pages does not create
an endless stream of self-generated records. Operator transcript reads do append
events but do not inflate participant-use counters. Empty reads are counted as
requests and do not imply a message was exchanged. A read event records the
server's prepared response, not proof that an agent consumed or acted on it.

Creation/send retries return their original response without duplicate send
events. Changed payloads on an existing key return `409`. Authenticated denied
access is recorded when its episode/chat is known. Missing or invalid credentials
receive `401`; anonymous attempts have no attributable actor and remain ordinary
HTTP telemetry. Chat responses disable HTTP caching. SQLite records and private
operator access are trusted research infrastructure, not an immutable public log.

The harness exposes these endpoints as agent tools when the private-chat lever
is enabled. Behavioral instructions and whether to expose the tools belong to
the experiment; the core's prohibition flag remains an audited label rather
than a transport restriction.

## Architecture contract

- **Boundary and capability:** the Rust core owns episode-scoped, two-person
  communication and durable audit evidence. The harness supplies behavioral
  instructions; Solidity continues to own game finance and voting rules.
- **Ownership and change points:** `chat/` owns membership, immutable history and
  prohibition settings, validation, and use cases. `store/chat.rs` owns SQLite
  transactions; `api/chat.rs` owns HTTP/authentication and OpenAPI. History modes
  and audit reporting can evolve independently of contract behavior.
- **Domain concepts:** chat, participant pair, exact UTF-8 message, audit event,
  and per-actor usage. Chats have immutable settings and append-only messages;
  there is no editable lifecycle or speculative state-machine abstraction.
- **Invariants:** only the two assigned participants can use a chat. Operator
  access is explicit and audited. Participants cannot declare communication
  permitted; operator-created controls may do so. Prohibited use remains possible
  and is flagged rather than blocked. Ordinary logs and public game snapshots
  never include messages.
- **History:** enabled returns chronological messages to either participant;
  disabled returns only the latest message. The operator always retains the
  full transcript. History settings cannot be changed retrospectively.
- **Use cases and interfaces:** create/list chats, send/read messages, inspect
  operator-only episode audit and transcript. All routes use `/v1` and existing
  bearer credentials; message reads and audit exports are bounded and paginated.
- **Failure model:** reject malformed input, self-chat, outsiders, unauthorized
  policy overrides, and changed idempotent payloads. Authenticated denied access
  receives durable metadata evidence. Storage failure fails closed.
- **Transactions and consistency:** create/send writes, idempotency response, and
  audit event commit together in SQLite. Reads snapshot messages and append their
  audit event in the same transaction. No RPC or chain operation participates.
  Stable caller-scoped keys prevent duplicate chats, messages, and send events;
  successful repeated reads are individually observable.
- **Data boundaries:** reuse Serde, rusqlite, UUIDs, existing bearer validation,
  and existing hashes rather than adding transport, auth, or crypto machinery.
  SQLite receives typed validated intent; HTTP handlers contain no chat policy.
- **Tests:** failing examples precede implementation. Prove two-way messages,
  latest-only/history behavior, role isolation, policy flags, immutable settings,
  idempotency, exact bodies, pagination, restart/migration durability, concurrent
  writers, denial traces, and atomic failure recovery. Real API tests run on the
  existing local Anvil fixture; the full shared gate checks regressions.
