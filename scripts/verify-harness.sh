#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"
python_bin="$repo_root/harness/.venv/bin/python"
if [ ! -x "$python_bin" ]; then
  printf 'Harness environment missing. Run bash scripts/setup-harness.sh.\n' >&2
  exit 1
fi
export PYTHONPATH="$repo_root/harness"
export PYTHONDONTWRITEBYTECODE=1
"$python_bin" -c 'import sys; assert sys.version_info >= (3, 12), "Python 3.12+ required"'
"$python_bin" -m unittest discover -s harness/tests -v
"$python_bin" harness/test_harness.py
