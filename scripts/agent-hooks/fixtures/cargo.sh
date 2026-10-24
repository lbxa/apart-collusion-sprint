#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >> "$CARGO_CALLS"
if [ "${CARGO_FAIL:-}" = "$1" ]; then
  printf 'Simulated cargo %s failure\n' "$1" >&2
  exit 1
fi
