#!/usr/bin/env bash
set -euo pipefail
[ "$*" = 'scripts/generate-core-client.py --check' ]
printf 'client\n' >> "$GATE_CALLS"
[ "${GATE_FAIL:-}" != client ]
