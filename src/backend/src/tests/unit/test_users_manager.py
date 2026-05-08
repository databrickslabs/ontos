"""
Unit tests for UsersManager
"""
import pytest
from unittest.mock import Mock, MagicMock
from databricks.sdk.errors import NotFound, DatabricksError
from src.controller.users_manager import UsersManager
from src.models.users import UserInfo


class TestUsersManager:
    """Test suite for UsersManager."""

    @pytest.fixture
    def mock_ws_client(self):
        """Create mock workspace client."""
        return Mock()

    @pytest.fixture
    def manager(self, mock_ws_client):
        """Create UsersManager instance for testing."""
        return UsersManager(ws_client=mock_ws_client)

    @pytest.fixture
    def mock_databricks_user(self):
        """Create mock Databricks user object."""
        user = Mock()
        user.id = "1234567890"
        user.user_name = "test@example.com"
        user.display_name = "Test User"
        user.active = True

        # Mock email
        email = Mock()
        email.value = "test@example.com"
        user.emails = [email]

        # Mock groups
        group1 = Mock()
        group1.display = "data_engineers"
        group2 = Mock()
        group2.display = "admins"
        user.groups = [group1, group2]

        return user

    # Initialization Tests

    def test_manager_initialization_with_client(self, mock_ws_client):
        """Test manager initializes with workspace client."""
        manager = UsersManager(ws_client=mock_ws_client)
        assert manager._ws_client == mock_ws_client

    def test_manager_initialization_without_client(self):
        """Test manager initializes without workspace client (logs warning)."""
        manager = UsersManager(ws_client=None)
        assert manager._ws_client is None

    # Get User Details Tests

    def test_get_user_details_by_email_success(
        self, manager, mock_ws_client, mock_databricks_user
    ):
        """Test successfully getting user details by email — real SCIM groups
        win and email is NOT appended (so the consumer-groups picker shows
        actual workspace groups, not the user's email)."""
        mock_ws_client.users.list.return_value = iter([mock_databricks_user])

        result = manager.get_user_details_by_email("test@example.com", "192.168.1.1")

        assert isinstance(result, UserInfo)
        assert result.email == "test@example.com"
        assert result.username == "test@example.com"
        assert result.user == "Test User"
        assert result.ip == "192.168.1.1"
        assert result.groups == ["data_engineers", "admins"]

    def test_get_user_details_by_email_no_groups_falls_back_to_email(
        self, manager, mock_ws_client, mock_databricks_user
    ):
        """When SCIM returns no groups (and users.get also returns none) the
        fallback should be email-as-implicit-group, preserving FEVM-style
        compatibility."""
        mock_databricks_user.groups = []
        mock_ws_client.users.list.return_value = iter([mock_databricks_user])
        # users.get(id) also returns no groups -> trigger fallback
        empty_user = Mock()
        empty_user.groups = []
        mock_ws_client.users.get.return_value = empty_user

        result = manager.get_user_details_by_email("test@example.com", "192.168.1.1")

        assert result.groups == ["test@example.com"]

    def test_get_user_details_by_email_none_groups_falls_back_to_email(
        self, manager, mock_ws_client, mock_databricks_user
    ):
        """Same as above but with groups=None on the SCIM payload."""
        mock_databricks_user.groups = None
        mock_ws_client.users.list.return_value = iter([mock_databricks_user])
        empty_user = Mock()
        empty_user.groups = None
        mock_ws_client.users.get.return_value = empty_user

        result = manager.get_user_details_by_email("test@example.com", "192.168.1.1")

        assert result.groups == ["test@example.com"]

    def test_get_user_details_by_email_no_email(
        self, manager, mock_ws_client, mock_databricks_user
    ):
        """Test getting user details when user has no email (uses username)."""
        mock_databricks_user.emails = []
        mock_ws_client.users.list.return_value = iter([mock_databricks_user])

        result = manager.get_user_details_by_email("test@example.com", "192.168.1.1")

        # Should fall back to username
        assert result.email == "test@example.com"

    def test_get_user_details_by_email_user_not_found(self, manager, mock_ws_client):
        """Test getting user details when user not found."""
        mock_ws_client.users.list.return_value = iter([])

        with pytest.raises(NotFound, match="not found via SDK"):
            manager.get_user_details_by_email("nonexistent@example.com", "192.168.1.1")

    def test_get_user_details_by_email_multiple_users(
        self, manager, mock_ws_client, mock_databricks_user
    ):
        """Test getting user details when multiple users found (uses first)."""
        user2 = Mock()
        user2.user_name = "test@example.com"
        user2.display_name = "Test User 2"
        user2.active = True
        email2 = Mock()
        email2.value = "test@example.com"
        user2.emails = [email2]
        user2.groups = []

        mock_ws_client.users.list.return_value = iter([mock_databricks_user, user2])

        result = manager.get_user_details_by_email("test@example.com", "192.168.1.1")

        # Should use first user
        assert result.user == "Test User"

    def test_get_user_details_by_email_no_workspace_client(self):
        """Test getting user details when workspace client not configured."""
        manager = UsersManager(ws_client=None)

        with pytest.raises(ValueError, match="WorkspaceClient is not configured"):
            manager.get_user_details_by_email("test@example.com", "192.168.1.1")

    def test_get_user_details_by_email_databricks_error(
        self, manager, mock_ws_client
    ):
        """Test handling of Databricks SDK errors."""
        mock_ws_client.users.list.side_effect = DatabricksError("API Error")

        with pytest.raises(RuntimeError, match="Databricks SDK error"):
            manager.get_user_details_by_email("test@example.com", "192.168.1.1")

    def test_get_user_details_by_email_unexpected_error(
        self, manager, mock_ws_client
    ):
        """Test handling of unexpected errors."""
        mock_ws_client.users.list.side_effect = Exception("Unexpected error")

        with pytest.raises(RuntimeError, match="Unexpected error during SDK user lookup"):
            manager.get_user_details_by_email("test@example.com", "192.168.1.1")

    def test_get_user_details_by_email_uses_filter(
        self, manager, mock_ws_client, mock_databricks_user
    ):
        """Test that correct filter is applied when listing users."""
        mock_ws_client.users.list.return_value = iter([mock_databricks_user])

        manager.get_user_details_by_email("test@example.com", "192.168.1.1")

        # Verify filter was used
        mock_ws_client.users.list.assert_called_once_with(
            filter='userName eq "test@example.com"'
        )

    def test_get_user_details_by_email_none_ip(
        self, manager, mock_ws_client, mock_databricks_user
    ):
        """Test getting user details with None IP address."""
        mock_ws_client.users.list.return_value = iter([mock_databricks_user])

        result = manager.get_user_details_by_email("test@example.com", None)

        assert result.ip is None

    def test_get_user_details_by_email_extracts_group_display_names(
        self, manager, mock_ws_client, mock_databricks_user
    ):
        """Test that group display names are correctly extracted."""
        group_with_display = Mock()
        group_with_display.display = "team_alpha"

        group_without_display = Mock()
        group_without_display.display = None

        mock_databricks_user.groups = [group_with_display, group_without_display]
        mock_ws_client.users.list.return_value = iter([mock_databricks_user])

        result = manager.get_user_details_by_email("test@example.com", "192.168.1.1")

        # Should only include groups with display names; email NOT appended
        # because we resolved at least one real group.
        assert result.groups == ["team_alpha"]

    # --- get_current_user (OBO path used by /api/user/details) ---

    def _make_group(self, display: str) -> Mock:
        g = Mock()
        g.display = display
        return g

    def test_get_current_user_returns_real_scim_groups_from_me(
        self, manager, mock_databricks_user
    ):
        """current_user.me() includes groups -> use them, do not append email."""
        obo = Mock()
        obo.current_user.me.return_value = mock_databricks_user

        result = manager.get_current_user(obo_client=obo, real_ip="10.0.0.1")

        assert result.groups == ["data_engineers", "admins"]
        # users.get(id) NOT called when me() already returned groups.
        obo.users.get.assert_not_called()

    def test_get_current_user_falls_back_to_users_get_when_me_has_no_groups(
        self, manager, mock_databricks_user
    ):
        """When current_user.me() returns groups=[], re-fetch via users.get(id)
        and return those real workspace SCIM groups."""
        # Initial me() response has no groups.
        me_user = Mock()
        me_user.id = "1234567890"
        me_user.user_name = "test@example.com"
        me_user.display_name = "Test User"
        email = Mock()
        email.value = "test@example.com"
        me_user.emails = [email]
        me_user.groups = []

        # users.get(id) returns the full SCIM record with real groups.
        full_user = Mock()
        full_user.groups = [
            self._make_group("admins"),
            self._make_group("users"),
            self._make_group("account-ops-users"),
        ]

        obo = Mock()
        obo.current_user.me.return_value = me_user
        obo.users.get.return_value = full_user

        result = manager.get_current_user(obo_client=obo, real_ip="10.0.0.1")

        obo.users.get.assert_called_once_with("1234567890")
        assert result.groups == ["admins", "users", "account-ops-users"]
        # Email NOT in groups when real SCIM membership was resolved.
        assert "test@example.com" not in result.groups

    def test_get_current_user_email_fallback_when_scim_unavailable(
        self, manager, mock_databricks_user
    ):
        """When both me() and users.get(id) return no groups (FEVM-style
        workspaces), preserve legacy email-as-implicit-group fallback."""
        me_user = Mock()
        me_user.id = "1234567890"
        me_user.user_name = "test@example.com"
        me_user.display_name = "Test User"
        email = Mock()
        email.value = "test@example.com"
        me_user.emails = [email]
        me_user.groups = []

        empty_full_user = Mock()
        empty_full_user.groups = []

        obo = Mock()
        obo.current_user.me.return_value = me_user
        obo.users.get.return_value = empty_full_user

        result = manager.get_current_user(obo_client=obo, real_ip="10.0.0.1")

        assert result.groups == ["test@example.com"]

    def test_get_current_user_email_fallback_when_users_get_raises(
        self, manager, mock_databricks_user
    ):
        """If users.get(id) raises (403/timeout/etc), don't blow up — fall
        back to email-as-implicit-group."""
        me_user = Mock()
        me_user.id = "1234567890"
        me_user.user_name = "test@example.com"
        me_user.display_name = "Test User"
        email = Mock()
        email.value = "test@example.com"
        me_user.emails = [email]
        me_user.groups = []

        obo = Mock()
        obo.current_user.me.return_value = me_user
        obo.users.get.side_effect = Exception("permission denied")

        result = manager.get_current_user(obo_client=obo, real_ip="10.0.0.1")

        assert result.groups == ["test@example.com"]

    def test_get_current_user_no_obo_client(self, manager):
        """ValueError when OBO client is missing."""
        with pytest.raises(ValueError, match="OBO WorkspaceClient is required"):
            manager.get_current_user(obo_client=None)

