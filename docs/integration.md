# Harness and engine integration

## Architecture contract

- **Boundary and capability:** `harness/` runs experiments and agent deliberation;
  `core/` exposes `/v1` game operations; `contracts/` enforces escrow, deadlines,
  votes, settlement, and withdrawal credits. The harness calls HTTP, never SQLite
  or contract internals.
- **Change points:** models and treatments change in the harness. Protocol rules
  change in the contract and versioned API. Python `CoreClient` connects to an
  existing URL with supplied credentials and generated validated endpoint calls.
  `LocalEngine` owns subprocesses, development credentials, and Anvil clock control;
  `CoreEngineAPI` preserves the experiment interface and converts token amounts.
- **Domain and invariants:** immutable episode rosters have 3, 5, or 7 jurors.
  Equal party bonds and payout shares map exactly to integer base units and basis
  points. Engine settlement is authoritative; failed infrastructure must never
  become a computed verdict or fabricated payout.
- **Ports and use cases:** `GameAPI` connects the experiment runner to either the
  Rust adapter or an explicitly selected mock. Register, post, challenge,
  commit/reveal, settle, expire, and read balances use documented `/v1` routes.
  Deliberation messages, straw polls, and simulated bribes remain harness records.
  `CoreClient` also exposes the separate, authenticated private-chat API; the
  experiment runner does not automatically route deliberation through it.
- **Lifecycle:** local runs own one Rust process and its isolated Anvil node.
  Startup uses machine-readable discovery with a fresh loopback listener;
  cleanup closes HTTP and reaps the process on success, failure, and cancellation.
  Only the owned local node may have its clock advanced to absolute deadlines.
- **Failure model:** transport errors, invalid schemas, failed or reverted
  operations, and unconfirmed transactions propagate as infrastructure failures.
  Unknown phases and settlement shapes fail closed. There is no mock fallback.
- **Idempotency and consistency:** stable per-episode, per-action keys identify
  mutating requests. Rust owns the durable journal and signed transaction
  recovery. SDK game actions return durable operation handles; `wait_operation` and
  the experiment adapter accept success only with a successful confirmed receipt.
  A saved operation ID can be reconciled after opening a fresh client. Repeating
  an uncertain request requires its original body and idempotency key.
- **Private chat:** creation and sends return typed chat/message responses,
  rather than chain-operation handles. Their stable keys prevent duplicate
  chats/messages. Member reads honor immutable latest-only/history settings;
  retained transcripts and usage audits require explicit operator methods.
  Prohibited communication is delivered and flagged. Membership remains enforced,
  and chat bodies stay out of public game state, ordinary logs, and audit metadata.
- **Precision and contract drift:** generated amounts remain integer strings;
  the experiment adapter exposes exact Decimal token amounts. Financial exports
  encode Decimal quantities as strings. Regenerate the OpenAPI snapshot and Python
  models/calls with `python scripts/generate-core-client.py`; the shared CI gate
  checks both against the current Rust schema builder.
- **Research exports:** preserve backend/deployment evidence, assigned attack
  targets and counts, valid reveals, and separately simulated side payments.
  Keep evaluator labels out of agent observations and memory. History detectors
  compare stable role slots; detector categories remain heuristic indicators.
- **Tests:** failing adapter regressions precede fixes. Deterministic scripted
  agents exercise actual HTTP, Rust, SQLite, Solidity, and Anvil without model
  keys or public networks. Test both winners, absent jurors, abort, expiry,
  exact payouts, custom stakes, errors, role checks, and cleanup. Run the shared
  verification gate before handoff.
