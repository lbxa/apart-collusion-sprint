#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
fixture="$(mktemp -d "${TMPDIR:-/tmp}/veracity-harness-setup.XXXXXX")"
fixture="$(cd "$fixture" && pwd)"
trap 'rm -rf "$fixture"' EXIT
mkdir -p "$fixture/repo with spaces/scripts" "$fixture/bin"
cp "$repo_root/scripts/setup-harness.sh" "$fixture/repo with spaces/scripts/setup-harness.sh"
cp "$repo_root/scripts/agent-hooks/fixtures/uv.sh" "$fixture/bin/uv"
chmod +x "$fixture/bin/uv"
export PATH="$fixture/bin:$PATH"
export UV_CALLS="$fixture/uv-calls"
export UV_ARGUMENTS="$fixture/uv-arguments"

UV_CACHE_DIR="$fixture/actions-cache" bash "$fixture/repo with spaces/scripts/setup-harness.sh"
[ "$(sort -u "$UV_CALLS")" = "$fixture/actions-cache" ]
[ "$(cat "$UV_ARGUMENTS")" = "$(printf '%s\n' sync --project "$fixture/repo with spaces/harness" --locked)" ]
: > "$UV_CALLS"
: > "$UV_ARGUMENTS"
env -u UV_CACHE_DIR bash "$fixture/repo with spaces/scripts/setup-harness.sh"
[ "$(sort -u "$UV_CALLS")" = "$fixture/repo with spaces/.tools/uv-cache" ]
[ "$(cat "$UV_ARGUMENTS")" = "$(printf '%s\n' sync --project "$fixture/repo with spaces/harness" --locked)" ]
printf 'Harness setup: single locked project, inherited cache, and workspace fallback passed.\n'
