#!/usr/bin/env bash
set -euo pipefail
if [ "$1" = "--version" ]; then
  printf 'forge Version: 1.8.6\n'
  exit 0
fi
printf '%s\n' "$*" >> "$FORGE_CALLS"
if [ "${FORGE_FAIL:-}" = "$1" ]; then
  printf 'Simulated forge %s failure\n' "$1" >&2
  exit 1
fi
