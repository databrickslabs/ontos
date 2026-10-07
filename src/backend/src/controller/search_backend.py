"""Pluggable search backend behind the ``SEARCH_BACKEND`` setting.

Two implementations, selected at startup:

- ``InMemoryBackend`` — the historical in-process index + tokenized scorer
  (``search_scoring``). Default; used for LOCAL/dev and as a fallback.
- ``PostgresBackend`` — DB-backed full-text search over the ``search_documents``
  table (``search_repository``). Lets the in-memory index be retired so search
  RAM drops from O(entities) to ~O(1).

Both expose the same surface so callers (REST route, MCP tools, index-sync
hooks) don't care which is active:

- ``search(...)``   -> paginated/faceted dict (MCP tools; matches ``search_scoring.search_index``)
- ``search_items(...)`` -> ranked ``List[SearchIndexItem]`` (REST; caller applies auth)
- ``upsert`` / ``remove`` / ``rebuild`` -> index maintenance
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional

from src.common.logging import get_logger
from src.common.search_interfaces import SearchIndexItem
from src.controller import search_scoring

logger = get_logger(__name__)


class SearchBackend(ABC):
    @abstractmethod
    def search(
        self,
        query: str,
        *,
        type_filter: Optional[str] = None,
        filters: Optional[Dict[str, Optional[str]]] = None,
        allowed_features: Optional[Iterable[str]] = None,
        limit: int = 25,
        offset: int = 0,
        include_facets: bool = True,
    ) -> Dict[str, Any]:
        """Paginated/faceted search (MCP tools)."""

    @abstractmethod
    def search_items(self, query: str, *, limit: int = 200) -> List[SearchIndexItem]:
        """Ranked items for the REST path; the caller applies permission filtering."""

    # --- index maintenance (no-op-safe) ---
    def upsert(self, items: Iterable[SearchIndexItem]) -> None:  # pragma: no cover - overridden
        ...

    def remove(self, item_id: str) -> None:  # pragma: no cover - overridden
        ...

    def rebuild(self, items: Iterable[SearchIndexItem]) -> None:  # pragma: no cover - overridden
        ...


class InMemoryBackend(SearchBackend):
    """Wraps the SearchManager's in-memory index + tokenized scorer."""

    def __init__(self, manager: Any):
        self._m = manager  # SearchManager (duck-typed to avoid a circular import)

    def search(self, query, *, type_filter=None, filters=None, allowed_features=None,
               limit=25, offset=0, include_facets=True) -> Dict[str, Any]:
        # allowed_features is unused in-memory (MCP is scope-based; REST uses search_items).
        return search_scoring.search_index(
            self._m.index, query, self._m.config,
            type_filter=type_filter, filters=filters,
            limit=limit, offset=offset, include_facets=include_facets,
        )

    def search_items(self, query, *, limit=200) -> List[SearchIndexItem]:
        scored = search_scoring.score_and_rank(self._m.index, query, self._m.config)
        return [s.item for s in scored[:limit]]

    def upsert(self, items: Iterable[SearchIndexItem]) -> None:
        for item in items:
            self._m._index_upsert_local(item)

    def remove(self, item_id: str) -> None:
        self._m._index_remove_local(item_id)

    def rebuild(self, items: Iterable[SearchIndexItem]) -> None:
        self._m.index = list(items)


class PostgresBackend(SearchBackend):
    """DB-backed full-text search over the search_documents table."""

    def __init__(self, session_factory):
        # session_factory() -> context manager yielding a Session (get_db_session).
        self._session_factory = session_factory

    def search(self, query, *, type_filter=None, filters=None, allowed_features=None,
               limit=25, offset=0, include_facets=True) -> Dict[str, Any]:
        from src.repositories import search_repository
        with self._session_factory() as db:
            return search_repository.search(
                db, query, type_filter=type_filter, filters=filters,
                allowed_features=allowed_features, limit=limit, offset=offset,
                include_facets=include_facets,
            )

    def search_items(self, query, *, limit=200) -> List[SearchIndexItem]:
        from src.repositories import search_repository
        with self._session_factory() as db:
            return search_repository.search_index_items(db, query, limit=limit)

    def upsert(self, items: Iterable[SearchIndexItem]) -> None:
        from src.repositories import search_repository
        rows = list(items)
        if not rows:
            return
        try:
            with self._session_factory() as db:
                search_repository.upsert_documents(db, rows)
        except Exception as e:  # best-effort incremental sync; periodic reindex is the backstop
            logger.warning(f"PostgresBackend.upsert failed for {len(rows)} item(s): {e}")

    def remove(self, item_id: str) -> None:
        from src.repositories import search_repository
        try:
            with self._session_factory() as db:
                search_repository.delete_document(db, item_id)
        except Exception as e:
            logger.warning(f"PostgresBackend.remove failed for {item_id}: {e}")

    def rebuild(self, items: Iterable[SearchIndexItem]) -> None:
        from src.repositories import search_repository
        rows = list(items)
        with self._session_factory() as db:
            search_repository.replace_all(db, rows)
        logger.info(f"PostgresBackend: rebuilt search_documents with {len(rows)} items.")


def create_backend(manager: Any, backend_name: str) -> SearchBackend:
    """Factory: 'postgres' -> PostgresBackend, anything else -> InMemoryBackend."""
    if (backend_name or "memory").lower() == "postgres":
        from src.common.database import get_db_session
        logger.info("SearchManager using PostgresBackend (DB-backed full-text search).")
        return PostgresBackend(get_db_session)
    logger.info("SearchManager using InMemoryBackend (in-process index).")
    return InMemoryBackend(manager)
