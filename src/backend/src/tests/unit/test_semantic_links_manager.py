"""
Unit tests for SemanticLinksManager
"""
import pytest
from pydantic import ValidationError
from unittest.mock import Mock, MagicMock, patch
from src.controller.semantic_links_manager import SemanticLinksManager
from src.models.semantic_links import EntitySemanticLink, EntitySemanticLinkCreate
from src.db_models.semantic_links import EntitySemanticLinkDb


class TestEntitySemanticLinkCreateModel:
    """Validate the EntityType Literal accepts the polymorphic 'asset' value."""

    def test_asset_entity_type_validates(self):
        payload = EntitySemanticLinkCreate(
            entity_id="11111111-2222-3333-4444-555555555555",
            entity_type="asset",
            iri="http://example.com/schema/Customer",
            label="Customer",
        )
        assert payload.entity_type == "asset"

    def test_unknown_entity_type_rejected(self):
        with pytest.raises(ValidationError):
            EntitySemanticLinkCreate(
                entity_id="x",
                entity_type="not_an_entity_type",  # type: ignore[arg-type]
                iri="http://example.com/x",
            )


class TestSemanticLinksManager:
    """Test suite for SemanticLinksManager."""

    @pytest.fixture
    def mock_db(self):
        """Create mock database session."""
        db = Mock()
        db.execute = Mock()
        db.flush = Mock()
        db.refresh = Mock()
        db.add = Mock()
        return db

    @pytest.fixture
    def mock_semantic_models_manager(self):
        """Create mock semantic models manager."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_db, mock_semantic_models_manager):
        """Create SemanticLinksManager instance for testing."""
        return SemanticLinksManager(db=mock_db, semantic_models_manager=mock_semantic_models_manager)

    @pytest.fixture
    def sample_link_db(self):
        """Sample semantic link database object."""
        link = Mock(spec=EntitySemanticLinkDb)
        link.id = 1
        link.entity_id = "entity-123"
        link.entity_type = "data_product"
        link.iri = "http://example.com/schema/Product"
        link.label = "Product"
        return link

    @pytest.fixture
    def sample_link_create(self):
        """Sample semantic link creation data."""
        return EntitySemanticLinkCreate(
            entity_id="entity-123",
            entity_type="data_product",
            iri="http://example.com/schema/Product",
            label="Product",
        )

    # Initialization Tests

    def test_manager_initialization(self, mock_db, mock_semantic_models_manager):
        """Test manager initializes with db and semantic models manager."""
        manager = SemanticLinksManager(db=mock_db, semantic_models_manager=mock_semantic_models_manager)
        assert manager._db == mock_db
        assert manager._semantic_models_manager == mock_semantic_models_manager

    def test_manager_initialization_without_semantic_models_manager(self, mock_db):
        """Test manager initializes without semantic models manager."""
        manager = SemanticLinksManager(db=mock_db, semantic_models_manager=None)
        assert manager._db == mock_db
        assert manager._semantic_models_manager is None

    # Resolve Entity Name Tests

    def test_resolve_entity_name_data_domain(self, manager, mock_db):
        """Test resolving entity name for data domain."""
        mock_result = Mock()
        mock_result.__getitem__ = Mock(return_value="Domain Name")
        mock_db.execute.return_value.fetchone.return_value = mock_result

        result = manager._resolve_entity_name("domain-123", "data_domain")

        assert result == "Domain Name"

    def test_resolve_entity_name_data_product(self, manager, mock_db):
        """Test resolving entity name for data product."""
        mock_result = Mock()
        mock_result.__getitem__ = Mock(return_value="Product Title")
        mock_db.execute.return_value.fetchone.return_value = mock_result

        result = manager._resolve_entity_name("product-123", "data_product")

        assert result == "Product Title"

    def test_resolve_entity_name_data_contract(self, manager, mock_db):
        """Test resolving entity name for data contract."""
        mock_result = Mock()
        mock_result.__getitem__ = Mock(return_value="Contract Name")
        mock_db.execute.return_value.fetchone.return_value = mock_result

        result = manager._resolve_entity_name("contract-123", "data_contract")

        assert result == "Contract Name"

    def test_resolve_entity_name_asset(self, manager, mock_db):
        """Test resolving entity name for asset (polymorphic AssetDb row)."""
        mock_result = Mock()
        mock_result.__getitem__ = Mock(return_value="customers_table")
        mock_db.execute.return_value.fetchone.return_value = mock_result

        result = manager._resolve_entity_name(
            "11111111-2222-3333-4444-555555555555", "asset"
        )

        assert result == "customers_table"
        # Ensure the SQL targets the shared assets table (same path as dataset)
        called_sql = str(mock_db.execute.call_args[0][0])
        assert "FROM assets" in called_sql

    def test_resolve_entity_name_not_found(self, manager, mock_db):
        """Test resolving entity name when entity not found."""
        mock_db.execute.return_value.fetchone.return_value = None

        result = manager._resolve_entity_name("nonexistent", "data_product")

        assert result is None

    def test_resolve_entity_name_database_error(self, manager, mock_db):
        """Test handling of database errors when resolving entity name."""
        mock_db.execute.side_effect = Exception("Database error")

        result = manager._resolve_entity_name("entity-123", "data_product")

        assert result is None

    # To API Tests

    def test_to_api_with_label(self, manager, sample_link_db):
        """Test converting DB object to API model with existing label."""
        result = manager._to_api(sample_link_db)

        assert isinstance(result, EntitySemanticLink)
        assert result.id == "1"
        assert result.entity_id == "entity-123"
        assert result.entity_type == "data_product"
        assert result.iri == "http://example.com/schema/Product"
        assert result.label == "Product"

    def test_to_api_without_label_resolves_name(self, manager, sample_link_db, mock_db):
        """Test converting DB object to API model resolves name when no label."""
        sample_link_db.label = None
        mock_result = Mock()
        mock_result.__getitem__ = Mock(return_value="Resolved Name")
        mock_db.execute.return_value.fetchone.return_value = mock_result

        result = manager._to_api(sample_link_db)

        assert result.label == "Resolved Name"

    # List for Entity Tests

    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_list_for_entity_empty(self, mock_repo, manager):
        """Test listing semantic links for entity when none exist."""
        mock_repo.list_for_entity.return_value = []

        result = manager.list_for_entity("entity-123", "data_product")

        assert result == []
        mock_repo.list_for_entity.assert_called_once_with(
            manager._db, "entity-123", "data_product"
        )

    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_list_for_entity_with_results(self, mock_repo, manager, sample_link_db):
        """Test listing semantic links for entity with results."""
        mock_repo.list_for_entity.return_value = [sample_link_db]

        result = manager.list_for_entity("entity-123", "data_product")

        assert len(result) == 1
        assert result[0].entity_id == "entity-123"

    # List for IRI Tests

    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_list_for_iri_explicit_links_only(self, mock_repo, manager, sample_link_db):
        """Test listing entities for IRI with explicit links only."""
        mock_repo.list_for_iri.return_value = [sample_link_db]

        result = manager.list_for_iri("http://example.com/schema/Product")

        assert len(result) == 1
        assert result[0].iri == "http://example.com/schema/Product"

    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_list_for_iri_includes_inferred_links(
        self, mock_repo, manager, sample_link_db, mock_semantic_models_manager
    ):
        """Test listing entities for IRI includes inferred links from graph."""
        mock_repo.list_for_iri.return_value = [sample_link_db]
        
        # Mock SPARQL query results
        mock_semantic_models_manager.query.return_value = [
            {
                'subject': 'urn:ontos:data_product:inferred-123',
                'label': 'Inferred Product'
            }
        ]

        result = manager.list_for_iri("http://example.com/schema/Product")

        assert len(result) == 2  # 1 explicit + 1 inferred
        # Check for inferred link
        inferred = [r for r in result if r.id.startswith("inferred:")]
        assert len(inferred) == 1
        assert inferred[0].entity_id == "inferred-123"

    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_list_for_iri_without_semantic_models_manager(
        self, mock_repo, manager, sample_link_db
    ):
        """Test listing entities for IRI without semantic models manager."""
        manager._semantic_models_manager = None
        mock_repo.list_for_iri.return_value = [sample_link_db]

        result = manager.list_for_iri("http://example.com/schema/Product")

        # Should only return explicit links
        assert len(result) == 1

    # Link Exists Tests

    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_link_exists_true(self, mock_repo, manager, sample_link_db):
        """Test checking if link exists returns true."""
        mock_repo.get_by_entity_and_iri.return_value = sample_link_db

        result = manager._link_exists("entity-123", "data_product", "http://example.com/schema/Product")

        assert result is True

    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_link_exists_false(self, mock_repo, manager):
        """Test checking if link exists returns false."""
        mock_repo.get_by_entity_and_iri.return_value = None

        result = manager._link_exists("entity-123", "data_product", "http://example.com/schema/Product")

        assert result is False

    # Add Link Tests

    @patch('src.controller.semantic_links_manager.change_log_manager')
    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_add_link_success(self, mock_repo, mock_change_log, manager, sample_link_create, sample_link_db):
        """Test successfully adding a new semantic link."""
        mock_repo.get_by_entity_and_iri.return_value = None  # Link doesn't exist
        mock_repo.create.return_value = sample_link_db

        result = manager.add(sample_link_create, created_by="user@example.com")

        assert isinstance(result, EntitySemanticLink)
        assert result.entity_id == "entity-123"
        mock_repo.create.assert_called_once()
        manager._db.flush.assert_called_once()
        manager._db.refresh.assert_called_once()

    @patch('src.controller.semantic_links_manager.change_log_manager')
    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_add_link_for_asset(self, mock_repo, mock_change_log, manager):
        """Test adding a semantic link with entity_type='asset' (UUID-based)."""
        asset_uuid = "11111111-2222-3333-4444-555555555555"
        payload = EntitySemanticLinkCreate(
            entity_id=asset_uuid,
            entity_type="asset",
            iri="http://example.com/schema/Customer",
            label="Customer",
        )
        created_db = Mock(spec=EntitySemanticLinkDb)
        created_db.id = 42
        created_db.entity_id = asset_uuid
        created_db.entity_type = "asset"
        created_db.iri = "http://example.com/schema/Customer"
        created_db.label = "Customer"
        mock_repo.get_by_entity_and_iri.return_value = None
        mock_repo.create.return_value = created_db

        result = manager.add(payload, created_by="user@example.com")

        assert result.entity_type == "asset"
        assert result.entity_id == asset_uuid
        mock_repo.create.assert_called_once()

    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_add_link_already_exists(self, mock_repo, manager, sample_link_create, sample_link_db):
        """Test adding link that already exists returns existing link."""
        mock_repo.get_by_entity_and_iri.return_value = sample_link_db  # Link exists

        result = manager.add(sample_link_create, created_by="user@example.com")

        # Should return existing link without creating new one
        mock_repo.create.assert_not_called()
        assert result.entity_id == "entity-123"

    @patch('src.controller.semantic_links_manager.change_log_manager')
    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_add_link_logs_change(self, mock_repo, mock_change_log, manager, sample_link_create, sample_link_db):
        """Test that adding link logs change."""
        mock_repo.get_by_entity_and_iri.return_value = None
        mock_repo.create.return_value = sample_link_db

        manager.add(sample_link_create, created_by="user@example.com")

        mock_change_log.log_change_with_details.assert_called_once()

    # Remove Link Tests

    @patch('src.controller.semantic_links_manager.change_log_manager')
    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_remove_link_success(self, mock_repo, mock_change_log, manager, sample_link_db):
        """Test successfully removing a semantic link."""
        mock_repo.remove.return_value = sample_link_db

        result = manager.remove("1", removed_by="user@example.com")

        assert result is True
        mock_repo.remove.assert_called_once_with(manager._db, id="1")

    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_remove_link_not_found(self, mock_repo, manager):
        """Test removing non-existent link."""
        mock_repo.remove.return_value = None

        result = manager.remove("nonexistent", removed_by="user@example.com")

        assert result is False

    @patch('src.controller.semantic_links_manager.change_log_manager')
    @patch('src.controller.semantic_links_manager.entity_semantic_links_repo')
    def test_remove_link_logs_change(self, mock_repo, mock_change_log, manager, sample_link_db):
        """Test that removing link logs change."""
        mock_repo.remove.return_value = sample_link_db

        manager.remove("1", removed_by="user@example.com")

        mock_change_log.log_change_with_details.assert_called_once()

