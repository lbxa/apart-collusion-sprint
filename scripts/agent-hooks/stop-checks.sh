#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
hook_input="$(cat)"
if [ -z "$hook_input" ]; then
  hook_input='{}'
fi
stop_hook_active="$(printf '%s' "$hook_input" | jq -r '.stop_hook_active == true')"
mkdir -p "$repo_root/.harness/verification"
log_file="$(mktemp "$repo_root/.harness/verification/run.XXXXXX")"

if bash "$repo_root/scripts/verify.sh" >"$log_file" 2>&1; then
  printf '{}\n'
elif [ "$stop_hook_active" = "true" ]; then
  jq -n --arg message "Verification is still failing. Report the unresolved failure and log: $log_file" \
    '{systemMessage: $message}'
else
  jq -n --arg reason "Verification failed. Read $log_file, repair the failure, and rerun bash scripts/verify.sh before handing off." \
    '{decision: "block", reason: $reason}'
fi
