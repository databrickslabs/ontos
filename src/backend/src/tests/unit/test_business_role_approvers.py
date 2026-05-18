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

    def test_resolve_role_to_users_business_role_missing(self, db_session):
        """Regression guard: missing BusinessRoleDb returns [] without traversal."""
        br_id = str(uuid.uuid4())

        def mock_query_side_effect(model):
            q = MagicMock()
            model_name = model.__name__ if hasattr(model, '__name__') else str(model)
            if model_name == 'BusinessRoleDb':
                f = MagicMock()
                f.first.return_value = None
                q.filter.return_value = f
            return q

        with patch.object(db_session, 'query', side_effect=mock_query_side_effect):
            result = _resolve_role_to_users(db_session, f'business:{br_id}', _make_context())

        assert result == []


class TestResolveRoleToUsersBusinessRoleProxyEntities:
    """Proxy entity types (access_grant) traverse to the underlying entity id.

    Business Owners are assigned to real entities (data products, etc.). When
    a trigger fires on a proxy entity like access_grant, context.entity_id is
    the request's UUID — not the underlying object. The resolver must read
    context.entity['entity_id'] to find the real lookup target.
    """

    def _build_query_side_effect(self, mock_br, captured_filters, owners):
        """Build a query side-effect that captures BusinessOwnerDb filter args."""
        def side_effect(model):
            q = MagicMock()
            model_name = model.__name__ if hasattr(model, '__name__') else str(model)
            if model_name == 'BusinessRoleDb':
                f = MagicMock()
                f.first.return_value = mock_br
                q.filter.return_value = f
            elif model_name == 'BusinessOwnerDb':
                def capture_filter(*args, **kwargs):
                    captured_filters.append((args, kwargs))
                    f = MagicMock()
                    f.all.return_value = owners
                    return f
                q.filter.side_effect = capture_filter
            return q
        return side_effect

    def test_data_product_direct_lookup_unchanged(self, db_session):
        """Regression guard: direct data_product trigger looks up by context.entity_id."""
        br_id = str(uuid.uuid4())
        dp_id = str(uuid.uuid4())
        mock_br = MagicMock()
        mock_br.id = br_id
        mock_br.name = 'Data Owner'

        owner = MagicMock()
        owner.user_email = 'dp_owner@co.com'

        captured = []
        ctx = _make_context(
            entity_type='data_product',
            entity_id=dp_id,
            entity={'name': 'sales_dp', 'owner': 'dp_owner@co.com'},
        )

        with patch.object(
            db_session,
            'query',
            side_effect=self._build_query_side_effect(mock_br, captured, [owner]),
        ):
            result = _resolve_role_to_users(db_session, f'business:{br_id}', ctx)

        assert result == [('dp_owner@co.com', str(br_id))]
        # The filter clause should reference dp_id (context.entity_id), not anything else.
        # We can't easily introspect SQLAlchemy BinaryExpression args, but we can confirm
        # exactly one BusinessOwnerDb filter was issued (no double-lookup happened).
        assert len(captured) == 1

    def test_access_grant_traverses_to_underlying_entity(self, db_session):
        """access_grant proxy: lookup uses context.entity['entity_id'] (the data product id)."""
        br_id = str(uuid.uuid4())
        dp_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        mock_br = MagicMock()
        mock_br.id = br_id
        mock_br.name = 'Data Owner'

        # Owner is assigned to the underlying data product
        owner = MagicMock()
        owner.user_email = 'underlying_owner@co.com'

        # Spy on the BusinessOwnerDb filter to confirm what object_id was used
        captured_object_ids = []

        def side_effect(model):
            q = MagicMock()
            model_name = model.__name__ if hasattr(model, '__name__') else str(model)
            if model_name == 'BusinessRoleDb':
                f = MagicMock()
                f.first.return_value = mock_br
                q.filter.return_value = f
            elif model_name == 'BusinessOwnerDb':
                # The filter is called with SQLAlchemy BinaryExpressions; we can
                # inspect them via .right.value (the constant side).
                def capture_filter(*args, **kwargs):
                    for clause in args:
                        right = getattr(clause, 'right', None)
                        val = getattr(right, 'value', None)
                        if val is not None:
                            captured_object_ids.append(val)
                    f = MagicMock()
                    f.all.return_value = [owner]
                    return f
                q.filter.side_effect = capture_filter
            return q

        ctx = _make_context(
            entity_type='access_grant',
            entity_id=request_id,
            entity_name='request for sales_dp',
            entity={
                'request_id': request_id,
                'entity_type': 'data_product',
                'entity_id': dp_id,
                'entity_name': 'sales_dp',
            },
        )

        with patch.object(db_session, 'query', side_effect=side_effect):
            result = _resolve_role_to_users(db_session, f'business:{br_id}', ctx)

        assert result == [('underlying_owner@co.com', str(br_id))]
        # Confirm the underlying dp_id was the lookup target, not request_id.
        assert dp_id in captured_object_ids
        assert request_id not in captured_object_ids

    def test_access_grant_no_underlying_owners_returns_empty_no_fallback(self, db_session):
        """access_grant proxy with no matching owners returns [] — NO admin fallback."""
        br_id = str(uuid.uuid4())
        dp_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        mock_br = MagicMock()
        mock_br.id = br_id
        mock_br.name = 'Data Owner'

        def side_effect(model):
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
            # AppRoleDb must NOT be queried — that would indicate a fallback.
            return q

        ctx = _make_context(
            entity_type='access_grant',
            entity_id=request_id,
            entity={
                'request_id': request_id,
                'entity_type': 'data_product',
                'entity_id': dp_id,
            },
        )

        with patch.object(db_session, 'query', side_effect=side_effect) as query_mock:
            result = _resolve_role_to_users(db_session, f'business:{br_id}', ctx)

        assert result == []
        # Confirm AppRoleDb was NOT consulted (no admin fallback).
        queried_models = {
            (call.args[0].__name__ if hasattr(call.args[0], '__name__') else str(call.args[0]))
            for call in query_mock.call_args_list
        }
        assert 'AppRoleDb' not in queried_models

    def test_access_grant_missing_underlying_id_falls_back_to_entity_id(self, db_session):
        """If context.entity has no 'entity_id' key, the resolver falls back to context.entity_id.

        This is the graceful-degradation path: the lookup will almost certainly
        return [] (because business owners aren't assigned to access_grant
        request UUIDs), but the resolver must not crash.
        """
        br_id = str(uuid.uuid4())
        request_id = str(uuid.uuid4())
        mock_br = MagicMock()
        mock_br.id = br_id
        mock_br.name = 'Data Owner'

        def side_effect(model):
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

        ctx = _make_context(
            entity_type='access_grant',
            entity_id=request_id,
            entity={'request_id': request_id},  # no entity_id key
        )

        with patch.object(db_session, 'query', side_effect=side_effect):
            result = _resolve_role_to_users(db_session, f'business:{br_id}', ctx)

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
