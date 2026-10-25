#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/veracity-verify-test.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/repo with spaces/scripts" "$fixture/bin"
cp "$repo_root/scripts/verify.sh" "$fixture/repo with spaces/scripts/verify.sh"
cp "$repo_root/scripts/agent-hooks/fixtures/verify.sh" "$fixture/repo with spaces/scripts/verify-harness.sh"
cp "$repo_root/scripts/agent-hooks/fixtures/cargo.sh" "$fixture/bin/cargo"
chmod +x "$fixture/bin/cargo"
export PATH="$fixture/bin:$PATH"
export CARGO_CALLS="$fixture/cargo-calls"
bash "$fixture/repo with spaces/scripts/verify.sh"
diff -u "$repo_root/scripts/agent-hooks/fixtures/cargo-calls.txt" "$CARGO_CALLS"

for failure in fmt clippy test build; do
  : > "$CARGO_CALLS"
  if CARGO_FAIL="$failure" bash "$fixture/repo with spaces/scripts/verify.sh" >"$fixture/output" 2>&1; then
    printf 'Verification hid a cargo %s failure\n' "$failure" >&2
    exit 1
  fi
  [ "$(tail -n 1 "$CARGO_CALLS" | cut -d ' ' -f 1)" = "$failure" ]
done

mkdir -p "$fixture/repo with spaces/contracts"
cp "$repo_root/contracts/foundry.toml" "$fixture/repo with spaces/contracts/foundry.toml"
cp "$repo_root/.foundry-version" "$fixture/repo with spaces/.foundry-version"
cp "$repo_root/scripts/agent-hooks/fixtures/forge.sh" "$fixture/bin/forge"
chmod +x "$fixture/bin/forge"
export FORGE_CALLS="$fixture/forge-calls"
for failure in fmt test; do
  : > "$CARGO_CALLS"
  if FORGE_FAIL="$failure" bash "$fixture/repo with spaces/scripts/verify.sh" >"$fixture/output" 2>&1; then
    printf 'Verification hid a forge %s failure\n' "$failure" >&2
    exit 1
  fi
  [ ! -s "$CARGO_CALLS" ]
done

if VERIFY_EXIT=1 bash "$fixture/repo with spaces/scripts/verify.sh" >"$fixture/output" 2>&1; then
  printf 'Verification hid a harness test failure\n' >&2
  exit 1
fi
[ "$(tail -n 1 "$CARGO_CALLS" | cut -d ' ' -f 1)" = build ]

mkdir -p "$fixture/repo with spaces/.claude/hooks"
cp "$repo_root/scripts/agent-hooks/fixtures/verify.sh" "$fixture/repo with spaces/.claude/hooks/failing.test.sh"
: > "$CARGO_CALLS"
if VERIFY_EXIT=1 bash "$fixture/repo with spaces/scripts/verify.sh" >"$fixture/output" 2>&1; then
  printf 'Verification hid a hook test failure\n' >&2
  exit 1
fi
[ ! -s "$CARGO_CALLS" ]
printf 'Verification: hook, Forge, Cargo, and harness failures, gate order, and locked flags passed.\n'
