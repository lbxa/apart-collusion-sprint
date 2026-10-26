#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

command -v uv >/dev/null 2>&1 || { printf 'Install uv for harness-v2 verification.\n' >&2; exit 1; }
command -v docker >/dev/null 2>&1 || { printf 'Install Docker for isolated harness-v2 tests.\n' >&2; exit 1; }
docker info >/dev/null
uv sync --project harness-v2 --locked
uv run --project harness-v2 --locked ruff check harness-v2/src harness-v2/tests
uv run --project harness-v2 --locked ruff format --check harness-v2/src harness-v2/tests
uv run --project harness-v2 --locked pytest harness-v2/tests -m ''
