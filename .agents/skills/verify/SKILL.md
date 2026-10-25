---
name: verify
description: Run the Rust workspace and agent-hook verification gate before handing off repository changes. Use focused Cargo checks while iterating.
---

# Verify

Run `bash scripts/verify.sh` from the repository root. It runs isolated hook
tests, pinned Foundry formatting/unit/fuzz/invariant tests, deployment artifact
consistency, `cargo fmt --all -- --check`, Clippy with warnings denied, Cargo tests
(including doctests), and builds all workspace targets. Dependencies must match
the committed `Cargo.lock`; the toolchain is pinned in `rust-toolchain.toml`.

Iterate with `cargo test -p veracity-game-service <test_name>` or the owning crate's
equivalent, then rerun the full gate after fixes. Cargo reuses build artifacts;
tests still execute. Do not substitute `cargo check` for tests or builds.

Default verification requires local loopback listeners for isolated Anvil nodes,
but no public networks, model credentials, or funded public wallets. Run setup
first to install pinned Foundry and compiler dependencies. In managed sandboxes,
request local test execution escalation when binding is denied; do not convert
these failures into skipped tests. Report missing runtime evidence explicitly.

Both Codex and Claude Stop hooks invoke the same gate. A failed first Stop
requests one repair continuation. A repeated failure emits a warning and permits
an honest handoff. It does not turn failed verification into success. Logs live
under `.harness/verification/`; include unresolved failures in the final response.
Direct `bash scripts/verify.sh` always fails if any check fails.
