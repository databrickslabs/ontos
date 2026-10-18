"""Live search-indexing managers, for write paths outside those managers.

Code that writes an entity row directly (e.g. ``workflow_executor`` flipping a
status after a review) can't call the owning manager's private reindex hook
without the app wiring. ``app.py`` registers every SearchableAsset manager here
once the SearchManager is attached; ``reindex_*`` helpers are no-ops until then
(tests, early startup) and never raise.
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.common.logging import get_logger

logger = get_logger(__name__)

_live: dict[str, Any] = {}


def register_live_search_managers(managers: Iterable[Any]) -> None:
    for mgr in managers:
        _live[type(mgr).__name__] = mgr


def get_live_manager(class_name: str) -> Any | None:
    return _live.get(class_name)


def reindex_product(db_product: Any, db: Any) -> None:
    """Refresh one data product's search entry from its DB row."""
    mgr = _live.get("DataProductsManager")
    if mgr is None or db_product is None:
        return
    try:
        mgr._update_search_index(mgr._load_product_with_tags(db_product, db=db))
    except Exception as e:
        logger.warning(f"Failed to reindex product {getattr(db_product, 'id', '?')}: {e}")


def reindex_asset(db_asset: Any) -> None:
    """Refresh one asset's search entry from its DB row."""
    mgr = _live.get("AssetsManager")
    if mgr is None or db_asset is None:
        return
    try:
        mgr._update_search_index(db_asset)
    except Exception as e:
        logger.warning(f"Failed to reindex asset {getattr(db_asset, 'id', '?')}: {e}")
