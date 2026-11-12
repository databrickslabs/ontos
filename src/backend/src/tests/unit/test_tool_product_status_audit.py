"""The product status tools audit a status change as the change-status route does.

``POST /api/data-products/{id}/change-status`` writes ``DEPRECATE`` (with the
deprecation reason, sunset date and replacement) for a deprecation, ``RETIRE`` for
a retirement and ``CHANGE_STATUS`` for any other target. ``update_data_product``
with a status writes the same entries, through Ask Ontos (``ToolRegistry.execute``)
and MCP (``check_tool_permission`` + ``tool.execute``, as ``mcp_routes``).
"""
import asyncio
import uuid
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.features import FeatureAccessLevel
from src.controller import audit_manager
from src.controller.data_products_manager import DataProductsManager
from src.controller.lifecycle_fields import LIFECYCLE_AUDIT_ACTIONS
from src.db_models.data_products import DataProductDb
from src.tools.base import ToolCaller, ToolContext, check_tool_permission
from src.tools.registry import create_default_registry

CALLER = ToolCaller(
    email='sue@example.com', auth_path='test',
    permissions={'data-products': FeatureAccessLevel.READ_WRITE},
)


def _ask_ontos(ctx, tool, args):
    return asyncio.run(create_default_registry().execute(tool, ctx, args))


def _mcp(ctx, tool, args):
    impl = create_default_registry().get(tool)
    refusal = check_tool_permission(impl, ctx)
    return refusal or asyncio.run(impl.execute(ctx, **args))


@pytest.fixture(params=['ask_ontos', 'mcp'])
def run(request):
    return {'ask_ontos': _ask_ontos, 'mcp': _mcp}[request.param]


@pytest.fixture
def audit(monkeypatch):
    entries = []
    monkeypatch.setattr(audit_manager, 'log_system_action', lambda **kw: entries.append(kw))
    return entries


def _product(db, status, name='Product'):
    row = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct', name=name,
        version='1.0.0', status=status, draft_owner_id=CALLER.email,
    )
    db.add(row)
    db.commit()
    return row


@pytest.fixture
def world(db_session):
    products = DataProductsManager(db=db_session, ws_client=MagicMock(),
                                   notifications_manager=MagicMock(), tags_manager=MagicMock())
    products._update_search_index = lambda *a, **k: None
    return SimpleNamespace(db=db_session, products=products)


def _update(world, run, product_id, **args):
    ctx = ToolContext(db=world.db, settings=MagicMock(), caller=CALLER,
                      data_products_manager=world.products)
    return run(ctx, 'update_data_product', {'product_id': product_id, **args})


def test_the_action_map_is_the_one_the_routes_use():
    assert LIFECYCLE_AUDIT_ACTIONS == {'deprecated': 'DEPRECATE', 'retired': 'RETIRE'}


def test_a_deprecation_is_audited_as_deprecate_with_its_details(world, run, audit):
    replacement = _product(world.db, 'active', 'Replacement')
    product = _product(world.db, 'active')
    sunset = date.today() + timedelta(days=30)
    res = _update(world, run, product.id, status='deprecated',
                  deprecation_reason='Superseded', sunset_date=sunset.isoformat(),
                  replacement_id=replacement.id)
    assert res.success is True, res.error
    assert [(e['action'], e['success']) for e in audit] == [('DEPRECATE', True)]
    assert audit[0]['feature'] == 'data-products'
    assert audit[0]['username'] == CALLER.email
    details = audit[0]['details']
    assert details['product_id'] == product.id
    assert details['new_status'] == 'deprecated'
    assert details['deprecation_reason'] == 'Superseded'
    assert details['sunset_date'] == sunset.isoformat()
    assert details['replacement_id'] == replacement.id
    assert details['tool_name'] == 'update_data_product'


def test_a_retirement_is_audited_as_retire(world, run, audit):
    product = _product(world.db, 'deprecated')
    res = _update(world, run, product.id, status='retired')
    assert res.success is True, res.error
    assert [(e['action'], e['success']) for e in audit] == [('RETIRE', True)]
    assert audit[0]['details']['product_id'] == product.id
    assert audit[0]['details']['new_status'] == 'retired'
    # Only a deprecation carries the deprecation details.
    assert 'deprecation_reason' not in audit[0]['details']


def test_a_failed_deprecation_is_audited_as_a_failed_deprecate(world, run, audit):
    product = _product(world.db, 'active')
    res = _update(world, run, product.id, status='deprecated')  # no reason
    assert res.success is False
    assert [(e['action'], e['success']) for e in audit] == [('DEPRECATE', False)]


def test_another_transition_is_still_audited_as_change_status(world, run, audit):
    product = _product(world.db, 'draft')
    res = _update(world, run, product.id, status='proposed')
    assert res.success is True, res.error
    assert [(e['action'], e['success']) for e in audit] == [('CHANGE_STATUS', True)]
    assert audit[0]['details']['new_status'] == 'proposed'
    assert 'deprecation_reason' not in audit[0]['details']


def test_the_schema_lists_retired_as_a_status():
    # A deprecated product retires through change-status, so the tool offers it.
    status = create_default_registry().get('update_data_product').parameters['status']
    assert 'retired' in status['enum']
    assert 'retired' in status['description']
