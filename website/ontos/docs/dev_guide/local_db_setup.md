---
sidebar_position: 3
---

# Local Database Setup

Ontos can be installed in your local environment as an application and connected to a local PostgreSQL database. The next section explains how to configure and run PostgreSQL on your machine.

### Install PostgreSQL

**macOS (Homebrew):**
```bash
brew install postgresql@16
brew services start postgresql@16
```

After installation, add to your PATH:
```bash
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
```

### Create Database and User

Connect as superuser:
```bash
psql -U $(whoami) -d postgres
```

Run these SQL commands:
```sql
-- Create application user
CREATE ROLE ontos_app_user WITH LOGIN PASSWORD '<your_password>';
GRANT ontos_app_user TO "<your_postgres_user>";

-- Create database
CREATE DATABASE app_ontos;
GRANT ALL PRIVILEGES ON DATABASE app_ontos TO ontos_app_user;
GRANT USAGE ON SCHEMA public TO ontos_app_user;
GRANT CREATE ON SCHEMA public TO ontos_app_user;
\q
```

Reconnect to the new database:
```bash
psql -U $(whoami) -d app_ontos
```

Create the application schema:
```sql
CREATE SCHEMA app_ontos;
ALTER SCHEMA app_ontos OWNER TO ontos_app_user;
GRANT USAGE ON SCHEMA app_ontos TO ontos_app_user;
GRANT ALL ON SCHEMA app_ontos TO ontos_app_user;
\q
```

### Configure Environment

Add to your `.env`:
```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_USER=ontos_app_user
POSTGRES_PASSWORD=<your_password>
POSTGRES_DB=app_ontos
POSTGRES_DB_SCHEMA=app_ontos
ENV=LOCAL
```

### Optional: DB-backed search

Locally search runs in memory by default. Deployed apps run it on Postgres (`SEARCH_BACKEND=postgres` in `app.yaml`). To do the same locally, add:

```env
SEARCH_BACKEND=postgres
SEARCH_ENGINE=auto                # auto | pg | lakebase
SEARCH_TRGM_THRESHOLD=0.45        # typo fallback; lower = more permissive
SEARCH_BACKFILL_WAIT_SECONDS=30   # first boot only: how long startup waits for the backfill
SEARCH_BACKFILL_BATCH_SIZE=500    # rows per upsert transaction
```

At startup the app checks which extensions the database has and logs the engine it picked. Locally that's the portable `pg` engine. The `lakebase` engine is only selected on a Lakebase project with Lakebase Search enabled.

With the Postgres backend, search reads from the `search_documents` table; there is no in-memory index. Every boot reconciles that table with the current entities. Entities are read at startup, and the table is written in a background thread:

- It upserts every entity in small batches, writing only rows whose content changed. Then it removes rows for entities that no longer exist.
  - If any manager fails, the removal step is skipped.
  - An entity type that no manager returned is never removed.
  - Either way, a broken manager can't empty its part of the index.
- Edits and deletions made while the reconcile runs win over its snapshot.
- Engine detection and index creation run on the same background thread. Until they finish, search answers without the typo fallback.
- If the table is empty (first boot), startup waits up to `SEARCH_BACKFILL_WAIT_SECONDS`, then serves from the partial index while the backfill finishes. Otherwise search answers from the existing rows straight away.
- With several replicas, only one reconciles at a time (Postgres advisory lock). All replicas read and write the same table.
- Progress is logged as `Search reconcile: …`. `POST /api/search/rebuild-index` starts a reconcile on demand.

To roll back, set `SEARCH_BACKEND=memory` and restart: the in-memory index is rebuilt from the entities, nothing is lost.

- **`pg_trgm`** (typo-tolerant fallback when a query has no matches) ships with Postgres. It's a trusted extension, so the app creates it itself when the app user has `CREATE` on the database, which the grants above include.
- **`pgvector`** (vector search, coming in a later release) needs a separate install: `brew install pgvector`.

To run the Postgres search tests against your local server:

```bash
cd src
SEARCH_TEST_PG_URL="postgresql+psycopg2:///postgres?host=/tmp" \
  hatch -e dev run pytest backend/src/tests/integration/test_search_*_pg.py
```

The tests create and drop their own throwaway schema.