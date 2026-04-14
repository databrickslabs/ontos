#!/usr/bin/env bash
# Regenerate pinned requirements.txt files with hashes from .in source files.
# Requires: uv (https://github.com/astral-sh/uv)
#
# Usage: ./scripts/lock-requirements.sh
set -euo pipefail

PYTHON_VERSION="3.10"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

for req_in in \
  "$REPO_ROOT/src/requirements.in" \
  "$REPO_ROOT/src/backend/requirements.in" \
  "$REPO_ROOT/src/e2e/requirements.in"; do

  req_txt="${req_in%.in}.txt"
  echo "Compiling $(basename "$(dirname "$req_in")")/$(basename "$req_in") -> $(basename "$req_txt")"
  uv pip compile "$req_in" \
    --generate-hashes \
    --python-version "$PYTHON_VERSION" \
    --output-file "$req_txt"
done

echo "Done. Commit the updated .txt files."
