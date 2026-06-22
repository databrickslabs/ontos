"""
Unit tests for ApprovalsManager

Tests approval queue management including:
- Getting approvals queue
- Filtering by entity type
"""
import pytest
import uuid

from src.controller.approvals_manager import ApprovalsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb


class TestApprovalsManager:
    """Test suite for ApprovalsManager"""

    @pytest.fixture
    def manager(self):
        """Create ApprovalsManager instance for testing."""
        return ApprovalsManager()

    def test_manager_initialization(self, manager):
        """Test manager initializes successfully."""
        assert manager is not None

    def test_get_approvals_queue_empty(self, manager, db_session):
        """Test getting approvals queue when none exist."""
        # Act
        result = manager.get_approvals_queue(db=db_session)

        # Assert
        assert result is not None
        assert 'contracts' in result
        assert 'products' in result
        assert result['contracts'] == []
        assert result['products'] == []

    def test_get_approvals_queue_with_contracts(self, manager, db_session):
        """Test getting approvals queue with pending contracts."""
        # Arrange - Create contracts with different statuses
        contract1 = DataContractDb(
            id=str(uuid.uuid4()),
            name="Proposed Contract",
            version="1.0.0",
            status="proposed",
            created_by="user@example.com",
        )
        contract2 = DataContractDb(
            id=str(uuid.uuid4()),
            name="Under Review Contract",
            version="1.0.0",
            status="under_review",
            created_by="user@example.com",
        )
        contract3 = DataContractDb(
            id=str(uuid.uuid4()),
            name="Active Contract",
            version="1.0.0",
            status="active",
            created_by="user@example.com",
        )
        db_session.add_all([contract1, contract2, contract3])
        db_session.commit()

        # Act
        result = manager.get_approvals_queue(db=db_session)

        # Assert
        assert len(result['contracts']) == 2
        contract_ids = [c['id'] for c in result['contracts']]
        assert contract1.id in contract_ids
        assert contract2.id in contract_ids
        assert contract3.id not in contract_ids

    def test_get_approvals_queue_with_products(self, manager, db_session):
        """Proposed/under_review products surface; draft and active do not.

        A product only enters the steward review queue once it has been
        submitted for review (request-certify transitions draft -> proposed).
        A still-draft product is not yet awaiting review and must not appear;
        an active product is already published. See ONT-CUJ-020.
        """
        # Arrange - Create products across the lifecycle
        proposed = DataProductDb(
            id=str(uuid.uuid4()),
            name="Proposed Product",
            version="1.0.0",
            status="proposed",
        )
        under_review = DataProductDb(
            id=str(uuid.uuid4()),
            name="Under Review Product",
            version="1.0.0",
            status="under_review",
        )
        draft = DataProductDb(
            id=str(uuid.uuid4()),
            name="Draft Product",
            version="1.0.0",
            status="draft",
        )
        active = DataProductDb(
            id=str(uuid.uuid4()),
            name="Active Product",
            version="1.0.0",
            status="active",
        )
        db_session.add_all([proposed, under_review, draft, active])
        db_session.commit()

        # Act
        result = manager.get_approvals_queue(db=db_session)

        # Assert - only the two awaiting-review products surface
        product_ids = {p['id'] for p in result['products']}
        assert product_ids == {proposed.id, under_review.id}
        assert draft.id not in product_ids
        assert active.id not in product_ids

    def test_proposed_product_surfaces_after_request_certify(self, manager, db_session):
        """Regression for ONT-CUJ-020: a product submitted for review (proposed)
        appears in the steward approvals queue.

        Before the fix the products query filtered on status == 'draft', so a
        product that had been moved to 'proposed' by request-certify (ONT-CUJ-019)
        never surfaced to stewards ('No results').
        """
        # Arrange - a product that has been submitted for review
        proposed = DataProductDb(
            id=str(uuid.uuid4()),
            name="Awaiting Steward Review",
            version="1.0.0",
            status="proposed",
        )
        db_session.add(proposed)
        db_session.commit()

        # Act
        result = manager.get_approvals_queue(db=db_session)

        # Assert
        assert len(result['products']) == 1
        assert result['products'][0]['id'] == proposed.id
        assert result['products'][0]['title'] == "Awaiting Steward Review"
        assert result['products'][0]['status'] == "proposed"

    def test_get_approvals_queue_mixed(self, manager, db_session):
        """Test getting approvals queue with both contracts and products."""
        # Arrange
        contract = DataContractDb(
            id=str(uuid.uuid4()),
            name="Proposed Contract",
            version="1.0.0",
            status="proposed",
            created_by="user@example.com",
        )
        product = DataProductDb(
            id=str(uuid.uuid4()),
            name="Proposed Product",
            version="1.0.0",
            status="proposed",
        )
        db_session.add_all([contract, product])
        db_session.commit()

        # Act
        result = manager.get_approvals_queue(db=db_session)

        # Assert
        assert len(result['contracts']) == 1
        assert len(result['products']) == 1
        assert result['contracts'][0]['name'] == "Proposed Contract"
        assert result['products'][0]['title'] == "Proposed Product"

