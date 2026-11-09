#!/usr/bin/env bash
set -eu

# Resolve directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/../backend" && pwd)"
DEST_DIR="${BACKEND_DIR}/static"

# Optionally ship a locally-built frontend instead of building here, to keep a
# constrained Databricks Apps build within its build-time deadline. This is an
# explicit opt-in so a normal deploy ALWAYS rebuilds: set SKIP_FRONTEND_BUILD=1
# (e.g. in app.yaml), or drop a `.prebuilt` marker file into the static dir when
# you build it locally. If the skip is requested but no bundle is present we fail
# rather than start an app with no UI. See the "shipping a prebuilt frontend"
# note in docs/getting_started/install_databricks.
if [[ "${SKIP_FRONTEND_BUILD:-}" == "1" || -f "${DEST_DIR}/.prebuilt" ]]; then
  if [[ ! -f "${DEST_DIR}/index.html" ]]; then
    echo "Error: frontend build skipped but ${DEST_DIR}/index.html is missing" >&2
    exit 1
  fi
  echo "Using prebuilt static assets in ${DEST_DIR}; skipping frontend build."
  exit 0
fi

FRONTEND_DIR="$(cd "${SCRIPT_DIR}/../frontend" && pwd)"
SRC_DIR="${FRONTEND_DIR}/static"

echo "Building frontend in ${FRONTEND_DIR}..."
# The peer-dep conflict (@hookform/resolvers wants ajv-formats@^2, project pins ^3)
# is handled by src/frontend/.npmrc (legacy-peer-deps=true, added in #822), which
# npm reads even via --prefix — so no CLI flag is needed here.
npm --prefix "${FRONTEND_DIR}" ci --silent --no-audit --no-fund || npm --prefix "${FRONTEND_DIR}" install --silent --no-audit --no-fund
npm --prefix "${FRONTEND_DIR}" run build

if [[ ! -d "${SRC_DIR}" ]]; then
  echo "Error: build output not found at ${SRC_DIR}"
  exit 1
fi

echo "Copying assets from ${SRC_DIR} to ${DEST_DIR}..."
rm -rf "${DEST_DIR}"
mkdir -p "${DEST_DIR}"
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete "${SRC_DIR}/" "${DEST_DIR}/"
else
  cp -R "${SRC_DIR}/." "${DEST_DIR}/"
fi

echo "Static assets copied to ${DEST_DIR}"


