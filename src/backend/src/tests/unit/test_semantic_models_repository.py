"""
Unit tests for SemanticModelsRepository

Tests database operations for semantic model management including:
- CRUD operations (create, read, list, update, delete)
- Get by name
"""
import pytest
import uuid

from src.repositories.semantic_models_repository import SemanticModelsRepository
from src.db_models.semantic_models import SemanticModelDb


class TestSemanticModelsRepository:
    """Test suite for SemanticModelsRepository"""

    @pytest.fixture
    def repository(self):
        """Create repository instance for testing."""
        return SemanticModelsRepository(SemanticModelDb)

    def test_create_semantic_model(self, repository, db_session):
        """Test creating a semantic model."""
        # Arrange
        model_db = SemanticModelDb(
            id=str(uuid.uuid4()),
            name="Test Model",
            format="rdfs",
            content_text="<rdf:RDF>content</rdf:RDF>",
        )

        # Act
        db_session.add(model_db)
        db_session.commit()
        db_session.refresh(model_db)

        # Assert
        assert model_db.name == "Test Model"

    def test_get_semantic_model_by_id(self, repository, db_session):
        """Test retrieving a semantic model by ID."""
        # Arrange
        model_db = SemanticModelDb(
            id=str(uuid.uuid4()),
            name="Test Model",
            format="rdfs",
            content_text="<rdf:RDF>content</rdf:RDF>",
        )
        db_session.add(model_db)
        db_session.commit()

        # Act
        result = repository.get(db_session, id=model_db.id)

        # Assert
        assert result is not None
        assert result.id == model_db.id

    def test_get_by_name(self, repository, db_session):
        """Test retrieving a semantic model by name."""
        # Arrange
        model_db = SemanticModelDb(
            id=str(uuid.uuid4()),
            name="Unique Model Name",
            format="rdfs",
            content_text="<rdf:RDF>content</rdf:RDF>",
        )
        db_session.add(model_db)
        db_session.commit()

        # Act
        result = repository.get_by_name(db_session, name="Unique Model Name")

        # Assert
        assert result is not None
        assert result.name == "Unique Model Name"

    def test_get_by_name_not_found(self, repository, db_session):
        """Test retrieving non-existent semantic model by name."""
        # Act
        result = repository.get_by_name(db_session, name="Nonexistent Model")

        # Assert
        assert result is None

    def test_get_multi_empty(self, repository, db_session):
        """Test listing semantic models when none exist."""
        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert result == []

    def test_get_multi_models(self, repository, db_session):
        """Test listing multiple semantic models."""
        # Arrange
        for i in range(3):
            model_db = SemanticModelDb(
                id=str(uuid.uuid4()),
                name=f"Model {i}",
                format="rdfs",
                content_text=f"<rdf:RDF>content {i}</rdf:RDF>",
            )
            db_session.add(model_db)
        db_session.commit()

        # Act
        result = repository.get_multi(db_session)

        # Assert
        assert len(result) == 3

    def test_update_semantic_model(self, repository, db_session):
        """Test updating a semantic model."""
        # Arrange
        model_db = SemanticModelDb(
            id=str(uuid.uuid4()),
            name="Original Name",
            format="rdfs",
            content_text="<rdf:RDF>original</rdf:RDF>",
            enabled=True,
        )
        db_session.add(model_db)
        db_session.commit()

        # Act
        model_db.name = "Updated Name"
        model_db.enabled = False
        db_session.commit()
        db_session.refresh(model_db)

        # Assert
        assert model_db.name == "Updated Name"
        assert model_db.enabled is False

    def test_delete_semantic_model(self, repository, db_session):
        """Test deleting a semantic model."""
        # Arrange
        model_db = SemanticModelDb(
            id=str(uuid.uuid4()),
            name="Test Model",
            format="rdfs",
            content_text="<rdf:RDF>content</rdf:RDF>",
        )
        db_session.add(model_db)
        db_session.commit()
        model_id = model_db.id

        # Act
        repository.remove(db_session, id=model_id)
        db_session.commit()

        # Assert
        deleted = repository.get(db_session, id=model_id)
        assert deleted is None

    def test_count_semantic_models(self, repository, db_session):
        """Test counting semantic models."""
        # Arrange
        for i in range(5):
            model_db = SemanticModelDb(
                id=str(uuid.uuid4()),
                name=f"Model {i}",
                format="rdfs",
                content_text=f"<rdf:RDF>content {i}</rdf:RDF>",
            )
            db_session.add(model_db)
        db_session.commit()

        # Act
        count = repository.count(db_session)

        # Assert
        assert count == 5

    def test_create_with_skos_format(self, repository, db_session):
        """Test creating a semantic model with SKOS format."""
        # Arrange
        model_db = SemanticModelDb(
            id=str(uuid.uuid4()),
            name="SKOS Model",
            format="skos",
            content_text="<skos:ConceptScheme>content</skos:ConceptScheme>",
        )

        # Act
        db_session.add(model_db)
        db_session.commit()
        db_session.refresh(model_db)

        # Assert
        assert model_db.format == "skos"

