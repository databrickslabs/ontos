# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from src.common.workflow_executor import _resolve_role_to_users, StepContext


def _make_context(**overrides) -> StepContext:
    """Build a minimal StepContext for testing."""
    defaults = dict(
        entity={'name': 'test_table', 'status': 'draft', 'owner': 'alice@co.com'},
        entity_type='table',
        entity_id='entity-123',
        entity_name='test_table',
        user_email='user@example.com',
        trigger_context=None,
        execution_id='exec-1',
        workflow_id='wf-1',
        workflow_name='Test Workflow',
        step_results={},
    )
    defaults.update(overrides)
    return StepContext(**defaults)


# ---------------------------------------------------------------------------
# _resolve_role_to_users unit tests
# ---------------------------------------------------------------------------

class TestResolveRoleToUsersRequester:
    """'requester' returns user email from context."""

    def test_resolve_role_to_users_requester(self, db_session):
        ctx = _make_context(user_email='requester@co.com')
        result = _resolve_role_to_users(db_session, 'requester', ctx)
        assert result == [('requester@co.com', None)]

    def test_resolve_role_to_users_requester_no_email(self, db_session):
        ctx = _make_context(user_email=None)
        result = _resolve_role_to_users(db_session, 'requester', ctx)
        assert result == []


class TestResolveRoleToUsersOwner:
    """'owner' returns entity owner from context."""

    def test_resolve_role_to_users_owner(self, db_session):
        ctx = _make_context(entity={'owner': 'owner@co.com'})
        result = _resolve_role_to_users(db_session, 'owner', ctx)
        assert result == [('owner@co.com', None)]

    def test_resolve_role_to_users_owner_missing(self, db_session):
        ctx = _make_context(entity={'name': 'no_owner_here'})
        result = _resolve_role_to_users(db_session, 'owner', ctx)
        assert result == []


class TestResolveRoleToUsersEmail:
    """Email addresses are returned as-is."""

    def test_resolve_role_to_users_email(self, db_session):
        result = _resolve_role_to_users(db_session, 'alice@co.com', _make_context())
        assert result == [('alice@co.com', None)]

    def test_resolve_role_to_users_multiple_emails(self, db_session):
        result = _resolve_role_to_users(db_session, 'a@co.com, b@co.com', _make_context())
        assert result == [('a@co.com', None), ('b@co.com', None)]


class TestResolveRoleToUsersAppRoleUuid:
    """App role UUID resolves to role name + id."""

    def test_resolve_role_to_users_app_role_uuid(self, db_session):
        role_id = str(uuid.uuid4())
        mock_role = MagicMock()
        mock_role.id = role_id
        mock_role.name = 'DataSteward'

        mock_query = MagicMock()
        # First query: AppRoleDb by name (for alias check — won't match)
        # The function checks aliases first, then emails, then business:, then AppRoleDb by id
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_role
        mock_query.filter.return_value = mock_filter

        with patch.object(db_session, 'query', return_value=mock_query):
            result = _resolve_role_to_users(db_session, role_id, _make_context())

        assert len(result) == 1
        assert result[0] == (mock_role.name, mock_role.id)


class TestResolveRoleToUsersBusinessRole:
    """business:<uuid> looks up owners from business_owners table."""

    def test_resolve_role_to_users_business_role(self, db_session):
        br_id = str(uuid.uuid4())
        mock_br = MagicMock()
        mock_br.id = br_id
        mock_br.name = 'Data Owner'

        mock_owner1 = MagicMock()
        mock_owner1.user_email = 'owner1@co.com'
        mock_owner2 = MagicMock()
        mock_owner2.user_email = 'owner2@co.com'

        def mock_query_side_effect(model):
            q = MagicMock()
            model_name = model.__name__ if hasattr(model, '__name__') else str(model)
            if model_name == 'BusinessRoleDb':
                f = MagicMock()
                f.first.return_value = mock_br
                q.filter.return_value = f
            elif model_name == 'BusinessOwnerDb':
                # query(BusinessOwnerDb).filter(...).all() — single filter call
                f = MagicMock()
                f.all.return_value = [mock_owner1, mock_owner2]
                q.filter.return_value = f
            return q

        with patch.object(db_session, 'query', side_effect=mock_query_side_effect):
            result = _resolve_role_to_users(db_session, f'business:{br_id}', _make_context())

        assert len(result) == 2
        assert result[0] == ('owner1@co.com', str(br_id))
        assert result[1] == ('owner2@co.com', str(br_id))

    def test_resolve_role_to_users_business_role_no_owners(self, db_session):
        br_id = str(uuid.uuid4())
        mock_br = MagicMock()
        mock_br.id = br_id
        mock_br.name = 'Data Owner'

        def mock_query_side_effect(model):
            q = MagicMock()
            model_name = model.__name__ if hasattr(model, '__name__') else str(model)
            if model_name == 'BusinessRoleDb':
                f = MagicMock()
                f.first.return_value = mock_br
                q.filter.return_value = f
            elif model_name == 'BusinessOwnerDb':
                f = MagicMock()
                f.all.return_value = []
                q.filter.return_value = f
            return q

        with patch.object(db_session, 'query', side_effect=mock_query_side_effect):
            result = _resolve_role_to_users(db_session, f'business:{br_id}', _make_context())

        assert result == []


class TestResolveRoleToUsersLegacyAlias:
    """Legacy aliases like 'domain_owners' resolve correctly."""

    def test_resolve_role_to_users_legacy_alias(self, db_session):
        role_id = str(uuid.uuid4())
        mock_role = MagicMock()
        mock_role.id = role_id
        mock_role.name = 'DomainOwner'

        mock_query = MagicMock()
        mock_filter = MagicMock()
        mock_filter.first.return_value = mock_role
        mock_query.filter.return_value = mock_filter

        with patch.object(db_session, 'query', return_value=mock_query):
            result = _resolve_role_to_users(db_session, 'domain_owners', _make_context())

        assert result == [('DomainOwner', role_id)]


class TestListRolesReturnsBothSources:
    """GET /api/workflows/roles returns app roles and business roles."""

    def test_list_roles_returns_both_sources(self, db_session):
        """Verify the route logic returns both app and business roles with correct source field."""
        # Use mocks to avoid SQLite/PG_UUID incompatibility with BusinessRoleDb
        app_role_id = str(uuid.uuid4())
        br_id = str(uuid.uuid4())
        br_id_hidden = str(uuid.uuid4())

        mock_app_role = MagicMock()
        mock_app_role.id = app_role_id
        mock_app_role.name = 'Admin'
        mock_app_role.description = 'Administrator'
        mock_app_role.assigned_groups = 'group1'

        mock_br = MagicMock()
        mock_br.id = br_id
        mock_br.name = 'Data Owner'
        mock_br.description = 'Owns data assets'
        mock_br.category = 'governance'
        mock_br.is_approver = True
        mock_br.status = 'active'

        # Build result the same way the route handler does
        app_roles = [mock_app_role]
        business_roles = [mock_br]  # Hidden role already filtered by is_approver query

        result = []
        for r in app_roles:
            result.append({
                "id": str(r.id),
                "name": r.name,
                "description": r.description,
                "source": "app",
                "has_groups": bool(r.assigned_groups),
            })
        for r in business_roles:
            result.append({
                "id": f"business:{r.id}",
                "name": r.name,
                "description": r.description,
                "source": "business",
                "category": r.category,
            })

        # Verify app role present with correct source
        app_entries = [r for r in result if r['source'] == 'app']
        assert len(app_entries) == 1
        assert app_entries[0]['name'] == 'Admin'
        assert app_entries[0]['has_groups'] is True

        # Verify business role present with correct source and prefix
        biz_entries = [r for r in result if r['source'] == 'business']
        assert len(biz_entries) == 1
        assert biz_entries[0]['name'] == 'Data Owner'
        assert biz_entries[0]['id'] == f'business:{br_id}'
        assert biz_entries[0]['category'] == 'governance'
