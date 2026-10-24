# Repository Guidelines

## Project Structure & Module Organization

This Cargo workspace follows the Veracity agent testing specification in `SPEC.md`. Start with modules in `runner/`; add crates only for concrete ownership boundaries. `runner/src/main.rs` is currently an empty entry point.

The spec reserves `contracts/` for Foundry, `scenarios/` for fixtures, `configs/` for experiment definitions, and `deployments/` for chain manifests. Add these with their implementations. Shared skills live in `.agents/skills/`; `.claude/skills` points there. Agent definitions and hooks live in `.codex/` and `.claude/`.

## Build, Test, and Development Commands

- `bash scripts/setup.sh`: check prerequisites and fetch locked dependencies.
- `bash scripts/verify.sh`: run hook tests, formatting, Clippy, tests, and builds.
- `cargo build --workspace --locked`: build workspace packages.
- `cargo test --workspace --locked`: run unit, integration, and documentation tests.
- `cargo test -p veracity-runner`: test the runner during iteration.
- `cargo fmt --all`: format Rust sources.
- `cargo clippy --workspace --all-targets --all-features --locked -- -D warnings`: reject lint warnings.

Rust, rustfmt, and Clippy are pinned in `rust-toolchain.toml`. Commit `Cargo.lock`; update dependencies deliberately.

## Coding Style & Naming Conventions

Use Rust 2024 and rustfmt's default four-space indentation. Use `snake_case` for modules, functions, and variables; `PascalCase` for types and traits; and `SCREAMING_SNAKE_CASE` for constants. Prefer explicit ownership, typed errors, and narrow module boundaries. Share dependency versions through `[workspace.dependencies]` when needed. Workspace members inherit the unsafe-code prohibition.

## Testing Guidelines

Put unit tests beside implementation in `#[cfg(test)]` modules and integration tests under `runner/tests/`. Name tests after observable behavior. Cover protocol boundaries, transaction recovery, commitment encoding, and observation isolation as features arrive. Default tests must be deterministic and independent of public networks, funded wallets, and model APIs. No coverage percentage is configured yet.

## Commit & Pull Request Guidelines

Existing history uses short descriptive subjects. Prefer focused, imperative messages such as `Add Cargo verification hooks`. Pull requests should describe behavior, link relevant spec sections or issues, and report verification results and blockers.

## Agent-Specific Instructions

Use Context7 for current dependency and tool documentation: resolve the library ID, then query the full question. Author source and documentation directly with editing tools. Never commit wallet keys, credentials, or private observations. Both Stop hooks share `scripts/agent-hooks/stop-checks.sh`; disclose failures even when a repeated failure permits handoff.
