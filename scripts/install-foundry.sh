#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="$(cat "$repo_root/.foundry-version")"
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) platform=darwin_arm64 ;;
  Darwin-x86_64) platform=darwin_amd64 ;;
  Linux-x86_64) platform=linux_amd64 ;;
  Linux-aarch64) platform=linux_arm64 ;;
  *) printf 'Unsupported Foundry platform\n' >&2; exit 1 ;;
esac

archive="foundry_${version}_${platform}.tar.gz"
download_dir="$(mktemp -d "${TMPDIR:-/tmp}/veracity-foundry.XXXXXX")"
trap 'rm -rf "$download_dir"' EXIT
release_url="https://github.com/foundry-rs/foundry/releases/download/$version"
curl --fail --location --retry 3 "$release_url/$archive" -o "$download_dir/$archive"
curl --fail --location --retry 3 "$release_url/${archive%.tar.gz}.sha256" -o "$download_dir/checksum"
expected_checksum="$(awk '{print $1}' "$download_dir/checksum")"
if command -v sha256sum >/dev/null 2>&1; then
  actual_checksum="$(sha256sum "$download_dir/$archive" | awk '{print $1}')"
else
  actual_checksum="$(shasum -a 256 "$download_dir/$archive" | awk '{print $1}')"
fi
if [ "$expected_checksum" != "$actual_checksum" ]; then
  printf 'Foundry release checksum mismatch\n' >&2
  exit 1
fi
mkdir -p "$repo_root/.tools/bin"
tar -xzf "$download_dir/$archive" -C "$repo_root/.tools/bin" forge anvil cast chisel
"$repo_root/.tools/bin/forge" --version
printf 'Foundry %s installed in .tools/bin\n' "$version"
