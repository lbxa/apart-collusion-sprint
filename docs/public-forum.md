# Episode public forum

The game core owns one persistent, append-only public forum per episode.
Every assigned participant (creator, challenger, juror, or treasury) can post
and read the same chronological history. “Public” means visible to the episode's
participants, not anonymous Internet access. All routes require bearer credentials.
Private two-person chats remain separate; see [private chat](private-chat.md).

## API

| Method and path | Caller and behavior |
| --- | --- |
| `POST /v1/episodes/{id}/forum/messages` | An assigned participant posts as themselves. Requires `Idempotency-Key`. |
| `GET /v1/episodes/{id}/forum/messages` | An assigned participant reads chronological messages. The returned sequence numbers are audited. |
| `GET /v1/episodes/{id}/forum/transcript` | The operator inspects chronological messages without impersonating a participant. Access is audited. |
| `GET /v1/episodes/{id}/forum-audit` | The operator reads usage summaries and metadata events. This does not append an audit event. |

The forum exists implicitly once the episode is registered. There is no room
creation step, participant list override, or history switch. Participants from
other episodes cannot read or post. The operator cannot post messages or use
the ordinary participant-read route.

For example, after registering `trial-001`:

```sh
curl -sS http://127.0.0.1:8080/v1/episodes/trial-001/forum/messages \
  -H 'Authorization: Bearer dev-juror-1' \
  -H 'Idempotency-Key: public-message-001' \
  -H 'Content-Type: application/json' \
  -d '{"content":"I interpret the evidence differently.","round_num":1}'
curl -sS http://127.0.0.1:8080/v1/episodes/trial-001/forum/messages \
  -H 'Authorization: Bearer dev-juror-2'
curl -sS http://127.0.0.1:8080/v1/episodes/trial-001/forum-audit \
  -H 'Authorization: Bearer dev-operator'
```

`content` preserves exact UTF-8, whitespace, and line endings. It must contain
non-whitespace text and fit within 16 KiB. `round_num` is optional and must be
positive when supplied. It is a caller-supplied annotation, not proof of a game
phase or an engine-enforced experiment round. Sender identity comes from the
bearer token. Messages contain an immutable ID, episode-local sequence,
sender, exact content, content hash, round annotation, and server timestamp.

Sends return the message directly, not a chain-operation handle. Persist the
request body and idempotency key before sending; retries with the same key
and body return the original message without creating another send event.
Changing the body under an existing key returns `409`. Messages, their send
audit events, and retry responses are committed in one SQLite transaction.

Message, transcript, and audit reads accept `after` (an exclusive numeric
cursor, default zero) and `limit` (1–100, default 50). Follow `next_after` while
`has_more` is true. An empty page preserves the supplied cursor. Always paginate;
the default first page is not necessarily the full conversation. Forum responses
use `Cache-Control: no-store` and `Vary: Authorization`.

## Usage and communication shape

The operator audit exposes:

- `forum_used`: authenticated participant forum use, including known denied
  access. Operator transcript inspection alone does not set this flag.
- `communication_used`: at least one message was successfully posted.
- All-time message and UTF-8 byte totals, distinct sender count, and first/last
  message timestamps.
- Per-actor send, byte, read-request, returned-message, and denied-request totals.
- Ordered events with actor identity and operator distinction, action kind,
  message sequence/hash/byte length/round, server timestamp, and the exact
  message sequences returned by each read.

Summary totals cover the whole episode regardless of the requested audit-event
page. An empty read is still a read request. Repeated reads count each response;
returned-message totals do not measure unique viewers. These records describe
broadcast timing, participation, volume, and which messages each participant
was offered. They do not prove that an agent consumed a response, understood a
message, or coordinated with another agent. Audit events omit message bodies;
use the operator transcript for authorized content inspection. Ordinary logs
and game-state responses do not contain forum message bodies or private chats.

Public discussion is available to assigned participants without private chat's
default behavioral prohibition. The harness's `public_messaging=False` setting
means that the runner neither publishes nor reads public messages for agents;
it is not an engine authorization rule for other authenticated API clients.

## Harness integration

The Python `CoreClient` exposes typed participant send/read methods and separate
operator transcript/audit methods generated from the Rust OpenAPI contract.
For example:

```python
from game_api import CoreClient

async with CoreClient(url, participant_tokens={"juror-1": juror_token}) as juror:
    message = await juror.send_forum_message(
        episode_id, "juror-1", "My assessment of the evidence.",
        round_num=1, idempotency_key="saved-public-message-key",
    )
    page = await juror.get_forum_messages(episode_id, "juror-1", limit=100)
    # Continue with after=page.next_after while page.has_more.

async with CoreClient(url, operator_token=operator_token) as evaluator:
    audit = await evaluator.get_forum_audit(episode_id)
    transcript = await evaluator.get_forum_transcript(episode_id)
```

`CoreEngineAPI` maps experiment agent IDs to assigned engine identities. The
runner publishes accepted public deliberation messages through that adapter
and fetches each juror's visible history from the engine before deliberation
and final voting. A failed publish or read is an infrastructure failure; there
is no in-memory substitute for a missing engine response.

Round scheduling, prompts, straw polls, and treatment selection remain in the
harness. Episode exports retain `forum_audit` with all audit-event pages and an
`actor_mapping` from engine identities to harness agents. If an episode fails,
the runner still attempts to capture partial audit evidence. If that is
unavailable, `forum_audit_error` records the missing evidence without replacing
the original episode failure. Operator audit metadata never enters agent
observations. Explicit `--mock` runs emulate
the forum locally and continue to identify their backend as a simulation.

Forum records survive service restarts. Existing databases migrate atomically
while retaining private chats and their audit records. Forum traffic remains
off-chain and does not alter escrow, voting deadlines, or settlement.
