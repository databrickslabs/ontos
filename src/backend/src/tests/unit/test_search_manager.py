"""
Unit tests for SearchManager
"""
import pytest
from unittest.mock import Mock, MagicMock
from src.controller.search_manager import SearchManager
from src.common.search_interfaces import SearchIndexItem
from src.common.features import FeatureAccessLevel
from src.models.users import UserInfo


class TestSearchManager:
    """Test suite for SearchManager."""

    @pytest.fixture
    def sample_search_items(self):
        """Sample search index items."""
        return [
            SearchIndexItem(
                id="item-1",
                type="data-product",
                feature_id="data-products",
                title="Product Alpha",
                description="First product",
                link="/products/1",
                tags=["production", "data"],
            ),
            SearchIndexItem(
                id="item-2",
                type="data-contract",
                feature_id="data-contracts",
                title="Contract Beta",
                description="Test contract",
                link="/contracts/2",
                tags=["draft"],
            ),
            SearchIndexItem(
                id="item-3",
                type="data-product",
                feature_id="data-products",
                title="Product Gamma",
                description="Second product with alpha mention",
                link="/products/3",
                tags=["development"],
            ),
        ]

    @pytest.fixture
    def mock_searchable_manager(self, sample_search_items):
        """Create mock searchable manager."""
        manager = Mock()
        manager.__class__.__name__ = "MockManager"
        manager.get_search_index_items.return_value = sample_search_items
        return manager

    @pytest.fixture
    def mock_auth_manager(self):
        """Create mock authorization manager."""
        return Mock()

    @pytest.fixture
    def sample_user(self):
        """Sample user info."""
        return UserInfo(
            username="testuser",
            email="test@example.com",
            user="Test User",
            ip="127.0.0.1",
            groups=["users", "data_consumers"],
        )

    # Initialization Tests

    def test_manager_initialization(self, mock_searchable_manager):
        """Test manager initializes and builds index."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])

        assert len(manager.searchable_managers) == 1
        assert len(manager.index) == 3
        mock_searchable_manager.get_search_index_items.assert_called_once()

    def test_manager_initialization_multiple_managers(self, mock_searchable_manager):
        """Test initialization with multiple searchable managers."""
        manager2 = Mock()
        manager2.__class__.__name__ = "Manager2"
        manager2.get_search_index_items.return_value = [
            SearchIndexItem(
                id="item-4",
                type="compliance-policy",
                feature_id="compliance",
                title="Policy 1",
                description="Compliance policy",
                link="/compliance/1",
            )
        ]

        manager = SearchManager(searchable_managers=[mock_searchable_manager, manager2])

        assert len(manager.searchable_managers) == 2
        assert len(manager.index) == 4

    def test_manager_initialization_empty_managers(self):
        """Test initialization with no managers."""
        manager = SearchManager(searchable_managers=[])

        assert len(manager.searchable_managers) == 0
        assert len(manager.index) == 0

    # Build Index Tests

    def test_build_index_success(self, mock_searchable_manager):
        """Test building search index."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])

        assert len(manager.index) == 3
        assert manager.index[0].title == "Product Alpha"

    def test_build_index_skips_items_without_feature_id(self):
        """Test that items without feature_id are skipped."""
        mock_manager = Mock()
        mock_manager.__class__.__name__ = "TestManager"
        
        # Create items with and without feature_id
        item_with_id = SearchIndexItem(
            id="item-1",
            type="data-product",
            feature_id="data-products",
            title="Valid Item",
            description="Has feature_id",
            link="/item/1",
        )
        item_without_id = SearchIndexItem(
            id="item-2",
            type="data-product",
            feature_id="",  # Empty feature_id
            title="Invalid Item",
            description="No feature_id",
            link="/item/2",
        )
        
        mock_manager.get_search_index_items.return_value = [item_with_id, item_without_id]

        manager = SearchManager(searchable_managers=[mock_manager])

        # Only the item with feature_id should be indexed
        assert len(manager.index) == 1
        assert manager.index[0].id == "item-1"

    def test_build_index_handles_manager_exception(self):
        """Test building index when a manager throws an exception."""
        mock_manager1 = Mock()
        mock_manager1.__class__.__name__ = "GoodManager"
        mock_manager1.get_search_index_items.return_value = [
            SearchIndexItem(
                id="item-1",
                type="data-product",
                feature_id="data-products",
                title="Good Item",
                description="From working manager",
                link="/item/1",
            )
        ]

        mock_manager2 = Mock()
        mock_manager2.__class__.__name__ = "BadManager"
        mock_manager2.get_search_index_items.side_effect = Exception("Manager error")

        manager = SearchManager(searchable_managers=[mock_manager1, mock_manager2])

        # Should only have items from the good manager
        assert len(manager.index) == 1
        assert manager.index[0].id == "item-1"

    # Search Tests

    def test_search_by_title(self, mock_searchable_manager, mock_auth_manager, sample_user):
        """Test searching by title."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])
        
        # Mock authorization to allow all
        mock_auth_manager.get_user_effective_permissions.return_value = {
            "data-products": FeatureAccessLevel.READ_ONLY,
            "data-contracts": FeatureAccessLevel.READ_ONLY,
        }
        mock_auth_manager.has_permission.return_value = True

        results = manager.search("Alpha", mock_auth_manager, sample_user)

        assert len(results) == 2  # "Product Alpha" and "Second product with alpha mention"
        assert results[0].title == "Product Alpha"

    def test_search_by_description(self, mock_searchable_manager, mock_auth_manager, sample_user):
        """Test searching by description."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])
        
        mock_auth_manager.get_user_effective_permissions.return_value = {
            "data-contracts": FeatureAccessLevel.READ_ONLY,
        }
        mock_auth_manager.has_permission.return_value = True

        results = manager.search("test", mock_auth_manager, sample_user)

        assert len(results) == 1
        assert results[0].title == "Contract Beta"

    def test_search_by_tag(self, mock_searchable_manager, mock_auth_manager, sample_user):
        """Test searching by tag."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])
        
        mock_auth_manager.get_user_effective_permissions.return_value = {
            "data-products": FeatureAccessLevel.READ_ONLY,
        }
        mock_auth_manager.has_permission.return_value = True

        results = manager.search("production", mock_auth_manager, sample_user)

        assert len(results) == 1
        assert results[0].title == "Product Alpha"

    def test_search_case_insensitive(self, mock_searchable_manager, mock_auth_manager, sample_user):
        """Test that search is case insensitive."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])
        
        mock_auth_manager.get_user_effective_permissions.return_value = {
            "data-products": FeatureAccessLevel.READ_ONLY,
        }
        mock_auth_manager.has_permission.return_value = True

        results_lower = manager.search("alpha", mock_auth_manager, sample_user)
        results_upper = manager.search("ALPHA", mock_auth_manager, sample_user)

        assert len(results_lower) == len(results_upper)
        assert results_lower[0].id == results_upper[0].id

    def test_search_empty_query(self, mock_searchable_manager, mock_auth_manager, sample_user):
        """Test that empty query returns no results."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])

        results = manager.search("", mock_auth_manager, sample_user)

        assert results == []

    def test_search_no_matches(self, mock_searchable_manager, mock_auth_manager, sample_user):
        """Test searching with no matches."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])
        
        mock_auth_manager.get_user_effective_permissions.return_value = {}
        mock_auth_manager.has_permission.return_value = True

        results = manager.search("nonexistent", mock_auth_manager, sample_user)

        assert len(results) == 0

    def test_search_filters_by_permissions(self, mock_searchable_manager, mock_auth_manager, sample_user):
        """Test that search filters results by user permissions."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])
        
        # User has permission for data-products but not data-contracts
        mock_auth_manager.get_user_effective_permissions.return_value = {
            "data-products": FeatureAccessLevel.READ_ONLY,
            "data-contracts": FeatureAccessLevel.NONE,
        }
        
        def check_permission(perms, feature_id, level):
            return feature_id == "data-products"
        
        mock_auth_manager.has_permission.side_effect = check_permission

        # Search for "product" should return products but not contracts
        results = manager.search("product", mock_auth_manager, sample_user)

        assert len(results) == 2
        assert all(r.feature_id == "data-products" for r in results)

    def test_search_user_without_groups(self, mock_searchable_manager, mock_auth_manager):
        """Test search for user without groups returns empty."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])
        
        user_no_groups = UserInfo(
            username="nogroups",
            email="nogroups@example.com",
            user="No Groups User",
            ip="127.0.0.1",
            groups=[],
        )

        results = manager.search("Alpha", mock_auth_manager, user_no_groups)

        assert results == []

    def test_search_handles_auth_exception(self, mock_searchable_manager, mock_auth_manager, sample_user):
        """Test that search handles authorization exceptions gracefully."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])
        
        mock_auth_manager.get_user_effective_permissions.side_effect = Exception("Auth error")

        results = manager.search("Alpha", mock_auth_manager, sample_user)

        assert results == []

    def test_search_with_team_role_override(self, mock_searchable_manager, mock_auth_manager, sample_user):
        """Test search with team role override."""
        manager = SearchManager(searchable_managers=[mock_searchable_manager])
        
        mock_auth_manager.get_user_effective_permissions.return_value = {
            "data-products": FeatureAccessLevel.ADMIN,
        }
        mock_auth_manager.has_permission.return_value = True

        results = manager.search("Alpha", mock_auth_manager, sample_user, team_role_override="admin")

        # Verify team_role_override was passed to auth_manager
        mock_auth_manager.get_user_effective_permissions.assert_called_once_with(
            sample_user.groups, "admin"
        )
        assert len(results) >= 1

