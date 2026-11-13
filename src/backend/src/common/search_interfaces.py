from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Dict, Any, TYPE_CHECKING
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from src.controller.search_manager import SearchManager

from src.common.logging import get_logger

_logger = get_logger(__name__)


class SearchIndexItem(BaseModel):
    """Standardized structure for items returned by searchable assets."""
    id: str = Field(..., description="Unique identifier for the search item (e.g., 'product::uuid', 'term::uuid')")
    type: str = Field(..., description="Type of the asset (e.g., 'data-product', 'glossary-term', 'data-contract')")
    title: str = Field(..., description="Primary display title for the search result")
    description: Optional[str] = Field(None, description="Short description or snippet for context")
    link: str = Field(..., description="URL path to navigate to the item's details page")
    tags: List[str] = Field(default_factory=list, description="Associated tags for filtering/searching")
    feature_id: str = Field(..., description="Identifier of the feature this item belongs to (e.g., 'data-products', 'glossary')")
    extra_data: Dict[str, Any] = Field(
        default_factory=dict, 
        description="Additional custom fields for search indexing (e.g., owner, status, version)"
    )

    class Config:
        pass


class SearchableAsset(ABC):
    """Abstract Base Class for managers that provide searchable items."""

    _search_manager: Optional[SearchManager] = None

    def set_search_manager(self, search_manager: SearchManager) -> None:
        """Inject the SearchManager reference (called once during startup)."""
        self._search_manager = search_manager

    def _notify_index_upsert(self, item: SearchIndexItem) -> None:
        """Upsert a single item in the search index. Safe no-op if SearchManager not yet wired."""
        if self._search_manager is None:
            return
        try:
            self._search_manager.upsert_item(item)
        except Exception as e:
            _logger.warning(f"Failed to upsert search index item {item.id}: {e}")

    def _notify_index_upsert_many(self, items: List[SearchIndexItem]) -> None:
        """Upsert several items in one backend call. Safe no-op if SearchManager not yet wired."""
        if self._search_manager is None or not items:
            return
        try:
            self._search_manager.upsert_items(items)
        except Exception as e:
            _logger.warning(f"Failed to upsert {len(items)} search index items: {e}")

    def _notify_index_remove(self, item_id: str) -> None:
        """Remove a single item from the search index. Safe no-op if SearchManager not yet wired."""
        if self._search_manager is None:
            return
        try:
            self._search_manager.remove_item(item_id)
        except Exception as e:
            _logger.warning(f"Failed to remove search index item {item_id}: {e}")

    @abstractmethod
    def get_search_index_items(self) -> List[SearchIndexItem]:
        """
        Fetches items from the manager's domain and maps them
        to the standardized SearchIndexItem format.

        Returns:
            List[SearchIndexItem]: A list of items prepared for the global search index.
        """
        pass