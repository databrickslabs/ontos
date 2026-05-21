"""Directory layer manager.

Reads provider configuration from ``app_settings``, dispatches to the
right concrete ``DirectoryProvider``, and caches search results in
memory for 5 minutes per (provider_type, config_signature, query) key.
The cache is per-instance and the manager is held as a singleton on
``app.state``.

The manager itself is provider-agnostic: adding a new provider is a
matter of:

1. Implementing ``DirectoryProvider`` in ``src.controller.directory_providers``.
2. Registering it in ``_PROVIDER_REGISTRY`` below.
3. (If the provider needs new settings) adding the keys to
   ``DirectoryProviderConfig`` and to the read/write paths here.

No changes to routes or models otherwise.
"""

import time
from threading import Lock
from typing import Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.controller.directory_providers import (
    DirectoryError,
    DirectoryProvider,
    DirectoryProviderConfig,
    DirectoryProviderContext,
    EntraIdProvider,
    FileProvider,
    LakebaseProvider,
)
from src.models.directory import (
    DirectoryProviderType,
    DirectoryStatus,
    Principal,
    SETTING_KEY_CONNECTION_NAME,
    SETTING_KEY_FILE_PATH,
    SETTING_KEY_LAKEBASE_TABLE,
    SETTING_KEY_PROVIDER_TYPE,
)
from src.repositories.app_settings_repository import app_settings_repo

logger = get_logger(__name__)


_CACHE_TTL_SECONDS = 5 * 60
_DEFAULT_SEARCH_LIMIT = 20


# Provider registry. Each factory takes (context, config) and returns
# a DirectoryProvider. Adding a new provider requires only an entry
# here plus an implementation in src.controller.directory_providers;
# routes and models stay untouched.
ProviderFactory = Callable[
    [DirectoryProviderContext, DirectoryProviderConfig], DirectoryProvider
]
_PROVIDER_REGISTRY: Dict[str, ProviderFactory] = {
    DirectoryProviderType.ENTRA.value: EntraIdProvider,
    DirectoryProviderType.LAKEBASE.value: LakebaseProvider,
    DirectoryProviderType.FILE.value: FileProvider,
}


# Each provider declares which settings keys are required so the
# manager can decide ``configured=True/False`` without instantiating
# the provider.
_REQUIRED_KEYS: Dict[str, Tuple[str, ...]] = {
    DirectoryProviderType.ENTRA.value: (SETTING_KEY_CONNECTION_NAME,),
    DirectoryProviderType.LAKEBASE.value: (SETTING_KEY_LAKEBASE_TABLE,),
    DirectoryProviderType.FILE.value: (SETTING_KEY_FILE_PATH,),
}


class DirectoryManager:
    """Stateless dispatcher + per-instance TTL cache.

    All methods are safe to call from concurrent request handlers; the
    internal cache is guarded by a lock.
    """

    def __init__(self) -> None:
        self._cache: Dict[
            Tuple[str, Tuple[Optional[str], ...], str, str],
            Tuple[float, List[Principal]],
        ] = {}
        self._lock = Lock()
        # Track which (provider_type, config_signature) tuple the
        # cache was filled for; flip => purge.
        self._cache_keyed_on: Optional[Tuple[str, Tuple[Optional[str], ...]]] = None

    # ----- public API ---------------------------------------------------------

    def get_status(self, db: Session) -> DirectoryStatus:
        """Return the live ``configured`` flag plus a redaction-safe summary."""

        provider_type, config = self._read_settings(db)
        configured = self._is_configured(provider_type, config)
        return DirectoryStatus(
            configured=configured,
            provider_type=provider_type or None,
            connection_name=config.connection_name,
            lakebase_table=config.lakebase_table,
            file_path=config.file_path,
        )

    def search(
        self,
        db: Session,
        ctx: DirectoryProviderContext,
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

        provider_type, config = self._read_settings(db)
        if not self._is_configured(provider_type, config):
            return []

        assert provider_type is not None  # narrowed by _is_configured
        signature = config.signature()
        self._invalidate_if_keyed_changed(provider_type, signature)

        wanted = {t for t in types if t in {"user", "group"}} or {"user", "group"}
        results: List[Principal] = []
        seen: set = set()

        provider = self._build_provider(provider_type, ctx, config)

        if "user" in wanted:
            for p in self._cached(
                provider_type, signature, "user", query, limit,
                lambda: provider.search_users(query, limit),
            ):
                key = (p.type, p.id)
                if key not in seen:
                    seen.add(key)
                    results.append(p)

        if "group" in wanted:
            for p in self._cached(
                provider_type, signature, "group", query, limit,
                lambda: provider.search_groups(query, limit),
            ):
                key = (p.type, p.id)
                if key not in seen:
                    seen.add(key)
                    results.append(p)

        # Honour the caller's overall limit even after cross-type merge.
        return results[:limit]

    def test(self, db: Session, ctx: DirectoryProviderContext) -> None:
        """Probe the configured provider. Raises ``DirectoryError`` if unhealthy."""

        provider_type, config = self._read_settings(db)
        if not provider_type:
            raise DirectoryError("Directory provider is not configured")
        if not self._is_configured(provider_type, config):
            missing = _REQUIRED_KEYS.get(provider_type, ())
            raise DirectoryError(
                f"Provider {provider_type!r} is missing required setting(s): "
                f"{', '.join(missing)}"
            )
        provider = self._build_provider(provider_type, ctx, config)
        provider.test()

    def invalidate_cache(self) -> None:
        """Drop all cached results. Call after any setting change."""

        with self._lock:
            self._cache.clear()
            self._cache_keyed_on = None

    # ----- internals ----------------------------------------------------------

    def _read_settings(
        self, db: Session,
    ) -> Tuple[Optional[str], DirectoryProviderConfig]:
        provider_type = app_settings_repo.get_by_key(db, SETTING_KEY_PROVIDER_TYPE)
        config = DirectoryProviderConfig(
            connection_name=app_settings_repo.get_by_key(db, SETTING_KEY_CONNECTION_NAME) or None,
            lakebase_table=app_settings_repo.get_by_key(db, SETTING_KEY_LAKEBASE_TABLE) or None,
            file_path=app_settings_repo.get_by_key(db, SETTING_KEY_FILE_PATH) or None,
        )
        return (provider_type or None), config

    def _is_configured(
        self, provider_type: Optional[str], config: DirectoryProviderConfig,
    ) -> bool:
        if not provider_type or provider_type not in _PROVIDER_REGISTRY:
            return False
        required = _REQUIRED_KEYS.get(provider_type, ())
        # Translate setting keys to config-field names.
        key_to_field = {
            SETTING_KEY_CONNECTION_NAME: "connection_name",
            SETTING_KEY_LAKEBASE_TABLE: "lakebase_table",
            SETTING_KEY_FILE_PATH: "file_path",
        }
        for key in required:
            field = key_to_field.get(key)
            if field is None:
                # Defensive: an unknown required key means the
                # registry is misconfigured at code level. Treat as
                # not-configured rather than crash.
                logger.warning(
                    "Provider %s declares unknown required setting key %s",
                    provider_type, key,
                )
                return False
            if not getattr(config, field):
                return False
        return True

    def _build_provider(
        self,
        provider_type: str,
        ctx: DirectoryProviderContext,
        config: DirectoryProviderConfig,
    ) -> DirectoryProvider:
        factory = _PROVIDER_REGISTRY.get(provider_type)
        if factory is None:
            raise DirectoryError(
                f"Unknown directory provider type: {provider_type!r}"
            )
        return factory(ctx, config)

    def _invalidate_if_keyed_changed(
        self,
        provider_type: str,
        signature: Tuple[Optional[str], ...],
    ) -> None:
        with self._lock:
            current = (provider_type, signature)
            if self._cache_keyed_on is not None and self._cache_keyed_on != current:
                self._cache.clear()
            self._cache_keyed_on = current

    def _cached(
        self,
        provider_type: str,
        signature: Tuple[Optional[str], ...],
        kind: str,
        query: str,
        limit: int,
        loader: Callable[[], List[Principal]],
    ) -> List[Principal]:
        # Normalise the query so capitalisation / surrounding whitespace
        # doesn't bypass the cache.
        cache_key = (provider_type, signature, kind, f"{query.strip().lower()}|{limit}")
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
    factory: ProviderFactory,
    *,
    required_keys: Tuple[str, ...] = (),
) -> None:
    """Register an additional provider implementation at runtime.

    Used by tests to inject stub providers without touching the
    production registry. ``required_keys`` mirrors the production
    convention so the manager can compute ``configured`` correctly
    for the stub too; default empty means "no required settings".
    """

    _PROVIDER_REGISTRY[provider_type] = factory
    if required_keys:
        _REQUIRED_KEYS[provider_type] = required_keys


def unregister_provider(provider_type: str) -> None:
    """Inverse of :func:`register_provider`, primarily for test teardown."""

    _PROVIDER_REGISTRY.pop(provider_type, None)
    _REQUIRED_KEYS.pop(provider_type, None)
