# Veracity Game Engine and Collusion Harness

A versioned HTTP API for the Veracity dispute game in [SPEC.md](SPEC.md).
The Rust service connects to a non-upgradeable Solidity contract that enforces
escrow, timed commit/reveal voting, full-jury majorities, and withdrawal credits.
The Python experiment harness in `harness/` supplies agents, deliberation,
treatments, observations, and evaluation metrics. It wraps the Rust
engine through HTTP; experiment behavior stays outside the engine. Creating a
game through the API does not require an experiment or scenario record.

Share [the API integration guide](docs/api.md) with the harness team. The running
service exposes the same guide at `/v1/docs` and OpenAPI 3.1 at `/v1/openapi.json`.
[Architecture and rule authority](docs/architecture.md) describes the boundaries.

## Development

Install Rust through rustup, uv, Bash, Git, curl, tar, jq, `sha256sum` or `shasum`, and a native C build toolchain
for bundled SQLite. Rust 1.94.0, rustfmt, and Clippy are pinned in
`rust-toolchain.toml`; Foundry is pinned in `.foundry-version`. Setup downloads
checksum-verified Foundry binaries into `.tools/bin`, builds with pinned Solidity
0.8.28/Cancun, verifies the deployment artifact, fetches locked Rust dependencies,
and installs the locked Python dependencies into `harness/.venv` with Python 3.12.

```sh
bash scripts/setup.sh
RUST_LOG=info cargo run --locked -p veracity-game-service -- --local
```

Local mode starts an isolated Anvil instance, deploys the contract, and listens
on `http://127.0.0.1:8080`. It uses development-only credentials: `dev-operator`,
`dev-creator`, `dev-challenger`, `dev-juror-1` through `dev-juror-7`, and
`dev-treasury`. These credentials cannot be used with a non-loopback listener.

```sh
curl -sS http://127.0.0.1:8080/v1/health
curl -sS http://127.0.0.1:8080/v1/episodes \
  -H 'Authorization: Bearer dev-operator' \
  -H 'Idempotency-Key: trial-001-register' \
  -H 'Content-Type: application/json' \
  --data-binary @examples/episode.json
```

Each local invocation starts a fresh chain and records its private SQLite data
under `.harness/runs/<run-id>/game.sqlite`. `Ctrl-C` stops the server and its
node. The chain is ephemeral; use external deployment mode for experiments
that must resume across server restarts. A supplied `--database` in local mode
must be new so a fresh chain cannot silently replace an existing experiment.

## Run the integrated harness

From the repository root, after setup:

```sh
cargo build --workspace --locked
harness/.venv/bin/python harness/run_knockout.py \
  --condition knockout_honest --dry-run --episodes 2 \
  --output .harness/experiments/smoke
```

The harness starts its own Rust server and Anvil on fresh loopback ports, calls
`/v1`, commits/reveals votes, reads contract settlement, and stops both processes.
`--dry-run` selects scripted agents and still uses the real game. `--mock` is an
explicit alternative for harness-only simulations. No model key or public RPC
is needed for the command above. See [the harness guide](harness/README.md) and
[the integration contract](docs/integration.md) for units, limits, and evidence.

## API documentation

Start the local service using the Development commands above, then:

1. Open [the OpenAPI 3.1 JSON](http://127.0.0.1:8080/v1/openapi.json)
   in your browser and copy the entire document.
2. Open [Swagger Editor](https://editor.swagger.io/) and replace its example
   specification with the copied JSON. The editor renders the endpoints,
   request bodies, response schemas, and authentication requirements.

Share the JSON document with teammates so they can open the same API reference
in an OpenAPI-compatible viewer. For lifecycle examples and local credentials,
read [the integration guide](docs/api.md), also served at
[`/v1/docs`](http://127.0.0.1:8080/v1/docs). That endpoint serves Markdown;
the service does not currently bundle an interactive documentation viewer.

## Persistent deployments

Use [configs/server.example.toml](configs/server.example.toml) as a template.
Replace its placeholder contract address and expected deployed runtime code
hash with a verified deployment, then provide the referenced private keys and
unique bearer credentials through environment variables. The constructor's
operator must match `operator_id`. Restart with the same chain, configuration,
signers, and database. Run one active service process per database:

```sh
cargo run --locked -p veracity-game-service -- \
  --config configs/server.toml --database .harness/game.sqlite
```

Only explicitly configured Anvil (31337) and Polygon Amoy (80002) are accepted.
Startup checks chain identity, runtime code hash, ABI version, operator signer,
and the database's immutable deployment binding. Recovery retains signed
transactions and private reveal material instead of issuing another economic
action. Keep the private database as a recovery backup; public event exports
intentionally omit private action requests and secrets.

RPC requests have a ten-second timeout and a three-second connection timeout.
Transient HTTP 429/503 and classified RPC rate-limit responses use at most
three exponential-backoff retries, with jitter, a two-second delay cap, and
five seconds of total sleep. Semantic reverts are not retried. Broadcast retries
reuse the exact persisted signed bytes; signing is outside the retry boundary.

Public Amoy execution requires an operator-managed deployment and funded test
wallets. Default tests use local Anvil and require no public RPC or model API.

## Verification

```sh
bash scripts/verify.sh
```

The gate runs hook regression tests, Solidity formatting/unit/fuzz/invariant
tests, deployment artifact consistency, Rust formatting, Clippy with warnings
denied, Rust unit/integration/doctests, all-target builds, and Python harness
regressions including real server/Anvil acceptance tests. The Rust integration
tests deploy the real contract on isolated Anvil nodes and drive the actual HTTP
router, including retries, restart recovery, and reorg evidence. Environments
that prohibit loopback listeners must grant local network execution for these
tests; they are never silently skipped.

For focused iteration, use `cargo test -p veracity-game-service --test e2e_game` or
`.tools/bin/forge test --root contracts --match-test <name>`. Format with
`cargo fmt --all` and `.tools/bin/forge fmt --root contracts`. Deliberate contract
changes require `forge build --root contracts` followed by
`bash contracts/check-artifact.sh --write`; commit the resulting artifact.

The workspace stays in one Rust crate with `api`, `game`, `chain`, `store`, and
configuration modules. The Solidity contract owns financial rules; Rust does
not independently calculate a competing settlement ledger. See
[contracts/README.md](contracts/README.md) for the contract's acceptance tests.

## Agent tooling

`AGENTS.md` supplies shared contributor guidance; `CLAUDE.md` imports it.
`.agents/skills/` is the canonical skill directory, shared with Claude through
`.claude/skills`. Agent definitions remain in `.codex/agents` and `.claude/agents`.
Context7 runs as a standalone JavaScript documentation helper through `npx`;
Node.js is needed only for that helper, not for Rust builds or verification.

Both Stop hooks invoke `scripts/agent-hooks/stop-checks.sh`, which saves each
verification run under `.harness/verification/`. On failure it requests one
repair continuation. If verification still fails, it displays a warning and
permits a handoff that must disclose the failure. Direct verification always
returns a failing exit status when a check fails.
Hook payloads follow the [Codex](https://learn.chatgpt.com/docs/hooks) and
[Claude Code](https://code.claude.com/docs/en/hooks) event contracts.

The Claude worktree hook runs `scripts/setup.sh` in the new checkout. It uses
the cached remote default branch, falling back to `HEAD`; set
`VERACITY_WORKTREE_BASE_REF` to test or use another committed ref. Setup failure
rolls back only worktrees and branches created by that invocation.

## Changelog

### 2026-10-25

- Integrate the Python harness under `harness/` while preserving Rust and Solidity
  rule authority. Default experiment entrypoints call the Rust `/v1` API; mocks
  require an explicit flag and saved results identify their backend.
- Extend the shared verification gate to test the actual Python → Rust → Anvil
  flow without model credentials. Preserve imported historical results separately
  from new verification evidence.
- Respect an inherited `UV_CACHE_DIR` during harness setup so GitHub's setup-uv
  action saves the cache actually used; local setup falls back to `.tools/uv-cache`.

### 2026-10-24

- Expose game operations through `/v1` HTTP and generated OpenAPI because the
  external team owns the experiment harness. Keep the spec's protocol rules
  authoritative over incompatible direct-vote and floating-point handoff examples.
- Persist idempotent operations, signed transactions, reveal secrets, and receipt
  evidence before external side effects; use actual contract state for finance.
- Name the API crate `veracity-game-service` under `core/` to distinguish
  the game server from the external experiment harness.
- Use one Cargo workspace with the initial `core/` package to follow the spec's
  module-first implementation plan without introducing speculative crates.
- Share one Rust verification gate and one skills directory between Codex and
  Claude so their checks and instructions cannot diverge by copying files.
