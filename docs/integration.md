# Harness and engine integration

This is the current single-harness integration boundary. The retired
structured-action design is documented in [the legacy guide](../harness/LEGACY.md).
See [the harness guide](../harness/README.md) for commands and
[the research contract](benchmark.md) for Collusion measurement.

## Architecture contract

- **Boundary and capability:** `harness/` runs experiments and agent deliberation;
  `core/` exposes `/v1` game operations; `contracts/` enforces escrow, deadlines,
  votes, settlement, and withdrawal credits. The harness calls HTTP, never SQLite
  or contract internals.
- **Change points:** models and treatments change in the harness. Protocol rules
  change in the contract and versioned API. Python `CoreClient` connects to an
  existing URL with supplied credentials and generated validated endpoint calls.
  `LocalEngine` owns subprocesses, development credentials, and Anvil clock control.
  The autonomous runner owns scheduling, while the participant gateway owns
  identity and information visibility. There is no legacy experiment adapter.
- **Domain and invariants:** immutable episode rosters have an odd jury of 3 to 15.
  Equal party bonds and payout shares map exactly to integer base units and basis
  points. Engine settlement is authoritative; failed infrastructure must never
  become a computed verdict or fabricated payout.
- **Ports and use cases:** `harness/src/game_api/` supplies the validated HTTP
  boundary. Register, post, challenge,
  commit/reveal, settle, expire, and read balances use documented `/v1` routes.
  Public deliberation messages are posted to the episode's core forum and read
  back under participant identities. Scheduling, configuration, annotation, and
  evaluation stay in the harness; there are no simulated financial extensions.
  `CoreClient` also exposes the separate, authenticated private-chat API; the
  experiment runner uses it for agent private messages when `private_chat` is
  enabled. Public deliberation and private messages retain separate reads,
  visibility rules, and audit records.
- **Lifecycle:** local runs own one Rust process and its isolated Anvil node.
  Startup uses machine-readable discovery with a fresh loopback listener;
  cleanup closes HTTP and reaps the process on success, failure, and cancellation.
  Only the owned local node may have its clock advanced to absolute deadlines.
  Episodic mode creates a fresh chain per case. Continuous mode retains one chain,
  accounts, and withdrawal credits across cases in the session. Conversation
  memory is an independent setting, not a proxy for financial continuity.
- **Failure model:** transport errors, invalid schemas, failed or reverted
  operations, and unconfirmed transactions propagate as infrastructure failures.
  Unknown phases and settlement shapes fail closed. No Python game backend or
  settlement calculator substitutes for an engine response.
- **Idempotency and consistency:** stable per-episode, per-action keys identify
  mutating requests. Rust owns the durable journal and signed transaction
  recovery. SDK game actions return durable operation handles; `wait_operation` and
  runner accept success only with a successful confirmed receipt.
  A saved operation ID can be reconciled after opening a fresh client. Repeating
  an uncertain request requires its original body and idempotency key.
- **Private chat:** creation and sends return typed chat/message responses,
  rather than chain-operation handles. Their stable keys prevent duplicate
  chats/messages. Member reads honor immutable latest-only/history settings;
  retained transcripts and usage audits require explicit operator methods.
  Prohibited communication is delivered and flagged. Membership remains enforced,
  and chat bodies stay out of public game state, ordinary logs, and audit metadata.
- **Public forum:** one append-only, episode-scoped forum is available to all
  assigned participants. Sends return message models directly and persist
  atomically with idempotency responses and audit events. Authenticated reads
  record the exact returned sequences. Separate operator transcript/audit
  methods expose communication volume, senders, rounds, and read patterns.
  The gateway enforces participant channel access independently of the core's
  participant authorization. Operator audit retention does not depend on
  participant history settings.
  Forum failures propagate; observations never substitute a local message cache.
  See [the forum guide](public-forum.md) for audit interpretation and pagination.
- **Precision and contract drift:** generated financial amounts remain exact
  integer strings, with no competing floating-point payout calculation.
  ABI 2 withdrawal-credit transfers are authoritative actions, separate from
  settlement entitlements and promised payments. Regenerate the OpenAPI snapshot and Python
  models/calls with `python scripts/generate-core-client.py`; the shared CI gate
  checks both against the current Rust schema builder.
- **Research exports:** preserve source/input/model versions, actual submitted
  claims, exact settlement and transfers, exposure ordering, messages/actions,
  failures, and missing evidence. Keep evaluator labels out of agent observations
  and memory. Proposal, agreement, implementation, success, independent reference
  grades, and jury outcomes are separate observations. No mechanical false-vote
  flag or model annotation supplies independent proof of collusion.
- **Provider and tracking boundary:** Cloudflare requests execute on the host
  under one campaign spending ledger and shared rate store. Provider/operator
  credentials and ledgers never enter participant containers. W&B scope and
  credential loading remain separate from the game API; uploading a completed
  artifact does not provide compute or restore an interrupted financial world.
- **Tests:** failing adapter regressions precede fixes. Deterministic scripted
  agents exercise actual HTTP, Rust, SQLite, Solidity, and Anvil without model
  keys or public networks. Test both winners, absent jurors, abort, expiry,
  exact payouts, custom stakes, errors, role checks, and cleanup. Run the shared
  verification gate before handoff.
