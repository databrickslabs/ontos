"""
Unit tests for AuthorizationManager

Tests authorization and permission management including:
- Effective permission calculation
- Permission merging from multiple roles
- Team role overrides
- Access level checking
"""
import pytest
import uuid
from unittest.mock import Mock

from src.controller.authorization_manager import AuthorizationManager
from src.models.settings import AppRole
from src.common.features import FeatureAccessLevel


class TestAuthorizationManager:
    """Test suite for AuthorizationManager"""

    @pytest.fixture
    def mock_settings_manager(self):
        """Create a mock SettingsManager."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_settings_manager):
        """Create AuthorizationManager instance for testing."""
        return AuthorizationManager(settings_manager=mock_settings_manager)

    @pytest.fixture
    def developer_role(self):
        """Create a developer role with basic permissions."""
        return AppRole(
            id=uuid.uuid4(),
            name="Developer",
            description="Developer role",
            assigned_groups=["developers"],
            feature_permissions={
                "data-products": FeatureAccessLevel.READ_WRITE,
                "data-contracts": FeatureAccessLevel.READ_WRITE,
                "teams": FeatureAccessLevel.READ_ONLY,
            },
            home_sections=[],
            approval_privileges={},
        )

    @pytest.fixture
    def admin_role(self):
        """Create an admin role with full permissions."""
        return AppRole(
            id=uuid.uuid4(),
            name="Admin",
            description="Admin role",
            assigned_groups=["admins"],
            feature_permissions={
                "data-products": FeatureAccessLevel.ADMIN,
                "data-contracts": FeatureAccessLevel.ADMIN,
                "teams": FeatureAccessLevel.ADMIN,
                "settings": FeatureAccessLevel.ADMIN,
            },
            home_sections=[],
            approval_privileges={},
        )

    @pytest.fixture
    def viewer_role(self):
        """Create a viewer role with read-only permissions."""
        return AppRole(
            id=uuid.uuid4(),
            name="Viewer",
            description="Viewer role",
            assigned_groups=["viewers"],
            feature_permissions={
                "data-products": FeatureAccessLevel.READ_ONLY,
                "data-contracts": FeatureAccessLevel.READ_ONLY,
            },
            home_sections=[],
            approval_privileges={},
        )

    # Effective permission calculation tests
    def test_get_effective_permissions_no_groups(self, manager, mock_settings_manager):
        """Test calculating permissions with no user groups."""
        mock_settings_manager.list_app_roles.return_value = []
        
        result = manager.get_user_effective_permissions([])
        
        # Should return NONE for all features
        assert all(level == FeatureAccessLevel.NONE for level in result.values())

    def test_get_effective_permissions_single_role(self, manager, mock_settings_manager, developer_role):
        """Test calculating permissions from a single matching role."""
        mock_settings_manager.list_app_roles.return_value = [developer_role]
        
        result = manager.get_user_effective_permissions(["developers"])
        
        # Should have permissions from developer role
        assert result["data-products"] == FeatureAccessLevel.READ_WRITE
        assert result["data-contracts"] == FeatureAccessLevel.READ_WRITE
        assert result["teams"] == FeatureAccessLevel.READ_ONLY

    def test_get_effective_permissions_no_matching_roles(self, manager, mock_settings_manager, developer_role):
        """Test calculating permissions when no roles match user groups."""
        mock_settings_manager.list_app_roles.return_value = [developer_role]
        
        result = manager.get_user_effective_permissions(["unknown-group"])
        
        # Should return NONE for all features
        assert all(level == FeatureAccessLevel.NONE for level in result.values())

    def test_get_effective_permissions_multiple_roles(self, manager, mock_settings_manager, developer_role, viewer_role):
        """Test merging permissions from multiple matching roles."""
        mock_settings_manager.list_app_roles.return_value = [developer_role, viewer_role]
        
        result = manager.get_user_effective_permissions(["developers", "viewers"])
        
        # Should take the highest permission level for each feature
        assert result["data-products"] == FeatureAccessLevel.READ_WRITE  # Higher of READ_WRITE and READ_ONLY
        assert result["data-contracts"] == FeatureAccessLevel.READ_WRITE

    def test_get_effective_permissions_highest_wins(self, manager, mock_settings_manager, developer_role, admin_role):
        """Test that highest permission level wins when merging."""
        mock_settings_manager.list_app_roles.return_value = [developer_role, admin_role]
        
        result = manager.get_user_effective_permissions(["developers", "admins"])
        
        # Admin permissions should win
        assert result["data-products"] == FeatureAccessLevel.ADMIN
        assert result["data-contracts"] == FeatureAccessLevel.ADMIN
        assert result["teams"] == FeatureAccessLevel.ADMIN
        assert result["settings"] == FeatureAccessLevel.ADMIN

    def test_get_effective_permissions_partial_group_match(self, manager, mock_settings_manager, developer_role):
        """Test permissions when user has some matching and some non-matching groups."""
        mock_settings_manager.list_app_roles.return_value = [developer_role]
        
        result = manager.get_user_effective_permissions(["developers", "other-group"])
        
        # Should still get developer permissions
        assert result["data-products"] == FeatureAccessLevel.READ_WRITE

    # Team role override tests
    def test_get_effective_permissions_with_team_override(self, manager, mock_settings_manager, developer_role, admin_role):
        """Test that team role override takes precedence."""
        mock_settings_manager.list_app_roles.return_value = [developer_role, admin_role]
        
        result = manager.get_user_effective_permissions(
            user_groups=["developers"],
            team_role_override="Admin"
        )
        
        # Should use admin permissions despite only having developer group
        assert result["data-products"] == FeatureAccessLevel.ADMIN
        assert result["settings"] == FeatureAccessLevel.ADMIN

    def test_get_effective_permissions_invalid_team_override(self, manager, mock_settings_manager, developer_role):
        """Test fallback when team role override doesn't exist."""
        mock_settings_manager.list_app_roles.return_value = [developer_role]
        
        result = manager.get_user_effective_permissions(
            user_groups=["developers"],
            team_role_override="NonExistentRole"
        )
        
        # Should fall back to group-based permissions
        assert result["data-products"] == FeatureAccessLevel.READ_WRITE

    # has_permission tests
    def test_has_permission_sufficient(self, manager):
        """Test permission check when user has sufficient access."""
        effective_permissions = {
            "data-products": FeatureAccessLevel.READ_WRITE,
            "data-contracts": FeatureAccessLevel.READ_ONLY,
        }
        
        # User has READ_WRITE, requires READ_ONLY
        assert manager.has_permission(
            effective_permissions,
            "data-products",
            FeatureAccessLevel.READ_ONLY
        ) is True

    def test_has_permission_exact_match(self, manager):
        """Test permission check with exact level match."""
        effective_permissions = {
            "data-products": FeatureAccessLevel.READ_WRITE,
        }
        
        assert manager.has_permission(
            effective_permissions,
            "data-products",
            FeatureAccessLevel.READ_WRITE
        ) is True

    def test_has_permission_insufficient(self, manager):
        """Test permission check when user lacks sufficient access."""
        effective_permissions = {
            "data-products": FeatureAccessLevel.READ_ONLY,
        }
        
        # User has READ_ONLY, requires READ_WRITE
        assert manager.has_permission(
            effective_permissions,
            "data-products",
            FeatureAccessLevel.READ_WRITE
        ) is False

    def test_has_permission_none_level(self, manager):
        """Test permission check when user has no access."""
        effective_permissions = {
            "data-products": FeatureAccessLevel.NONE,
        }
        
        assert manager.has_permission(
            effective_permissions,
            "data-products",
            FeatureAccessLevel.READ_ONLY
        ) is False

    def test_has_permission_missing_feature(self, manager):
        """Test permission check for feature not in permissions."""
        effective_permissions = {
            "data-products": FeatureAccessLevel.READ_WRITE,
        }
        
        # Feature not in permissions should default to NONE
        assert manager.has_permission(
            effective_permissions,
            "unknown-feature",
            FeatureAccessLevel.READ_ONLY
        ) is False

    def test_has_permission_admin_level(self, manager):
        """Test permission check with admin level."""
        effective_permissions = {
            "settings": FeatureAccessLevel.ADMIN,
        }
        
        # Admin should have all lower levels
        assert manager.has_permission(
            effective_permissions,
            "settings",
            FeatureAccessLevel.READ_ONLY
        ) is True
        assert manager.has_permission(
            effective_permissions,
            "settings",
            FeatureAccessLevel.READ_WRITE
        ) is True
        assert manager.has_permission(
            effective_permissions,
            "settings",
            FeatureAccessLevel.ADMIN
        ) is True

    # Edge cases
    def test_get_effective_permissions_none_groups(self, manager, mock_settings_manager):
        """Test handling None as user groups."""
        mock_settings_manager.list_app_roles.return_value = []
        
        result = manager.get_user_effective_permissions(None)
        
        # Should handle None gracefully and return NONE for all features
        assert all(level == FeatureAccessLevel.NONE for level in result.values())

    def test_get_effective_permissions_role_with_unknown_feature(self, manager, mock_settings_manager):
        """Test handling role with permission for unknown feature."""
        role_with_unknown = AppRole(
            id=uuid.uuid4(),
            name="TestRole",
            description="Test",
            assigned_groups=["test"],
            feature_permissions={
                "data-products": FeatureAccessLevel.READ_WRITE,
                "unknown-feature-xyz": FeatureAccessLevel.ADMIN,  # Unknown feature
            },
            home_sections=[],
            approval_privileges={},
        )
        mock_settings_manager.list_app_roles.return_value = [role_with_unknown]

        result = manager.get_user_effective_permissions(["test"])

        # Should process valid features and skip unknown ones
        assert result["data-products"] == FeatureAccessLevel.READ_WRITE
        assert "unknown-feature-xyz" not in result or result.get("unknown-feature-xyz") == FeatureAccessLevel.NONE


class TestIsUserOntosAdmin:
    """Tests for ``AuthorizationManager.is_user_ontos_admin``.

    Regression coverage for #404 — verifies the admin gate uses role membership
    (``AppRole.is_admin``) and is decoupled from ``settings:ADMIN``.
    """

    @pytest.fixture
    def mock_settings_manager(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_settings_manager):
        return AuthorizationManager(settings_manager=mock_settings_manager)

    @staticmethod
    def _role(name, assigned_groups, is_admin=False, feature_permissions=None):
        return AppRole(
            id=uuid.uuid4(),
            name=name,
            description=f"{name} role",
            assigned_groups=assigned_groups,
            feature_permissions=feature_permissions or {},
            home_sections=[],
            approval_privileges={},
            is_admin=is_admin,
        )

    def test_returns_false_for_empty_groups(self, manager, mock_settings_manager):
        mock_settings_manager.list_app_roles.return_value = [
            self._role("Admin", ["admins"], is_admin=True),
        ]
        assert manager.is_user_ontos_admin([]) is False
        assert manager.is_user_ontos_admin(None) is False

    def test_returns_true_when_group_matches_is_admin_role(self, manager, mock_settings_manager):
        mock_settings_manager.list_app_roles.return_value = [
            self._role("Admin", ["admins"], is_admin=True),
            self._role("Producer", ["data-producers"]),
        ]
        assert manager.is_user_ontos_admin(["admins"]) is True

    def test_group_match_is_case_insensitive(self, manager, mock_settings_manager):
        # Mismatched casing on either side must still match — group sources differ
        # (settings.yaml vs identity headers).
        mock_settings_manager.list_app_roles.return_value = [
            self._role("Admin", ["Admins"], is_admin=True),
        ]
        assert manager.is_user_ontos_admin(["aDmInS"]) is True

    def test_returns_false_when_only_non_admin_role_matches(self, manager, mock_settings_manager):
        # User belongs to a role that has settings:ADMIN but is NOT flagged is_admin.
        # This is the core #404 regression: settings:ADMIN must not imply Ontos admin.
        mock_settings_manager.list_app_roles.return_value = [
            self._role(
                "Settings Admin",
                ["settings-admins"],
                is_admin=False,
                feature_permissions={"settings": FeatureAccessLevel.ADMIN},
            ),
            self._role("Admin", ["admins"], is_admin=True),
        ]
        assert manager.is_user_ontos_admin(["settings-admins"]) is False

    def test_returns_false_when_no_role_matches(self, manager, mock_settings_manager):
        mock_settings_manager.list_app_roles.return_value = [
            self._role("Admin", ["admins"], is_admin=True),
        ]
        assert manager.is_user_ontos_admin(["data-producers"]) is False

    def test_returns_false_when_admin_role_has_no_assigned_groups(self, manager, mock_settings_manager):
        # Defense-in-depth: a misconfigured admin role with empty assigned_groups
        # must NOT grant admin to every user.
        mock_settings_manager.list_app_roles.return_value = [
            self._role("Admin", [], is_admin=True),
        ]
        assert manager.is_user_ontos_admin(["anyone"]) is False

    def test_handles_multiple_admin_roles(self, manager, mock_settings_manager):
        mock_settings_manager.list_app_roles.return_value = [
            self._role("Platform Admin", ["platform-admins"], is_admin=True),
            self._role("Data Admin", ["data-admins"], is_admin=True),
        ]
        assert manager.is_user_ontos_admin(["data-admins"]) is True
        assert manager.is_user_ontos_admin(["platform-admins"]) is True
        assert manager.is_user_ontos_admin(["other"]) is False

    def test_settings_manager_failure_denies_admin(self, manager, mock_settings_manager):
        # If we can't load roles, fail closed — never silently elevate.
        mock_settings_manager.list_app_roles.side_effect = RuntimeError("db down")
        assert manager.is_user_ontos_admin(["admins"]) is False


# =============================================================================
# Issue #326 — get_user_effective_role_ids
# =============================================================================

_ROLE_A_ID = uuid.UUID("aaaaaaaa-0000-0000-0000-000000000001")
_ROLE_B_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


def _make_role(role_id: uuid.UUID, name: str, groups: list[str]) -> AppRole:
    return AppRole(
        id=role_id,
        name=name,
        description=None,
        assigned_groups=groups,
        feature_permissions={},
        home_sections=[],
        approval_privileges={},
    )


class TestGetUserEffectiveRoleIds:
    """Tests for AuthorizationManager.get_user_effective_role_ids (issue #326)."""

    @pytest.fixture
    def mock_settings_manager(self):
        return Mock()

    @pytest.fixture
    def manager(self, mock_settings_manager):
        return AuthorizationManager(settings_manager=mock_settings_manager)

    def test_group_derived_single_role(self, manager, mock_settings_manager):
        """Viewer's group matches one role → that role's ID is returned."""
        role = _make_role(_ROLE_A_ID, "Data Producer", ["data-producers"])
        mock_settings_manager.list_app_roles.return_value = [role]

        result = manager.get_user_effective_role_ids(["data-producers"])

        assert result == {str(_ROLE_A_ID)}

    def test_group_derived_multiple_roles(self, manager, mock_settings_manager):
        """Viewer belongs to groups that match two roles → both IDs returned."""
        role_a = _make_role(_ROLE_A_ID, "Data Producer", ["producers"])
        role_b = _make_role(_ROLE_B_ID, "Data Steward", ["stewards"])
        mock_settings_manager.list_app_roles.return_value = [role_a, role_b]

        result = manager.get_user_effective_role_ids(["producers", "stewards"])

        assert result == {str(_ROLE_A_ID), str(_ROLE_B_ID)}

    def test_group_derived_no_match(self, manager, mock_settings_manager):
        """Viewer's groups don't match any role → empty set."""
        role = _make_role(_ROLE_A_ID, "Data Producer", ["producers"])
        mock_settings_manager.list_app_roles.return_value = [role]

        result = manager.get_user_effective_role_ids(["consumers"])

        assert result == set()

    def test_empty_groups(self, manager, mock_settings_manager):
        """Empty group list → empty set."""
        mock_settings_manager.list_app_roles.return_value = [
            _make_role(_ROLE_A_ID, "Data Producer", ["producers"])
        ]
        result = manager.get_user_effective_role_ids([])
        assert result == set()

    def test_none_groups(self, manager, mock_settings_manager):
        """None group list → empty set."""
        mock_settings_manager.list_app_roles.return_value = [
            _make_role(_ROLE_A_ID, "Data Producer", ["producers"])
        ]
        result = manager.get_user_effective_role_ids(None)
        assert result == set()

    def test_applied_override_pins_to_single_role(self, manager, mock_settings_manager):
        """Applied role override → exactly that one role UUID is returned."""
        role_a = _make_role(_ROLE_A_ID, "Data Producer", ["producers"])
        role_b = _make_role(_ROLE_B_ID, "Data Steward", ["stewards"])
        mock_settings_manager.list_app_roles.return_value = [role_a, role_b]

        # Viewer has groups matching role_a but override pins to role_b
        result = manager.get_user_effective_role_ids(
            ["producers"], applied_role_override_id=str(_ROLE_B_ID)
        )

        assert result == {str(_ROLE_B_ID)}

    def test_applied_override_unknown_id_returns_empty(self, manager, mock_settings_manager):
        """Applied override ID not found in roles list → empty set."""
        mock_settings_manager.list_app_roles.return_value = [
            _make_role(_ROLE_A_ID, "Data Producer", ["producers"])
        ]
        unknown_id = str(uuid.uuid4())

        result = manager.get_user_effective_role_ids(["producers"], unknown_id)

        assert result == set()

    def test_case_insensitive_group_matching(self, manager, mock_settings_manager):
        """Group matching is case-insensitive (role has 'Producers', user has 'PRODUCERS')."""
        role = _make_role(_ROLE_A_ID, "Data Producer", ["Producers"])
        mock_settings_manager.list_app_roles.return_value = [role]

        result = manager.get_user_effective_role_ids(["PRODUCERS"])

        assert result == {str(_ROLE_A_ID)}


