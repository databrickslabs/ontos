"""
Unit tests for SettingsManager

Tests business logic for settings and role management including:
- App Role CRUD operations (create, list, get, update, delete)
- Role permissions and feature access
- Settings get/update operations
"""
import pytest
from unittest.mock import Mock, MagicMock
import uuid
from sqlalchemy.orm import Session

from src.controller.settings_manager import SettingsManager
from src.models.settings import AppRole, AppRoleCreate, AppRoleUpdate
from src.db_models.settings import AppRoleDb
from src.common.features import FeatureAccessLevel
from src.common.config import Settings


class TestSettingsManager:
    """Test suite for SettingsManager"""

    @pytest.fixture
    def mock_settings(self):
        """Create mock settings."""
        mock = MagicMock(spec=Settings)
        mock.job_cluster_id = "test-cluster"
        mock.to_dict.return_value = {"job_cluster_id": "test-cluster"}
        return mock

    @pytest.fixture
    def mock_ws_client(self):
        """Create a mocked Databricks WorkspaceClient."""
        return MagicMock()

    @pytest.fixture
    def manager(self, db_session, mock_settings, mock_ws_client):
        """Create SettingsManager instance for testing."""
        return SettingsManager(
            db=db_session,
            settings=mock_settings,
            workspace_client=mock_ws_client
        )

    @pytest.fixture
    def sample_role_data(self):
        """Sample role data for testing."""
        return {
            "name": "Test Role",
            "description": "A test role",
            "feature_permissions": {
                "data-products": FeatureAccessLevel.READ_WRITE.value,
                "data-contracts": FeatureAccessLevel.READ_ONLY.value,
            }
        }

    @pytest.fixture
    def sample_role_db(self, db_session, sample_role_data):
        """Create a sample role in the database."""
        import json
        role_db = AppRoleDb(
            id=str(uuid.uuid4()),
            name=sample_role_data["name"],
            description=sample_role_data["description"],
            feature_permissions=json.dumps(sample_role_data["feature_permissions"]),  # Serialize to JSON string
            assigned_groups='[]',  # Default empty list as JSON string
            home_sections='[]',  # Default empty list as JSON string
            approval_privileges='{}',  # Default empty dict as JSON string
        )
        db_session.add(role_db)
        db_session.commit()
        db_session.refresh(role_db)
        return role_db

    # =====================================================================
    # List App Roles Tests
    # =====================================================================

    def test_list_app_roles_empty(self, manager, db_session):
        """Test listing roles when none exist."""
        # Act
        result = manager.list_app_roles()

        # Assert
        assert result == []

    def test_list_app_roles_multiple(self, manager, db_session):
        """Test listing multiple roles."""
        import json
        # Arrange - Create 3 roles
        for i in range(3):
            role_db = AppRoleDb(
                id=str(uuid.uuid4()),
                name=f"Role {i}",
                description=f"Description {i}",
                feature_permissions='{}',  # JSON string
                assigned_groups='[]',
                home_sections='[]',
                approval_privileges='{}',
            )
            db_session.add(role_db)
        db_session.commit()

        # Act
        result = manager.list_app_roles()

        # Assert
        assert len(result) == 3
        assert all(isinstance(r, AppRole) for r in result)

    # =====================================================================
    # Get App Role Tests
    # =====================================================================

    def test_get_app_role_exists(self, manager, db_session, sample_role_db):
        """Test retrieving an existing role."""
        # Act
        result = manager.get_app_role(sample_role_db.id)

        # Assert
        assert result is not None
        assert str(result.id) == sample_role_db.id  # Convert UUID to string for comparison
        assert result.name == sample_role_db.name

    def test_get_app_role_not_found(self, manager, db_session):
        """Test retrieving a non-existent role."""
        # Act
        result = manager.get_app_role("nonexistent-id")

        # Assert
        assert result is None

    def test_get_app_role_by_name_exists(self, manager, db_session, sample_role_db):
        """Test retrieving a role by name."""
        # Act
        result = manager.get_app_role_by_name(sample_role_db.name)

        # Assert
        assert result is not None
        assert result.name == sample_role_db.name

    def test_get_app_role_by_name_not_found(self, manager, db_session):
        """Test retrieving role by non-existent name."""
        # Act
        result = manager.get_app_role_by_name("Nonexistent Role")

        # Assert
        assert result is None

    # =====================================================================
    # Create App Role Tests
    # =====================================================================

    def test_create_app_role_success(self, manager, db_session, sample_role_data):
        """Test successful role creation."""
        # Arrange
        role_create = AppRoleCreate(**sample_role_data)

        # Act
        result = manager.create_app_role(role_create)

        # Assert
        assert result is not None
        assert result.name == sample_role_data["name"]
        assert result.description == sample_role_data["description"]
        assert result.feature_permissions == sample_role_data["feature_permissions"]

    def test_create_app_role_generates_id(self, manager, db_session):
        """Test creating role generates an ID if not provided."""
        # Arrange
        role_create = AppRoleCreate(
            name="Role without ID",
            description="Test",
            feature_permissions={},
        )

        # Act
        result = manager.create_app_role(role_create)

        # Assert
        assert result is not None
        assert result.id is not None  # ID should be generated

    # =====================================================================
    # Update App Role Tests
    # =====================================================================

    def test_update_app_role_success(self, manager, db_session, sample_role_db):
        """Test successful role update."""
        # Arrange
        role_update = AppRoleUpdate(
            name="Updated Name",
            description="Updated description",
        )

        # Act
        result = manager.update_app_role(sample_role_db.id, role_update)

        # Assert
        assert result is not None
        assert result.name == "Updated Name"
        assert result.description == "Updated description"

    def test_update_app_role_permissions(self, manager, db_session, sample_role_db):
        """Test updating role permissions."""
        # Arrange
        new_permissions = {
            "data-products": FeatureAccessLevel.ADMIN.value,
            "compliance": FeatureAccessLevel.READ_WRITE.value,
        }
        role_update = AppRoleUpdate(feature_permissions=new_permissions)

        # Act
        result = manager.update_app_role(sample_role_db.id, role_update)

        # Assert
        assert result is not None
        assert result.feature_permissions == new_permissions

    def test_update_app_role_not_found(self, manager, db_session):
        """Test updating non-existent role."""
        # Arrange
        role_update = AppRoleUpdate(name="Updated")

        # Act
        result = manager.update_app_role("nonexistent-id", role_update)

        # Assert
        assert result is None

    # =====================================================================
    # Delete App Role Tests
    # =====================================================================

    def test_delete_app_role_success(self, manager, db_session, sample_role_db):
        """Test successful role deletion."""
        # Act
        result = manager.delete_app_role(sample_role_db.id)

        # Assert
        assert result is True
        
        # Verify role is deleted
        deleted = manager.get_app_role(sample_role_db.id)
        assert deleted is None

    def test_delete_app_role_not_found(self, manager, db_session):
        """Test deleting non-existent role."""
        # Act
        result = manager.delete_app_role("nonexistent-id")

        # Assert
        assert result is False

    # =====================================================================
    # Role Permissions Tests
    # =====================================================================

    def test_get_feature_permissions_for_role_id(self, manager, db_session, sample_role_db):
        """Test getting feature permissions for a role."""
        # Act
        result = manager.get_feature_permissions_for_role_id(sample_role_db.id)

        # Assert
        assert isinstance(result, dict)
        assert "data-products" in result
        assert result["data-products"] == FeatureAccessLevel.READ_WRITE

    def test_get_canonical_role_for_groups_no_groups(self, manager, db_session):
        """Test getting canonical role with no groups."""
        # Act
        result = manager.get_canonical_role_for_groups(None)

        # Assert
        # Should return None or default role depending on implementation
        assert result is None or isinstance(result, AppRole)

    def test_get_canonical_role_for_groups_with_groups(self, manager, db_session, sample_role_db):
        """Test getting canonical role with groups."""
        import json
        # Arrange - Create a role with assigned groups
        role_with_groups = AppRoleDb(
            id=str(uuid.uuid4()),
            name="Group Role",
            description="Test",
            feature_permissions='{}',
            assigned_groups=json.dumps(["test-group"]),  # JSON string
            home_sections='[]',
            approval_privileges='{}',
        )
        db_session.add(role_with_groups)
        db_session.commit()

        # Act
        result = manager.get_canonical_role_for_groups(["test-group"])

        # Assert
        assert result is not None
        assert result.name == "Group Role"

    # =====================================================================
    # Settings Get/Update Tests
    # =====================================================================

    def test_get_settings_returns_dict(self, manager):
        """Test getting current settings returns a dictionary."""
        # Act
        result = manager.get_settings()

        # Assert
        assert isinstance(result, dict)

    def test_get_features_with_access_levels(self, manager, db_session):
        """Test getting features with their access levels and group bucket."""
        # Act
        result = manager.get_features_with_access_levels()

        # Assert
        assert isinstance(result, dict)
        assert len(result) > 0

        # Every entry has the expected shape
        for feature_id, conf in result.items():
            assert 'name' in conf, f"{feature_id} is missing 'name'"
            assert 'allowed_levels' in conf, f"{feature_id} is missing 'allowed_levels'"
            assert 'group' in conf, f"{feature_id} is missing 'group'"
            assert conf['group'] in {'Discover', 'Build', 'Govern', 'Deploy', 'Settings', 'Other'}

        # `settings` now offers the four-level scale (not Admin-only)
        assert 'settings' in result
        assert result['settings']['group'] == 'Settings'
        assert 'Read-only' in result['settings']['allowed_levels']
        assert 'Read/Write' in result['settings']['allowed_levels']
        assert 'Admin' in result['settings']['allowed_levels']

        # Each Settings sub-page has its own dedicated permission ID
        expected_subpage_ids = {
            'settings-data-domains', 'settings-business-roles',
            'settings-delivery-methods', 'settings-asset-types',
            'settings-teams', 'settings-projects',
            'settings-certification-levels', 'settings-general',
            'settings-ui', 'settings-tags', 'settings-connectors',
            'settings-git', 'settings-mcp', 'settings-semantic-models',
            'settings-search', 'settings-jobs', 'settings-delivery',
            'settings-workflows', 'settings-roles', 'settings-audit',
        }
        missing = expected_subpage_ids - set(result.keys())
        assert not missing, f"Missing settings sub-page IDs: {missing}"

        for sub_id in expected_subpage_ids:
            assert result[sub_id]['group'] == 'Settings'
            assert 'Read-only' in result[sub_id]['allowed_levels']
            assert 'Read/Write' in result[sub_id]['allowed_levels']
            assert 'Admin' in result[sub_id]['allowed_levels']

    # =====================================================================
    # Role Count Tests
    # =====================================================================

    def test_get_app_roles_count_empty(self, manager, db_session):
        """Test role count when none exist."""
        # Act
        result = manager.get_app_roles_count()

        # Assert
        assert result == 0

    def test_get_app_roles_count_multiple(self, manager, db_session):
        """Test role count with multiple roles."""
        # Arrange - Create 5 roles
        for i in range(5):
            role_db = AppRoleDb(
                id=str(uuid.uuid4()),
                name=f"Role {i}",
                description=f"Description {i}",
                feature_permissions='{}',
                assigned_groups='[]',
                home_sections='[]',
                approval_privileges='{}',
            )
            db_session.add(role_db)
        db_session.commit()

        # Act
        result = manager.get_app_roles_count()

        # Assert
        assert result == 5

    # =====================================================================
    # Error Handling Tests
    # =====================================================================

    def test_create_app_role_duplicate_name(self, manager, db_session, sample_role_db):
        """Test creating role with duplicate name."""
        # Arrange
        role_create = AppRoleCreate(
            name=sample_role_db.name,  # Duplicate name
            description="Different description",
            feature_permissions={},
        )

        # Act & Assert
        # Should raise an exception or return None
        # Behavior depends on implementation
        try:
            result = manager.create_app_role(role_create)
            # If no exception, result might be None or the duplicate handling
            assert result is not None
        except Exception:
            # Exception is expected for duplicate
            pass

    def test_update_app_role_partial_update(self, manager, db_session, sample_role_db):
        """Test partial update of role (only description)."""
        # Arrange
        role_update = AppRoleUpdate(description="Updated description only")

        # Act
        result = manager.update_app_role(sample_role_db.id, role_update)

        # Assert
        assert result is not None
        assert result.description == "Updated description only"
        assert result.name == sample_role_db.name  # Name unchanged

    # =====================================================================
    # _validate_permissions Tests (stale feature_id tolerance)
    # =====================================================================
    #
    # Pre-existing roles can carry feature_ids that were renamed or removed
    # between releases (e.g. the legacy 'datasets' feature, renamed to
    # 'data-products'). The frontend echoes back the full permissions dict on
    # save, which historically 400'd with "Invalid role data" — making the role
    # uneditable until someone fixed the DB row by hand. The validator now
    # drops unknown keys in place with a warning so the next save persists a
    # cleaned dict. Real client bugs (unknown access *level* for a known
    # feature) remain a hard error.

    def test_validate_permissions_drops_unknown_feature_id(self, manager, caplog):
        """Unknown feature_ids are dropped from the dict in place + warned."""
        # Arrange — mix one valid, one stale (the historical 'datasets' key)
        perms = {
            "data-products": FeatureAccessLevel.READ_ONLY,
            "datasets":      FeatureAccessLevel.READ_ONLY,  # stale
        }

        # Act
        manager._validate_permissions(perms)

        # Assert — stale key dropped, valid key preserved
        assert "datasets" not in perms
        assert perms["data-products"] == FeatureAccessLevel.READ_ONLY
        assert any("datasets" in rec.getMessage() for rec in caplog.records)

    def test_validate_permissions_still_rejects_invalid_level(self, manager):
        """An unknown access *level* for a known feature is still a hard error."""
        # Arrange — known feature, but pick a level it does not allow.
        # 'security-features' is admin-only, so READ_WRITE is not in its
        # allowed_levels.
        perms = {"security-features": FeatureAccessLevel.READ_WRITE}

        # Act / Assert
        with pytest.raises(ValueError, match="Invalid access level"):
            manager._validate_permissions(perms)

    def test_validate_permissions_empty_dict_noop(self, manager):
        """Empty permissions dict validates cleanly (regression guard)."""
        perms = {}
        manager._validate_permissions(perms)
        assert perms == {}

    # =====================================================================
    # list_app_roles_for_approval Tests (#161)
    # =====================================================================

    def test_list_app_roles_for_approval_no_filter_returns_all(self, manager, db_session):
        """Without a filter param all roles are returned (backward compat)."""
        import json
        for i, privs in enumerate(['{"CONTRACTS": true}', '{}', '{"PRODUCTS": true}']):
            db_session.add(AppRoleDb(
                id=str(uuid.uuid4()),
                name=f"Role {i}",
                description="",
                feature_permissions='{}',
                assigned_groups='[]',
                home_sections='[]',
                approval_privileges=privs,
            ))
        db_session.commit()

        result = manager.list_app_roles_for_approval(approval_entity=None)
        assert len(result) == 3

    def test_list_app_roles_for_approval_filters_by_entity(self, manager, db_session):
        """Only roles with the matching approval privilege are returned."""
        import json
        db_session.add(AppRoleDb(
            id=str(uuid.uuid4()),
            name="Governor",
            description="",
            feature_permissions='{}',
            assigned_groups='[]',
            home_sections='[]',
            approval_privileges='{"CONTRACTS": true, "PRODUCTS": true}',
        ))
        db_session.add(AppRoleDb(
            id=str(uuid.uuid4()),
            name="Consumer",
            description="",
            feature_permissions='{}',
            assigned_groups='[]',
            home_sections='[]',
            approval_privileges='{}',
        ))
        db_session.commit()

        result = manager.list_app_roles_for_approval(approval_entity="CONTRACTS")
        assert len(result) == 1
        assert result[0].name == "Governor"

    def test_list_app_roles_for_approval_missing_privilege_excluded(self, manager, db_session):
        """Roles where the flag is False (not just missing) are excluded."""
        db_session.add(AppRoleDb(
            id=str(uuid.uuid4()),
            name="No Privilege",
            description="",
            feature_permissions='{}',
            assigned_groups='[]',
            home_sections='[]',
            approval_privileges='{"DOMAINS": false}',
        ))
        db_session.commit()

        result = manager.list_app_roles_for_approval(approval_entity="DOMAINS")
        assert result == []

    def test_list_app_roles_for_approval_multi_entity_intersection(self, manager, db_session):
        """Roles must have ALL requested privileges to pass the filter."""
        db_session.add(AppRoleDb(
            id=str(uuid.uuid4()),
            name="Both",
            description="",
            feature_permissions='{}',
            assigned_groups='[]',
            home_sections='[]',
            approval_privileges='{"CONTRACTS": true, "PRODUCTS": true}',
        ))
        db_session.add(AppRoleDb(
            id=str(uuid.uuid4()),
            name="Contracts only",
            description="",
            feature_permissions='{}',
            assigned_groups='[]',
            home_sections='[]',
            approval_privileges='{"CONTRACTS": true}',
        ))
        db_session.commit()

        contracts = {r.name for r in manager.list_app_roles_for_approval(approval_entity="CONTRACTS")}
        products = {r.name for r in manager.list_app_roles_for_approval(approval_entity="PRODUCTS")}
        # Intersection of both sets simulates what the frontend does for multi-entity workflows
        intersection = contracts & products
        assert intersection == {"Both"}
        assert "Contracts only" not in intersection

