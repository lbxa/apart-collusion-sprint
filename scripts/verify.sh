#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

for test_script in "$repo_root"/scripts/agent-hooks/*.test.sh "$repo_root"/.claude/hooks/*.test.sh; do
  [ -f "$test_script" ] || continue
  bash "$test_script"
done

if [ -f "$repo_root/scripts/decision-index.py" ]; then
  python3 "$repo_root/scripts/decision-index.py" --check
fi

export PATH="$repo_root/.tools/bin:$PATH"
if [ -f "$repo_root/contracts/foundry.toml" ]; then
  required_foundry="$(cat "$repo_root/.foundry-version")"
  if ! command -v forge >/dev/null 2>&1 || [ "$(forge --version | sed -n '1p')" != "forge Version: ${required_foundry#v}" ]; then
    printf 'Install pinned Foundry with bash scripts/install-foundry.sh\n' >&2
    exit 1
  fi
  forge fmt --check --root "$repo_root/contracts"
  forge test --root "$repo_root/contracts"
  if [ -f "$repo_root/contracts/check-artifact.sh" ]; then
    bash "$repo_root/contracts/check-artifact.sh"
  fi
fi

cargo fmt --all -- --check
cargo clippy --workspace --all-targets --all-features --locked -- -D warnings
cargo test --workspace --all-features --locked
cargo build --workspace --all-targets --all-features --locked
bash "$repo_root/scripts/verify-harness.sh"
