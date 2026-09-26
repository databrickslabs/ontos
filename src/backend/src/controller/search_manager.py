from __future__ import annotations # Ensure forward references work
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Iterable, TYPE_CHECKING
import re

# Import Search Interfaces
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
# Import Permission Checker and Feature Access Level
if TYPE_CHECKING:
    from src.common.authorization import PermissionChecker
# Import AuthorizationManager and UserInfo
from src.controller.authorization_manager import AuthorizationManager
from src.models.users import UserInfo
from src.common.features import FeatureAccessLevel
# Import search configuration
from src.common.search_config_loader import get_search_config_loader, SearchConfigLoader
from src.models.search_config import (
    SearchConfig,
    FieldConfig,
    MatchType,
    SortField,
)
# Shared, tokenized scoring core (single source of truth for match logic).
from src.controller import search_scoring

from src.common.logging import get_logger
logger = get_logger(__name__)


@dataclass
class SearchMatch:
    """Represents a search match with scoring information."""
    item: SearchIndexItem
    matched_field: str          # Which field matched (title, description, tags, etc.)
    field_priority: int         # Priority of the matched field (lower = better)
    boost_score: float          # Boost score from the field config
    match_quality: float        # Quality of the match (1.0 = exact, 0.5 = partial, etc.)
    
    @property
    def total_score(self) -> float:
        """Calculate total score for ranking."""
        return self.boost_score * self.match_quality


class SearchManager:
    def __init__(
        self,
        searchable_managers: Iterable[SearchableAsset],
        config_loader: Optional[SearchConfigLoader] = None
    ):
        """
        Initialize search manager with a collection of pre-instantiated searchable asset managers.
        
        Args:
            searchable_managers: Iterable of managers implementing SearchableAsset
            config_loader: Optional SearchConfigLoader instance. Uses global loader if not provided.
        """
        self.searchable_managers = list(searchable_managers)
        self.index: List[SearchIndexItem] = []
        self._config_loader = config_loader or get_search_config_loader()
        
        logger.info(f"SearchManager initialized with {len(self.searchable_managers)} managers.")
        
        self.build_index() # Build index after receiving managers

    @property
    def config(self) -> SearchConfig:
        """Get the current search configuration (with hot-reload support)."""
        return self._config_loader.load()

    def _is_item_enabled(self, item: SearchIndexItem) -> bool:
        """Check whether an item passes feature_id and config-enabled checks."""
        if not hasattr(item, 'feature_id') or not item.feature_id:
            return False
        config = self.config
        asset_config = config.asset_types.get(item.type)
        if not asset_config and item.type.startswith("asset-"):
            asset_config = config.asset_types.get("asset")
        if asset_config and not asset_config.enabled:
            return False
        return True

    def build_index(self):
        """Builds or rebuilds the search index by querying searchable managers."""
        logger.info(f"Building search index from {len(self.searchable_managers)} managers...")
        new_index: List[SearchIndexItem] = []
        config = self.config

        for manager in self.searchable_managers:
            manager_name = manager.__class__.__name__
            try:
                items = manager.get_search_index_items()
                for item in items:
                    if not self._is_item_enabled(item):
                        logger.debug(f"Skipping item {item.id} from {manager_name} (disabled or missing feature_id)")
                        continue
                    new_index.append(item)
            except Exception as e:
                logger.error(f"Failed to get search items from {manager_name}: {e}", exc_info=True)
        
        self.index = new_index
        logger.info(f"Search index build complete. Total items: {len(self.index)}")

    def upsert_item(self, item: SearchIndexItem) -> None:
        """Insert or update a single item in the index."""
        if not self._is_item_enabled(item):
            logger.debug(f"upsert_item: skipping {item.id} (disabled or missing feature_id)")
            return
        for i, existing in enumerate(self.index):
            if existing.id == item.id:
                self.index[i] = item
                logger.debug(f"Search index: updated {item.id}")
                return
        self.index.append(item)
        logger.debug(f"Search index: added {item.id}")

    def remove_item(self, item_id: str) -> None:
        """Remove an item from the index by id. No-op if not found."""
        for i, existing in enumerate(self.index):
            if existing.id == item_id:
                self.index.pop(i)
                logger.debug(f"Search index: removed {item_id}")
                return
        logger.debug(f"Search index: {item_id} not found for removal")

    def search(
        self, 
        query: str, 
        auth_manager: AuthorizationManager, 
        user: UserInfo, 
        team_role_override: Optional[str] = None
    ) -> List[SearchIndexItem]:
        """
        Performs a configurable search on indexed items.
        
        Uses search configuration to determine:
        - Which fields to search (based on indexed flag)
        - How to match (prefix, substring, exact, fuzzy)
        - How to rank results (by field priority, then boost score)
        
        Supports special query prefixes:
        - tag:namespace/tagname - Filter by exact tag match
        - tag:namespace - Filter by namespace prefix (matches all tags in namespace)
        
        Results are filtered by user permissions.
        
        Args:
            query: The search query string
            auth_manager: AuthorizationManager for permission checking
            user: Current user info
            team_role_override: Optional team role override
            
        Returns:
            List of matching SearchIndexItem, sorted by relevance
        """
        if not query:
            return []

        query_stripped = query.strip()
        if not query_stripped:
            return []
        
        config = self.config
        matches: List[SearchMatch] = []
        
        # Check for tag: prefix filter
        if query_stripped.lower().startswith('tag:'):
            tag_pattern = query_stripped[4:].strip()  # Extract pattern after 'tag:'
            matches = self._filter_by_tag(tag_pattern, config)
        else:
            # Normal search: tokenized scoring via the shared scorer, then wrapped
            # in SearchMatch so downstream permission-filtering and ranking are unchanged.
            for scored in search_scoring.score_and_rank(self.index, query_stripped, config):
                matches.append(SearchMatch(
                    item=scored.item,
                    matched_field="",
                    field_priority=scored.field_priority,
                    boost_score=scored.total_score,
                    match_quality=1.0,
                ))

        # Filter based on permissions using AuthorizationManager
        if not user.groups:
             logger.warning(f"User {user.username} has no groups, returning empty search results.")
             return []
             
        filtered_matches: List[SearchMatch] = []
        try:
             effective_permissions = auth_manager.get_user_effective_permissions(user.groups, team_role_override)
             for match in matches:
                 if auth_manager.has_permission(effective_permissions, match.item.feature_id, FeatureAccessLevel.READ_ONLY):
                     filtered_matches.append(match)
        except Exception as e:
            logger.error(f"Error checking permissions during search for user {user.username}: {e}", exc_info=True)
            return []

        # Sort results based on ranking configuration
        sorted_matches = self._sort_matches(filtered_matches, config)
        
        # Extract items from matches
        results = [m.item for m in sorted_matches]
        
        logger.info(
            f"Search for '{query}' returned {len(results)} results "
            f"after permission filtering for user {user.username}."
        )
        return results

    def _filter_by_tag(
        self, 
        tag_pattern: str, 
        config: SearchConfig
    ) -> List[SearchMatch]:
        """
        Filter indexed items by tag pattern.
        
        Supports:
        - Exact match: tag:namespace/tagname - matches items with exactly that tag
        - Namespace prefix: tag:namespace - matches all items with tags starting with 'namespace/'
        
        Args:
            tag_pattern: The tag pattern to match (e.g., 'finance/pii' or 'finance')
            config: Search configuration
            
        Returns:
            List of SearchMatch for items that have matching tags
        """
        matches: List[SearchMatch] = []
        pattern_lower = tag_pattern.lower()
        
        # Determine if this is an exact match or prefix match
        # If pattern contains '/', it's an exact match; otherwise prefix match
        is_exact_match = '/' in pattern_lower
        
        for item in self.index:
            if not item.tags:
                continue
            
            # Check if any tag matches the pattern
            tag_matched = False
            for tag in item.tags:
                tag_lower = str(tag).lower()
                
                if is_exact_match:
                    # Exact match: pattern must equal the tag
                    if tag_lower == pattern_lower:
                        tag_matched = True
                        break
                else:
                    # Prefix match: tag must start with pattern + '/'
                    # e.g., pattern 'finance' matches 'finance/pii', 'finance/sensitive'
                    if tag_lower.startswith(pattern_lower + '/') or tag_lower == pattern_lower:
                        tag_matched = True
                        break
            
            if tag_matched:
                # Get the tags field config for scoring
                field_configs = config.get_all_field_configs(item.type)
                tags_config = field_configs.get('tags')
                
                matches.append(SearchMatch(
                    item=item,
                    matched_field='tags',
                    field_priority=tags_config.priority if tags_config else 10,
                    boost_score=tags_config.boost if tags_config else 1.0,
                    match_quality=1.0,  # Exact tag matches get full quality
                ))
        
        return matches

    def _find_best_match(
        self, 
        item: SearchIndexItem, 
        query: str, 
        config: SearchConfig
    ) -> Optional[SearchMatch]:
        """
        Find the best matching field for an item.
        
        Returns the match with the lowest priority (highest importance) if multiple fields match.
        """
        best_match: Optional[SearchMatch] = None
        
        # Get all field configs for this asset type
        field_configs = config.get_all_field_configs(item.type)
        
        # Check each configured field
        for field_name, field_config in field_configs.items():
            if not field_config.indexed:
                continue
            
            # Get the field value
            value = self._get_field_value(item, field_name)
            if value is None:
                continue
            
            # Check if this field matches
            match_quality = self._check_match(value, query, field_config.match_type)
            if match_quality > 0:
                match = SearchMatch(
                    item=item,
                    matched_field=field_name,
                    field_priority=field_config.priority,
                    boost_score=field_config.boost,
                    match_quality=match_quality,
                )
                
                # Keep the best match (lowest priority = highest importance)
                if best_match is None or match.field_priority < best_match.field_priority:
                    best_match = match
                elif match.field_priority == best_match.field_priority:
                    # Same priority, prefer higher boost score
                    if match.total_score > best_match.total_score:
                        best_match = match
        
        return best_match

    def _get_field_value(self, item: SearchIndexItem, field_name: str) -> Optional[str]:
        """Get the value of a field from a SearchIndexItem (delegates to the shared scorer)."""
        return search_scoring.get_field_value(item, field_name)

    def _check_match(self, value: str, query: str, match_type: MatchType) -> float:
        """Check how well a query matches a value (delegates to the shared scorer)."""
        return search_scoring.check_match(value, query, match_type)

    def _fuzzy_match(self, value: str, query: str) -> float:
        """Fuzzy match score in [0, 1] (delegates to the shared scorer)."""
        return search_scoring.fuzzy_match(value, query)

    def _sort_matches(self, matches: List[SearchMatch], config: SearchConfig) -> List[SearchMatch]:
        """
        Sort matches according to ranking configuration.
        """
        ranking = config.ranking
        
        def sort_key(match: SearchMatch) -> tuple:
            """Generate sort key based on ranking config."""
            keys = []
            
            for sort_field in [ranking.primary_sort, ranking.secondary_sort, ranking.tertiary_sort]:
                if sort_field == SortField.MATCH_PRIORITY:
                    keys.append(match.field_priority)  # Lower is better
                elif sort_field == SortField.BOOST_SCORE:
                    keys.append(-match.total_score)  # Higher is better (negate for ascending sort)
                elif sort_field == SortField.TITLE_ASC:
                    keys.append(match.item.title.lower() if match.item.title else "")
                elif sort_field == SortField.TITLE_DESC:
                    # Reverse by using a tuple that inverts string comparison
                    keys.append(tuple(-ord(c) for c in (match.item.title.lower() if match.item.title else "")))
            
            return tuple(keys)
        
        return sorted(matches, key=sort_key)

    def reload_config(self) -> None:
        """Force reload the search configuration from disk."""
        self._config_loader.load(force_reload=True)
        logger.info("Search configuration reloaded")

    def get_config(self) -> SearchConfig:
        """Get the current search configuration."""
        return self.config
