# Game service architecture

## Scope and rule authority

`SPEC.md` version 0.2 defines the contract mechanism; `CONSTITUTION.md` is the
canonical participant constitution. `docs/benchmark.md` owns experimental design
and evaluation thresholds. The HTTP API
replaces the spec's CLI-first presentation. The external experiment harness owns
models, deliberation, private observations, and evaluation metrics.
The game service owns episode registration, validated actions, chain submission,
artifacts, durable operation records, and settlement queries.
It also owns the public episode forum, experimental private-chat primitive,
and their separate audit trails. The harness schedules discussion and builds
observations; the core persists public messages and authenticates their reads.
Behavioral prohibition is observable rather than a transport restriction;
participant membership remains enforced. See [private chat](private-chat.md).
The [public forum](public-forum.md) is available to all assigned episode
participants, with operator transcript access kept distinct from participant use.

Game instantiation requires only game identifiers, participants, and protocol
parameters. Legacy experiment/scenario tags are optional opaque correlation
data, retained for stored-configuration compatibility. They do not drive game
rules, scheduling, agent execution, or evaluation. The engine owns no experiment
or scenario lifecycle. Tests must exercise registration without these tags.

The retired hackathon handoff is not an interface contract. Contract ABI 2
preserves integer base units, deposit-with-commit, domain-separated commit/reveal,
and immutable chain-time deadlines. It extends the ABI 1 mechanism with odd
juries of three through fifteen and transfers of existing withdrawal credit.
New deployments require ABI 2; historical ABI 1 evidence and recovery databases
remain separate and are not migrated into a new financial world.

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
- `core/src/chat/`: immutable pair/history/prohibition settings, caller policy,
  bounded messages, and audit use cases. SQLite work runs outside the chain
  mutex and off the async runtime; messages never become contract events.
- `core/src/forum/`: shared episode history, authenticated posting/reads,
  and metadata audits of public communication. Sends and their audit/retry
  records commit atomically; private chats retain separate membership rules.
- `harness/`: Python agent execution, observations, treatments, and metrics.
  `CoreClient` owns HTTP sessions and operation recovery over generated, validated
  `/v1` calls. `LocalEngine` owns development processes and Anvil time control;
  both live in `harness/src/game_api/`. Isolated participants discover and call
  the HTTP interface themselves. See
  [the integration contract](integration.md).

The harness contains no alternative game engine. Scripted test fixtures use
the same Rust/Solidity path as live agents. Experiment configuration describes
stakes and payout shares without computing a verdict, payout, refund, or bond
forfeiture. There are no simulated side payments or majority bonuses; side
payments, where a treatment allows them, are contract credit transfers. Read-only
historical export conversion preserves recorded settlements without executing
the protocol. The root constitution is retained and delivered verbatim; evaluator
labels and scenario coalition plans remain outside participant observations.

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
