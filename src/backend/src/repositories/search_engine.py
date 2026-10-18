"""Capability-detected search engine for the Postgres search backend.

One backend, two engines, chosen by what the database actually has installed
(not by where the app runs):

- ``pg``       — portable: works on local Postgres, CI, and a Lakebase project
                 without Lakebase Search. Uses ``pg_trgm`` (and later pgvector).
- ``lakebase`` — Lakebase Search enabled: ``lakebase_text`` (BM25) +
                 ``lakebase_vector`` (ANN). Keyword results still come from the
                 Settings-driven scorer, exactly as on ``pg``; BM25 is an extra
                 ranked list (``search_repository.bm25_rank``, #1059) that hybrid
                 fusion (#1061) combines with it and the vector list (#1060).

``pg_trgm`` is available on Lakebase too, so typo tolerance works everywhere
the extension can be created.
"""
from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.common.logging import get_logger

logger = get_logger(__name__)

LAKEBASE_EXTENSIONS = frozenset({"lakebase_text", "lakebase_vector"})
# Portable extensions the engines use; created if available and permitted.
# ``vector`` (pgvector) only when semantic search is on (an embedding size).
PORTABLE_EXTENSIONS = ("pg_trgm", "vector")
VALID_ENGINES = ("auto", "pg", "lakebase")

TITLE_TRGM_INDEX = "ix_search_documents_title_trgm"
# Embedding ANN index (#1060): HNSW (pgvector) on pg, lakebase_ann on lakebase.
# Separate names, so switching engine replaces one with the other.
EMBEDDING_INDEXES = {"hnsw": "ix_search_documents_embedding_hnsw", "lakebase_ann": "ix_search_documents_embedding_ann"}
# lakebase engine: one lakebase_bm25 index per field tsvector (#1059).
BM25_INDEXES = {
    col: f"ix_search_documents_{col}_bm25" for col in ("title_tsv", "description_tsv", "aux_tsv")
}


class SearchEngineUnavailable(RuntimeError):
    """An explicitly requested engine can't run on this database."""


def _qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True)
class SearchEngine:
    name: str                          # "pg" | "lakebase"
    installed: frozenset[str]          # extensions installed in the database
    ext_schemas: Mapping[str, str] = field(default_factory=dict)  # extension -> schema
    # Size of the embedding column once ensured (0 = no vector column, semantic off).
    embedding_dim: int = 0

    @property
    def has_trgm(self) -> bool:
        return "pg_trgm" in self.installed

    def trgm(self, obj: str) -> str:
        """Schema-qualified pg_trgm object. The app pins ``search_path`` to its
        own schema, so an extension installed elsewhere (e.g. ``public``) must
        be referenced explicitly."""
        schema = self.ext_schemas.get("pg_trgm")
        return f"{_qident(schema)}.{obj}" if schema else obj

    def trgm_op(self, op: str) -> str:
        schema = self.ext_schemas.get("pg_trgm")
        return f"OPERATOR({_qident(schema)}.{op})" if schema else op

    @property
    def has_vector(self) -> bool:
        return "vector" in self.installed

    @property
    def vector_index_method(self) -> str:
        """lakebase_ann (storage-backed, survives scale-to-zero) where Lakebase
        Search is on, pgvector HNSW everywhere else."""
        return "lakebase_ann" if self.name == "lakebase" and "lakebase_vector" in self.installed else "hnsw"

    def vec(self, obj: str) -> str:
        schema = self.ext_schemas.get("vector")
        return f"{_qident(schema)}.{obj}" if schema else obj

    def vec_op(self, op: str = "<=>") -> str:
        schema = self.ext_schemas.get("vector")
        return f"OPERATOR({_qident(schema)}.{op})" if schema else op

    @property
    def has_bm25(self) -> bool:
        """BM25 ranking (lakebase_text) is used only on the lakebase engine."""
        return self.name == "lakebase" and "lakebase_text" in self.installed

    def bm25(self, obj: str) -> str:
        schema = self.ext_schemas.get("lakebase_text")
        return f"{_qident(schema)}.{obj}" if schema else obj

    def bm25_op(self) -> str:
        schema = self.ext_schemas.get("lakebase_text")
        return f"OPERATOR({_qident(schema)}.<@>)" if schema else "<@>"


def choose_engine(
    requested: str, installed: Iterable[str], ext_schemas: Mapping[str, str] | None = None,
) -> SearchEngine:
    """Pure selection rule (unit-testable): see module docstring."""
    req = (requested or "auto").strip().lower()
    if req not in VALID_ENGINES:
        raise SearchEngineUnavailable(
            f"SEARCH_ENGINE={requested!r} is not one of {', '.join(VALID_ENGINES)}"
        )
    inst = frozenset(installed)
    has_lakebase = inst >= LAKEBASE_EXTENSIONS
    if req == "lakebase" and not has_lakebase:
        missing = ", ".join(sorted(LAKEBASE_EXTENSIONS - inst))
        raise SearchEngineUnavailable(
            f"SEARCH_ENGINE=lakebase but the database is missing: {missing}. "
            "Enable Lakebase Search on the Lakebase project (note: this restarts all "
            "project computes and can't be undone), or set SEARCH_ENGINE=auto."
        )
    name = "lakebase" if (req == "lakebase" or (req == "auto" and has_lakebase)) else "pg"
    return SearchEngine(name=name, installed=inst, ext_schemas=dict(ext_schemas or {}))


def _installed(db) -> dict[str, str]:
    """Installed extension -> the schema it lives in."""
    rows = db.execute(text(
        "SELECT e.extname, n.nspname FROM pg_extension e "
        "JOIN pg_namespace n ON n.oid = e.extnamespace"
    ))
    return {r[0]: r[1] for r in rows}


def _available(db) -> frozenset[str]:
    return frozenset(r[0] for r in db.execute(text("SELECT name FROM pg_available_extensions")))


def prepare_engine(session_factory: Callable, requested: str, *, embedding_dim: int = 0) -> SearchEngine:
    """Create usable portable extensions, pick the engine, ensure its indexes.

    Idempotent; safe on every startup and across replicas. Missing privileges or
    unavailable extensions degrade the engine (logged), never fail search —
    except an explicit ``SEARCH_ENGINE=lakebase`` that can't be honored.
    """
    with session_factory() as db:
        available = _available(db)
        installed = _installed(db)
    wanted = [e for e in PORTABLE_EXTENSIONS if e != "vector" or embedding_dim]
    if (requested or "auto").strip().lower() in ("auto", "lakebase"):
        # Only offered once Lakebase Search is enabled on the project (that switch
        # is the irreversible step; creating the extensions is not).
        wanted += sorted(LAKEBASE_EXTENSIONS)
    for ext in wanted:
        if ext in installed or ext not in available:
            continue
        # CASCADE: lakebase_vector requires pgvector's ``vector`` extension.
        _try_ddl(session_factory, f"CREATE EXTENSION IF NOT EXISTS {ext} CASCADE", f"extension {ext}")
    with session_factory() as db:
        installed = _installed(db)

    engine = choose_engine(requested, installed.keys(), installed)
    if embedding_dim and not engine.has_vector:
        logger.info("pgvector not available: semantic search is off (lexical only).")
    elif embedding_dim and ensure_embedding_columns(session_factory, engine, embedding_dim):
        from dataclasses import replace
        engine = replace(engine, embedding_dim=embedding_dim)
    # (ensure_embedding_columns logs why semantic search is off otherwise)
    ensure_search_indexes(session_factory, engine)
    logger.info(
        "Search engine: %s (requested=%s; pg_trgm=%s; lakebase_text=%s; lakebase_vector=%s)",
        engine.name, requested, engine.has_trgm,
        "lakebase_text" in engine.installed, "lakebase_vector" in engine.installed,
    )
    if not engine.has_trgm:
        logger.info("pg_trgm not available: the typo-tolerant search fallback is off.")
    return engine


# Added outside Alembic (pgvector is optional); alembic/env.py ignores them.
EMBEDDING_COLUMNS = ("embedding", "embedding_hash", "embedded_at", "embedding_claimed_at")


def ensure_embedding_columns(session_factory: Callable, engine: SearchEngine, dim: int) -> bool:
    """Add the embedding columns (needs pgvector, so not in Alembic). Returns
    True when the column exists with ``dim`` dimensions.

    ``ALTER TABLE`` takes an ACCESS EXCLUSIVE lock even when every column
    already exists, and a waiting one blocks all reads behind it, so it only
    runs for missing columns and gives up quickly if the table is busy (the
    next startup retries)."""
    types = {
        "embedding": f"{engine.vec('vector')}({int(dim)})", "embedding_hash": "text",
        "embedded_at": "timestamptz", "embedding_claimed_at": "timestamptz",
    }
    try:
        with session_factory() as db:
            cols = dict(db.execute(text(
                "SELECT attname, atttypmod FROM pg_attribute "
                "WHERE attrelid = 'search_documents'::regclass AND attnum > 0 AND NOT attisdropped "
                "AND attname = ANY(:names)"
            ), {"names": list(EMBEDDING_COLUMNS)}).all())
            missing = [c for c in EMBEDDING_COLUMNS if c not in cols]
            if missing:
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                db.execute(text(
                    "ALTER TABLE search_documents "
                    + ", ".join(f"ADD COLUMN IF NOT EXISTS {c} {types[c]}" for c in missing)
                ))
                db.commit()
                cols["embedding"] = int(dim) if "embedding" in missing else cols["embedding"]
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning(f"Could not add the embedding columns to search_documents; semantic search is off: {e}")
        return False
    actual = cols.get("embedding")
    if int(actual) != int(dim):
        logger.error(
            f"search_documents.embedding has {actual} dimensions but SEARCH_EMBEDDING_DIM is {dim}; "
            "semantic search is off until they match. To switch models, drop the column "
            "(ALTER TABLE search_documents DROP COLUMN embedding) and restart: every document "
            "is embedded again."
        )
        return False
    return True


def ensure_search_indexes(session_factory: Callable, engine: SearchEngine) -> None:
    """Engine-specific indexes on search_documents (Alembic only adds portable columns)."""
    # CONCURRENTLY: building on a populated table must not block the writes
    # other replicas keep making to search_documents.
    if engine.has_trgm:
        _create_index_concurrently(
            session_factory, TITLE_TRGM_INDEX,
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {TITLE_TRGM_INDEX} "
            f"ON search_documents USING gin (lower(title) {engine.trgm('gin_trgm_ops')})",
        )
    if engine.has_bm25:
        for col, name in BM25_INDEXES.items():
            _create_index_concurrently(
                session_factory, name,
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON search_documents USING lakebase_bm25 ({col})",
            )
    if engine.embedding_dim:
        method = engine.vector_index_method
        name = EMBEDDING_INDEXES[method]
        _create_index_concurrently(
            session_factory, name,
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {name} ON search_documents "
            f"USING {method} (embedding {engine.vec('vector_cosine_ops')})",
        )
        for other_method, other in EMBEDDING_INDEXES.items():
            if other_method != method:
                try:
                    with _autocommit(session_factory) as conn:
                        conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {other}"))
                except Exception as e:  # pragma: no cover - environment dependent
                    logger.warning(f"Could not drop {other}: {e}")
    if engine.has_bm25:
        # Lakebase guidance for text-search tables: VACUUM (which refreshes BM25
        # statistics) should follow inserts at a fixed threshold, not a growing one.
        _try_ddl(
            session_factory,
            "ALTER TABLE search_documents SET (autovacuum_vacuum_insert_scale_factor = 0)",
            "autovacuum setting on search_documents",
        )


def refresh_bm25_statistics(session_factory: Callable, engine: Optional[SearchEngine]) -> Dict[str, Any]:
    """Rebuild the BM25 indexes so their corpus statistics (IDF, average length)
    reflect the current rows. BM25 statistics are computed at index build time,
    so run this after a bulk load (the startup reconcile) or on a schedule.
    Returns {index: seconds}; no-op off the lakebase engine."""
    if engine is None or not engine.has_bm25:
        return {}
    out: Dict[str, Any] = {}
    for name in BM25_INDEXES.values():
        started = time.monotonic()
        try:
            with _autocommit(session_factory) as conn:
                conn.execute(text(f"REINDEX INDEX CONCURRENTLY {name}"))
            out[name] = round(time.monotonic() - started, 3)
        except Exception as e:  # pragma: no cover - environment dependent
            logger.warning(f"Could not rebuild {name}: {e}")
            out[name] = None
        # An interrupted REINDEX CONCURRENTLY leaves an INVALID <name>_ccnew copy
        # that still costs a write on every upsert; drop any such leftovers.
        _drop_invalid_indexes(session_factory, f"{name}_ccnew%")
    logger.info(f"BM25 statistics refreshed: {out}")
    return out


@contextmanager
def _autocommit(session_factory: Callable):
    """A connection outside a transaction block (CONCURRENTLY DDL requires it),
    with the same connect options (pinned search_path) as the app's sessions."""
    with session_factory() as db:
        bind = db.get_bind()
    with bind.connect() as conn:
        yield conn.execution_options(isolation_level="AUTOCOMMIT")


def _drop_invalid_indexes(session_factory: Callable, name_pattern: str) -> List[str]:
    """Drop INVALID indexes (failed/interrupted CONCURRENTLY builds) in the current
    schema whose name matches ``name_pattern`` (LIKE). Returns the dropped names."""
    dropped: List[str] = []
    try:
        with _autocommit(session_factory) as conn:
            names = [r[0] for r in conn.execute(text(
                "SELECT c.relname FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = current_schema() AND NOT i.indisvalid AND c.relname LIKE :p"
            ), {"p": name_pattern})]
            for name in names:
                conn.execute(text(f"DROP INDEX CONCURRENTLY IF EXISTS {_qident(name)}"))
                dropped.append(name)
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning(f"Could not clean up invalid indexes matching {name_pattern}: {e}")
    if dropped:
        logger.warning(f"Dropped invalid search indexes: {dropped}")
    return dropped


def _create_index_concurrently(session_factory: Callable, name: str, ddl: str) -> None:
    """``CREATE INDEX CONCURRENTLY IF NOT EXISTS`` that heals a previous failed
    build: such a build leaves an INVALID index under the same name, which
    IF NOT EXISTS would otherwise skip forever."""
    _drop_invalid_indexes(session_factory, name)
    try:
        with _autocommit(session_factory) as conn:
            conn.execute(text(ddl))
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning(f"Could not create index {name}: {e}")
        _drop_invalid_indexes(session_factory, name)


def _try_ddl(session_factory: Callable, sql: str, what: str) -> None:
    """Run one DDL statement in its own transaction; log and continue on failure
    (insufficient privilege, a concurrent replica creating the same object)."""
    try:
        with session_factory() as db:
            db.execute(text(sql))
            db.commit()
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning(f"Could not create {what}: {e}")
