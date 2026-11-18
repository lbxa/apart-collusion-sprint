#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
if ! command -v uv >/dev/null 2>&1; then
  printf 'Install uv to set up the Python harness: https://docs.astral.sh/uv/getting-started/installation/\n' >&2
  exit 1
fi
export UV_CACHE_DIR="${UV_CACHE_DIR:-$repo_root/.tools/uv-cache}"
uv sync --project "$repo_root/harness" --locked
