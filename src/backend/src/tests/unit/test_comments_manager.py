"""
Unit tests for CommentsManager
"""
import pytest
import json
from datetime import datetime
from unittest.mock import Mock, MagicMock, patch
from uuid import UUID
from src.controller.comments_manager import CommentsManager
from src.models.comments import CommentCreate, CommentUpdate, Comment
from src.db_models.comments import CommentDb, CommentStatus


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
        comment.id = "comment-123"
        comment.entity_id = "entity-456"
        comment.entity_type = "data_product"
        comment.title = "Test Comment"
        comment.comment = "This is a test comment"
        comment.audience = None
        comment.status = CommentStatus.ACTIVE
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
        assert result.id == "comment-123"
        assert result.title == "Test Comment"

    # Create Comment Tests

    def test_create_comment_success(self, manager, mock_repository, sample_comment_create, sample_comment_db):
        """Test creating a comment."""
        mock_repository.create_with_audience.return_value = sample_comment_db

        db_session = Mock()
        result = manager.create_comment(db_session, data=sample_comment_create, user_email="user@example.com")

        assert isinstance(result, Comment)
        assert result.id == "comment-123"
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
        )
        sample_comment_db.audience = '["admins", "data_stewards"]'
        mock_repository.create_with_audience.return_value = sample_comment_db

        db_session = Mock()
        result = manager.create_comment(db_session, data=comment_data, user_email="admin@example.com")

        assert result.id == "comment-123"
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
        assert result.comments[0].id == "comment-123"

    def test_list_comments_filtered_by_groups(self, manager, mock_repository, sample_comment_db):
        """Test listing comments filtered by user groups."""
        comment2 = Mock(spec=CommentDb)
        comment2.id = "comment-456"
        comment2.entity_id = "entity-456"
        comment2.entity_type = "data_product"
        comment2.title = "Another Comment"
        comment2.comment = "Another test"
        comment2.audience = '["admins"]'
        comment2.status = CommentStatus.ACTIVE
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
        updated_comment.__dict__.update(sample_comment_db.__dict__)
        updated_comment.title = "Updated Title"

        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = True
        mock_repository.update_with_audience.return_value = updated_comment

        db_session = Mock()
        update_data = CommentUpdate(title="Updated Title")
        result = manager.update_comment(
            db_session,
            comment_id="comment-123",
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
            db_session, comment_id="comment-123", user_email="user@example.com"
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
            db_session, comment_id="comment-123", user_email="other@example.com"
        )

        assert result is False

    # Get Comment Tests

    def test_get_comment_success(self, manager, mock_repository, sample_comment_db):
        """Test getting a comment by ID."""
        mock_repository.get.return_value = sample_comment_db

        db_session = Mock()
        result = manager.get_comment(db_session, comment_id="comment-123")

        assert result is not None
        assert result.id == "comment-123"

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
            db_session, comment_id="comment-123", user_email="user@example.com"
        )

        assert result is True

    def test_can_user_modify_comment_false(self, manager, mock_repository, sample_comment_db):
        """Test permission check returns false."""
        mock_repository.get.return_value = sample_comment_db
        mock_repository.can_user_modify.return_value = False

        db_session = Mock()
        result = manager.can_user_modify_comment(
            db_session, comment_id="comment-123", user_email="other@example.com"
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


# =============================================================================
# Issue #326 — role audience parity with workflows
# =============================================================================

ROLE_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
ROLE_UUID_2 = "11111111-2222-3333-4444-555555555555"
COMMENT_UUID = "cccccccc-dddd-eeee-ffff-000000000001"


def _make_comment_db(
    comment_id: str = COMMENT_UUID,
    audience_json: str | None = None,
    project_id: str | None = None,
) -> Mock:
    """Build a minimal CommentDb mock."""
    c = Mock(spec=CommentDb)
    c.id = comment_id
    c.entity_id = "e-1"
    c.entity_type = "data_product"
    c.title = "Test"
    c.comment = "body"
    c.audience = audience_json
    c.project_id = project_id
    c.status = CommentStatus.ACTIVE
    c.comment_type = None
    c.rating = None
    c.created_by = "author@example.com"
    c.updated_by = "author@example.com"
    c.created_at = datetime(2024, 1, 1)
    c.updated_at = datetime(2024, 1, 1)
    return c


class TestRoleAudienceParity:
    """Tests for issue #326 – role_id:<uuid> and legacy role:<name> audience matching."""

    @pytest.fixture
    def mock_auth_manager(self):
        m = Mock()
        m.get_user_effective_role_ids.return_value = {ROLE_UUID}
        return m

    @pytest.fixture
    def mock_settings_manager(self):
        m = Mock()
        # get_app_role_by_name returns a role whose id matches ROLE_UUID
        role = Mock()
        role.id = UUID(ROLE_UUID)
        m.get_app_role_by_name.return_value = role
        return m

    @pytest.fixture
    def mock_repo(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_repo, mock_settings_manager, mock_auth_manager):
        return CommentsManager(
            comments_repository=mock_repo,
            settings_manager=mock_settings_manager,
            authorization_manager=mock_auth_manager,
        )

    # ------------------------------------------------------------------
    # _resolve_viewer_role_ids
    # ------------------------------------------------------------------

    def test_resolve_viewer_role_ids_group_derived(self, manager, mock_auth_manager):
        """Group membership resolves to a set of role UUIDs."""
        mock_auth_manager.get_user_effective_role_ids.return_value = {ROLE_UUID}
        result = manager._resolve_viewer_role_ids(["data-producers"], None)
        assert result == {ROLE_UUID}
        mock_auth_manager.get_user_effective_role_ids.assert_called_once_with(
            ["data-producers"], None
        )

    def test_resolve_viewer_role_ids_override(self, manager, mock_auth_manager):
        """Applied role override ID is passed through to auth_manager."""
        mock_auth_manager.get_user_effective_role_ids.return_value = {ROLE_UUID_2}
        result = manager._resolve_viewer_role_ids(["some-group"], ROLE_UUID_2)
        assert result == {ROLE_UUID_2}
        mock_auth_manager.get_user_effective_role_ids.assert_called_once_with(
            ["some-group"], ROLE_UUID_2
        )

    def test_resolve_viewer_role_ids_no_auth_manager(self, mock_repo):
        """Falls back to empty set when no auth manager is available."""
        mgr = CommentsManager(comments_repository=mock_repo)
        result = mgr._resolve_viewer_role_ids(["some-group"])
        assert result == set()

    # ------------------------------------------------------------------
    # list_comments – role_id:<uuid> token matching (new format)
    # ------------------------------------------------------------------

    def test_list_comments_role_id_token_match(self, manager, mock_repo, mock_auth_manager):
        """Comments tagged role_id:<uuid> are visible to a viewer who holds that role."""
        comment = _make_comment_db(
            audience_json=json.dumps([f"role_id:{ROLE_UUID}"])
        )
        mock_auth_manager.get_user_effective_role_ids.return_value = {ROLE_UUID}
        # First call (all_comments), second call (visible)
        mock_repo.list_for_entity.side_effect = [
            [comment],
            [comment],
        ]

        db = Mock()
        result = manager.list_comments(
            db, entity_type="data_product", entity_id="e-1",
            user_groups=["data-producers"]
        )

        assert result.visible_count == 1
        assert str(result.comments[0].id) == COMMENT_UUID

    def test_list_comments_role_id_token_no_match(self, manager, mock_repo, mock_auth_manager):
        """Comments tagged role_id:<uuid> are hidden when viewer doesn't hold that role."""
        comment = _make_comment_db(
            audience_json=json.dumps([f"role_id:{ROLE_UUID}"])
        )
        mock_auth_manager.get_user_effective_role_ids.return_value = {ROLE_UUID_2}  # different role
        mock_repo.list_for_entity.side_effect = [
            [comment],  # all comments
            [],          # none visible (repo filters out mismatched role_id)
        ]

        db = Mock()
        result = manager.list_comments(
            db, entity_type="data_product", entity_id="e-1",
            user_groups=["other-group"]
        )

        assert result.visible_count == 0

    # ------------------------------------------------------------------
    # list_comments – legacy role:<name> token matching
    # ------------------------------------------------------------------

    def test_list_comments_legacy_role_name_token_match(
        self, manager, mock_repo, mock_auth_manager, mock_settings_manager
    ):
        """Legacy role:<name> tokens are resolved to UUIDs and matched."""
        comment = _make_comment_db(
            audience_json=json.dumps(["role:Data Producer"])
        )
        mock_auth_manager.get_user_effective_role_ids.return_value = {ROLE_UUID}
        # Repo returns the comment in all_comments but NOT in visible (repo doesn't know
        # about the name→id resolution; manager does the supplemental check).
        mock_repo.list_for_entity.side_effect = [
            [comment],  # all
            [],          # visible (role:<name> not matched by repo directly)
        ]
        # settings_manager resolves "Data Producer" → role with id=ROLE_UUID
        role = Mock()
        role.id = UUID(ROLE_UUID)
        mock_settings_manager.get_app_role_by_name.return_value = role

        db = Mock()
        result = manager.list_comments(
            db, entity_type="data_product", entity_id="e-1",
            user_groups=["data-producers"]
        )

        # Supplemental loop should add the comment
        assert result.visible_count == 1
        mock_settings_manager.get_app_role_by_name.assert_called_once_with("Data Producer")

    def test_list_comments_legacy_role_name_token_no_match(
        self, manager, mock_repo, mock_auth_manager, mock_settings_manager
    ):
        """Legacy role:<name> token is NOT matched when viewer holds a different role."""
        comment = _make_comment_db(
            audience_json=json.dumps(["role:Data Producer"])
        )
        mock_auth_manager.get_user_effective_role_ids.return_value = {ROLE_UUID_2}
        mock_repo.list_for_entity.side_effect = [
            [comment],
            [],
        ]
        # Name resolves to ROLE_UUID, but viewer only holds ROLE_UUID_2
        role = Mock()
        role.id = UUID(ROLE_UUID)
        mock_settings_manager.get_app_role_by_name.return_value = role

        db = Mock()
        result = manager.list_comments(
            db, entity_type="data_product", entity_id="e-1",
            user_groups=["consumers"]
        )

        assert result.visible_count == 0

    # ------------------------------------------------------------------
    # list_comments – override path
    # ------------------------------------------------------------------

    def test_list_comments_override_role_id_match(
        self, manager, mock_repo, mock_auth_manager
    ):
        """Applied role_id override pins the viewer to exactly that role."""
        comment = _make_comment_db(
            audience_json=json.dumps([f"role_id:{ROLE_UUID}"])
        )
        mock_auth_manager.get_user_effective_role_ids.return_value = {ROLE_UUID}
        mock_repo.list_for_entity.side_effect = [
            [comment],
            [comment],
        ]

        db = Mock()
        result = manager.list_comments(
            db, entity_type="data_product", entity_id="e-1",
            applied_role_override_id=ROLE_UUID
        )

        assert result.visible_count == 1
        mock_auth_manager.get_user_effective_role_ids.assert_called_once_with(
            None, ROLE_UUID
        )

    # ------------------------------------------------------------------
    # Ensure repo is called with user_role_ids kwarg
    # ------------------------------------------------------------------

    def test_list_comments_passes_role_ids_to_repo(
        self, manager, mock_repo, mock_auth_manager
    ):
        """Manager passes resolved role_ids to the repository for SQL-level filtering."""
        mock_auth_manager.get_user_effective_role_ids.return_value = {ROLE_UUID}
        mock_repo.list_for_entity.return_value = []

        db = Mock()
        manager.list_comments(
            db, entity_type="data_product", entity_id="e-1",
            user_groups=["producers"]
        )

        # Second call is the visible-comments query; check user_role_ids was passed
        calls = mock_repo.list_for_entity.call_args_list
        assert len(calls) == 2
        visible_call_kwargs = calls[1].kwargs
        assert visible_call_kwargs.get("user_role_ids") == {ROLE_UUID}

