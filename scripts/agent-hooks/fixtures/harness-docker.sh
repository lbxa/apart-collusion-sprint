#!/usr/bin/env bash
set -euo pipefail
[ "$*" = info ]
printf 'docker\n' >> "$GATE_CALLS"
[ "${GATE_FAIL:-}" != docker ]
