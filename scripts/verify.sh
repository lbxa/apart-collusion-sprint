#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

for test_script in "$repo_root"/scripts/agent-hooks/*.test.sh "$repo_root"/.claude/hooks/*.test.sh; do
  [ -f "$test_script" ] || continue
  bash "$test_script"
done

cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --all-features --locked
cargo build --workspace --all-targets --all-features --locked
