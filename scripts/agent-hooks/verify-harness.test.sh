#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/veracity-harness-gate.XXXXXX")"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/repo with spaces/scripts" "$fixture/repo with spaces/harness/.venv/bin" "$fixture/bin"
cp "$repo_root/scripts/verify-harness.sh" "$fixture/repo with spaces/scripts/verify-harness.sh"
cp "$repo_root/scripts/agent-hooks/fixtures/harness-docker.sh" "$fixture/bin/docker"
cp "$repo_root/scripts/agent-hooks/fixtures/harness-uv.sh" "$fixture/bin/uv"
cp "$repo_root/scripts/agent-hooks/fixtures/harness-python.sh" "$fixture/repo with spaces/harness/.venv/bin/python"
chmod +x "$fixture/bin/docker" "$fixture/bin/uv" "$fixture/repo with spaces/harness/.venv/bin/python"
export PATH="$fixture/bin:$PATH"
export GATE_CALLS="$fixture/gate-calls"

bash "$fixture/repo with spaces/scripts/verify-harness.sh"
[ "$(cat "$GATE_CALLS")" = "$(printf '%s\n' docker sync client lint format unit integration)" ]

for failure in docker sync client lint format unit integration; do
  : > "$GATE_CALLS"
  if GATE_FAIL="$failure" bash "$fixture/repo with spaces/scripts/verify-harness.sh" >"$fixture/output" 2>&1; then
    printf 'Harness verification hid the %s failure\n' "$failure" >&2
    exit 1
  fi
  [ "$(tail -n 1 "$GATE_CALLS")" = "$failure" ]
done

printf 'Harness verification: locked project, required Docker, unit/integration stages, and failure propagation passed.\n'
