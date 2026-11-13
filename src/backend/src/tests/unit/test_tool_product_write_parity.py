"""The data product write tools apply the ownership rule and audit of the REST routes.

``update_data_product`` changes fields only for a caller that ``PUT
/api/data-products/{id}`` lets through (``update_product_with_auth``: draft owner,
owning team, project member, data-products admin); a status change alone needs
only the level, as ``change-status``. ``create_draft_data_product`` makes the
caller the draft owner, as ``POST /api/data-products`` does. Each change writes
the data-products audit entry of its route (CREATE / UPDATE / CHANGE_STATUS /
DEPRECATE / RETIRE / DELETE) with the caller as username.
"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.features import FeatureAccessLevel
from src.common.workflow_triggers import StatusChangeBlockedError
from src.controller import audit_manager
from src.controller import projects_manager as projects_module
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_products import DataProductDb
from src.tools.base import ToolCaller, ToolContext
from src.tools.registry import create_default_registry

# Spelled out so the tests run (and fail) on a tree without the constant.
PRODUCT_EDIT_NOT_ALLOWED_CODE = 'product_edit_not_allowed'
TEAM = 'team-owners'
PROJECT = 'project-1'
RW = {'data-products': FeatureAccessLevel.READ_WRITE}
ADMIN_LEVEL = {'data-products': FeatureAccessLevel.ADMIN}

NON_OWNER = ToolCaller(email='carl@example.com', auth_path='test', permissions=RW)
OWNER = ToolCaller(email='Sue@example.com', auth_path='test', permissions=RW)
MEMBER = ToolCaller(email='tom@example.com', auth_path='test', permissions=RW,
                    team_ids={TEAM})
PROJECT_MEMBER = ToolCaller(email='pam@example.com', auth_path='test', permissions=RW)
ADMIN = ToolCaller(email='ann@example.com', auth_path='test', permissions=ADMIN_LEVEL,
                   products_admin=True)
# May edit: every persona but NON_OWNER.
EDITORS = {'owner': OWNER, 'member': MEMBER, 'project member': PROJECT_MEMBER,
           'admin': ADMIN}
PERSONAS = {'non-owner': NON_OWNER, **EDITORS}


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def audit(monkeypatch):
    entries = []
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: entries.append(kw))
    return entries


@pytest.fixture
def world(db_session, monkeypatch, audit):
    """A published product with a draft owner, an owning team and a project."""
    row = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        name='Published product', version='1.0.0', status='active',
        draft_owner_id='sue@example.com', owner_team_id=TEAM, project_id=PROJECT,
    )
    db_session.add(row)
    db_session.commit()
    # Project membership: only PROJECT_MEMBER is a member of PROJECT.
    monkeypatch.setattr(
        projects_module.projects_manager, 'is_user_project_member',
        lambda db, user_identifier, user_groups, project_id, settings:
            user_identifier == PROJECT_MEMBER.email and project_id == PROJECT,
    )
    products = DataProductsManager(db=db_session, ws_client=MagicMock(),
                                   notifications_manager=MagicMock(), tags_manager=MagicMock())
    products._update_search_index = lambda *a, **k: None
    return SimpleNamespace(db=db_session, row=row, products=products, audit=audit)


def _call(world, caller, tool, **args):
    ctx = ToolContext(db=world.db, settings=MagicMock(), caller=caller,
                      data_products_manager=world.products)
    return _run(create_default_registry().execute(tool, ctx, args))


def _stored(world):
    world.db.expire_all()
    return world.db.get(DataProductDb, world.row.id)


def _route_allows(world, caller):
    """What PUT /api/data-products/{id} decides for the caller (its manager call)."""
    try:
        world.products.update_product_with_auth(
            product_id=world.row.id, product_data_dict={'name': world.row.name},
            user_email=caller.email, user_groups=caller.groups, db=world.db,
            caller_team_ids=list(caller.team_ids), is_feature_admin=caller.products_admin,
        )
        return True
    except PermissionError:
        return False


class TestUpdateNeedsAnOwner:
    def test_a_non_owner_cannot_change_the_fields(self, world):
        res = _call(world, NON_OWNER, 'update_data_product', product_id=world.row.id,
                    description='changed by a non-owner')
        assert res.success is False
        assert res.error_code == PRODUCT_EDIT_NOT_ALLOWED_CODE
        assert _stored(world).description is None
        assert [(e['action'], e['success']) for e in world.audit] == [('UPDATE', False)]
        assert world.audit[0]['username'] == NON_OWNER.email
        assert world.audit[0]['feature'] == 'data-products'

    def test_a_refused_change_with_a_status_writes_nothing(self, world):
        res = _call(world, NON_OWNER, 'update_data_product', product_id=world.row.id,
                    domain='Other', status='deprecated')
        assert res.error_code == PRODUCT_EDIT_NOT_ALLOWED_CODE
        assert _stored(world).status == 'active'

    @pytest.mark.parametrize('persona', sorted(EDITORS))
    def test_an_owner_or_admin_changes_the_fields(self, world, persona):
        res = _call(world, EDITORS[persona], 'update_data_product', product_id=world.row.id,
                    description=f'changed by {persona}')
        assert res.success is True, res.error
        assert _stored(world).description is not None
        assert [(e['action'], e['success']) for e in world.audit] == [('UPDATE', True)]
        assert world.audit[0]['username'] == EDITORS[persona].email
        assert world.audit[0]['details']['product_id'] == world.row.id
        assert world.audit[0]['details']['tool_name'] == 'update_data_product'

    @pytest.mark.parametrize('persona', sorted(PERSONAS))
    def test_the_tool_decides_like_the_put_route(self, world, persona):
        caller = PERSONAS[persona]
        res = _call(world, caller, 'update_data_product', product_id=world.row.id,
                    description='parity')
        assert res.success is _route_allows(world, caller), res.error

    def test_a_status_change_alone_needs_only_the_level(self, world):
        # As POST /api/data-products/{id}/change-status (Read/Write, no ownership rule).
        res = _call(world, NON_OWNER, 'update_data_product', product_id=world.row.id,
                    status='deprecated', deprecation_reason='Replaced')
        assert res.success is True, res.error
        assert _stored(world).status == 'deprecated'
        assert [(e['action'], e['success']) for e in world.audit] == [('DEPRECATE', True)]
        assert world.audit[0]['username'] == NON_OWNER.email
        assert world.audit[0]['details']['new_status'] == 'deprecated'


class TestCreateAndDelete:
    def test_the_creator_owns_the_draft(self, world):
        res = _call(world, NON_OWNER, 'create_draft_data_product', name='Chat draft',
                    description='made by the assistant', domain='Sales')
        assert res.success is True, res.error
        pid = res.data['product_id']
        world.db.expire_all()
        assert world.db.get(DataProductDb, pid).draft_owner_id == NON_OWNER.email
        assert [(e['action'], e['success']) for e in world.audit] == [('CREATE', True)]
        assert world.audit[0]['details']['created_resource_id'] == pid
        # The creator reads and edits it afterwards, as with the REST create.
        assert _call(world, NON_OWNER, 'get_data_product', product_id=pid).success is True
        res = _call(world, NON_OWNER, 'update_data_product', product_id=pid,
                    description='edited by its creator')
        assert res.success is True, res.error

    def test_a_delete_is_audited_and_names_the_caller(self, world, monkeypatch):
        seen = {}
        delete = world.products.delete_product

        def _delete(product_id, user=None, **kwargs):
            seen['user'] = user
            return delete(product_id, user=user, **kwargs)

        monkeypatch.setattr(world.products, 'delete_product', _delete)
        res = _call(world, ADMIN, 'delete_data_product', product_id=world.row.id)
        assert res.success is True, res.error
        assert seen['user'] == ADMIN.email
        assert [(e['action'], e['success']) for e in world.audit] == [('DELETE', True)]
        assert world.audit[0]['username'] == ADMIN.email


    def test_a_failed_delete_is_audited_as_failed(self, world, monkeypatch):
        monkeypatch.setattr(world.products, 'delete_product', lambda *a, **k: False)
        res = _call(world, ADMIN, 'delete_data_product', product_id=world.row.id)
        assert res.success is False
        assert [(e['action'], e['success']) for e in world.audit] == [('DELETE', False)]

    def test_a_blocked_status_change_is_audited_as_failed(self, world, monkeypatch):
        def _blocked(*args, **kwargs):
            raise StatusChangeBlockedError('active', 'deprecated', [])

        monkeypatch.setattr(world.products, 'transition_status', _blocked)
        res = _call(world, NON_OWNER, 'update_data_product', product_id=world.row.id,
                    status='deprecated', deprecation_reason='Replaced')
        assert res.success is False
        assert res.error_code == 'status_change_blocked'
        assert _stored(world).status == 'active'
        assert [(e['action'], e['success']) for e in world.audit] \
            == [('DEPRECATE', False)]


def test_the_route_helper_and_the_tool_share_the_ownership_rule(world):
    """``update_product_with_auth`` delegates to ``check_update_allowed``."""
    with pytest.raises(PermissionError):
        world.products.check_update_allowed(
            world.row, user_email=NON_OWNER.email, user_groups=[], db=world.db,
        )
    # The draft owner match is case-insensitive.
    world.products.check_update_allowed(
        world.row, user_email=OWNER.email, user_groups=[], db=world.db,
    )
