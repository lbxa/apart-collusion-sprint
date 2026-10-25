# Veracity Game API v1

The external experiment harness calls this HTTP API to create independent game
episodes, post claims and challenges, commit and reveal votes, settle, and
withdraw credits. The harness owns agent prompts, deliberation,
private observations, simulated bribes, and evaluation metrics. The contract
owns protocol state and money. An API request cannot change a registered rule.

The base path is `/v1`. The machine-readable OpenAPI document is available at
`GET /v1/openapi.json`; this guide is served by `GET /v1/docs`. Default local
development binds to loopback and uses an isolated Anvil chain, ID `31337`.
Public testnet operation supports explicitly configured Polygon Amoy, ID `80002`.
The service refuses other chain IDs, including mainnet.

## Authentication and request identity

Every protocol mutation and operation reconciliation request requires these headers:

```http
Authorization: Bearer <credential>
Idempotency-Key: <unique-command-key>
Content-Type: application/json
```

Chain-evidence replay is the exception: `POST /v1/chain/replay` requires an
operator bearer credential and JSON content type, but no `Idempotency-Key`.
It is naturally idempotent by chain-event identity and never broadcasts an
economic action. The count of newly recorded events can differ on repeat.

The server maps the bearer credential to the operator or one participant ID.
Participants cannot select another signer, address, transaction value, or gas
limit in request JSON. Operator credentials register episodes, settle/expire
episodes, and reconcile operations; they cannot masquerade as a juror to vote.
Give an agent only its own credential. The harness may hold all credentials but
must enforce its own observation and communication restrictions.

Credentials must be nonempty visible ASCII without whitespace and must be
unique. Never put tokens in URLs, prompts for unrelated agents, or shared logs.
Development credentials are for local test use only. Protect the HTTP transport
and use distinct strong credentials when exposing a service to another machine.

An idempotency key contains 1–128 visible ASCII characters without whitespace.
Reuse the same key and request body when retrying an uncertain command. The
same authenticated actor, route, episode, and key returns the existing operation.
Reusing that identity with a different body returns `409 CONFLICT`.
A new key means a new command; contract rules still reject duplicate deposits
or votes. Never work around a pending command by issuing a new key.

## Wire conventions

- JSON field names use `snake_case`; verdicts use `CREATOR_SUPPORTED` and
  `CHALLENGER_SUPPORTED` (`uint8` values 0 and 1 in the commitment ABI).
- Money is a canonical decimal **string** of integer native base units, with
  18 base-unit decimal places per native currency unit. For example, `"1000"`
  means 1,000 base units, not 1,000 POL. Floats and JSON numeric amounts are
  rejected. Payout shares and the juror multiplier are integer basis points.
- Episode IDs are caller-chosen strings of 1–128 safe characters. The API
  returns the corresponding bytes32 on-chain ID. IDs are immutable and unique.
- Contract hashes and addresses are `0x`-prefixed fixed-width hex strings.
- Deadlines are Unix timestamps in seconds from the chain. A window accepts
  actions at `timestamp < deadline`; the next phase starts at `timestamp >= deadline`.
- Artifacts are exact UTF-8 strings with LF line endings, at most 64 KiB each.
  CR line endings are rejected. The service does not trim or normalize text
  before hashing its bytes with Keccak-256. The total HTTP body limit is 128 KiB.
- Registered configuration is hashed using RFC 8785 canonical JSON and Keccak-256.

## Endpoints

| Method and path | Credential | Body / result |
| --- | --- | --- |
| `GET /v1/health` | Public | API version and configured deployment identity |
| `GET /v1/participants` | Public | Configured participant IDs and addresses |
| `POST /v1/episodes` | Operator | Registration configuration → operation |
| `GET /v1/episodes/{id}` | Public | Sanitized chain-backed episode snapshot |
| `POST /v1/episodes/{id}/claims` | Creator | `{"content":"..."}` → operation |
| `POST /v1/episodes/{id}/challenges` | Challenger | `{"evidence":"..."}` → operation |
| `POST /v1/episodes/{id}/commitments` | Juror | Verdict and assessment → operation |
| `POST /v1/episodes/{id}/reveals` | Same juror | `{}` → operation |
| `POST /v1/episodes/{id}/settle` | Operator | `{}` → operation after reveal deadline |
| `POST /v1/episodes/{id}/expire` | Operator | `{}` → operation after posting/challenge expiry |
| `POST /v1/episodes/{id}/withdrawals` | Participant | `{}` → operation withdrawing caller's global credits |
| `GET /v1/episodes/{id}/settlement` | Public | Terminal payout and vote decomposition |
| `GET /v1/episodes/{id}/balances` | Public | Episode entitlements and current global credits |
| `GET /v1/operations/{id}` | Public | Persisted operation state and chain evidence |
| `POST /v1/operations/{id}/reconcile` | Operator | `{}` → reconciled operation |
| `POST /v1/chain/replay` | Operator | Inclusive block range → count of newly recorded chain events |
| `GET /v1/chain/events?from_block=N&to_block=M` | Public | Stored chain-event JSON Lines export |

The designated role is fixed at registration and checked on-chain. Settlement
and expiry are permissionless on-chain even though this API uses an operator
credential to pay gas for those calls. Reconciliation is an administrative
recovery action, not authority to modify game rules.

The `phase` field has these values:

| Phase | Meaning |
| --- | --- |
| `REGISTERED` | Waiting for creator deposit until the posting deadline |
| `OPEN` | Claim posted; designated challenger may challenge before its deadline |
| `COMMIT` | Challenge posted; selected jurors may deposit and commit |
| `REVEAL` | Commit deadline reached; committed jurors may reveal before its deadline |
| `SETTLED_CREATOR` / `SETTLED_CHALLENGER` | Full-jury majority reached after the reveal deadline |
| `ABORTED` | Reveal deadline passed without either side reaching the full-jury threshold |
| `EXPIRED_UNCHALLENGED` | Posted claim expired without a challenge; full creator refund |
| `EXPIRED_UNFUNDED` | Posting deadline passed without the creator deposit |

Reaching the reveal deadline does not itself settle or move funds: the phase
remains `REVEAL` until a settlement transaction is included. Likewise, expiry
requires an explicit transaction. No API credential can extend a deadline.

## Python client

With `harness/` on `PYTHONPATH` and its locked dependencies installed, connect
to an existing service without starting a process or accessing its chain RPC:

```python
import os
from game_api import CoreClient
from game_api.generated import ProtocolParameters, RegisterEpisode

async def register_game():
    async with CoreClient(
        os.environ["GAME_URL"],
        operator_token=os.environ["OPERATOR_TOKEN"],
        participant_tokens={"creator": os.environ["CREATOR_TOKEN"]},
    ) as client:
        registration = RegisterEpisode(
            episode_id="trial-001", creator_id="creator", challenger_id="challenger",
            juror_ids=["juror-1", "juror-2", "juror-3"], treasury_id="treasury",
            parameters=ProtocolParameters(
                beta_wei="1000", gamma_bps=1000, posting_duration_secs=300,
                challenge_duration_secs=300, commit_duration_secs=300,
                reveal_duration_secs=300,
            ),
        )
        # Save the command body and key before sending. Save the returned ID too.
        operation = await client.register_episode(
            registration, idempotency_key="trial-001-register")
        confirmed = await client.wait_operation(operation)
        return confirmed.operation_id
```

Participant credential keys are deployment actor IDs, with no required local
names or Python registration mappings. Supply only the credentials needed by
the caller. Public reads require none; a participant-only client's
`wait_operation` polls evidence, while an operator client can also reconcile.
The operation lookup route remains public under this version of the API.

Game protocol actions are explicit and return validated operation handles immediately:

```python
commit = await client.commit(episode_id, juror_id, "CREATOR_SUPPORTED", assessment,
                             idempotency_key=saved_commit_key)
await client.wait_operation(commit)
# After the chain enters REVEAL:
reveal = await client.reveal(episode_id, juror_id, idempotency_key=saved_reveal_key)
await client.wait_operation(reveal)
# After the reveal deadline, using operator credentials:
settlement = await client.settle(episode_id, idempotency_key=saved_settle_key)
await client.wait_operation(settlement)
payouts = await client.get_settlement(episode_id)
```

These methods never advance time or perform other protocol actions. Rust stores
the ballot and salt for reveal. A new Python client needs only the same service,
credentials, episode/actor IDs, and saved command keys; it need not restore a set
of committed jurors. Inspect `get_episode` to discover commitments and reveals.

After a lost submission response, resend the identical action with its saved key
to retrieve the existing operation. After a wait timeout or interrupted Python
run, use `get_operation(saved_id)`, `reconcile_operation(saved_id)`, or
`wait_operation(saved_id)` on a fresh client. Waiting returns only a successful
confirmed receipt. `CoreHTTPError` retains validated `problem.code` and
`problem.message` when available; `CoreTransportError` retains the command key
and any known operation, and `CoreOperationTimeout` retains the latest operation.
Exception messages omit request/response bodies and credentials; inspect structured
details deliberately, since the server's message may contain application data.

Wire amounts remain validated decimal integer strings, so `int(payouts.winner_payout)`
is exact. `CoreEngineAPI` retains its legacy experiment interface using exact
`Decimal` token amounts (100 base units per token), including in metrics and
decimal-string financial exports. Explicit `MockGameAPI` behavior retains floats.

For local experiments, `LocalEngine` owns the Rust process, development credentials,
and Anvil clock. Its `advance_to_deadline`, `finish_voting`, and `expire_episode`
are explicit local conveniences. `CoreEngineAPI` composes that helper to preserve
existing experiments: `cast_vote` commits, and `settle` reveals eligible recorded
commitments before settlement. The reusable `CoreClient` has no such side effects.

### Regeneration

```sh
python scripts/generate-core-client.py
python scripts/generate-core-client.py --check
```

The Rust `export_openapi` example builds the same document served at
`/v1/openapi.json`, without starting a server or chain. Generation commits both
`docs/openapi.json` and `harness/game_api/generated.py`; CI checks both against
fresh Rust output. Generated calls cover JSON and text endpoints and validate
responses through strict Pydantic models. `core_types.py` retains compatibility
names, with only local startup metadata defined outside the HTTP schema.

The small generator supports this API's schema subset and rejects unsupported
schema features. `openapi-python-client` 0.29.1 was tested against the real
document; its attrs models did not preserve strict runtime field/pattern
validation, and its NDJSON response generation was incomplete. The checked-in
generator therefore uses the existing Pydantic dependency without adding a new
client runtime. Extend it explicitly when the API introduces new schema features.

## Local lifecycle example

Start the documented local service, then set its URL and role credentials in
your shell. The examples below use environment variables rather than embedding
credentials in a shareable request file.

```sh
export GAME_URL=http://127.0.0.1:8080
export OPERATOR_TOKEN=dev-operator
export CREATOR_TOKEN=dev-creator
export CHALLENGER_TOKEN=dev-challenger
export JUROR_TOKEN=dev-juror-1
```

These `dev-*` credentials are only for explicit `--local` mode. Additional local
credentials are `dev-juror-2` through `dev-juror-7` and `dev-treasury`. Each local
process starts a fresh Anvil deployment and SQLite run directory. For persistent
deployments and recovery across process restarts, use the documented `--config`
mode and retain that deployment's database and chain.

Creating a game requires only its ID, participants, and protocol parameters.
Experiment IDs, scenarios, agent models, prompts, treatments, and evaluation
records belong to the external harness. Optional legacy `experiment_id`,
`scenario_id`, and `provenance` tags remain accepted as opaque public correlation
data for compatibility; they are not required and trigger no harness behavior.
Never include private observations, labels, keys, or unrevealed decisions in
these public tags.

Register an episode with an equal party bond of 1,000 base units and a juror bond
of `floor(1000 × 1000 / 10000) = 100` base units. The three payout shares default
to 6,000/3,000/1,000 basis points when omitted.

```sh
curl -sS "$GAME_URL/v1/episodes" \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H 'Idempotency-Key: trial-001-register' -H 'Content-Type: application/json' \
  -d '{
    "episode_id":"trial-001",
    "creator_id":"creator",
    "challenger_id":"challenger",
    "juror_ids":["juror-1","juror-2","juror-3"],
    "treasury_id":"treasury",
    "parameters":{
      "beta_wei":"1000",
      "gamma_bps":1000,
      "posting_duration_secs":300,
      "challenge_duration_secs":300,
      "commit_duration_secs":300,
      "reveal_duration_secs":300
    }
  }'
```

Post and challenge while their respective windows are open:

```sh
curl -sS "$GAME_URL/v1/episodes/trial-001/claims" \
  -H "Authorization: Bearer $CREATOR_TOKEN" \
  -H 'Idempotency-Key: trial-001-claim' -H 'Content-Type: application/json' \
  -d '{"content":"The claim text, exactly as observed."}'

curl -sS "$GAME_URL/v1/episodes/trial-001/challenges" \
  -H "Authorization: Bearer $CHALLENGER_TOKEN" \
  -H 'Idempotency-Key: trial-001-challenge' -H 'Content-Type: application/json' \
  -d '{"evidence":"The counter-evidence text."}'
```

Each participating juror commits a verdict and assessment during `COMMIT`.
Committing also deposits that juror's bond. The service generates a fresh random
salt and durably records reveal material before broadcasting. Commit responses,
episode queries, and operation queries never expose the salt or unrevealed vote.

```sh
curl -sS "$GAME_URL/v1/episodes/trial-001/commitments" \
  -H "Authorization: Bearer $JUROR_TOKEN" \
  -H 'Idempotency-Key: trial-001-juror-1-commit' -H 'Content-Type: application/json' \
  -d '{"verdict":"CREATOR_SUPPORTED","assessment":"My assessment of the supplied evidence."}'
```

Repeat for the other jurors with their credentials and keys. During local tests
the test driver advances Anvil time; production clients wait for the stored
deadlines. The HTTP API has no administrative phase-advance endpoint.

At or after `commit_deadline` and before `reveal_deadline`, each committer reveals:

```sh
curl -sS "$GAME_URL/v1/episodes/trial-001/reveals" \
  -H "Authorization: Bearer $JUROR_TOKEN" \
  -H 'Idempotency-Key: trial-001-juror-1-reveal' -H 'Content-Type: application/json' -d '{}'
```

After `reveal_deadline`, settle and inspect the result:

```sh
curl -sS "$GAME_URL/v1/episodes/trial-001/settle" \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H 'Idempotency-Key: trial-001-settle' -H 'Content-Type: application/json' -d '{}'
curl -sS "$GAME_URL/v1/episodes/trial-001/settlement"
curl -sS "$GAME_URL/v1/episodes/trial-001/balances"
```

Every credited participant, including the treasury, withdraws using its own
credential. A withdrawal receives **all current credits for that address across
episodes**. Historical episode entitlements remain available after withdrawal.

```sh
curl -sS "$GAME_URL/v1/episodes/trial-001/withdrawals" \
  -H "Authorization: Bearer $CREATOR_TOKEN" \
  -H 'Idempotency-Key: trial-001-creator-withdraw' -H 'Content-Type: application/json' -d '{}'
```

If no claim is posted, expire at the posting deadline (`EXPIRED_UNFUNDED`). If a
claim is posted without a challenge, expire at the challenge deadline
(`EXPIRED_UNCHALLENGED`); the creator receives the entire party bond and no fee
or factual truth label is assigned.

## Operations, errors, and recovery

Registration returns `201` when confirmed; other successful mutations return
`200`. An operation awaiting inclusion or the configured confirmation depth
returns `202`. These codes describe an operation's actual state, not an invented
successful economic action. Poll its `operation_id`:

Wait for `confirmed` before submitting a dependent command. A `202` response
does not establish that the action was included; `reverted` and `failed` are
terminal operation failures, even when a later operation query returns HTTP `200`.

```sh
curl -sS "$GAME_URL/v1/operations/<operation-id>"
curl -sS "$GAME_URL/v1/operations/<operation-id>/reconcile" \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H 'Idempotency-Key: reconciliation-001' -H 'Content-Type: application/json' -d '{}'
```

Operations distinguish accepted, prepared, submitted, included, confirmed,
reverted, and failed states. A transaction receipt includes hash, block number
and hash, gas used, effective gas price, and confirmation count. Confirmation
depth is explicit and is never labeled finality. On uncertain submissions,
reconciliation uses the saved signed transaction hash and nonce instead of
signing a second economic action. Keep the private SQLite file and reveal
material when restarting the service; a public export is not a recovery backup.

Errors have a stable JSON envelope:

```json
{"error":{"code":"INVALID_REQUEST","message":"Request JSON is invalid."}}
```

Missing/invalid credentials return `401`, disallowed credentials return `403`,
unknown resources return `404`, conflicting commands or rejected game actions
return `409`, malformed requests return `422`, oversized bodies return `413`,
and unavailable chain services return `503`. Internal failures return a generic
`500` without exposing keys, tokens, private command bodies, or RPC credentials.

## Chain evidence replay and export

The operator can replay logs from the configured contract's deployment block.
Each inclusive range must contain at most 10,000 blocks. Repeated replay
deduplicates events by chain ID, contract, block hash, transaction hash, and log
index; canonical block checks rewind affected evidence before rebuilding.
Replay reconciles evidence and cannot change financial state or create payouts.
It does not use command idempotency keys: unchanged event identities cannot be
inserted twice, while a repeated range may report fewer newly recorded events.

```sh
curl -sS "$GAME_URL/v1/chain/replay" \
  -H "Authorization: Bearer $OPERATOR_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"from_block":1,"to_block":1000}'
curl -sS "$GAME_URL/v1/chain/events?from_block=1&to_block=1000" > chain-events.jsonl
```

The export uses `application/x-ndjson`: one stored public on-chain event record
per line, sorted by block and log identity. It excludes private command bodies,
assessment text, reveal secrets, credentials, and wallet keys. An empty set of
stored events returns an empty stream. Replay cannot reconstruct private
off-chain artifacts or the harness's observations.

## Settlement and harness compatibility

The quorum is always `floor(configured_jury_size / 2) + 1`, even when jurors are
absent. Valid minority revealers receive the same participation reward as
majority revealers. A juror who never commits deposits nothing and forfeits
nothing. A committer who does not reveal forfeits the deposited juror bond.
No majority aborts the dispute: both party bonds and valid revealers' bonds are
refunded; only non-revealers' deposited bonds go to the treasury.

`winner_payout` includes the winner's original bond. `juror_payouts` include
juror bond refunds. `protocol_fee` includes the protocol percentage and jury
division dust, **excluding** separately reported `forfeited_bonds`. `refunds`
contains party refunds on abort/expiry; juror refunds remain in `juror_payouts`.
All monetary result fields are decimal base-unit strings. Ground truth is never
inferred from the contract's verdict.

The historical `harness/GAME_BUILDER_HANDOFF.md` cannot be used unchanged:

| Handoff operation or convention | v1 mapping |
| --- | --- |
| `register_episode` | `POST /v1/episodes`; use integer strings and odd jury 3–7 |
| `post_claim`, `challenge` | Submit artifact text to the corresponding endpoint |
| `post_juror_bond`, then `cast_vote` | Replace with commitment including verdict/assessment, then later reveal |
| `start_deliberation` | Harness schedules rounds over core forum messages; no game state override |
| `start_voting` | Read/wait for chain-derived deadlines; no operator transition |
| `settle`, `expire` | Request a terminal transaction, then read settlement |
| `get_state`, `get_balances` | Read the episode and balance endpoints |
| Jury sizes 11–101 | Rejected; changing the bound needs a protocol revision |
| Floating-point currency | Convert to exact base-unit strings before calling |

The handoff's sample with a 10-unit party bond, 1-unit juror bonds, three valid
revealers, and two forfeitures is arithmetically inconsistent. Under the specified
60/30/10 split, each of those three revealers receives **2 units**, the winner
receives 16, and the treasury receives 1 protocol unit plus 2 forfeited units:
`16 + 3 × 2 + 3 = 25` deposited units. A 1.60 juror payout applies to five valid
revealers, without those forfeitures. Integer rounding follows `SPEC.md` §9.2:
initial percentage residual goes to the winner, jury-division dust to treasury.

## Experimental private chat

The core also exposes authenticated two-participant chats. See
[the private-chat guide](private-chat.md) for create/send/read examples,
latest-only versus full history, operator audit flags, and retained transcripts.
These off-chain endpoints leave voting, escrow, and settlement unchanged.
`CoreClient` exposes participant-bound chat methods and separate operator audit
methods using the same generated, validated contract. Chat creation and sends
return chat/message models directly; do not pass these responses to
`wait_operation`. Their idempotency keys recover the original response after
an uncertain send without broadcasting a chain transaction.

## Public episode forum

The core owns one append-only public forum per episode. Assigned participants
post and read through `POST`/`GET /v1/episodes/{id}/forum/messages`; operator
transcript and usage-audit reads use `/v1/episodes/{id}/forum/transcript` and
`/v1/episodes/{id}/forum-audit`. Sends require an idempotency key and return a
message directly. All reads are bounded and cursor-paginated. Metadata audits
record senders, rounds, UTF-8 bytes, timing, and exact returned message sequences
without including message bodies. See [the public-forum guide](public-forum.md)
for credentials, examples, harness integration, and interpretation limits.
