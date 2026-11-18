#!/usr/bin/env bash
set -euo pipefail
[ "$2" = --project ]
[ "$3" = harness ]
[ "$4" = --locked ]
case "$1:${5:-}:${6:-}" in
  sync::) stage=sync ;;
  run:ruff:check) stage=lint ;;
  run:ruff:format) stage=format ;;
  run:pytest:harness/tests)
    case "$*" in
      *'-m not integration'*) stage=unit ;;
      *'-m integration'*) stage=integration ;;
      *) exit 1 ;;
    esac
    ;;
  *) exit 1 ;;
esac
printf '%s\n' "$stage" >> "$GATE_CALLS"
[ "${GATE_FAIL:-}" != "$stage" ]
