# Game service architecture

## Scope and rule authority

`SPEC.md` version 0.2 defines the game rules. The HTTP API requested by the user
replaces the spec's CLI-first presentation. The external experiment harness owns
models, deliberation, coalitions, private observations, and evaluation metrics.
The game service owns episode registration, validated actions, chain submission,
artifacts, durable operation records, and settlement queries.

Game instantiation requires only game identifiers, participants, and protocol
parameters. Legacy experiment/scenario tags are optional opaque correlation
data, retained for stored-configuration compatibility. They do not drive game
rules, scheduling, agent execution, or evaluation. The engine owns no experiment
or scenario lifecycle. Tests must exercise registration without these tags.

`harness/GAME_BUILDER_HANDOFF.md` describes the harness's desired interface, but differs
from the protocol: it suggests floating-point money, juries above seven, separate
juror deposits, direct votes, and manually advanced phases. Version 1 preserves
the spec's integer base units, odd juries of three through seven, deposit-with-
commit, domain-separated commit/reveal, and immutable chain-time deadlines.
Integration documentation must explain these differences explicitly.

## Ownership and boundaries

- `contracts/`: the non-upgradeable contract owns escrow, phase guards, vote
  validation, full-roster majorities, payout accounting, and withdrawals.
- `core/src/chain/`: typed Alloy calls own signing, RPC validation, transaction
  construction, receipt evidence, and reconciliation. RPC objects stay here.
- `core/src/game/`: episode configuration, artifact integrity, immutable
  participant assignments, action coordination, and response snapshots.
- `core/src/store/`: SQLite transactions own persisted episode definitions,
  reveal secrets, idempotency records, and chain evidence.
- `core/src/api/`: versioned HTTP DTOs, authentication, request validation,
  consistent errors, and OpenAPI. Handlers delegate game operations.
- `harness/`: Python agent execution, observations, treatments, and metrics.
  Its `CoreEngineAPI` adapter owns local process lifecycle and validated `/v1`
  transport. See [the integration contract](integration.md).

Keep one crate and one process. Create modules for these real ownership
boundaries; do not introduce generic repository or service hierarchies.

## Invariants and change boundaries

Financial state is authoritative on-chain. Rust cannot override a deadline,
change a registered roster, reduce a quorum, or invent a successful receipt.
Exactly one economic action may result from retries of the same operation.
Withdrawals can access only the selected caller's credits. Commit salts and
unrevealed votes must not appear in public responses, logs, or exports.

API schemas and harness adapters may change independently of contract rules.
Contract addresses, code hashes, ABI version, chain IDs, and confirmation policy
are explicit deployment identity. Only Anvil (31337) and Amoy (80002) are allowed;
the default development flow uses an isolated local Anvil instance.

## Failure and consistency model

SQLite transactions reserve an idempotency key and persist intent before any
broadcast. Persist reveal material before commitments. Serialize transactions
per signer. Persist signed transaction identity before submission and reconcile
uncertain submissions by hash and nonce; do not blindly sign another action.
Return distinct validation, conflict, chain-revert, and unavailable outcomes.
An unresolved operation remains inspectable and cannot be mistaken for success.

Store receipt block identity and deduplicate chain evidence. A receipt with a
configured confirmation depth is called confirmed, not finalized. Read state
from the contract instead of trusting a stale financial projection. Off-chain
records retain artifact bytes and audit information that chain logs cannot
reconstruct. Network-dependent behavior stays outside pure validation.

## Test strategy

Apply `.agents/skills/tdd/SKILL.md`: write an observable failing test, confirm
the intended failure, implement the smallest change, and expand outward.

1. Solidity examples cover both winners, abort, both expiry outcomes, exact
   deposits, immutable registration, invalid/replayed commitments, timing edges,
   absent jurors, non-reveal forfeiture, dust, and hostile withdrawals.
2. Fuzz/invariant tests check deposited funds against locked liabilities,
   outstanding credits, and withdrawals; minority votes retain entitlements.
3. Rust tests check integer DTOs, artifact hashing, canonical configuration,
   authentication, idempotency, persistent secrets, and error classification.
4. Anvil integration tests exercise the actual deployed contract through the
   versioned API and reconcile API settlement fields with on-chain balances.
5. Failure injection checks retries/restarts and uncertain transaction recovery.

No public RPC endpoint, funded public wallet, or model provider is needed for
default verification. Public Amoy execution remains an explicit deployment and
operational action, never an implicit test side effect.
