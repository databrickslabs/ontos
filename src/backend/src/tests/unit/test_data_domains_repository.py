"""
Unit tests for DataDomainRepository

Tests the repository layer CRUD operations and data mapping for data domains.
"""
import pytest
import uuid
from sqlalchemy.orm import Session

from src.repositories.data_domain_repository import data_domain_repo
from src.models.data_domains import DataDomainCreate, DataDomainUpdate
from src.db_models.data_domains import DataDomain


class TestDataDomainRepository:
    """Test suite for DataDomainRepository CRUD operations"""

    @pytest.fixture
    def sample_create_model(self):
        """Sample DataDomainCreate model for testing."""
        return DataDomainCreate(
            name="Repo Test Domain",
            description="Repository testing domain",
            parent_id=None,
            tags=None,
        )

    # =====================================================================
    # Create Tests
    # =====================================================================

    def test_create_domain_success(self, db_session: Session, sample_create_model):
        """Test creating a domain via repository."""
        # Act
        result = data_domain_repo.create(db=db_session, obj_in=sample_create_model)

        # Assert
        assert result is not None
        assert result.name == sample_create_model.name
        assert result.description == sample_create_model.description
        assert result.id is not None
        # created_by should be set to 'system' by default (see repository implementation)
        assert result.created_by == "system"

        # Verify persistence
        db_session.commit()
        fetched = db_session.query(DataDomain).filter_by(id=result.id).first()
        assert fetched is not None
        assert fetched.name == sample_create_model.name

    def test_create_domain_with_caller_provided_id(self, db_session: Session):
        """Test that a caller-provided UUID is used verbatim as the domain id."""
        # Arrange
        provided_id = uuid.uuid4()
        model = DataDomainCreate(
            name="Custom Id Domain",
            id=provided_id,
        )

        # Act
        result = data_domain_repo.create(db=db_session, obj_in=model)

        # Assert - stored as the provided UUID (stringified for the String PK)
        assert result.id == str(provided_id)
        db_session.commit()
        fetched = db_session.query(DataDomain).filter_by(id=str(provided_id)).first()
        assert fetched is not None

    def test_create_domain_without_id_generates_one(self, db_session: Session):
        """Test that omitting id still auto-generates a UUID (default fires)."""
        # Arrange
        model = DataDomainCreate(name="Auto Id Domain")

        # Act
        result = data_domain_repo.create(db=db_session, obj_in=model)

        # Assert - a UUID was generated and is parseable
        assert result.id is not None
        uuid.UUID(result.id)  # does not raise

    def test_create_domain_with_parent(self, db_session: Session):
        """Test creating domain with parent relationship."""
        # Arrange - Create parent domain
        parent_model = DataDomainCreate(
            name="Parent Domain",
            description="Parent domain",
        )
        parent = data_domain_repo.create(db=db_session, obj_in=parent_model)
        db_session.commit()

        # Act - Create child domain
        child_model = DataDomainCreate(
            name="Child Domain",
            description="Child domain",
            parent_id=uuid.UUID(parent.id),
        )
        child = data_domain_repo.create(db=db_session, obj_in=child_model)

        # Assert
        assert child.parent_id == parent.id
        db_session.refresh(parent)
        assert len(parent.children) == 1
        assert parent.children[0].id == child.id

    def test_create_domain_minimal_fields(self, db_session: Session):
        """Test creating domain with only required fields."""
        # Arrange
        minimal_model = DataDomainCreate(
            name="Minimal Domain",
            created_by="test@example.com",
        )

        # Act
        result = data_domain_repo.create(db=db_session, obj_in=minimal_model)

        # Assert
        assert result is not None
        assert result.name == minimal_model.name
        assert result.description is None
        assert result.parent_id is None

    def test_create_domain_sets_created_by(self, db_session: Session):
        """Test that created_by is set correctly."""
        # Note: created_by is not part of DataDomainCreate model
        # It's set by the manager layer when calling create_domain
        # The repository sets it to 'system' if missing
        # This test verifies the repository's default behavior
        
        # Arrange
        model = DataDomainCreate(
            name="Test Domain",
        )

        # Act
        result = data_domain_repo.create(db=db_session, obj_in=model)

        # Assert - Repository defaults to 'system' if created_by not provided
        assert result.created_by == "system"

    def test_create_domain_without_created_by_uses_system(self, db_session: Session):
        """Test that missing created_by defaults to 'system'."""
        # Arrange
        model = DataDomainCreate(
            name="Test Domain",
        )
        # Don't set created_by

        # Act
        result = data_domain_repo.create(db=db_session, obj_in=model)

        # Assert
        assert result.created_by == "system"

    # =====================================================================
    # Get Tests
    # =====================================================================

    def test_get_domain_by_id_exists(
        self, db_session: Session, sample_create_model
    ):
        """Test retrieving domain by ID when it exists."""
        # Arrange
        created = data_domain_repo.create(db=db_session, obj_in=sample_create_model)

        # Act
        result = data_domain_repo.get(db=db_session, id=created.id)

        # Assert
        assert result is not None
        assert result.id == created.id
        assert result.name == created.name

    def test_get_domain_by_id_not_found(self, db_session: Session):
        """Test retrieving non-existent domain returns None."""
        # Act
        result = data_domain_repo.get(db=db_session, id="nonexistent-id")

        # Assert
        assert result is None

    def test_get_domain_with_details_loads_relationships(
        self, db_session: Session
    ):
        """Test that get_with_details loads parent and children."""
        # Arrange - Create parent and children
        parent_model = DataDomainCreate(
            name="Parent Domain",
        )
        parent = data_domain_repo.create(db=db_session, obj_in=parent_model)

        child1_model = DataDomainCreate(
            name="Child Domain 1",
            parent_id=uuid.UUID(parent.id),
        )
        child1 = data_domain_repo.create(db=db_session, obj_in=child1_model)

        child2_model = DataDomainCreate(
            name="Child Domain 2",
            parent_id=uuid.UUID(parent.id),
        )
        child2 = data_domain_repo.create(db=db_session, obj_in=child2_model)

        db_session.commit()

        # Act
        result = data_domain_repo.get_with_details(db=db_session, id=uuid.UUID(parent.id))

        # Assert
        assert result is not None
        assert len(result.children) == 2
        assert result.parent is None  # Parent has no parent

        # Test child has parent loaded
        child_result = data_domain_repo.get_with_details(db=db_session, id=uuid.UUID(child1.id))
        assert child_result.parent is not None
        assert child_result.parent.id == parent.id

    def test_get_by_name_exists(self, db_session: Session, sample_create_model):
        """Test retrieving domain by name."""
        # Arrange
        created = data_domain_repo.create(db=db_session, obj_in=sample_create_model)

        # Act
        result = data_domain_repo.get_by_name(db=db_session, name=sample_create_model.name)

        # Assert
        assert result is not None
        assert result.id == created.id
        assert result.name == sample_create_model.name

    def test_get_by_name_not_found(self, db_session: Session):
        """Test retrieving non-existent domain by name returns None."""
        # Act
        result = data_domain_repo.get_by_name(db=db_session, name="Nonexistent Domain")

        # Assert
        assert result is None

    # =====================================================================
    # Get Multi (List) Tests
    # =====================================================================

    def test_get_multi_empty(self, db_session: Session):
        """Test listing domains when none exist."""
        # Act
        result = data_domain_repo.get_multi(db=db_session)

        # Assert
        assert isinstance(result, list)
        assert len(result) == 0

    def test_get_multi_returns_all(self, db_session: Session):
        """Test get_multi returns all domains."""
        # Arrange - Create multiple domains
        for i in range(3):
            model = DataDomainCreate(
                name=f"Domain {i}",
                description=f"Domain {i} description",
            )
            data_domain_repo.create(db=db_session, obj_in=model)

        # Act
        result = data_domain_repo.get_multi(db=db_session)

        # Assert
        assert len(result) == 3

    def test_get_multi_pagination(self, db_session: Session):
        """Test pagination with skip and limit."""
        # Arrange - Create 10 domains
        for i in range(10):
            model = DataDomainCreate(
                name=f"Domain {i:02d}",  # Zero-padded for consistent ordering
            )
            data_domain_repo.create(db=db_session, obj_in=model)

        # Act - Get second page (skip 5, limit 3)
        result = data_domain_repo.get_multi(db=db_session, skip=5, limit=3)

        # Assert
        assert len(result) == 3

    def test_get_multi_with_details_loads_relationships(self, db_session: Session):
        """Test that get_multi_with_details loads parent and children."""
        # Arrange - Create hierarchy
        parent_model = DataDomainCreate(
            name="Parent",
        )
        parent = data_domain_repo.create(db=db_session, obj_in=parent_model)

        child_model = DataDomainCreate(
            name="Child",
            parent_id=uuid.UUID(parent.id),
        )
        data_domain_repo.create(db=db_session, obj_in=child_model)

        db_session.commit()

        # Act
        result = data_domain_repo.get_multi_with_details(db=db_session)

        # Assert
        assert len(result) == 2
        # Find parent and verify children loaded
        parent_result = next((d for d in result if d.name == "Parent"), None)
        assert parent_result is not None
        assert len(parent_result.children) == 1

    def test_get_multi_ordered_by_name(self, db_session: Session):
        """Test that results are ordered by name."""
        # Arrange - Create domains in reverse order
        for name in ["Zebra", "Alpha", "Bravo"]:
            model = DataDomainCreate(
                name=name,
            )
            data_domain_repo.create(db=db_session, obj_in=model)

        # Act
        result = data_domain_repo.get_multi_with_details(db=db_session)

        # Assert
        names = [d.name for d in result]
        assert names == ["Alpha", "Bravo", "Zebra"]

    # =====================================================================
    # Update Tests
    # =====================================================================

    def test_update_domain_success(
        self, db_session: Session, sample_create_model
    ):
        """Test updating domain via repository."""
        # Arrange
        created = data_domain_repo.create(db=db_session, obj_in=sample_create_model)

        update_model = DataDomainUpdate(
            name="Updated Name",
            description="Updated description",
        )

        # Act
        result = data_domain_repo.update(
            db=db_session,
            db_obj=created,
            obj_in=update_model
        )

        # Assert
        assert result.name == "Updated Name"
        assert result.description == "Updated description"
        assert result.id == created.id

    def test_update_domain_with_dict(
        self, db_session: Session, sample_create_model
    ):
        """Test updating domain with dictionary."""
        # Arrange
        created = data_domain_repo.create(db=db_session, obj_in=sample_create_model)

        update_dict = {
            "name": "Dict Updated Name",
            "description": "Dict updated description"
        }

        # Act
        result = data_domain_repo.update(
            db=db_session,
            db_obj=created,
            obj_in=update_dict
        )

        # Assert
        assert result.name == "Dict Updated Name"
        assert result.description == "Dict updated description"

    def test_update_domain_partial_fields(
        self, db_session: Session, sample_create_model
    ):
        """Test partial update only changes specified fields."""
        # Arrange
        created = data_domain_repo.create(db=db_session, obj_in=sample_create_model)
        original_name = created.name

        update_dict = {"description": "New description only"}

        # Act
        result = data_domain_repo.update(
            db=db_session,
            db_obj=created,
            obj_in=update_dict
        )

        # Assert
        assert result.description == "New description only"
        assert result.name == original_name  # Name unchanged

    def test_update_domain_change_parent(self, db_session: Session):
        """Test updating domain's parent relationship."""
        # Arrange - Create two potential parents and a child
        parent1_model = DataDomainCreate(
            name="Parent 1",
        )
        parent1 = data_domain_repo.create(db=db_session, obj_in=parent1_model)

        parent2_model = DataDomainCreate(
            name="Parent 2",
        )
        parent2 = data_domain_repo.create(db=db_session, obj_in=parent2_model)

        child_model = DataDomainCreate(
            name="Child",
            parent_id=uuid.UUID(parent1.id),
        )
        child = data_domain_repo.create(db=db_session, obj_in=child_model)
        db_session.commit()

        # Act - Change parent
        update_dict = {"parent_id": uuid.UUID(parent2.id)}
        result = data_domain_repo.update(
            db=db_session,
            db_obj=child,
            obj_in=update_dict
        )

        # Assert
        assert result.parent_id == parent2.id
        db_session.refresh(parent2)
        assert len(parent2.children) == 1

    # =====================================================================
    # Delete Tests
    # =====================================================================

    def test_delete_domain_success(
        self, db_session: Session, sample_create_model
    ):
        """Test deleting domain via repository."""
        # Arrange
        created = data_domain_repo.create(db=db_session, obj_in=sample_create_model)
        domain_id = created.id

        # Act
        result = data_domain_repo.remove(db=db_session, id=domain_id)

        # Assert
        assert result is not None
        assert result.id == domain_id

        # Verify deletion
        fetched = data_domain_repo.get(db=db_session, id=domain_id)
        assert fetched is None

    def test_delete_domain_not_found(self, db_session: Session):
        """Test deleting non-existent domain returns None."""
        # Act
        result = data_domain_repo.remove(db=db_session, id="nonexistent-id")

        # Assert
        assert result is None

    def test_delete_domain_cascades_to_children(self, db_session: Session):
        """Test that deleting parent cascades to children."""
        # Arrange - Create parent with children
        parent_model = DataDomainCreate(
            name="Parent",
        )
        parent = data_domain_repo.create(db=db_session, obj_in=parent_model)

        child_model = DataDomainCreate(
            name="Child",
            parent_id=uuid.UUID(parent.id),
        )
        child = data_domain_repo.create(db=db_session, obj_in=child_model)
        child_id = child.id
        db_session.commit()

        # Act - Delete parent
        data_domain_repo.remove(db=db_session, id=parent.id)
        db_session.commit()

        # Assert - Child should also be deleted (cascade)
        child_after_delete = data_domain_repo.get(db=db_session, id=child_id)
        assert child_after_delete is None

    # =====================================================================
    # Model Conversion Tests
    # =====================================================================

    def test_api_to_db_model_conversion(
        self, db_session: Session, sample_create_model
    ):
        """Test conversion from API model to DB model."""
        # Act
        result = data_domain_repo.create(db=db_session, obj_in=sample_create_model)

        # Assert
        assert isinstance(result, DataDomain)
        # Verify field mapping
        assert result.name == sample_create_model.name
        assert result.description == sample_create_model.description

    def test_uuid_to_string_conversion_for_parent_id(self, db_session: Session):
        """Test that UUID parent_id is converted to string for SQLite."""
        # Arrange
        parent_model = DataDomainCreate(
            name="Parent",
        )
        parent = data_domain_repo.create(db=db_session, obj_in=parent_model)

        # Act - Create child with UUID parent_id
        child_model = DataDomainCreate(
            name="Child",
            parent_id=uuid.UUID(parent.id),  # UUID object
        )
        child = data_domain_repo.create(db=db_session, obj_in=child_model)

        # Assert - parent_id stored as string
        assert isinstance(child.parent_id, str)
        assert child.parent_id == parent.id
