# Veracity game service

The `veracity-game-service` executable serves the `/v1` API. See
[the integration guide](../docs/api.md) for requests and
[the workspace README](../README.md) for startup and verification.

The crate's capability boundaries are: `api` authenticates and validates
HTTP; `game` coordinates immutable episode actions; `chain` owns typed RPC and
signing; `chat` owns experimental two-person communication and audit policy;
`forum` owns shared episode messages and public communication audits;
`store` owns SQLite records, the operation journal, and private reveal material.
Financial decisions remain authoritative in `contracts/src/Veracity.sol`.

See [private chat](../docs/private-chat.md) for the simple chat API. History
controls participant retrieval; operators always retain a private audit transcript.
See [public forum](../docs/public-forum.md) for shared participant history and
metadata audits of participation, volume, rounds, and exact read responses.

## Changelog

### 2026-10-25

- Add an episode-wide public forum with durable send/read metadata, separate
  operator transcript access, and usage summaries. Migrate existing databases
  atomically while preserving private chats and their audits.
- Provide episode-scoped private chat in the core. Prohibited communication is
  delivered and flagged for observation; only the operator can provision permitted
  controls. History-disabled participants see only the latest message while audit
  transcripts persist. Keep this off-chain and separate from game settlement.
- Commit chat effects and audit records together, and migrate version-one
  databases atomically. Failed audit writes must never produce unaudited messages.
- Emit one JSON startup record on stdout in local mode with the actual API/RPC
  listeners and deployment identity. Harnesses can use port zero without
  scraping diagnostic logs or guessing which Anvil instance to control.

### 2026-10-24

- Require only game inputs at registration. Experiment/scenario identifiers are
  optional legacy correlation tags; experiment execution and evaluation belong
  to the external harness, not this engine. Preserve legacy serialization so
  existing stored configurations retain their original commitment hashes.
- Use `core/` and `veracity-game-service` for the crate and executable;
  the external harness runs experiments, while this service exposes the game.
- Gas/fee budget and funding failures are retryable infrastructure outcomes,
  not contract rejections. Preserve accepted intent and ballot material so the
  harness can distinguish unavailable infrastructure from agent abstention.
- A definitively rejected unsigned commit may release its unowned reveal
  material atomically with the failed audit record. Other accepted or signed
  commitments protect that material against deletion and replacement.
- Persist signed bytes before sending; recover by hash and nonce. Only the
  matching unbroadcast reservation may be released after a persistence failure.
- Recheck every stored fork hash at a height and restore event rows from durable
  receipts. Current financial queries verify immutable local/contract agreement
  and read contract state rather than trusting an orphaned projection.
