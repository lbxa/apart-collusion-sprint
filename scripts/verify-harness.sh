#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

command -v uv >/dev/null 2>&1 || { printf 'Install uv for harness verification.\n' >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { printf 'Install Docker for isolated harness tests.\n' >&2; exit 1; }
docker info >/dev/null
export UV_CACHE_DIR="${UV_CACHE_DIR:-$repo_root/.tools/uv-cache}"
uv sync --project harness --locked
python_bin="$repo_root/harness/.venv/bin/python"
"$python_bin" scripts/generate-core-client.py --check
uv run --project harness --locked ruff check harness/src harness/tests
uv run --project harness --locked ruff format --check harness/src harness/tests
uv run --project harness --locked pytest harness/tests -m 'not integration'
# Keep fast unit iteration in one process; overlap expensive integration cases.
# The swarm group keeps two 17-participant arenas off the daemon at the same time.
uv run --project harness --locked pytest harness/tests -m integration -n 2 --dist=loadgroup
