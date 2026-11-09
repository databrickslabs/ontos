"""Integration test for the l1 multi-domain migration backfill (#520).

The l1 migration (entity_domain_associations) uses Postgres-only SQL — gen_random_uuid(),
information_schema guards, ON CONFLICT ON CONSTRAINT, a partial-unique index, and a
uuid->varchar cast — so it cannot run on the SQLite unit suite. This test drives the REAL
migration via `alembic upgrade head` against a throwaway schema on a live Postgres, and is
SKIPPED unless a DSN is provided.

To run it, set ONTOS_TEST_PG_DSN to a psycopg2 SQLAlchemy Postgres URL for a THROWAWAY
database (driver ``postgresql+psycopg2``; supply host, port, db, user, the DB/OAuth token
as the password, and ``sslmode=require`` for Lakebase), then::

    hatch -e dev run pytest -p no:cacheprovider -o addopts="" \
      backend/src/tests/integration/test_l1_migration_backfill.py

For Lakebase, mint the token with ``databricks database generate-database-credential``
(URL-encode the ``@`` in an email username as ``%40``).
"""
import os
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

DSN = os.environ.get("ONTOS_TEST_PG_DSN")
BACKEND_DIR = Path(__file__).resolve().parents[3]  # .../src/backend

pytestmark = pytest.mark.skipif(
    not DSN, reason="ONTOS_TEST_PG_DSN not set; l1 migration backfill test needs a live Postgres."
)

PRE_L1_SETUP = """
DROP SCHEMA IF EXISTS {schema} CASCADE;
CREATE SCHEMA {schema};
SET search_path TO {schema};
CREATE TABLE data_domains (id VARCHAR PRIMARY KEY, name VARCHAR NOT NULL);
CREATE TABLE teams (id VARCHAR PRIMARY KEY, name VARCHAR, domain_id VARCHAR);
CREATE TABLE data_contracts (id VARCHAR PRIMARY KEY, name VARCHAR, domain_id VARCHAR);
CREATE TABLE assets (id UUID PRIMARY KEY DEFAULT gen_random_uuid(), name VARCHAR, domain_id VARCHAR);
CREATE TABLE data_products (id VARCHAR PRIMARY KEY, name VARCHAR, domain VARCHAR);
INSERT INTO data_domains (id, name) VALUES ('dom-sales','Sales'), ('dom-mkt','Marketing');
INSERT INTO teams (id, name, domain_id) VALUES ('team-1','T1','dom-sales');
INSERT INTO data_contracts (id, name, domain_id) VALUES ('contract-1','C1','dom-mkt');
INSERT INTO assets (id, name, domain_id) VALUES ('11111111-1111-1111-1111-111111111111','A1','dom-sales');
INSERT INTO data_products (id, name, domain) VALUES
  ('prod-id','P-ById','dom-sales'), ('prod-name','P-ByName','Marketing'), ('prod-bad','P-Bad','no-such');
CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL,
  CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num));
INSERT INTO alembic_version (version_num) VALUES ('k1_merge_aa1_c1_g3');
"""


@pytest.fixture
def schema_name():
    return "l1_migtest_" + uuid.uuid4().hex[:8]


def _engine():
    return create_engine(DSN)


def test_l1_backfills_primary_then_drops_legacy_columns(schema_name):
    engine = _engine()
    try:
        with engine.begin() as conn:
            for stmt in PRE_L1_SETUP.format(schema=schema_name).split(";"):
                if stmt.strip():
                    conn.execute(text(stmt))

        # Drive the REAL migration in that schema (stamped at k1 -> runs only l1).
        env = {**os.environ, "PGSCHEMA": schema_name, "DB_USE_PASSWORD_AUTH": "true"}
        proc = subprocess.run(
            ["hatch", "-e", "dev", "run", "alembic", "upgrade", "head"],
            cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True, timeout=300,
        )
        assert proc.returncode == 0, f"alembic upgrade failed:\n{proc.stdout}\n{proc.stderr}"

        with engine.connect() as conn:
            conn.execute(text(f'SET search_path TO {schema_name}'))
            rows = conn.execute(text(
                "SELECT eda.entity_type, eda.entity_id, dd.name, eda.is_primary "
                "FROM entity_domain_associations eda JOIN data_domains dd ON dd.id = eda.domain_id"
            )).fetchall()
            got = {(r[0], r[1]): (r[2], r[3]) for r in rows}

            # Every legacy single-domain value backfilled as PRIMARY.
            assert got[("team", "team-1")] == ("Sales", True)
            assert got[("data_contract", "contract-1")] == ("Marketing", True)
            assert got[("asset", "11111111-1111-1111-1111-111111111111")] == ("Sales", True)
            assert got[("data_product", "prod-id")] == ("Sales", True)       # resolved by id
            assert got[("data_product", "prod-name")] == ("Marketing", True)  # resolved by name
            assert ("data_product", "prod-bad") not in got                    # unresolvable -> skipped
            assert len(got) == 5

            # Legacy columns dropped.
            for table, col in [("teams", "domain_id"), ("data_contracts", "domain_id"),
                               ("assets", "domain_id"), ("data_products", "domain")]:
                exists = conn.execute(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema=:s AND table_name=:t AND column_name=:c"
                ), {"s": schema_name, "t": table, "c": col}).scalar()
                assert exists is None, f"{table}.{col} should have been dropped"
    finally:
        with engine.begin() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS {schema_name} CASCADE'))
        engine.dispose()
