#!/usr/bin/env bash
set -eu

# Resolve directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$(cd "${SCRIPT_DIR}/../backend" && pwd)"
DEST_DIR="${BACKEND_DIR}/static"

# Skip the frontend build when prebuilt static assets are already present
# (shipped in the deployment). This lets constrained environments ship a
# locally-built frontend and keeps the Databricks Apps builder within its
# build-time deadline instead of running npm ci + vite build from scratch.
if [[ -d "${DEST_DIR}" && -n "$(ls -A "${DEST_DIR}" 2>/dev/null)" ]]; then
  echo "Prebuilt static assets found in ${DEST_DIR}; skipping frontend build."
  exit 0
fi

FRONTEND_DIR="$(cd "${SCRIPT_DIR}/../frontend" && pwd)"
SRC_DIR="${FRONTEND_DIR}/static"

echo "Building frontend in ${FRONTEND_DIR}..."
# --legacy-peer-deps: the lockfile has a peer-dep conflict (@hookform/resolvers
# expects ajv-formats@^2 while the project pins ajv-formats@^3); without this
# flag strict npm (npm >= 7) fails `npm ci` with ERESOLVE.
npm --prefix "${FRONTEND_DIR}" ci --silent --no-audit --no-fund --legacy-peer-deps || npm --prefix "${FRONTEND_DIR}" install --silent --no-audit --no-fund --legacy-peer-deps
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


