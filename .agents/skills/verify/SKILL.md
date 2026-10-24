---
name: verify
description: Run the Rust workspace and agent-hook verification gate before handing off repository changes. Use focused Cargo checks while iterating.
---

# Verify

Run `bash scripts/verify.sh` from the repository root. It runs isolated hook
tests, `cargo fmt --all -- --check`, Clippy with warnings denied, Cargo tests
(including doctests), and builds all workspace targets. Dependencies must match
the committed `Cargo.lock`; the toolchain is pinned in `rust-toolchain.toml`.

Iterate with `cargo test -p veracity-runner <test_name>` or the owning crate's
equivalent, then rerun the full gate after fixes. Cargo reuses build artifacts;
tests still execute. Do not substitute `cargo check` for tests or builds.

Default verification must work without public networks, model credentials, or
funded wallets. Once contract or chain behavior exists, also run its documented
Foundry and local Anvil checks. Report missing runtime evidence explicitly;
a passing scaffold does not prove the experiment protocol works.

Both Codex and Claude Stop hooks invoke the same gate. A failed first Stop
requests one repair continuation. A repeated failure emits a warning and permits
an honest handoff. It does not turn failed verification into success. Logs live
under `.harness/verification/`; include unresolved failures in the final response.
Direct `bash scripts/verify.sh` always fails if any check fails.
