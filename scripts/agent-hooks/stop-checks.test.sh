#!/usr/bin/env bash
set -euo pipefail
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/veracity-stop-test.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/scripts/agent-hooks"
cp "$repo_root/scripts/agent-hooks/stop-checks.sh" "$fixture/scripts/agent-hooks/"
cp "$repo_root/scripts/agent-hooks/fixtures/verify.sh" "$fixture/scripts/verify.sh"
hook="$fixture/scripts/agent-hooks/stop-checks.sh"

printf '{}' | bash "$hook" >"$fixture/output" 2>"$fixture/errors"
jq -se 'length == 1 and (.[0] | type == "object" and .decision != "block")' "$fixture/output" >/dev/null

printf '{"stop_hook_active":false}' | VERIFY_EXIT=1 bash "$hook" >"$fixture/output" 2>"$fixture/errors"
jq -se 'length == 1 and (.[0] | .decision == "block" and (.reason | contains("Verification failed")))' "$fixture/output" >/dev/null

printf '{"stop_hook_active":true}' | VERIFY_EXIT=1 bash "$hook" >"$fixture/output" 2>"$fixture/errors"
jq -se 'length == 1 and (.[0] | .decision != "block" and (.systemMessage | contains("still failing")))' "$fixture/output" >/dev/null
find "$fixture/.harness/verification" -type f -name 'run.*' | while IFS= read -r log; do
  grep -q 'Fixture verification output' "$log"
done
[ "$(find "$fixture/.harness/verification" -type f -name 'run.*' | wc -l | tr -d ' ')" = "3" ]
printf 'Stop hook: valid JSON, one repair continuation, bounded retries, and logs passed.\n'
