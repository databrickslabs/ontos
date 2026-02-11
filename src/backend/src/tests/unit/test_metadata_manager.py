"""
Unit tests for MetadataManager
"""
import uuid
from datetime import datetime
import pytest
from unittest.mock import Mock, MagicMock
from databricks.sdk.service.catalog import VolumeType
from src.controller.metadata_manager import MetadataManager
from src.models.metadata import RichTextCreate, RichTextUpdate, LinkCreate, LinkUpdate, DocumentCreate
from src.db_models.metadata import RichTextMetadataDb, LinkMetadataDb, DocumentMetadataDb


class TestMetadataManager:
    """Test suite for MetadataManager."""

    @pytest.fixture
    def mock_rich_text_repo(self):
        """Create mock rich text repository."""
        return Mock()

    @pytest.fixture
    def mock_link_repo(self):
        """Create mock link repository."""
        return Mock()

    @pytest.fixture
    def mock_document_repo(self):
        """Create mock document repository."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_rich_text_repo, mock_link_repo, mock_document_repo):
        """Create MetadataManager instance for testing."""
        return MetadataManager(
            rich_text_repository=mock_rich_text_repo,
            link_repository=mock_link_repo,
            document_repository=mock_document_repo,
        )

    @pytest.fixture
    def sample_rich_text_db(self):
        """Sample rich text database object."""
        rt = Mock(spec=RichTextMetadataDb)
        rt.id = uuid.UUID("12345678-1234-1234-1234-123456789012")
        rt.entity_type = "data_product"
        rt.entity_id = "product-456"
        rt.title = "Documentation"
        rt.short_description = "Product docs"
        rt.content_markdown = "# Test\nContent"
        rt.is_shared = False
        rt.level = 50
        rt.inheritable = True
        rt.created_by = "user@example.com"
        rt.updated_by = "user@example.com"
        rt.created_at = datetime(2024, 1, 1, 12, 0, 0)
        rt.updated_at = datetime(2024, 1, 1, 12, 0, 0)
        return rt

    @pytest.fixture
    def sample_link_db(self):
        """Sample link database object."""
        link = Mock(spec=LinkMetadataDb)
        link.id = uuid.UUID("22345678-1234-1234-1234-123456789012")
        link.entity_type = "data_contract"
        link.entity_id = "contract-456"
        link.title = "Related Link"
        link.short_description = "External resource"
        link.url = "https://example.com"
        link.is_shared = False
        link.level = 50
        link.inheritable = True
        link.created_by = "user@example.com"
        link.updated_by = "user@example.com"
        link.created_at = datetime(2024, 1, 1, 12, 0, 0)
        link.updated_at = datetime(2024, 1, 1, 12, 0, 0)
        return link

    @pytest.fixture
    def sample_document_db(self):
        """Sample document database object."""
        doc = Mock(spec=DocumentMetadataDb)
        doc.id = uuid.UUID("32345678-1234-1234-1234-123456789012")
        doc.entity_type = "data_product"
        doc.entity_id = "product-789"
        doc.title = "User Guide"
        doc.short_description = "PDF guide"
        doc.original_filename = "guide.pdf"
        doc.content_type = "application/pdf"
        doc.size_bytes = 1024000
        doc.storage_path = "/volumes/catalog/schema/volume/guide.pdf"
        doc.is_shared = False
        doc.level = 50
        doc.inheritable = True
        doc.created_by = "user@example.com"
        doc.updated_by = "user@example.com"
        doc.created_at = datetime(2024, 1, 1, 12, 0, 0)
        doc.updated_at = datetime(2024, 1, 1, 12, 0, 0)
        return doc

    # Initialization Tests

    def test_manager_initialization(self, mock_rich_text_repo, mock_link_repo, mock_document_repo):
        """Test manager initializes with repositories."""
        manager = MetadataManager(
            rich_text_repository=mock_rich_text_repo,
            link_repository=mock_link_repo,
            document_repository=mock_document_repo,
        )
        assert manager._rich_text_repo == mock_rich_text_repo
        assert manager._link_repo == mock_link_repo
        assert manager._document_repo == mock_document_repo

    # Rich Text Tests

    def test_create_rich_text_success(self, manager, mock_rich_text_repo, sample_rich_text_db):
        """Test creating rich text metadata."""
        mock_rich_text_repo.create.return_value = sample_rich_text_db
        mock_db = Mock()

        data = RichTextCreate(
            entity_type="data_product",
            entity_id="product-456",
            title="Documentation",
            short_description="Product docs",
            content_markdown="# Test\nContent",
        )

        result = manager.create_rich_text(mock_db, data=data, user_email="user@example.com")

        assert result.id == uuid.UUID("12345678-1234-1234-1234-123456789012")
        mock_rich_text_repo.create.assert_called_once()
        assert mock_db.commit.called

    def test_list_rich_texts_empty(self, manager, mock_rich_text_repo):
        """Test listing rich texts when none exist."""
        mock_rich_text_repo.list_for_entity.return_value = []
        mock_db = Mock()

        result = manager.list_rich_texts(mock_db, entity_type="data_product", entity_id="product-456")

        assert result == []

    def test_list_rich_texts_with_results(self, manager, mock_rich_text_repo, sample_rich_text_db):
        """Test listing rich texts with results."""
        mock_rich_text_repo.list_for_entity.return_value = [sample_rich_text_db]
        mock_db = Mock()

        result = manager.list_rich_texts(mock_db, entity_type="data_product", entity_id="product-456")

        assert len(result) == 1
        assert result[0].id == uuid.UUID("12345678-1234-1234-1234-123456789012")

    def test_update_rich_text_success(self, manager, mock_rich_text_repo, sample_rich_text_db):
        """Test updating rich text metadata."""
        updated_rt = Mock(spec=RichTextMetadataDb)
        for attr in (
            "id", "entity_type", "entity_id", "title", "short_description", "content_markdown",
            "is_shared", "level", "inheritable", "created_by", "updated_by",
            "created_at", "updated_at",
        ):
            setattr(updated_rt, attr, getattr(sample_rich_text_db, attr))
        updated_rt.title = "Updated Title"

        mock_rich_text_repo.get.return_value = sample_rich_text_db
        mock_rich_text_repo.update.return_value = updated_rt
        mock_db = Mock()

        update_data = RichTextUpdate(title="Updated Title")
        result = manager.update_rich_text(
            mock_db, id="12345678-1234-1234-1234-123456789012", data=update_data, user_email="user@example.com"
        )

        assert result is not None
        assert result.title == "Updated Title"

    def test_update_rich_text_not_found(self, manager, mock_rich_text_repo):
        """Test updating non-existent rich text."""
        mock_rich_text_repo.get.return_value = None
        mock_db = Mock()

        update_data = RichTextUpdate(title="Updated")
        result = manager.update_rich_text(mock_db, id="nonexistent", data=update_data, user_email="user@example.com")

        assert result is None

    def test_delete_rich_text_success(self, manager, mock_rich_text_repo, sample_rich_text_db):
        """Test deleting rich text metadata."""
        mock_rich_text_repo.get.return_value = sample_rich_text_db
        mock_rich_text_repo.remove.return_value = sample_rich_text_db
        mock_db = Mock()

        result = manager.delete_rich_text(
            mock_db, id="12345678-1234-1234-1234-123456789012", user_email="user@example.com"
        )

        assert result is True
        mock_rich_text_repo.remove.assert_called_once()

    def test_delete_rich_text_not_found(self, manager, mock_rich_text_repo):
        """Test deleting non-existent rich text."""
        mock_rich_text_repo.get.return_value = None
        mock_db = Mock()

        result = manager.delete_rich_text(mock_db, id="nonexistent", user_email="user@example.com")

        assert result is False

    # Link Tests

    def test_create_link_success(self, manager, mock_link_repo, sample_link_db):
        """Test creating link metadata."""
        mock_link_repo.create.return_value = sample_link_db
        mock_db = Mock()

        data = LinkCreate(
            entity_type="data_contract",
            entity_id="contract-456",
            title="Related Link",
            short_description="External resource",
            url="https://example.com",
        )

        result = manager.create_link(mock_db, data=data, user_email="user@example.com")

        assert result.id == uuid.UUID("22345678-1234-1234-1234-123456789012")
        mock_link_repo.create.assert_called_once()

    def test_list_links_empty(self, manager, mock_link_repo):
        """Test listing links when none exist."""
        mock_link_repo.list_for_entity.return_value = []
        mock_db = Mock()

        result = manager.list_links(mock_db, entity_type="data_contract", entity_id="contract-456")

        assert result == []

    def test_list_links_with_results(self, manager, mock_link_repo, sample_link_db):
        """Test listing links with results."""
        mock_link_repo.list_for_entity.return_value = [sample_link_db]
        mock_db = Mock()

        result = manager.list_links(mock_db, entity_type="data_contract", entity_id="contract-456")

        assert len(result) == 1
        assert result[0].url == "https://example.com"

    def test_update_link_success(self, manager, mock_link_repo, sample_link_db):
        """Test updating link metadata."""
        updated_link = Mock(spec=LinkMetadataDb)
        for attr in (
            "id", "entity_type", "entity_id", "title", "short_description", "url",
            "is_shared", "level", "inheritable", "created_by", "updated_by",
            "created_at", "updated_at",
        ):
            setattr(updated_link, attr, getattr(sample_link_db, attr))
        updated_link.url = "https://updated.com"

        mock_link_repo.get.return_value = sample_link_db
        mock_link_repo.update.return_value = updated_link
        mock_db = Mock()

        update_data = LinkUpdate(url="https://updated.com")
        result = manager.update_link(
            mock_db, id="22345678-1234-1234-1234-123456789012", data=update_data, user_email="user@example.com"
        )

        assert result is not None
        assert result.url == "https://updated.com"

    def test_update_link_not_found(self, manager, mock_link_repo):
        """Test updating non-existent link."""
        mock_link_repo.get.return_value = None
        mock_db = Mock()

        update_data = LinkUpdate(url="https://updated.com")
        result = manager.update_link(mock_db, id="nonexistent", data=update_data, user_email="user@example.com")

        assert result is None

    def test_delete_link_success(self, manager, mock_link_repo, sample_link_db):
        """Test deleting link metadata."""
        mock_link_repo.get.return_value = sample_link_db
        mock_link_repo.remove.return_value = sample_link_db
        mock_db = Mock()

        result = manager.delete_link(
            mock_db, id="22345678-1234-1234-1234-123456789012", user_email="user@example.com"
        )

        assert result is True

    def test_delete_link_not_found(self, manager, mock_link_repo):
        """Test deleting non-existent link."""
        mock_link_repo.get.return_value = None
        mock_db = Mock()

        result = manager.delete_link(mock_db, id="nonexistent", user_email="user@example.com")

        assert result is False

    # Document Tests

    def test_create_document_record_success(self, manager):
        """Test creating document record."""
        mock_db = Mock()

        # Simulate db.refresh populating DB-generated fields (id, timestamps, defaults)
        def _mock_refresh(db_obj):
            setattr(db_obj, "id", uuid.UUID("32345678-1234-1234-1234-123456789012"))
            setattr(db_obj, "created_at", datetime(2024, 1, 1, 12, 0, 0))
            setattr(db_obj, "updated_at", datetime(2024, 1, 1, 12, 0, 0))
            setattr(db_obj, "is_shared", False)
            setattr(db_obj, "level", 50)
            setattr(db_obj, "inheritable", True)

        mock_db.refresh = Mock(side_effect=_mock_refresh)

        data = DocumentCreate(
            entity_type="data_product",
            entity_id="product-789",
            title="User Guide",
            short_description="PDF guide",
        )

        result = manager.create_document_record(
            mock_db,
            data=data,
            filename="guide.pdf",
            content_type="application/pdf",
            size_bytes=1024000,
            storage_path="/volumes/catalog/schema/volume/guide.pdf",
            user_email="user@example.com",
        )

        assert result.title == "User Guide"
        assert mock_db.add.called
        assert mock_db.commit.called

    def test_list_documents_empty(self, manager, mock_document_repo):
        """Test listing documents when none exist."""
        mock_document_repo.list_for_entity.return_value = []
        mock_db = Mock()

        result = manager.list_documents(mock_db, entity_type="data_product", entity_id="product-789")

        assert result == []

    def test_list_documents_with_results(self, manager, mock_document_repo, sample_document_db):
        """Test listing documents with results."""
        mock_document_repo.list_for_entity.return_value = [sample_document_db]
        mock_db = Mock()

        result = manager.list_documents(mock_db, entity_type="data_product", entity_id="product-789")

        assert len(result) == 1
        assert result[0].original_filename == "guide.pdf"

    def test_get_document_success(self, manager, mock_document_repo, sample_document_db):
        """Test getting a document by ID."""
        mock_document_repo.get.return_value = sample_document_db
        mock_db = Mock()

        result = manager.get_document(mock_db, id="32345678-1234-1234-1234-123456789012")

        assert result is not None
        assert result.id == uuid.UUID("32345678-1234-1234-1234-123456789012")

    def test_get_document_not_found(self, manager, mock_document_repo):
        """Test getting non-existent document."""
        mock_document_repo.get.return_value = None
        mock_db = Mock()

        result = manager.get_document(mock_db, id="nonexistent")

        assert result is None

    def test_delete_document_success(self, manager, mock_document_repo, sample_document_db):
        """Test deleting document metadata."""
        mock_document_repo.get.return_value = sample_document_db
        mock_document_repo.remove.return_value = sample_document_db
        mock_db = Mock()

        result = manager.delete_document(
            mock_db, id="32345678-1234-1234-1234-123456789012", user_email="user@example.com"
        )

        assert result is True

    def test_delete_document_not_found(self, manager, mock_document_repo):
        """Test deleting non-existent document."""
        mock_document_repo.get.return_value = None
        mock_db = Mock()

        result = manager.delete_document(mock_db, id="nonexistent", user_email="user@example.com")

        assert result is False

    # Volume Management Tests

    def test_ensure_volume_path_existing_volume(self, manager):
        """Test ensuring volume path when volume exists."""
        mock_ws = Mock()
        mock_ws.volumes.read.return_value = Mock()  # Volume exists

        mock_settings = Mock()
        mock_settings.DATABRICKS_CATALOG = "test_catalog"
        mock_settings.DATABRICKS_SCHEMA = "test_schema"
        mock_settings.DATABRICKS_VOLUME = "test_volume"

        result = manager.ensure_volume_path(mock_ws, mock_settings, "documents")

        assert result == "/Volumes/test_catalog/test_schema/test_volume"
        mock_ws.volumes.read.assert_called_once()
        mock_ws.volumes.create.assert_not_called()

    def test_ensure_volume_path_creates_volume(self, manager):
        """Test ensuring volume path when volume doesn't exist."""
        mock_ws = Mock()
        mock_ws.volumes.read.side_effect = Exception("Volume not found")
        mock_ws.volumes.create.return_value = Mock()

        mock_settings = Mock()
        mock_settings.DATABRICKS_CATALOG = "test_catalog"
        mock_settings.DATABRICKS_SCHEMA = "test_schema"
        mock_settings.DATABRICKS_VOLUME = "test_volume"

        result = manager.ensure_volume_path(mock_ws, mock_settings, "documents")

        assert result == "/Volumes/test_catalog/test_schema/test_volume"
        mock_ws.volumes.create.assert_called_once_with(
            catalog_name="test_catalog",
            schema_name="test_schema",
            name="test_volume",
            volume_type=VolumeType.MANAGED,
        )

    def test_ensure_volume_path_creation_fails(self, manager):
        """Test volume path when creation fails."""
        mock_ws = Mock()
        mock_ws.volumes.read.side_effect = Exception("Volume not found")
        mock_ws.volumes.create.side_effect = Exception("Permission denied")

        mock_settings = Mock()
        mock_settings.DATABRICKS_CATALOG = "test_catalog"
        mock_settings.DATABRICKS_SCHEMA = "test_schema"
        mock_settings.DATABRICKS_VOLUME = "test_volume"

        with pytest.raises(Exception, match="Permission denied"):
            manager.ensure_volume_path(mock_ws, mock_settings, "documents")

