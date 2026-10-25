---
name: tdd
description: Use failing-test-first development for new Rust behavior and bug regressions. Prove important outcomes through Cargo tests, then implement and refactor within scope.
metadata:
  labels: [tdd, testing, quality, rust]
---

# Test-Driven Development

Use this workflow for meaningful behavior changes and regressions. Documentation,
empty scaffolds, and reversible formatting changes do not need artificial tests.

## Red, Green, Refactor

1. Add a focused test for an observable outcome or invariant.
2. Run it and confirm failure for the intended reason. A typo or missing fixture
   does not demonstrate the behavior under test.
3. Implement the smallest change that satisfies the requirement.
4. Rerun the focused test, then refactor while preserving behavior.
5. Run `bash scripts/verify.sh` before handoff.

## Rust Test Layout

Put unit tests in `#[cfg(test)] mod tests` near the implementation. Put integration
tests under the owning crate's `tests/` directory and public examples in doctests.
Use descriptive `snake_case` names such as `rejects_duplicate_episode_ids`.
Arrange inputs, act through the public boundary, and assert one coherent outcome.

```sh
cargo test -p veracity-game-service <test_name>
cargo test --workspace --all-features --locked
```

Use Cargo's built-in test harness. When async behavior is introduced, select
tests appropriate to the installed runtime and fetch current API documentation.
Do not add a framework simply to test synchronous code.

## Deterministic Boundaries

Use fixed seeds, controlled clocks, temporary directories, and local database
fixtures where applicable. Isolate model APIs and public RPC endpoints; local
Anvil belongs in explicit chain integration tests. Test recovery and failure
paths alongside happy paths, especially for commitments and transaction intents.

There is no configured coverage percentage. Prove the important invariants;
introduce a measurable coverage gate only with its actual tooling and agreement.
