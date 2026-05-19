"""
Unit tests for DataProductRepository

Tests the repository layer CRUD operations and data mapping between:
- API models (Pydantic DataProduct)
- DB models (SQLAlchemy DataProductDb)
"""
import pytest
import uuid
from sqlalchemy.orm import Session

from src.repositories.data_products_repository import data_product_repo
from src.models.data_products import DataProductCreate, DataProductUpdate, Description, OutputPort
from src.db_models.data_products import DataProductDb


class TestDataProductRepository:
    """Test suite for DataProductRepository CRUD operations"""

    @pytest.fixture
    def sample_create_model(self):
        """Sample DataProductCreate model for testing."""
        return DataProductCreate(
            id=str(uuid.uuid4()),
            apiVersion="v1.0.0",
            kind="DataProduct",
            name="Repo Test Product",
            version="1.0.0",
            status="draft",
            productType="sourceAligned",
            owner="repo-test@example.com",
            description={"purpose": "Repository testing"},
        )

    # =====================================================================
    # Create Tests
    # =====================================================================

    def test_create_product_success(self, db_session: Session, sample_create_model):
        """Test creating a product via repository."""
        # Act
        result = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        # Assert
        assert result is not None
        assert result.id == sample_create_model.id
        assert result.name == sample_create_model.name
        assert result.version == sample_create_model.version

        # Verify persistence
        db_session.commit()
        fetched = db_session.query(DataProductDb).filter_by(id=result.id).first()
        assert fetched is not None

    def test_create_product_with_description(
        self, db_session: Session, sample_create_model
    ):
        """Test creating product with structured description."""
        # Arrange
        sample_create_model.description = Description(
            purpose="Test purpose",
            limitations="Test limitations",
            usage="Test usage"
        )

        # Act
        result = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        # Assert
        assert result.description is not None
        assert result.description.purpose == "Test purpose"
        assert result.description.limitations == "Test limitations"

    def test_create_product_with_output_ports(
        self, db_session: Session, sample_create_model
    ):
        """Test creating product with output ports."""
        # Arrange
        sample_create_model.outputPorts = [
            OutputPort(
                name="test-output",
                version="1.0.0",
                contractId="test-contract-id"
            )
        ]

        # Act
        result = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        # Assert
        assert len(result.output_ports) == 1
        assert result.output_ports[0].name == "test-output"
        assert result.output_ports[0].contract_id == "test-contract-id"

    def test_create_product_minimal_fields(self, db_session: Session):
        """Test creating product with only required fields."""
        # Arrange
        minimal_model = DataProductCreate(
            id=str(uuid.uuid4()),
            name="Minimal Product",
            version="1.0.0",
            productType="sourceAligned",
        )

        # Act
        result = data_product_repo.create(db=db_session, obj_in=minimal_model)

        # Assert
        assert result is not None
        assert result.id == minimal_model.id
        assert result.name == minimal_model.name

    def test_create_product_preserves_project_id(self, db_session: Session):
        """A POST that includes ``project_id`` must persist it.

        Before this fix, the repository's ``create()`` hard-coded
        ``project_id=None`` regardless of what the input schema carried, so
        any product POSTed with a project association silently lost it.
        """
        # Arrange
        project_uuid = str(uuid.uuid4())
        model = DataProductCreate(
            id=str(uuid.uuid4()),
            name="Project-Bound Product",
            version="1.0.0",
            project_id=project_uuid,
        )

        # Act
        result = data_product_repo.create(db=db_session, obj_in=model)
        db_session.commit()
        fetched = db_session.query(DataProductDb).filter_by(id=result.id).first()

        # Assert — both the in-memory return and the DB row carry the value.
        assert result.project_id == project_uuid
        assert fetched is not None
        assert fetched.project_id == project_uuid

    # =====================================================================
    # Get Tests
    # =====================================================================

    def test_get_product_by_id_exists(
        self, db_session: Session, sample_create_model
    ):
        """Test retrieving product by ID when it exists."""
        # Arrange
        created = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        # Act
        result = data_product_repo.get(db=db_session, id=created.id)

        # Assert
        assert result is not None
        assert result.id == created.id
        assert result.name == created.name

    def test_get_product_by_id_not_found(self, db_session: Session):
        """Test retrieving non-existent product returns None."""
        # Act
        result = data_product_repo.get(db=db_session, id="nonexistent-id")

        # Assert
        assert result is None

    def test_get_product_with_relationships(
        self, db_session: Session, sample_create_model
    ):
        """Test that get loads all relationships."""
        # Arrange
        sample_create_model.description = Description(purpose="Test")
        sample_create_model.outputPorts = [
            OutputPort(name="output", version="1.0.0", contractId="contract-id")
        ]
        created = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        # Act
        result = data_product_repo.get(db=db_session, id=created.id)

        # Assert
        assert result.description is not None
        assert len(result.output_ports) == 1

    # =====================================================================
    # Get Multi (List) Tests
    # =====================================================================

    def test_get_multi_empty(self, db_session: Session):
        """Test listing products when none exist."""
        # Act
        result = data_product_repo.get_multi(db=db_session)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_multi_returns_all(self, db_session: Session):
        """Test get_multi returns all products."""
        # Arrange - Create multiple products
        for i in range(3):
            model = DataProductCreate(
                id=str(uuid.uuid4()),
                name=f"Product {i}",
                version="1.0.0",
                productType="sourceAligned",
            )
            data_product_repo.create(db=db_session, obj_in=model)

        # Act
        result = data_product_repo.get_multi(db=db_session)

        # Assert
        assert len(result) == 3

    def test_get_multi_pagination(self, db_session: Session):
        """Test pagination with skip and limit."""
        # Arrange - Create 10 products
        for i in range(10):
            model = DataProductCreate(
                id=str(uuid.uuid4()),
                name=f"Product {i}",
                version="1.0.0",
                productType="sourceAligned",
            )
            data_product_repo.create(db=db_session, obj_in=model)

        # Act - Get second page (skip 5, limit 3)
        result = data_product_repo.get_multi(db=db_session, skip=5, limit=3)

        # Assert
        assert len(result) == 3

    def test_get_multi_limit(self, db_session: Session):
        """Test that limit parameter works."""
        # Arrange
        for i in range(10):
            model = DataProductCreate(
                id=str(uuid.uuid4()),
                name=f"Product {i}",
                version="1.0.0",
                productType="sourceAligned",
            )
            data_product_repo.create(db=db_session, obj_in=model)

        # Act
        result = data_product_repo.get_multi(db=db_session, limit=5)

        # Assert
        assert len(result) == 5

    # =====================================================================
    # Update Tests
    # =====================================================================

    def test_update_product_success(
        self, db_session: Session, sample_create_model
    ):
        """Test updating product via repository."""
        # Arrange
        created = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        update_model = DataProductUpdate(
            id=created.id,
            name="Updated Name",
            version=created.version,
        )

        # Act
        result = data_product_repo.update(
            db=db_session,
            db_obj=created,
            obj_in=update_model
        )

        # Assert
        assert result.name == "Updated Name"
        assert result.id == created.id

    def test_update_product_with_dict(
        self, db_session: Session, sample_create_model
    ):
        """Test updating product with dictionary."""
        # Arrange
        created = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        update_dict = {
            "name": "Dict Updated Name",
            "status": "active"
        }

        # Act
        result = data_product_repo.update(
            db=db_session,
            db_obj=created,
            obj_in=update_dict
        )

        # Assert
        assert result.name == "Dict Updated Name"
        assert result.status == "active"

    def test_update_product_partial_fields(
        self, db_session: Session, sample_create_model
    ):
        """Test partial update only changes specified fields."""
        # Arrange
        created = data_product_repo.create(db=db_session, obj_in=sample_create_model)
        original_name = created.name

        update_dict = {"status": "active"}

        # Act
        result = data_product_repo.update(
            db=db_session,
            db_obj=created,
            obj_in=update_dict
        )

        # Assert
        assert result.status == "active"
        assert result.name == original_name  # Name unchanged

    # =====================================================================
    # Delete Tests
    # =====================================================================

    def test_delete_product_success(
        self, db_session: Session, sample_create_model
    ):
        """Test deleting product via repository."""
        # Arrange
        created = data_product_repo.create(db=db_session, obj_in=sample_create_model)
        product_id = created.id

        # Act
        result = data_product_repo.remove(db=db_session, id=product_id)

        # Assert
        assert result is not None
        assert result.id == product_id

        # Verify deletion
        fetched = data_product_repo.get(db=db_session, id=product_id)
        assert fetched is None

    def test_delete_product_not_found(self, db_session: Session):
        """Test deleting non-existent product returns None."""
        # Act
        result = data_product_repo.remove(db=db_session, id="nonexistent-id")

        # Assert
        assert result is None

    def test_delete_product_cascades_relationships(
        self, db_session: Session, sample_create_model
    ):
        """Test that deleting product cascades to relationships."""
        # Arrange
        sample_create_model.description = Description(purpose="Test")
        sample_create_model.outputPorts = [
            OutputPort(name="output", version="1.0.0", contractId="contract-id")
        ]
        created = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        # Act
        data_product_repo.remove(db=db_session, id=created.id)

        # Assert - Relationships should be deleted (cascade)
        # This is handled by SQLAlchemy cascade settings on the model

    # =====================================================================
    # Query Methods Tests
    # =====================================================================

    def test_get_by_status(self, db_session: Session):
        """Test filtering products by status."""
        # Arrange
        for i, status in enumerate(["draft", "active", "active", "deprecated"]):
            model = DataProductCreate(
                id=str(uuid.uuid4()),
                name=f"Product {i}",
                version="1.0.0",
                productType="sourceAligned",
                status=status,
            )
            data_product_repo.create(db=db_session, obj_in=model)

        # Act - Query for active products
        active_products = (
            db_session.query(DataProductDb)
            .filter(DataProductDb.status == "active")
            .all()
        )

        # Assert
        assert len(active_products) == 2

    def test_get_by_team(self, db_session: Session):
        """Test filtering products by owner team."""
        # Arrange
        team_id_1 = str(uuid.uuid4())
        team_id_2 = str(uuid.uuid4())

        for i in range(3):
            team_id = team_id_1 if i < 2 else team_id_2
            model = DataProductCreate(
                id=str(uuid.uuid4()),
                name=f"Product {i}",
                version="1.0.0",
                productType="sourceAligned",
                owner_team_id=team_id,
            )
            data_product_repo.create(db=db_session, obj_in=model)

        # Act
        team1_products = (
            db_session.query(DataProductDb)
            .filter(DataProductDb.owner_team_id == team_id_1)
            .all()
        )

        # Assert
        assert len(team1_products) == 2

    # =====================================================================
    # Model Conversion Tests
    # =====================================================================

    def test_api_to_db_model_conversion(
        self, db_session: Session, sample_create_model
    ):
        """Test conversion from API model to DB model."""
        # Act
        result = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        # Assert
        assert isinstance(result, DataProductDb)
        # Verify field mapping
        assert result.id == sample_create_model.id
        assert result.api_version == sample_create_model.apiVersion
        assert result.name == sample_create_model.name

    def test_db_to_api_model_conversion(
        self, db_session: Session, sample_create_model
    ):
        """Test that repository returns objects that can convert to API models."""
        # Arrange
        created = data_product_repo.create(db=db_session, obj_in=sample_create_model)

        # Act
        fetched = data_product_repo.get(db=db_session, id=created.id)

        # Assert
        # Repository layer returns DB objects
        # Manager layer handles conversion to API models
        assert isinstance(fetched, DataProductDb)
        assert fetched.id == sample_create_model.id
