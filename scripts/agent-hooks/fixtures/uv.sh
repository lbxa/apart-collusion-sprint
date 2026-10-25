#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$UV_CACHE_DIR" >> "$UV_CALLS"
