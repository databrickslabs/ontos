#!/usr/bin/env bash
# Regenerate pinned requirements.txt files with hashes from .in source files.
# Requires: uv (https://github.com/astral-sh/uv)
#
# Usage: ./scripts/lock-requirements.sh
set -euo pipefail

PYTHON_VERSION="3.10"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Optional: set UV_DEFAULT_INDEX to use a PyPI mirror (e.g. internal proxy).
# The index URL is NOT written into the lockfile, so the output is portable.
INDEX_ARGS=()
if [[ -n "${UV_DEFAULT_INDEX:-}" ]]; then
  echo "Using custom index: $UV_DEFAULT_INDEX"
  INDEX_ARGS=(--default-index "$UV_DEFAULT_INDEX")
fi

for req_in in \
  "$REPO_ROOT/src/requirements.in" \
  "$REPO_ROOT/src/backend/requirements.in" \
  "$REPO_ROOT/src/e2e/requirements.in"; do

  req_txt="${req_in%.in}.txt"
  echo "Compiling $(basename "$(dirname "$req_in")")/$(basename "$req_in") -> $(basename "$req_txt")"
  uv pip compile "$req_in" \
    --generate-hashes \
    --python-version "$PYTHON_VERSION" \
    "${INDEX_ARGS[@]+"${INDEX_ARGS[@]}"}" \
    --output-file "$req_txt"
done

echo "Done. Commit the updated .txt files."
