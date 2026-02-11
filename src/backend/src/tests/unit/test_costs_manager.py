"""
Unit tests for CostsManager
"""
import pytest
from datetime import date, datetime, timezone
from uuid import uuid4, UUID
from unittest.mock import Mock
from src.controller.costs_manager import CostsManager
from src.models.costs import CostItemCreate, CostItemUpdate, CostItem
from src.db_models.costs import CostItemDb

# Fixed UUID for deterministic test assertions
SAMPLE_COST_UUID = UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _make_cost_item_db(
    id_val=None,
    amount_cents=150000,
    cost_center="INFRASTRUCTURE",
):
    """Build a mock CostItemDb with properly typed values for Pydantic validation."""
    cost_item = Mock(spec=CostItemDb)
    cost_item.id = id_val or uuid4()
    cost_item.entity_type = "data_product"
    cost_item.entity_id = "product-456"
    cost_item.title = "Storage Costs"
    cost_item.description = "Monthly storage costs"
    cost_item.cost_center = cost_center
    cost_item.custom_center_name = None
    cost_item.amount_cents = amount_cents
    cost_item.currency = "USD"
    cost_item.start_month = date(2024, 1, 1)
    cost_item.end_month = None
    cost_item.created_by = None
    cost_item.updated_by = None
    cost_item.created_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    cost_item.updated_at = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    return cost_item


class TestCostsManager:
    """Test suite for CostsManager."""

    @pytest.fixture
    def mock_repository(self):
        """Create mock costs repository."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_repository):
        """Create CostsManager instance for testing."""
        return CostsManager(repository=mock_repository)

    @pytest.fixture
    def sample_cost_item_db(self):
        """Sample cost item database object."""
        return _make_cost_item_db(id_val=SAMPLE_COST_UUID, amount_cents=150000)

    @pytest.fixture
    def sample_cost_create(self):
        """Sample cost item creation data."""
        return CostItemCreate(
            entity_type="data_product",
            entity_id="product-456",
            title="Storage Costs",
            description="Monthly storage costs",
            cost_center="INFRASTRUCTURE",
            amount_cents=150000,
            currency="USD",
            start_month=date(2024, 1, 1),
        )

    # Initialization Tests

    def test_manager_initialization(self, mock_repository):
        """Test manager initializes with repository."""
        manager = CostsManager(repository=mock_repository)
        assert manager._repo == mock_repository

    # Create Tests

    def test_create_cost_item_success(self, manager, mock_repository, sample_cost_create, sample_cost_item_db):
        """Test creating a cost item."""
        mock_repository.create.return_value = sample_cost_item_db
        mock_db = Mock()

        result = manager.create(mock_db, data=sample_cost_create, user_email="user@example.com")

        assert isinstance(result, CostItem)
        assert result.id == SAMPLE_COST_UUID
        assert result.amount_cents == 150000
        mock_repository.create.assert_called_once()
        assert mock_db.commit.called

    def test_create_cost_item_logs_change(self, manager, mock_repository, sample_cost_create, sample_cost_item_db):
        """Test that creating a cost item logs a change."""
        mock_repository.create.return_value = sample_cost_item_db
        mock_db = Mock()

        manager.create(mock_db, data=sample_cost_create, user_email="user@example.com")

        # Verify change log entry was created
        assert mock_db.add.called
        assert mock_db.commit.call_count >= 2  # Once for create, once for change log

    # List Tests

    def test_list_cost_items_empty(self, manager, mock_repository):
        """Test listing cost items when none exist."""
        mock_repository.list_for_entity.return_value = []
        mock_db = Mock()

        result = manager.list(mock_db, entity_type="data_product", entity_id="product-456")

        assert result == []
        mock_repository.list_for_entity.assert_called_once_with(
            mock_db, entity_type="data_product", entity_id="product-456", month=None
        )

    def test_list_cost_items_with_results(self, manager, mock_repository, sample_cost_item_db):
        """Test listing cost items with results."""
        mock_repository.list_for_entity.return_value = [sample_cost_item_db]
        mock_db = Mock()

        result = manager.list(mock_db, entity_type="data_product", entity_id="product-456")

        assert len(result) == 1
        assert result[0].id == SAMPLE_COST_UUID
        assert result[0].amount_cents == 150000

    def test_list_cost_items_filtered_by_month(self, manager, mock_repository, sample_cost_item_db):
        """Test listing cost items filtered by month."""
        mock_repository.list_for_entity.return_value = [sample_cost_item_db]
        target_month = date(2024, 1, 1)
        mock_db = Mock()

        result = manager.list(
            mock_db, entity_type="data_product", entity_id="product-456", month=target_month
        )

        assert len(result) == 1
        mock_repository.list_for_entity.assert_called_once_with(
            mock_db, entity_type="data_product", entity_id="product-456", month=target_month
        )

    # Update Tests

    def test_update_cost_item_success(self, manager, mock_repository, sample_cost_item_db):
        """Test updating a cost item."""
        # Create updated item with same attributes but changed amount
        updated_item = _make_cost_item_db(
            id_val=SAMPLE_COST_UUID, amount_cents=200000
        )

        mock_repository.get.return_value = sample_cost_item_db
        mock_repository.update.return_value = updated_item
        mock_db = Mock()

        update_data = CostItemUpdate(amount_cents=200000)
        result = manager.update(mock_db, id="cost-123", data=update_data, user_email="user@example.com")

        assert result is not None
        assert result.amount_cents == 200000
        mock_repository.update.assert_called_once()

    def test_update_cost_item_not_found(self, manager, mock_repository):
        """Test updating non-existent cost item."""
        mock_repository.get.return_value = None
        mock_db = Mock()

        update_data = CostItemUpdate(amount_cents=200000)
        result = manager.update(mock_db, id="nonexistent", data=update_data, user_email="user@example.com")

        assert result is None

    def test_update_cost_item_logs_change(self, manager, mock_repository, sample_cost_item_db):
        """Test that updating a cost item logs a change."""
        updated_item = _make_cost_item_db(
            id_val=SAMPLE_COST_UUID, amount_cents=200000
        )

        mock_repository.get.return_value = sample_cost_item_db
        mock_repository.update.return_value = updated_item
        mock_db = Mock()

        update_data = CostItemUpdate(amount_cents=200000)
        manager.update(mock_db, id="cost-123", data=update_data, user_email="user@example.com")

        # Verify change log entry was created
        assert mock_db.add.called
        assert mock_db.commit.call_count >= 2

    # Delete Tests

    def test_delete_cost_item_success(self, manager, mock_repository, sample_cost_item_db):
        """Test deleting a cost item."""
        mock_repository.get.return_value = sample_cost_item_db
        mock_repository.remove.return_value = sample_cost_item_db
        mock_db = Mock()

        result = manager.delete(mock_db, id="cost-123", user_email="user@example.com")

        assert result is True
        mock_repository.remove.assert_called_once()

    def test_delete_cost_item_not_found(self, manager, mock_repository):
        """Test deleting non-existent cost item."""
        mock_repository.get.return_value = None
        mock_db = Mock()

        result = manager.delete(mock_db, id="nonexistent", user_email="user@example.com")

        assert result is False

    def test_delete_cost_item_logs_change(self, manager, mock_repository, sample_cost_item_db):
        """Test that deleting a cost item logs a change."""
        mock_repository.get.return_value = sample_cost_item_db
        mock_repository.remove.return_value = sample_cost_item_db
        mock_db = Mock()

        manager.delete(mock_db, id="cost-123", user_email="user@example.com")

        # Verify change log entry was created
        assert mock_db.add.called

    # Summarize Tests

    def test_summarize_costs_success(self, manager, mock_repository):
        """Test summarizing costs for an entity."""
        mock_repository.summarize_for_entity.return_value = (
            "USD",  # currency
            300000,  # total_cents
            {"INFRASTRUCTURE": 150000, "COMPUTE": 150000},  # by_center
            5,  # count
        )
        mock_db = Mock()

        target_month = date(2024, 1, 1)
        result = manager.summarize(
            mock_db, entity_type="data_product", entity_id="product-456", month=target_month
        )

        assert result.month == "2024-01"
        assert result.currency == "USD"
        assert result.total_cents == 300000
        assert result.items_count == 5
        assert result.by_center == {"INFRASTRUCTURE": 150000, "COMPUTE": 150000}

    def test_summarize_costs_empty(self, manager, mock_repository):
        """Test summarizing when no costs exist."""
        mock_repository.summarize_for_entity.return_value = (
            "USD",  # currency
            0,  # total_cents
            {},  # by_center
            0,  # count
        )
        mock_db = Mock()

        target_month = date(2024, 1, 1)
        result = manager.summarize(
            mock_db, entity_type="data_product", entity_id="product-456", month=target_month
        )

        assert result.total_cents == 0
        assert result.items_count == 0
        assert result.by_center == {}

    def test_summarize_costs_month_formatting(self, manager, mock_repository):
        """Test month formatting in summary."""
        mock_repository.summarize_for_entity.return_value = ("USD", 0, {}, 0)
        mock_db = Mock()

        # Test various dates
        result1 = manager.summarize(mock_db, entity_type="data_product", entity_id="p1", month=date(2024, 1, 15))
        result2 = manager.summarize(mock_db, entity_type="data_product", entity_id="p2", month=date(2024, 12, 31))

        assert result1.month == "2024-01"
        assert result2.month == "2024-12"

