"""
Unit tests for DataProductsManager - ODPS v1.0.0 Data Products

Tests business logic for data product operations including:
- CRUD operations (create, read, update, delete)
- Product lifecycle transitions (draft → proposed → active → deprecated)
- Contract integration
- Tag management
- Search functionality
"""
import pytest
from unittest.mock import Mock, MagicMock, patch
import uuid
from sqlalchemy.orm import Session

from src.controller.data_products_manager import DataProductsManager
from src.models.data_products import DataProduct, DataProductStatus
from src.db_models.data_products import DataProductDb
from src.tests.helpers import (
    create_sample_data_product_dict,
    compare_dicts_ignore_keys
)


class TestDataProductsManager:
    """Test suite for DataProductsManager"""

    @pytest.fixture
    def mock_ws_client(self):
        """Create a mocked Databricks WorkspaceClient."""
        return MagicMock()

    @pytest.fixture
    def mock_notifications_manager(self):
        """Create a mocked NotificationsManager."""
        return MagicMock()

    @pytest.fixture
    def mock_tags_manager(self):
        """Create a mocked TagsManager."""
        return MagicMock()

    @pytest.fixture
    def manager(
        self,
        db_session: Session,
        mock_ws_client,
        mock_notifications_manager,
        mock_tags_manager
    ):
        """Create DataProductsManager instance for testing."""
        return DataProductsManager(
            db=db_session,
            ws_client=mock_ws_client,
            notifications_manager=mock_notifications_manager,
            tags_manager=mock_tags_manager
        )

    @pytest.fixture
    def sample_product_data(self):
        """Sample data product data for testing."""
        return {
            "id": str(uuid.uuid4()),
            "name": "Test Data Product",
            "description": {"purpose": "Test product for unit tests"},
            "version": "1.0.0",
            "status": "draft",
            "productType": "sourceAligned",
            "owner": "test@example.com",
            "tags": ["test", "sample"],
        }

    # =====================================================================
    # Create Product Tests
    # =====================================================================

    def test_create_product_success(self, manager, db_session, sample_product_data):
        """Test successful product creation with all required fields."""
        # Act
        result = manager.create_product(sample_product_data, db=db_session)

        # Assert
        assert result is not None
        assert result.id == sample_product_data["id"]
        assert result.name == sample_product_data["name"]
        assert result.version == sample_product_data["version"]
        assert result.status == DataProductStatus.DRAFT.value
        # Verify DB persistence
        db_product = db_session.query(DataProductDb).filter_by(id=result.id).first()
        assert db_product is not None

    def test_create_product_generates_id_if_missing(
        self, manager, db_session, sample_product_data
    ):
        """Test that missing ID is auto-generated."""
        # Arrange
        del sample_product_data["id"]

        # Act
        result = manager.create_product(sample_product_data, db=db_session)

        # Assert
        assert result.id is not None
        assert isinstance(uuid.UUID(result.id), uuid.UUID)

    def test_create_product_sets_defaults(self, manager, db_session):
        """Test that ODPS defaults are set for missing fields."""
        # Arrange
        minimal_data = {
            "name": "Minimal Product",
            "version": "1.0.0",
            "productType": "sourceAligned",
        }

        # Act
        result = manager.create_product(minimal_data, db=db_session)

        # Assert
        assert result.apiVersion == "v1.0.0"
        assert result.kind == "DataProduct"
        assert result.status == DataProductStatus.DRAFT.value

    def test_create_product_with_tags(
        self, manager, db_session, sample_product_data, mock_tags_manager
    ):
        """Test product creation with tag assignments."""
        # Act
        result = manager.create_product(sample_product_data, db=db_session)

        # Assert
        assert result is not None
        # Tags should be handled by the tags manager
        # (actual tag persistence verified in integration tests)

    def test_create_product_validation_error(self, manager, db_session):
        """Test that invalid product data raises ValueError."""
        # Arrange
        invalid_data = {
            "name": "",  # Empty name should fail
            "version": "invalid",  # Invalid version format might fail
        }

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            manager.create_product(invalid_data, db=db_session)

        assert "Invalid ODPS product data" in str(exc_info.value)

    def test_create_product_duplicate_id(
        self, manager, db_session, sample_product_data
    ):
        """Test creating product with duplicate ID fails."""
        # Arrange - Create first product
        manager.create_product(sample_product_data.copy(), db=db_session)

        # Act & Assert - Try to create duplicate
        with pytest.raises(Exception):  # SQLAlchemy integrity error
            manager.create_product(sample_product_data, db=db_session)

    # =====================================================================
    # Get Product Tests
    # =====================================================================

    def test_get_product_exists(self, manager, db_session, sample_product_data):
        """Test retrieving existing product by ID."""
        # Arrange
        created = manager.create_product(sample_product_data, db=db_session)

        # Act
        result = manager.get_product(created.id)

        # Assert
        assert result is not None
        assert result.id == created.id
        assert result.name == created.name

    def test_get_product_not_found(self, manager):
        """Test retrieving non-existent product returns None."""
        # Act
        result = manager.get_product("nonexistent-id")

        # Assert
        assert result is None

    def test_get_product_with_tags(
        self, manager, db_session, sample_product_data
    ):
        """Test that get_product loads tags."""
        # Arrange
        created = manager.create_product(sample_product_data, db=db_session)

        # Act
        result = manager.get_product(created.id)

        # Assert
        assert result is not None
        # Tags should be loaded (actual tag loading verified in integration tests)

    # =====================================================================
    # List Products Tests
    # =====================================================================

    def test_list_products_empty(self, manager):
        """Test listing products when none exist."""
        # Act — use is_admin=True to exercise listing mechanics rather than
        # the (separately-tested) ownership scope filter.
        result = manager.list_products(is_admin=True)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 0

    def test_list_products_multiple(self, manager, db_session):
        """Test listing multiple products."""
        # Arrange
        for i in range(3):
            product_data = {
                "name": f"Product {i}",
                "version": "1.0.0",
                "productType": "sourceAligned",
            }
            manager.create_product(product_data, db=db_session)

        # Act
        result = manager.list_products(is_admin=True)

        # Assert
        assert len(result) == 3
        assert all(isinstance(p, DataProduct) for p in result)

    def test_list_products_pagination(self, manager, db_session):
        """Test pagination with skip and limit."""
        # Arrange
        for i in range(10):
            product_data = {
                "name": f"Product {i}",
                "version": "1.0.0",
                "productType": "sourceAligned",
            }
            manager.create_product(product_data, db=db_session)

        # Act - Get second page
        result = manager.list_products(skip=5, limit=3, is_admin=True)

        # Assert
        assert len(result) == 3

    # =====================================================================
    # Update Product Tests
    # =====================================================================

    def test_update_product_success(
        self, manager, db_session, sample_product_data
    ):
        """Test successful product update."""
        # Arrange
        created = manager.create_product(sample_product_data, db=db_session)
        update_data = {
            "id": created.id,
            "name": "Updated Product Name",
            "version": created.version,
        }

        # Act
        result = manager.update_product(created.id, update_data, db=db_session)

        # Assert
        assert result is not None
        assert result.name == "Updated Product Name"

    def test_update_product_not_found(self, manager, db_session):
        """Test updating non-existent product returns None."""
        # Arrange
        update_data = {
            "id": "nonexistent-id",
            "name": "Updated Name",
            "version": "1.0.0",
        }

        # Act
        result = manager.update_product(
            "nonexistent-id", update_data, db=db_session
        )

        # Assert
        assert result is None

    def test_update_product_validation_error(
        self, manager, db_session, sample_product_data
    ):
        """Test that invalid update data raises ValueError."""
        # Arrange
        created = manager.create_product(sample_product_data, db=db_session)
        invalid_update = {
            "id": created.id,
            "status": "invalid-status",  # Invalid status
        }

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            manager.update_product(created.id, invalid_update, db=db_session)

        assert "Invalid ODPS update data" in str(exc_info.value)

    def test_update_product_with_tags(
        self, manager, db_session, sample_product_data
    ):
        """Test updating product with new tags."""
        # Arrange
        created = manager.create_product(sample_product_data, db=db_session)
        update_data = {
            "id": created.id,
            "name": created.name,
            "version": created.version,
            "tags": ["updated", "new-tag"],
        }

        # Act
        result = manager.update_product(created.id, update_data, db=db_session)

        # Assert
        assert result is not None
        # Tag updates handled by tags manager (verified in integration tests)

    # =====================================================================
    # Delete Product Tests
    # =====================================================================

    def test_delete_product_success(
        self, manager, db_session, sample_product_data
    ):
        """Test successful product deletion."""
        # Arrange
        created = manager.create_product(sample_product_data, db=db_session)

        # Act
        result = manager.delete_product(created.id)

        # Assert
        assert result is True
        # Verify deletion
        deleted = manager.get_product(created.id)
        assert deleted is None

    def test_delete_product_not_found(self, manager):
        """Test deleting non-existent product returns False."""
        # Act
        result = manager.delete_product("nonexistent-id")

        # Assert
        assert result is False

    # =====================================================================
    # Lifecycle Transition Tests
    # =====================================================================

    def test_submit_for_certification_success(
        self, manager, db_session, sample_product_data
    ):
        """Test submitting draft product for certification."""
        # Arrange
        sample_product_data["status"] = "draft"
        created = manager.create_product(sample_product_data, db=db_session)

        # Act
        result = manager.submit_for_certification(created.id)

        # Assert
        assert result is not None
        # Status should transition (actual transition logic verified in integration tests)

    def test_publish_product_success(
        self, manager, db_session, sample_product_data
    ):
        """Test publishing an approved product."""
        # Arrange
        sample_product_data["status"] = "approved"
        # Add required output port with contract
        sample_product_data["outputPorts"] = [
            {
                "name": "test-output",
                "version": "1.0.0",
                "contractId": "test-contract-id",
            }
        ]
        created = manager.create_product(sample_product_data, db=db_session)

        # Act
        result = manager.publish_product(created.id)

        # Assert
        assert result is not None
        assert result.status == DataProductStatus.ACTIVE.value

    def test_publish_product_missing_contracts_fails(
        self, manager, db_session, sample_product_data
    ):
        """Test that publishing without contracts fails."""
        # Arrange
        sample_product_data["status"] = "approved"
        # No output ports with contracts
        created = manager.create_product(sample_product_data, db=db_session)

        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            manager.publish_product(created.id)

        assert "contract" in str(exc_info.value).lower()

    def test_deprecate_product_success(
        self, manager, db_session, sample_product_data
    ):
        """Test deprecating an active product."""
        # Arrange
        sample_product_data["status"] = "active"
        created = manager.create_product(sample_product_data, db=db_session)

        # Act
        result = manager.deprecate_product(created.id)

        # Assert
        assert result is not None
        assert result.status == DataProductStatus.DEPRECATED.value

    # =====================================================================
    # Contract Integration Tests
    # =====================================================================

    def test_create_from_contract_success(
        self, manager, db_session
    ):
        """Test creating product from contract."""
        # This test requires contract manager integration
        # Placeholder for integration test
        pass

    def test_get_products_by_contract(self, manager, db_session):
        """Test retrieving products by contract ID."""
        # This test requires contract setup
        # Placeholder for integration test
        pass

    def test_get_contracts_for_product(
        self, manager, db_session, sample_product_data
    ):
        """Test retrieving contracts for a product."""
        # Arrange
        sample_product_data["outputPorts"] = [
            {
                "name": "output1",
                "version": "1.0.0",
                "contractId": "contract-1",
            },
            {
                "name": "output2",
                "version": "1.0.0",
                "contractId": "contract-2",
            },
        ]
        created = manager.create_product(sample_product_data, db=db_session)

        # Act
        result = manager.get_contracts_for_product(created.id)

        # Assert
        assert isinstance(result, list)
        assert "contract-1" in result
        assert "contract-2" in result

    # =====================================================================
    # Utility Method Tests
    # =====================================================================

    def test_get_distinct_statuses(self, manager):
        """Test retrieving distinct status values."""
        # Act
        result = manager.get_distinct_statuses()

        # Assert
        assert isinstance(result, list)
        assert all(isinstance(s, str) for s in result)

    def test_get_distinct_product_types(self, manager):
        """Test retrieving distinct product types."""
        # Act
        result = manager.get_distinct_product_types()

        # Assert
        assert isinstance(result, list)

    def test_get_distinct_owners(self, manager, db_session):
        """Test retrieving distinct owners."""
        # Arrange - Create products with different owners
        for i, owner in enumerate(["owner1@test.com", "owner2@test.com"]):
            product_data = {
                "name": f"Product {i}",
                "version": "1.0.0",
                "productType": "sourceAligned",
                "owner": owner,
            }
            manager.create_product(product_data, db=db_session)

        # Act
        result = manager.get_distinct_owners()

        # Assert
        assert isinstance(result, list)
        assert "owner1@test.com" in result
        assert "owner2@test.com" in result

    def test_get_published_products(self, manager, db_session):
        """Marketplace lists products with publication_scope other than none."""
        configs = [
            ("draft", None),
            ("active", "domain"),
            ("active", "organization"),
            ("deprecated", None),
        ]
        for i, (status, pub_scope) in enumerate(configs):
            product_data = {
                "name": f"Product {i}",
                "version": "1.0.0",
                "productType": "sourceAligned",
                "status": status,
            }
            created = manager.create_product(product_data, db=db_session)
            if pub_scope:
                row = db_session.get(DataProductDb, created.id)
                assert row is not None
                row.publication_scope = pub_scope
                db_session.commit()

        result = manager.get_published_products()

        assert len(result) == 2
        assert {(p.publication_scope or "").lower() for p in result} == {"domain", "organization"}

    def test_get_published_products_scope_filter(self, manager, db_session):
        """Optional scope narrows marketplace products."""
        for name, scope in [("A", "domain"), ("B", "organization")]:
            product_data = {
                "name": name,
                "version": "1.0.0",
                "productType": "sourceAligned",
                "status": "active",
            }
            created = manager.create_product(product_data, db=db_session)
            row = db_session.get(DataProductDb, created.id)
            row.publication_scope = scope
            db_session.commit()

        domain_only = manager.get_published_products(scope="domain")
        assert len(domain_only) == 1
        assert domain_only[0].name == "A"

    # =====================================================================
    # Search Interface Tests
    # =====================================================================

    def test_get_search_index_items(self, manager, db_session):
        """Test that manager provides search index items."""
        # Arrange
        for i in range(3):
            product_data = {
                "name": f"Searchable Product {i}",
                "version": "1.0.0",
                "productType": "sourceAligned",
                "description": {"purpose": f"Purpose {i}"},
            }
            manager.create_product(product_data, db=db_session)

        # Act
        result = manager.get_search_index_items()

        # Assert
        assert isinstance(result, list)
        assert len(result) == 3
        # Each item should have required search fields
        for item in result:
            assert hasattr(item, 'id')
            assert hasattr(item, 'title')
            assert hasattr(item, 'description')

    # =====================================================================
    # Error Handling Tests
    # =====================================================================

    def test_create_product_db_error_handling(
        self, manager, db_session, sample_product_data
    ):
        """Test graceful handling of database errors during creation."""
        # Arrange - Force DB error by closing session
        db_session.close()

        # Act & Assert
        with pytest.raises(Exception):  # SQLAlchemy error
            manager.create_product(sample_product_data, db=db_session)

    def test_manager_without_workspace_client(self, db_session):
        """Test manager initialization without WorkspaceClient."""
        # Act
        manager = DataProductsManager(db=db_session, ws_client=None)

        # Assert
        # Should initialize but log warning
        assert manager is not None
        # SDK operations should handle missing client gracefully

    def test_manager_without_notifications(self, db_session):
        """Test manager initialization without NotificationsManager."""
        # Act
        manager = DataProductsManager(
            db=db_session,
            ws_client=MagicMock(),
            notifications_manager=None
        )

        # Assert
        assert manager is not None
        # Should work but notifications won't be sent
