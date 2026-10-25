# Harness and engine integration

## Architecture contract

- **Boundary and capability:** `harness/` runs experiments and agent deliberation;
  `core/` exposes `/v1` game operations; `contracts/` enforces escrow, deadlines,
  votes, settlement, and withdrawal credits. The harness calls HTTP, never SQLite
  or contract internals.
- **Change points:** models and treatments change in the harness. Protocol rules
  change in the contract and versioned API. The Python `CoreEngineAPI` adapter
  owns process lifecycle, credentials, transport, and DTO conversion.
- **Domain and invariants:** immutable episode rosters have 3, 5, or 7 jurors.
  Equal party bonds and payout shares map exactly to integer base units and basis
  points. Engine settlement is authoritative; failed infrastructure must never
  become a computed verdict or fabricated payout.
- **Ports and use cases:** `GameAPI` connects the experiment runner to either the
  Rust adapter or an explicitly selected mock. Register, post, challenge,
  commit/reveal, settle, expire, and read balances use documented `/v1` routes.
  Messages, straw polls, and simulated bribes remain harness records.
- **Lifecycle:** local runs own one Rust process and its isolated Anvil node.
  Startup uses machine-readable discovery with a fresh loopback listener;
  cleanup closes HTTP and reaps the process on success, failure, and cancellation.
  Only the owned local node may have its clock advanced to absolute deadlines.
- **Failure model:** transport errors, invalid schemas, failed or reverted
  operations, and unconfirmed transactions propagate as infrastructure failures.
  Unknown phases and settlement shapes fail closed. There is no mock fallback.
- **Idempotency and consistency:** stable per-episode, per-action keys identify
  mutating requests. Rust owns the durable journal and signed transaction
  recovery. Python accepts only confirmed actions and reads on-chain settlement;
  it does not replace the engine's repositories or transaction state machine.
- **Research exports:** preserve backend/deployment evidence, assigned attack
  targets and counts, valid reveals, and separately simulated side payments.
  Keep evaluator labels out of agent observations and memory. History detectors
  compare stable role slots; detector categories remain heuristic indicators.
- **Tests:** failing adapter regressions precede fixes. Deterministic scripted
  agents exercise actual HTTP, Rust, SQLite, Solidity, and Anvil without model
  keys or public networks. Test both winners, absent jurors, abort, expiry,
  exact payouts, custom stakes, errors, role checks, and cleanup. Run the shared
  verification gate before handoff.
