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

By default search runs in memory. To run it on Postgres, as a deployed app will, add:

```env
SEARCH_BACKEND=postgres
SEARCH_ENGINE=auto          # auto | pg | lakebase
SEARCH_TRGM_THRESHOLD=0.45  # typo fallback; lower = more permissive
```

At startup the app checks which extensions the database has and logs the engine it picked. Locally that's the portable `pg` engine. The `lakebase` engine is only selected on a Lakebase project with Lakebase Search enabled.

- **`pg_trgm`** (typo-tolerant fallback when a query has no matches) ships with Postgres. It's a trusted extension, so the app creates it itself when the app user has `CREATE` on the database, which the grants above include.
- **`pgvector`** (vector search, coming in a later release) needs a separate install: `brew install pgvector`.

To run the Postgres search tests against your local server:

```bash
cd src
SEARCH_TEST_PG_URL="postgresql+psycopg2:///postgres?host=/tmp" \
  hatch -e dev run pytest backend/src/tests/integration/test_search_*_pg.py
```

The tests create and drop their own throwaway schema.