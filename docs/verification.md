# Verification map

Run `bash scripts/setup.sh` once, then `bash scripts/verify.sh`. Verification
must run actual local Anvil nodes; a missing tool or denied loopback listener is
a failing check, never a reason to silently skip integration tests.

## Protocol rules

`contracts/test/Veracity.t.sol` exercises SPEC sections 7–9:

- Immutable registration, participant conflicts, jury size, exact deposits,
  arithmetic bounds, and the operator's limited authority.
- Actions before deadlines and next-phase/expiry behavior at the exact deadline.
- Standard ABI commitment domain separation, wrong preimages, invalid reveals,
  duplicate commitments/reveals, and the shared Rust/Solidity encoding vector.
- Both winning sides, full-roster quorum, minority rewards, absent jurors,
  withheld reveals, aborts, and both kinds of expiry.
- Integer payout residuals and dust, aggregate credits across episodes, failed
  withdrawals, reentrancy, event-ledger reconstruction, and single settlement.

`contracts/test/VeracityInvariant.t.sol` applies randomized action sequences
and checks deposited funds against locked liabilities, withdrawal credits, and
amounts withdrawn. Unsolicited surplus must not break solvency checks. Fuzz and
invariant run counts are pinned in `contracts/foundry.toml`.

`contracts/check-artifact.sh` compares the committed deployment artifact to the
current pinned compiler output. Rust and Solidity consume the same commitment
fixture in `contracts/fixtures/commitment.json`.

## Service and API boundaries

| Test file | Evidence |
| --- | --- |
| `core/tests/game_validation.rs` | Integer parameters, exact artifacts, canonical configuration, immutable roster validation |
| `core/tests/store_records.rs` | SQLite durability, idempotency races, private records, signed intent immutability, receipt/event recovery |
| `core/tests/chain_protocol.rs` | Chain allowlist and shared ABI commitment encoding |
| `core/tests/chain_rpc.rs` | Actual deployment, identity checks, funding/fee budgets, exact-byte rebroadcast, nonces, canonical receipts, replay, bounded RPC behavior |
| `core/tests/api_boundary.rs` | Role credentials, request/schema errors, body limits, versioning, documentation, replay permissions |
| `core/tests/e2e_game.rs` | HTTP → service → SQLite → Anvil flows, complete payouts/withdrawals, privacy, retries, restarts, and reorgs |
| `core/tests/configuration.rs` | Explicit startup modes, local listener restrictions, deployment identity, secret references, and database protection |
| `core/tests/private_chat.rs` | Pair privacy, latest/history reads, audit flags, operator controls, immutable settings, HTTP documentation and caching |
| `core/tests/chat_records.rs` | Atomic migrations, audit failure rollback, racing idempotent writes, and durable chat records |
| `core/tests/public_forum.rs` | Shared history, participant/operator boundaries, exact read audits, UTF-8 limits, idempotency, pagination, concurrency, and restart persistence |
| `core/tests/forum_records.rs` | Private-chat-preserving migration, forum audit rollback, and durable communication records |

Python forum tests cover generated-client credentials and strict responses,
full multi-page reads/exports, runner observation ordering, disabled
communication, partial-failure evidence, and actual HTTP → Rust → SQLite →
Anvil runs. The two-round, three-juror acceptance run checks six sends and nine
reads, including final voting observations, against exact engine audit records.

The implementation was built outward from failing contract examples to storage
and adapter tests, then real API acceptance tests. Review findings receive a
failing regression test before the corresponding behavioral fix.

## Interpretation and limits

The gate also runs `harness/tests/` through Python's unittest runner and the
imported `harness/test_harness.py` suite. Actual subprocess acceptance tests
cover local startup/cleanup, HTTP actions, exact economics, commit/reveal,
withholding versus absence, expiry, and engine evidence in experiment records.
Use `bash scripts/verify-harness.sh` after building Rust for focused integration
work. Mock-only checks are labeled separately and never replace these tests.

Passing these tests proves the encoded game rules and local integration paths
covered by the suites. It does not establish factual truth, detect collusion,
demonstrate model alignment, or validate the external experiment harness's
observation permissions or statistical methods.

No public Amoy deployment, public-wallet funding, or live model calls are part
of default verification. Amoy requires an explicit operator-managed deployment,
verified runtime code hash, funded test wallets, and its own smoke run. Receipt
confirmation depth is reported explicitly and is not described as finality.
