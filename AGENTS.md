# Repository Guidelines

## Project Structure & Module Organization

This workspace implements the `SPEC.md` game engine and `/v1` API; the external harness owns experiments and agents. `core/src/` contains `api`, `game`, `chain`, `store`, and configuration modules. `contracts/` owns Solidity rules, Foundry tests, and the deployment artifact. Keep financial authority in the contract; add crates only for concrete ownership boundaries.

`docs/api.md` is the harness integration guide; `docs/architecture.md` records boundaries. `configs/` and `examples/` contain deployment and request templates. Shared skills live in `.agents/skills/`; `.claude/skills` points there. Agent definitions and hooks live in `.codex/` and `.claude/`.

## Build, Test, and Development Commands

- `bash scripts/setup.sh`: install pinned local Foundry, build contracts, and fetch locked dependencies.
- `cargo run -p veracity-game-service -- --local`: start the API with isolated Anvil.
- `bash scripts/verify.sh`: run hooks, Solidity/Rust tests, artifact checks, formatting, Clippy, and builds.
- `cargo build --workspace --locked`: build workspace packages.
- `cargo test --workspace --locked`: run unit, integration, and documentation tests.
- `cargo test -p veracity-game-service`: test the service during iteration.
- `cargo fmt --all`: format Rust sources.
- `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`: reject lint warnings.

Rust tooling is pinned in `rust-toolchain.toml`; Foundry in `.foundry-version`. Commit `Cargo.lock` and intentional artifact updates.

## Coding Style & Naming Conventions

Use Rust 2024 and rustfmt's default four-space indentation. Use `snake_case` for modules, functions, and variables; `PascalCase` for types and traits; and `SCREAMING_SNAKE_CASE` for constants. Prefer explicit ownership, typed errors, and narrow module boundaries. Share dependency versions through `[workspace.dependencies]` when needed. Workspace members inherit the unsafe-code prohibition.

## Testing Guidelines

Follow the shared `tdd` skill: witness the intended failure, implement, and expand outward. Put unit tests in `#[cfg(test)]` modules and integration tests under `core/tests/`. Contract tests live in `contracts/test/`. Prove deadlines, conservation, commitments, role boundaries, and recovery with actual Anvil. Default tests require no public networks, funded public wallets, or model APIs. Never skip chain tests silently. No coverage percentage is configured.

## Commit & Pull Request Guidelines

Use focused, imperative subjects such as `Add Cargo verification hooks`. Pull requests should describe behavior, link spec sections or issues, and report verification results and blockers.

## Agent-Specific Instructions

Use Context7 for current dependency and tool documentation: resolve the library ID, then query the full question. Author source and documentation directly with editing tools. Never commit wallet keys, credentials, or private observations. Both Stop hooks share `scripts/agent-hooks/stop-checks.sh`; disclose failures even when a repeated failure permits handoff.
