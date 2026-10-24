#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

for prerequisite in cargo rustc git jq; do
  if ! command -v "$prerequisite" >/dev/null 2>&1; then
    printf 'Missing prerequisite: %s\n' "$prerequisite" >&2
    exit 1
  fi
done

cargo fmt --version
cargo clippy --version
cargo fetch --locked
printf 'Rust workspace setup complete. Run bash scripts/verify.sh.\n'
