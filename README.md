# Apart Collusion Sprint

Rust workspace for the Veracity agent testing environment described in
[SPEC.md](SPEC.md). The `runner/` package is an empty executable scaffold;
experiment execution and contracts are not implemented yet.

## Development

Install Rust through rustup, plus Bash, Git, and jq for the agent hooks. The
repository pins Rust 1.94.0, rustfmt, and Clippy in `rust-toolchain.toml`.

```sh
bash scripts/setup.sh
bash scripts/verify.sh
```

Setup checks prerequisites and fetches the committed Cargo dependency graph.
Verification runs isolated hook tests, rustfmt, Clippy with warnings denied,
Cargo tests (including doctests), and builds all workspace targets. Use
`cargo test -p veracity-runner` for focused iteration and `cargo fmt --all` to
format Rust. Commit `Cargo.lock` whenever dependencies change. No external
crates are needed for the initial scaffold.

The implementation starts with modules in `runner/`, as specified in `SPEC.md`.
Add crates only when a concrete ownership boundary needs them. The planned
`contracts/` Foundry project, scenarios, configurations, and deployment manifests
will be added with their owning implementation; Foundry is not required for
this Rust tooling setup.

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

### 2026-10-24

- Use one Cargo workspace with the initial `runner/` package to follow the spec's
  module-first implementation plan without introducing speculative crates.
- Share one Rust verification gate and one skills directory between Codex and
  Claude so their checks and instructions cannot diverge by copying files.
