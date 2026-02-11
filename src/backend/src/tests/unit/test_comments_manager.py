"""
Unit tests for CommentsManager
"""
import pytest
import json
import uuid
from datetime import datetime
from unittest.mock import Mock, MagicMock
from src.controller.comments_manager import CommentsManager
from src.models.comments import CommentCreate, CommentUpdate, Comment
from src.db_models.comments import CommentDb, CommentStatus, CommentType as DbCommentType


class TestCommentsManager:
    """Test suite for CommentsManager."""

    @pytest.fixture
    def mock_repository(self):
        """Create mock comments repository."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_repository):
        """Create CommentsManager instance for testing."""
        return CommentsManager(comments_repository=mock_repository)

    @pytest.fixture
    def sample_comment_db(self):
        """Sample comment database object."""
        comment = Mock(spec=CommentDb)
        comment.id = uuid.UUID("11111111-2222-3333-4444-555555555555")
        comment.entity_id = "entity-456"
        comment.entity_type = "data_product"
        comment.title = "Test Comment"
        comment.comment = "This is a test comment"
        comment.audience = None
        comment.project_id = None
        comment.status = CommentStatus.ACTIVE
        comment.comment_type = DbCommentType.COMMENT
        comment.rating = None
        comment.created_by = "user@example.com"
        comment.updated_by = "user@example.com"
        comment.created_at = datetime(2024, 1, 1, 0, 0, 0)
        comment.updated_at = datetime(2024, 1, 1, 0, 0, 0)
        return comment

    @pytest.fixture
    def sample_comment_create(self):
        """Sample comment creation data."""
        return CommentCreate(
            entity_id="entity-456",
            entity_type="data_product",
            title="Test Comment",
            comment="This is a test comment",
            audience=None,
            project_id="project-1",  # Project-scoped; global (project_id=None) requires admin
        )

    # Initialization Tests

    def test_manager_initialization(self, mock_repository):
        """Test manager initializes with repository."""
        manager = CommentsManager(comments_repository=mock_repository)
        assert manager._comments_repo == mock_repository

    # JSON Conversion Tests

    def test_convert_audience_from_json_none(self, manager, sample_comment_db):
        """Test converting None audience."""
        sample_comment_db.audience = None
        result = manager._convert_audience_from_json(sample_comment_db)
        assert result is None

    def test_convert_audience_from_json_valid(self, manager, sample_comment_db):
        """Test converting valid JSON audience."""
        sample_comment_db.audience = '["group1", "group2"]'
        result = manager._convert_audience_from_json(sample_comment_db)
        assert result == ["group1", "group2"]

    def test_convert_audience_from_json_invalid(self, manager, sample_comment_db):
        """Test converting invalid JSON audience."""
        sample_comment_db.audience = "invalid json"
        result = manager._convert_audience_from_json(sample_comment_db)
        assert result is None

    def test_db_to_api_model(self, manager, sample_comment_db):
        """Test converting database model to API model."""
        result = manager._db_to_api_model(sample_comment_db)
        assert isinstance(result, Comment)
        assert result.id == uuid.UUID("11111111-2222-3333-4444-555555555555")
        assert result.title == "Test Comment"

    # Create Comment Tests

    def test_create_comment_success(self, manager, mock_repository, sample_comment_create, sample_comment_db):
        """Test creating a comment."""
        mock_repository.create_with_audience.return_value = sample_comment_db

        db_session = Mock()
        result = manager.create_comment(db_session, data=sample_comment_create, user_email="user@example.com")

        assert isinstance(result, Comment)
        assert result.id == uuid.UUID("11111111-2222-3333-4444-555555555555")
        mock_repository.create_with_audience.assert_called_once()
        db_session.commit.assert_called_once()

    def test_create_comment_with_audience(self, manager, mock_repository, sample_comment_db):
        """Test creating a comment with specific audience."""
        comment_data = CommentCreate(
            entity_id="entity-789",
            entity_type="data_contract",
            title="Restricted Comment",
            comment="For admins only",
            audience=["admins", "data_stewards"],
            project_id="project-1",  # Project-scoped; global (project_id=None) requires admin
        )
        sample_comment_db.audience = '["admins", "data_stewards"]'
        mock_repository.create_with_audience.return_value = sample_comment_db

        db_session = Mock()
        result = manager.create_comment(db_session, data=comment_data, user_email="admin@example.com")

        assert result.id == uuid.UUID("11111111-2222-3333-4444-555555555555")
        mock_repository.create_with_audience.assert_called_once_with(
            db_session, obj_in=comment_data, created_by="admin@example.com"
        )

    # List Comments Tests

    def test_list_comments_empty(self, manager, mock_repository):
        """Test listing comments when none exist."""
        mock_repository.list_for_entity.return_value = []

        db_session = Mock()
        result = manager.list_comments(
            db_session, entity_type="data_product", entity_id="product-123"
        )

        assert result.total_count == 0
        assert result.visible_count == 0
        assert len(result.comments) == 0

    def test_list_comments_with_results(self, manager, mock_repository, sample_comment_db):
        """Test listing comments with results."""
        mock_repository.list_for_entity.return_value = [sample_comment_db]

        db_session = Mock()
        result = manager.list_comments(
            db_session, entity_type="data_product", entity_id="product-123"
        )

        assert result.total_count == 1
        assert result.visible_count == 1
        assert len(result.comments) == 1
        assert result.comments[0].id == uuid.UUID("11111111-2222-3333-4444-555555555555")

    def test_list_comments_filtered_by_groups(self, manager, mock_repository, sample_comment_db):
        """Test listing comments filtered by user groups."""
        comment2 = Mock(spec=CommentDb)
        comment2.id = uuid.UUID("66666666-7777-8888-9999-000000000000")
        comment2.entity_id = "entity-456"
        comment2.entity_type = "data_product"
        comment2.title = "Another Comment"
        comment2.comment = "Another test"
        comment2.audience = '["admins"]'
        comment2.project_id = None
        comment2.status = CommentStatus.ACTIVE
        comment2.comment_type = DbCommentType.COMMENT
        comment2.rating = None
        comment2.created_by = "admin@example.com"
        comment2.updated_by = "admin@example.com"
        comment2.created_at = datetime(2024, 1, 1, 0, 0, 0)
        comment2.updated_at = datetime(2024, 1, 1, 0, 0, 0)

        # First call returns all comments, second call returns filtered
        mock_repository.list_for_entity.side_effect = [
            [sample_comment_db, comment2],  # All comments
            [sample_comment_db],  # Visible to user
        ]

        db_session = Mock()
        result = manager.list_comments(
            db_session,
            entity_type="data_product",
            entity_id="product-123",
            user_groups=["users"],
        )

        assert result.total_count == 2
        assert result.visible_count == 1

    def test_list_comments_include_deleted(self, manager, mock_repository, sample_comment_db):
        """Test listing comments including deleted ones."""
        sample_comment_db.status = CommentStatus.DELETED
        mock_repository.list_for_entity.return_value = [sample_comment_db]

        db_session = Mock()
        result = manager.list_comments(
            db_session,
            entity_type="data_product",
            entity_id="product-123",
            include_deleted=True,
        )

        assert result.total_count == 1
        assert mock_repository.list_for_entity.call_args.kwargs["include_deleted"] is True

    # Update Comment Tests

    def test_update_comment_success(self, manager, mock_repository, sample_comment_db):
        """Test updating a comment."""
        updated_comment = Mock(spec=CommentDb)
        for attr in ("id", "entity_id", "entity_type", "comment", "audience", "project_id",
                     "status", "comment_type", "rating", "created_by", "updated_by",
                     "created_at", "updated_at"):
            setattr(updated_comment, attr, getattr(sample_comment_db, attr))
        updated_comment.title = "Updated Title"

        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = True
        mock_repository.update_with_audience.return_value = updated_comment

        db_session = Mock()
        update_data = CommentUpdate(title="Updated Title")
        result = manager.update_comment(
            db_session,
            comment_id="11111111-2222-3333-4444-555555555555",
            data=update_data,
            user_email="user@example.com",
        )

        assert result is not None
        assert result.title == "Updated Title"
        mock_repository.update_with_audience.assert_called_once()

    def test_update_comment_not_found(self, manager, mock_repository):
        """Test updating non-existent comment."""
        mock_repository.get.return_value = None

        db_session = Mock()
        update_data = CommentUpdate(title="Updated Title")
        result = manager.update_comment(
            db_session,
            comment_id="nonexistent",
            data=update_data,
            user_email="user@example.com",
        )

        assert result is None

    def test_update_comment_permission_denied(self, manager, mock_repository, sample_comment_db):
        """Test updating comment without permission."""
        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = False

        db_session = Mock()
        update_data = CommentUpdate(title="Updated Title")
        result = manager.update_comment(
            db_session,
            comment_id="comment-123",
            data=update_data,
            user_email="other@example.com",
        )

        assert result is None

    def test_update_comment_as_admin(self, manager, mock_repository, sample_comment_db):
        """Test admin can update any comment."""
        updated_comment = Mock(spec=CommentDb)
        updated_comment.__dict__.update(sample_comment_db.__dict__)

        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = True
        mock_repository.update_with_audience.return_value = updated_comment

        db_session = Mock()
        update_data = CommentUpdate(title="Admin Update")
        result = manager.update_comment(
            db_session,
            comment_id="comment-123",
            data=update_data,
            user_email="admin@example.com",
            is_admin=True,
        )

        assert result is not None
        mock_repository.can_user_modify.assert_called_with(sample_comment_db, "admin@example.com", True)

    # Delete Comment Tests

    def test_delete_comment_soft_success(self, manager, mock_repository, sample_comment_db):
        """Test soft deleting a comment."""
        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = True
        mock_repository.soft_delete.return_value = sample_comment_db

        db_session = Mock()
        result = manager.delete_comment(
            db_session, comment_id="11111111-2222-3333-4444-555555555555", user_email="user@example.com"
        )

        assert result is True
        mock_repository.soft_delete.assert_called_once()
        mock_repository.remove.assert_not_called()

    def test_delete_comment_hard_success(self, manager, mock_repository, sample_comment_db):
        """Test hard deleting a comment."""
        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = True
        mock_repository.remove.return_value = sample_comment_db

        db_session = Mock()
        result = manager.delete_comment(
            db_session, comment_id="comment-123", user_email="user@example.com", hard_delete=True
        )

        assert result is True
        mock_repository.remove.assert_called_once()
        mock_repository.soft_delete.assert_not_called()

    def test_delete_comment_not_found(self, manager, mock_repository):
        """Test deleting non-existent comment."""
        mock_repository.get.return_value = None

        db_session = Mock()
        result = manager.delete_comment(
            db_session, comment_id="nonexistent", user_email="user@example.com"
        )

        assert result is False

    def test_delete_comment_permission_denied(self, manager, mock_repository, sample_comment_db):
        """Test deleting comment without permission."""
        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = False

        db_session = Mock()
        result = manager.delete_comment(
            db_session, comment_id="11111111-2222-3333-4444-555555555555", user_email="other@example.com"
        )

        assert result is False

    # Get Comment Tests

    def test_get_comment_success(self, manager, mock_repository, sample_comment_db):
        """Test getting a comment by ID."""
        mock_repository.get.return_value = sample_comment_db

        db_session = Mock()
        result = manager.get_comment(db_session, comment_id="11111111-2222-3333-4444-555555555555")

        assert result is not None
        assert result.id == uuid.UUID("11111111-2222-3333-4444-555555555555")

    def test_get_comment_not_found(self, manager, mock_repository):
        """Test getting non-existent comment."""
        mock_repository.get.return_value = None

        db_session = Mock()
        result = manager.get_comment(db_session, comment_id="nonexistent")

        assert result is None

    # Permission Check Tests

    def test_can_user_modify_comment_true(self, manager, mock_repository, sample_comment_db):
        """Test permission check returns true."""
        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = True

        db_session = Mock()
        result = manager.can_user_modify_comment(
            db_session, comment_id="11111111-2222-3333-4444-555555555555", user_email="user@example.com"
        )

        assert result is True

    def test_can_user_modify_comment_false(self, manager, mock_repository, sample_comment_db):
        """Test permission check returns false."""
        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = False

        db_session = Mock()
        result = manager.can_user_modify_comment(
            db_session, comment_id="11111111-2222-3333-4444-555555555555", user_email="other@example.com"
        )

        assert result is False

    def test_can_user_modify_comment_not_found(self, manager, mock_repository):
        """Test permission check for non-existent comment."""
        mock_repository.get.return_value = None

        db_session = Mock()
        result = manager.can_user_modify_comment(
            db_session, comment_id="nonexistent", user_email="user@example.com"
        )

        assert result is False

