#!/usr/bin/env bash
set -euo pipefail
if [ "${FAIL_SETUP:-0}" = "1" ]; then
  exit 1
fi
touch "$(dirname "${BASH_SOURCE[0]}")/../.setup-complete"
