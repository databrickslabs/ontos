"""
Unit tests for ChangeLogManager
"""
import pytest
import json
from datetime import datetime
from unittest.mock import Mock, MagicMock
from src.controller.change_log_manager import ChangeLogManager
from src.db_models.change_log import ChangeLogDb


class TestChangeLogManager:
    """Test suite for ChangeLogManager."""

    @pytest.fixture
    def mock_repository(self):
        """Create mock change log repository."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_repository):
        """Create ChangeLogManager instance for testing."""
        return ChangeLogManager(change_log_repository=mock_repository)

    @pytest.fixture
    def sample_change_log_entry(self):
        """Sample change log database entry."""
        entry = Mock(spec=ChangeLogDb)
        entry.id = 1
        entry.entity_type = "data_product"
        entry.entity_id = "product-123"
        entry.action = "CREATE"
        entry.username = "user@example.com"
        entry.details_json = None
        entry.timestamp = datetime(2024, 1, 1, 0, 0, 0)
        return entry

    # Initialization Tests

    def test_manager_initialization(self, mock_repository):
        """Test manager initializes with repository."""
        manager = ChangeLogManager(change_log_repository=mock_repository)
        assert manager._change_log_repo == mock_repository

    # Log Change Tests

    def test_log_change_success(self, manager):
        """Test logging a change."""
        mock_db = Mock()
        
        mock_entry = Mock(spec=ChangeLogDb)
        mock_entry.id = 1
        mock_entry.entity_type = "data_product"
        mock_entry.entity_id = "product-123"
        mock_entry.action = "CREATE"
        mock_entry.username = "user@example.com"
        mock_entry.details_json = None

        # Mock the db.add, commit, refresh sequence
        def mock_refresh(obj):
            # Simulate refresh by setting id
            pass

        mock_db.add.return_value = None
        mock_db.commit.return_value = None
        mock_db.refresh.side_effect = mock_refresh

        result = manager.log_change(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
            action="CREATE",
            username="user@example.com",
        )

        assert isinstance(result, ChangeLogDb)
        assert result.entity_type == "data_product"
        assert result.entity_id == "product-123"
        assert result.action == "CREATE"
        assert result.username == "user@example.com"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.refresh.assert_called_once()

    def test_log_change_with_details_json(self, manager):
        """Test logging a change with JSON details."""
        mock_db = Mock()

        result = manager.log_change(
            mock_db,
            entity_type="data_contract",
            entity_id="contract-456",
            action="UPDATE",
            username="admin@example.com",
            details_json='{"field": "status", "old": "draft", "new": "proposed"}',
        )

        assert result.details_json == '{"field": "status", "old": "draft", "new": "proposed"}'

    def test_log_change_without_username(self, manager):
        """Test logging a change without username (system action)."""
        mock_db = Mock()

        result = manager.log_change(
            mock_db,
            entity_type="compliance_policy",
            entity_id="policy-789",
            action="AUTO_CHECK",
            username=None,
        )

        assert result.username is None

    # Log Change with Details Tests

    def test_log_change_with_details_dict(self, manager):
        """Test logging a change with structured details dict."""
        mock_db = Mock()

        details = {"field": "title", "old_value": "Old Title", "new_value": "New Title"}

        result = manager.log_change_with_details(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
            action="UPDATE",
            username="user@example.com",
            details=details,
        )

        # Verify details were serialized to JSON
        assert result.details_json is not None
        assert json.loads(result.details_json) == details

    def test_log_change_with_details_none(self, manager):
        """Test logging a change with None details."""
        mock_db = Mock()

        result = manager.log_change_with_details(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
            action="DELETE",
            username="user@example.com",
            details=None,
        )

        assert result.details_json is None

    def test_log_change_with_details_serialization_error(self, manager):
        """Test handling of JSON serialization errors."""
        mock_db = Mock()

        # Create an object that can't be serialized to JSON
        class NonSerializable:
            pass

        details = {"obj": NonSerializable()}

        result = manager.log_change_with_details(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
            action="UPDATE",
            username="user@example.com",
            details=details,
        )

        # Should log without details when serialization fails
        assert result.details_json is None

    # List Changes for Entity Tests

    def test_list_changes_for_entity_empty(self, manager, mock_repository):
        """Test listing changes when none exist."""
        mock_repository.list_by_entity.return_value = []
        mock_db = Mock()

        result = manager.list_changes_for_entity(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
        )

        assert result == []
        mock_repository.list_by_entity.assert_called_once_with(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
            action=None,
            limit=100,
        )

    def test_list_changes_for_entity_with_results(self, manager, mock_repository, sample_change_log_entry):
        """Test listing changes with results."""
        mock_repository.list_by_entity.return_value = [sample_change_log_entry]
        mock_db = Mock()

        result = manager.list_changes_for_entity(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
        )

        assert len(result) == 1
        assert result[0].entity_id == "product-123"

    def test_list_changes_for_entity_with_custom_limit(self, manager, mock_repository):
        """Test listing changes with custom limit."""
        mock_repository.list_by_entity.return_value = []
        mock_db = Mock()

        manager.list_changes_for_entity(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
            action=None,
            limit=50,
        )

        mock_repository.list_by_entity.assert_called_once_with(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
            action=None,
            limit=50,
        )

    # List Filtered Changes Tests

    def test_list_filtered_changes_no_filters(self, manager, mock_repository):
        """Test listing all changes without filters."""
        mock_repository.list_filtered.return_value = []
        mock_db = Mock()

        result = manager.list_filtered_changes(mock_db)

        assert result == []
        mock_repository.list_filtered.assert_called_once_with(
            mock_db,
            skip=0,
            limit=100,
            entity_type=None,
            entity_id=None,
            username=None,
            action=None,
            start_time=None,
            end_time=None,
        )

    def test_list_filtered_changes_with_entity_type_filter(self, manager, mock_repository):
        """Test listing changes filtered by entity type."""
        mock_repository.list_filtered.return_value = []
        mock_db = Mock()

        manager.list_filtered_changes(
            mock_db,
            entity_type="data_product",
        )

        mock_repository.list_filtered.assert_called_once()
        call_kwargs = mock_repository.list_filtered.call_args[1]
        assert call_kwargs["entity_type"] == "data_product"

    def test_list_filtered_changes_with_username_filter(self, manager, mock_repository):
        """Test listing changes filtered by username."""
        mock_repository.list_filtered.return_value = []
        mock_db = Mock()

        manager.list_filtered_changes(
            mock_db,
            username="user@example.com",
        )

        call_kwargs = mock_repository.list_filtered.call_args[1]
        assert call_kwargs["username"] == "user@example.com"

    def test_list_filtered_changes_with_action_filter(self, manager, mock_repository):
        """Test listing changes filtered by action."""
        mock_repository.list_filtered.return_value = []
        mock_db = Mock()

        manager.list_filtered_changes(
            mock_db,
            action="CREATE",
        )

        call_kwargs = mock_repository.list_filtered.call_args[1]
        assert call_kwargs["action"] == "CREATE"

    def test_list_filtered_changes_with_time_range(self, manager, mock_repository):
        """Test listing changes filtered by time range."""
        mock_repository.list_filtered.return_value = []
        mock_db = Mock()

        manager.list_filtered_changes(
            mock_db,
            start_time="2024-01-01T00:00:00",
            end_time="2024-12-31T23:59:59",
        )

        call_kwargs = mock_repository.list_filtered.call_args[1]
        assert call_kwargs["start_time"] == "2024-01-01T00:00:00"
        assert call_kwargs["end_time"] == "2024-12-31T23:59:59"

    def test_list_filtered_changes_with_pagination(self, manager, mock_repository):
        """Test listing changes with pagination."""
        mock_repository.list_filtered.return_value = []
        mock_db = Mock()

        manager.list_filtered_changes(
            mock_db,
            skip=20,
            limit=10,
        )

        call_kwargs = mock_repository.list_filtered.call_args[1]
        assert call_kwargs["skip"] == 20
        assert call_kwargs["limit"] == 10

    def test_list_filtered_changes_with_multiple_filters(self, manager, mock_repository):
        """Test listing changes with multiple filters applied."""
        mock_repository.list_filtered.return_value = []
        mock_db = Mock()

        manager.list_filtered_changes(
            mock_db,
            entity_type="data_product",
            entity_id="product-123",
            username="user@example.com",
            action="UPDATE",
            skip=10,
            limit=25,
        )

        call_kwargs = mock_repository.list_filtered.call_args[1]
        assert call_kwargs["entity_type"] == "data_product"
        assert call_kwargs["entity_id"] == "product-123"
        assert call_kwargs["username"] == "user@example.com"
        assert call_kwargs["action"] == "UPDATE"
        assert call_kwargs["skip"] == 10
        assert call_kwargs["limit"] == 25
