#!/usr/bin/env python3
"""Search Index Reindex workflow (#1059).

Maintenance for the DB-backed search table ``search_documents``. It works on
that table only; content is never re-derived from entities (the app's startup
reconcile does that).

- ``lakebase`` engine (Lakebase Search: ``lakebase_text`` + ``lakebase_vector``):
  rebuilds the ``lakebase_bm25`` indexes. BM25 corpus statistics (IDF, average
  document length) are computed when an index is built, so they drift as rows
  change until the index is rebuilt.
- ``pg`` engine: nothing goes stale; ``--reindex_all true`` optionally rebuilds
  the full-text / trigram indexes as routine maintenance.
- Always ``ANALYZE search_documents`` afterwards.

Indexes are rebuilt with ``REINDEX INDEX CONCURRENTLY``, so search keeps working
during the run. Prints a JSON summary (engine, rows, per-index seconds).
"""
import argparse
import json
import sys
import time
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

TABLE = "search_documents"
LAKEBASE_EXTENSIONS = ("lakebase_text", "lakebase_vector")


def _qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


# ============================================================================
# Lakebase OAuth connection (same approach as the compliance_checks workflow)
# ============================================================================

def get_oauth_token(ws_client, instance_name: str) -> tuple[str, str]:
    if not instance_name or instance_name in ("None", ""):
        raise RuntimeError(
            "Lakebase identifier is required but was not provided. It is auto-detected "
            "from the Databricks App resources when the job is run from Ontos."
        )
    user = ws_client.current_user.me().user_name
    if instance_name.startswith("projects/"):
        cred = ws_client.postgres.generate_database_credential(endpoint=instance_name)
    else:
        cred = ws_client.database.generate_database_credential(
            request_id=str(uuid4()), instance_names=[instance_name],
        )
    return user, cred.token


def create_engine_from_params(ws_client, *, host: str, db: str, port: str, schema: str,
                              instance_name: str) -> Engine:
    from urllib.parse import quote

    user, token = get_oauth_token(ws_client, instance_name)
    if not all([host, user, token, db]):
        raise RuntimeError("Missing Postgres connection parameters (host/db/user/token)")
    query = f"?sslmode=require&options=-csearch_path%3D{quote(schema)}" if schema else "?sslmode=require"
    print(f"  Connecting to postgresql://{user}:****@{host}:{port}/{db} (schema {schema})")
    url = f"postgresql+psycopg2://{quote(user, safe='')}:{quote(token, safe='')}@{host}:{port}/{db}{query}"
    return create_engine(url, pool_pre_ping=True)


# ============================================================================
# Reindex
# ============================================================================

def detect_engine(conn, schema: str) -> dict[str, Any]:
    installed = {r[0] for r in conn.execute(text("SELECT extname FROM pg_extension"))}
    indexes = [
        (r[0], r[1]) for r in conn.execute(
            text("SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = :s AND tablename = :t"),
            {"s": schema, "t": TABLE},
        )
    ]
    engine = "lakebase" if all(e in installed for e in LAKEBASE_EXTENSIONS) else "pg"
    bm25 = sorted(name for name, d in indexes if "lakebase_bm25" in d.lower())
    other = sorted(name for name, d in indexes if "lakebase_bm25" not in d.lower() and not name.endswith("_pkey"))
    return {"engine": engine, "bm25_indexes": bm25, "other_indexes": other}


def _invalid_indexes(conn, schema: str, pattern: str) -> list[str]:
    return [r[0] for r in conn.execute(text(
        "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = :s AND NOT i.indisvalid AND c.relname LIKE :p"
    ), {"s": schema, "p": pattern})]


def run_reindex(engine: Engine, schema: str, *, reindex_all: bool = False) -> dict[str, Any]:
    """Rebuild the search indexes and refresh statistics. Returns a summary dict."""
    started = time.monotonic()
    # REINDEX CONCURRENTLY can't run inside a transaction block.
    with engine.connect() as raw:
        conn = raw.execution_options(isolation_level="AUTOCOMMIT")
        exists = conn.execute(
            text("SELECT 1 FROM information_schema.tables WHERE table_schema = :s AND table_name = :t"),
            {"s": schema, "t": TABLE},
        ).scalar()
        if not exists:
            raise RuntimeError(f"{schema}.{TABLE} not found; is the DB-backed search enabled (SEARCH_BACKEND=postgres)?")

        info = detect_engine(conn, schema)
        rows = int(conn.execute(text(f"SELECT count(*) FROM {_qident(schema)}.{TABLE}")).scalar() or 0)
        targets: list[str] = list(info["bm25_indexes"])
        if reindex_all:
            targets += info["other_indexes"]

        reindexed: dict[str, float | None] = {}
        failed: list[str] = []
        for name in targets:
            t0 = time.monotonic()
            try:
                conn.execute(text(f"REINDEX INDEX CONCURRENTLY {_qident(schema)}.{_qident(name)}"))
                reindexed[name] = round(time.monotonic() - t0, 3)
                print(f"  Rebuilt {name} in {reindexed[name]}s")
            except Exception as e:
                reindexed[name] = None
                failed.append(name)
                print(f"  ERROR rebuilding {name}: {e}", file=sys.stderr)
            # A failed/interrupted REINDEX CONCURRENTLY leaves an INVALID
            # <name>_ccnew copy that still costs a write per upsert: drop it.
            for leftover in _invalid_indexes(conn, schema, f"{name}_ccnew%"):
                conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {_qident(schema)}.{_qident(leftover)}"))
                print(f"  Dropped invalid leftover index {leftover}")

        t0 = time.monotonic()
        conn.execute(text(f"ANALYZE {_qident(schema)}.{TABLE}"))
        analyze_seconds = round(time.monotonic() - t0, 3)

    summary = {
        "engine": info["engine"],
        "schema": schema,
        "rows": rows,
        "reindexed": reindexed,
        "failed": failed,
        "analyze_seconds": analyze_seconds,
        "total_seconds": round(time.monotonic() - started, 3),
    }
    if info["engine"] == "lakebase" and not info["bm25_indexes"]:
        summary["note"] = "lakebase engine but no BM25 indexes yet; the app creates them at startup"
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Rebuild the DB-backed search indexes")
    parser.add_argument("--reindex_all", type=str, default="false")
    parser.add_argument("--lakebase_instance_name", type=str, required=True)
    parser.add_argument("--postgres_host", type=str, required=True)
    parser.add_argument("--postgres_db", type=str, required=True)
    parser.add_argument("--postgres_port", type=str, default="5432")
    parser.add_argument("--postgres_schema", type=str, default="public")
    parser.add_argument("--product_name", type=str, default="ontos")
    parser.add_argument("--product_version", type=str, default="0.0.0")
    args, _ = parser.parse_known_args()

    from databricks.sdk import WorkspaceClient

    ws = WorkspaceClient(product=args.product_name, product_version=args.product_version)
    engine = create_engine_from_params(
        ws, host=args.postgres_host, db=args.postgres_db, port=args.postgres_port,
        schema=args.postgres_schema, instance_name=args.lakebase_instance_name,
    )
    summary = run_reindex(engine, args.postgres_schema, reindex_all=args.reindex_all.lower() == "true")
    print("SEARCH_REINDEX_SUMMARY " + json.dumps(summary))
    if summary["failed"]:
        raise SystemExit(f"Failed to rebuild: {', '.join(summary['failed'])}")


if __name__ == "__main__":
    main()
