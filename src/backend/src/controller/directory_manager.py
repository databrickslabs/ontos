"""Directory layer manager.

Reads provider configuration from ``app_settings``, dispatches to the
right concrete ``DirectoryProvider``, and caches search results in
memory for 5 minutes per (provider_type, query_shape) key. The cache
is per-instance and the manager is held as a singleton on
``app.state``.

The manager itself is provider-agnostic: adding a new provider is a
matter of registering another class in ``_PROVIDER_REGISTRY``.
"""

import time
from threading import Lock
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.controller.directory_providers import (
    DirectoryError,
    DirectoryProvider,
    EntraIdProvider,
)
from src.models.directory import (
    DirectoryProviderType,
    DirectoryStatus,
    Principal,
    SETTING_KEY_CONNECTION_NAME,
    SETTING_KEY_PROVIDER_TYPE,
)
from src.repositories.app_settings_repository import app_settings_repo

logger = get_logger(__name__)


_CACHE_TTL_SECONDS = 5 * 60
_DEFAULT_SEARCH_LIMIT = 20


# Provider registry. Adding a new provider requires only an entry here
# plus an implementation in src.controller.directory_providers; the
# manager, routes, and models stay untouched.
_PROVIDER_REGISTRY: Dict[str, Callable[[Any, str], DirectoryProvider]] = {
    DirectoryProviderType.ENTRA.value: EntraIdProvider,
}


class DirectoryManager:
    """Stateless dispatcher + per-instance TTL cache.

    All methods are safe to call from concurrent request handlers; the
    internal cache is guarded by a lock.
    """

    def __init__(self) -> None:
        self._cache: Dict[Tuple[str, str, str, str], Tuple[float, List[Principal]]] = {}
        self._lock = Lock()
        # Track which (provider_type, connection_name) tuple the cache
        # was filled for; flip => purge.
        self._cache_keyed_on: Optional[Tuple[str, str]] = None

    # ----- public API ---------------------------------------------------------

    def get_status(self, db: Session) -> DirectoryStatus:
        """Return the live ``configured`` flag plus a redaction-safe summary."""

        provider_type = app_settings_repo.get_by_key(db, SETTING_KEY_PROVIDER_TYPE)
        connection_name = app_settings_repo.get_by_key(db, SETTING_KEY_CONNECTION_NAME)
        configured = bool(provider_type) and bool(connection_name) and provider_type in _PROVIDER_REGISTRY
        return DirectoryStatus(
            configured=configured,
            provider_type=provider_type if provider_type else None,
            connection_name=connection_name if connection_name else None,
        )

    def search(
        self,
        db: Session,
        ws_client: Any,
        query: str,
        types: List[str],
        limit: int = _DEFAULT_SEARCH_LIMIT,
    ) -> List[Principal]:
        """Return up to ``limit`` principals matching ``query`` across ``types``.

        ``types`` may include any combination of ``"user"`` and
        ``"group"``. Results are de-duplicated by ``(type, id)`` to
        survive partial cache hits. Returns an empty list when the
        directory is not configured.
        """

        provider_type, connection_name = self._read_settings(db)
        if not provider_type or not connection_name:
            return []

        self._invalidate_if_keyed_changed(provider_type, connection_name)

        wanted = {t for t in types if t in {"user", "group"}} or {"user", "group"}
        results: List[Principal] = []
        seen: set = set()

        provider = self._build_provider(provider_type, ws_client, connection_name)

        if "user" in wanted:
            for p in self._cached(provider_type, connection_name, "user", query, limit,
                                  lambda: provider.search_users(query, limit)):
                key = (p.type, p.id)
                if key not in seen:
                    seen.add(key)
                    results.append(p)

        if "group" in wanted:
            for p in self._cached(provider_type, connection_name, "group", query, limit,
                                  lambda: provider.search_groups(query, limit)):
                key = (p.type, p.id)
                if key not in seen:
                    seen.add(key)
                    results.append(p)

        # Honour the caller's overall limit even after cross-type merge.
        return results[:limit]

    def test(self, db: Session, ws_client: Any) -> None:
        """Probe the configured provider. Raises ``DirectoryError`` if unhealthy."""

        provider_type, connection_name = self._read_settings(db)
        if not provider_type:
            raise DirectoryError("Directory provider is not configured")
        if not connection_name:
            raise DirectoryError("UC HTTP connection name is not configured")
        provider = self._build_provider(provider_type, ws_client, connection_name)
        provider.test()

    def invalidate_cache(self) -> None:
        """Drop all cached results. Call after any setting change."""

        with self._lock:
            self._cache.clear()
            self._cache_keyed_on = None

    # ----- internals ----------------------------------------------------------

    def _read_settings(self, db: Session) -> Tuple[Optional[str], Optional[str]]:
        provider_type = app_settings_repo.get_by_key(db, SETTING_KEY_PROVIDER_TYPE)
        connection_name = app_settings_repo.get_by_key(db, SETTING_KEY_CONNECTION_NAME)
        return (provider_type or None), (connection_name or None)

    def _build_provider(
        self,
        provider_type: str,
        ws_client: Any,
        connection_name: str,
    ) -> DirectoryProvider:
        factory = _PROVIDER_REGISTRY.get(provider_type)
        if factory is None:
            raise DirectoryError(
                f"Unknown directory provider type: {provider_type!r}"
            )
        return factory(ws_client, connection_name)

    def _invalidate_if_keyed_changed(self, provider_type: str, connection_name: str) -> None:
        with self._lock:
            current = (provider_type, connection_name)
            if self._cache_keyed_on is not None and self._cache_keyed_on != current:
                self._cache.clear()
            self._cache_keyed_on = current

    def _cached(
        self,
        provider_type: str,
        connection_name: str,
        kind: str,
        query: str,
        limit: int,
        loader: Callable[[], List[Principal]],
    ) -> List[Principal]:
        # Normalise the query so capitalisation / surrounding whitespace
        # doesn't bypass the cache.
        cache_key = (provider_type, connection_name, kind, f"{query.strip().lower()}|{limit}")
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and (now - entry[0]) < _CACHE_TTL_SECONDS:
                return entry[1]

        try:
            values = loader()
        except DirectoryError:
            raise
        except Exception as exc:
            raise DirectoryError(f"Directory lookup failed: {exc}") from exc

        with self._lock:
            self._cache[cache_key] = (time.monotonic(), values)
        return values


# Re-export for routes that only need the registry knowledge.
SUPPORTED_PROVIDER_TYPES: List[str] = list(_PROVIDER_REGISTRY.keys())


def register_provider(
    provider_type: str,
    factory: Callable[[Any, str], DirectoryProvider],
) -> None:
    """Register an additional provider implementation at runtime.

    Used by tests to inject stub providers without touching the
    production registry.
    """

    _PROVIDER_REGISTRY[provider_type] = factory


def unregister_provider(provider_type: str) -> None:
    """Inverse of :func:`register_provider`, primarily for test teardown."""

    _PROVIDER_REGISTRY.pop(provider_type, None)
