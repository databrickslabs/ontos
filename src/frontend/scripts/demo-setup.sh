#!/bin/sh
# Idempotently prepare everything the ontos demo needs from a cold start:
#   1. the local Postgres role + database (backend runs migrations on startup
#      but does NOT create the role/database itself in LOCAL mode), and
#   2. the Playwright Chromium browser binary.
#
# Demo mode assumes nothing is already set up. Safe to run repeatedly — every
# step is guarded ("if not exists" / install is a no-op when present). Reads
# connection values from src/backend/.env; the password is never echoed.
set -eu

# --- locate this script and the backend .env (script lives in src/frontend/scripts) ---
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="$SCRIPT_DIR/../../backend/.env"

if [ ! -f "$ENV_FILE" ]; then
  echo "[demo-setup] ERROR: backend .env not found at $ENV_FILE" >&2
  exit 1
fi

# --- read a key's value from .env (handles KEY=value, strips optional quotes) ---
read_env() {
  grep -E "^\s*$1\s*=" "$ENV_FILE" | head -1 | sed -E "s/^\s*$1\s*=\s*//; s/^[\"']//; s/[\"']\s*$//"
}

PGUSER_APP=$(read_env POSTGRES_USER); [ -n "$PGUSER_APP" ] || PGUSER_APP=$(read_env PGUSER)
PGPASS_APP=$(read_env POSTGRES_PASSWORD); [ -n "$PGPASS_APP" ] || PGPASS_APP=$(read_env PGPASSWORD)
PGDB_APP=$(read_env POSTGRES_DB); [ -n "$PGDB_APP" ] || PGDB_APP=$(read_env PGDATABASE)
PGHOST_APP=$(read_env POSTGRES_HOST); [ -n "$PGHOST_APP" ] || PGHOST_APP=localhost
PGPORT_APP=$(read_env POSTGRES_PORT); [ -n "$PGPORT_APP" ] || PGPORT_APP=5432

if [ -z "$PGUSER_APP" ] || [ -z "$PGPASS_APP" ] || [ -z "$PGDB_APP" ]; then
  echo "[demo-setup] ERROR: POSTGRES_USER / POSTGRES_PASSWORD / POSTGRES_DB must be set in $ENV_FILE" >&2
  exit 1
fi

# --- locate psql (PATH, then common Homebrew location) ---
PSQL=$(command -v psql 2>/dev/null || true)
if [ -z "$PSQL" ]; then
  for c in /opt/homebrew/opt/postgresql@*/bin/psql /usr/local/opt/postgresql@*/bin/psql; do
    [ -x "$c" ] && PSQL="$c" && break
  done
fi
if [ -z "$PSQL" ]; then
  echo "[demo-setup] ERROR: psql not found. Is PostgreSQL installed? (brew install postgresql@16)" >&2
  exit 1
fi

SUPER=$(whoami)
# Run all admin SQL as the local superuser against the default 'postgres' db.
admin() { "$PSQL" -v ON_ERROR_STOP=1 -U "$SUPER" -h "$PGHOST_APP" -p "$PGPORT_APP" -d postgres "$@"; }

echo "[demo-setup] ensuring role '$PGUSER_APP' and database '$PGDB_APP' on $PGHOST_APP:$PGPORT_APP"

# 1) role (create if missing; keep password in sync with .env on every run)
if [ "$(admin -tAc "SELECT 1 FROM pg_roles WHERE rolname='$PGUSER_APP'")" = "1" ]; then
  PGPASS_APP="$PGPASS_APP" admin -c "ALTER ROLE \"$PGUSER_APP\" WITH LOGIN PASSWORD '$PGPASS_APP'" >/dev/null
  echo "[demo-setup]   role exists (password synced)"
else
  PGPASS_APP="$PGPASS_APP" admin -c "CREATE ROLE \"$PGUSER_APP\" WITH LOGIN PASSWORD '$PGPASS_APP'" >/dev/null
  echo "[demo-setup]   role created"
fi
# let the superuser act on behalf of the app role (needed to own/grant objects)
admin -c "GRANT \"$PGUSER_APP\" TO \"$SUPER\"" >/dev/null 2>&1 || true

# 2) database (CREATE DATABASE can't run in a txn / IF NOT EXISTS, so guard it)
if [ "$(admin -tAc "SELECT 1 FROM pg_database WHERE datname='$PGDB_APP'")" = "1" ]; then
  echo "[demo-setup]   database exists"
else
  admin -c "CREATE DATABASE \"$PGDB_APP\" OWNER \"$PGUSER_APP\"" >/dev/null
  echo "[demo-setup]   database created"
fi

# 3) privileges (idempotent)
admin -c "GRANT ALL PRIVILEGES ON DATABASE \"$PGDB_APP\" TO \"$PGUSER_APP\"" >/dev/null
"$PSQL" -v ON_ERROR_STOP=1 -U "$SUPER" -h "$PGHOST_APP" -p "$PGPORT_APP" -d "$PGDB_APP" \
  -c "GRANT USAGE, CREATE ON SCHEMA public TO \"$PGUSER_APP\"" >/dev/null

echo "[demo-setup] db ready — backend will run migrations on startup"

# --- ensure the Playwright browser is installed (no-op when already present) ---
# Use the local Playwright binary so this works regardless of cwd. `install`
# only downloads when the browser is missing, so it's cheap on repeat runs.
PW="$SCRIPT_DIR/../node_modules/.bin/playwright"
if [ -x "$PW" ]; then
  echo "[demo-setup] ensuring Playwright Chromium is installed"
  "$PW" install chromium
else
  echo "[demo-setup] WARN: local playwright binary not found at $PW (run 'yarn install' first)" >&2
fi

echo "[demo-setup] done"
