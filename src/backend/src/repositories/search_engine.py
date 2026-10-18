"""Capability-detected search engine for the Postgres search backend.

One backend, two engines, chosen by what the database actually has installed
(not by where the app runs):

- ``pg``       — portable: works on local Postgres, CI, and a Lakebase project
                 without Lakebase Search. Uses ``pg_trgm`` (and later pgvector).
- ``lakebase`` — Lakebase Search enabled: ``lakebase_text`` (BM25) +
                 ``lakebase_vector`` (ANN). Engine-specific ranking lands in
                 #1059 / #1060; until then it behaves like ``pg``.

``pg_trgm`` is available on Lakebase too, so typo tolerance works everywhere
the extension can be created.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from sqlalchemy import text

from src.common.logging import get_logger

logger = get_logger(__name__)

LAKEBASE_EXTENSIONS = frozenset({"lakebase_text", "lakebase_vector"})
# Portable extensions the engines use; created if available and permitted.
PORTABLE_EXTENSIONS = ("pg_trgm",)
VALID_ENGINES = ("auto", "pg", "lakebase")

TITLE_TRGM_INDEX = "ix_search_documents_title_trgm"


class SearchEngineUnavailable(RuntimeError):
    """An explicitly requested engine can't run on this database."""


def _qident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


@dataclass(frozen=True)
class SearchEngine:
    name: str                          # "pg" | "lakebase"
    installed: frozenset[str]          # extensions installed in the database
    ext_schemas: Mapping[str, str] = field(default_factory=dict)  # extension -> schema

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


def prepare_engine(session_factory: Callable, requested: str) -> SearchEngine:
    """Create usable portable extensions, pick the engine, ensure its indexes.

    Idempotent; safe on every startup and across replicas. Missing privileges or
    unavailable extensions degrade the engine (logged), never fail search —
    except an explicit ``SEARCH_ENGINE=lakebase`` that can't be honored.
    """
    with session_factory() as db:
        available = _available(db)
        installed = _installed(db)
    for ext in PORTABLE_EXTENSIONS:
        if ext in installed or ext not in available:
            continue
        _try_ddl(session_factory, f"CREATE EXTENSION IF NOT EXISTS {ext}", f"extension {ext}")
    with session_factory() as db:
        installed = _installed(db)

    engine = choose_engine(requested, installed.keys(), installed)
    ensure_search_indexes(session_factory, engine)
    logger.info(
        "Search engine: %s (requested=%s; pg_trgm=%s; lakebase_text=%s; lakebase_vector=%s)",
        engine.name, requested, engine.has_trgm,
        "lakebase_text" in engine.installed, "lakebase_vector" in engine.installed,
    )
    if not engine.has_trgm:
        logger.info("pg_trgm not available: the typo-tolerant search fallback is off.")
    return engine


def ensure_search_indexes(session_factory: Callable, engine: SearchEngine) -> None:
    """Engine-specific indexes on search_documents (Alembic only adds portable columns)."""
    if engine.has_trgm:
        _try_ddl(
            session_factory,
            f"CREATE INDEX IF NOT EXISTS {TITLE_TRGM_INDEX} "
            f"ON search_documents USING gin (lower(title) {engine.trgm('gin_trgm_ops')})",
            "trigram index on search_documents.title",
        )


def _try_ddl(session_factory: Callable, sql: str, what: str) -> None:
    """Run one DDL statement in its own transaction; log and continue on failure
    (insufficient privilege, a concurrent replica creating the same object)."""
    try:
        with session_factory() as db:
            db.execute(text(sql))
            db.commit()
    except Exception as e:  # pragma: no cover - environment dependent
        logger.warning(f"Could not create {what}: {e}")
