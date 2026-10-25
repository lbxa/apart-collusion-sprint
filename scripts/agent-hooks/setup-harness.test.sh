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

UV_CACHE_DIR="$fixture/actions-cache" bash "$fixture/repo with spaces/scripts/setup-harness.sh"
[ "$(sort -u "$UV_CALLS")" = "$fixture/actions-cache" ]
: > "$UV_CALLS"
env -u UV_CACHE_DIR bash "$fixture/repo with spaces/scripts/setup-harness.sh"
[ "$(sort -u "$UV_CALLS")" = "$fixture/repo with spaces/.tools/uv-cache" ]
printf 'Harness setup: inherited cache and workspace fallback passed.\n'
