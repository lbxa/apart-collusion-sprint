#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

for prerequisite in cargo rustc git jq curl tar; do
  if ! command -v "$prerequisite" >/dev/null 2>&1; then
    printf 'Missing prerequisite: %s\n' "$prerequisite" >&2
    exit 1
  fi
done
if ! command -v sha256sum >/dev/null 2>&1 && ! command -v shasum >/dev/null 2>&1; then
  printf 'Missing prerequisite: sha256sum or shasum\n' >&2
  exit 1
fi

export PATH="$repo_root/.tools/bin:$PATH"
required_foundry="$(cat "$repo_root/.foundry-version")"
if ! command -v forge >/dev/null 2>&1 || [ "$(forge --version | sed -n '1p')" != "forge Version: ${required_foundry#v}" ]; then
  bash "$repo_root/scripts/install-foundry.sh"
fi
forge build --root "$repo_root/contracts"
bash "$repo_root/contracts/check-artifact.sh"
cargo fmt --version
cargo clippy --version
cargo fetch --locked
bash "$repo_root/scripts/setup-harness.sh"
printf 'Engine and harness setup complete. Run bash scripts/verify.sh.\n'
