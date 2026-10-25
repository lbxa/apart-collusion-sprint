#!/usr/bin/env bash
set -euo pipefail

contract_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
built_artifact="$contract_root/out/Veracity.sol/Veracity.json"
committed_artifact="$contract_root/artifacts/Veracity.json"
normalized_artifact="$(mktemp "${TMPDIR:-/tmp}/veracity-artifact.XXXXXX")"
trap 'rm -f "$normalized_artifact"' EXIT

if [ ! -f "$built_artifact" ]; then
  printf 'Build the contract first: forge build --root contracts\n' >&2
  exit 1
fi

jq -S '{
  abi,
  bytecode: {object: .bytecode.object},
  deployedBytecode: {
    object: .deployedBytecode.object
  },
  compiler: (
    .metadata | if type == "string" then fromjson else . end | {compiler, settings}
  )
}' "$built_artifact" > "$normalized_artifact"

case "${1:---check}" in
  --write)
    cp "$normalized_artifact" "$committed_artifact"
    ;;
  --check)
    if ! cmp -s "$normalized_artifact" "$committed_artifact"; then
      printf 'Contract artifact is stale. After building, run bash contracts/check-artifact.sh --write.\n' >&2
      exit 1
    fi
    ;;
  *)
    printf 'Usage: bash contracts/check-artifact.sh [--check|--write]\n' >&2
    exit 2
    ;;
esac
