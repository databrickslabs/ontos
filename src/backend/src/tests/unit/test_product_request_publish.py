"""POST /api/data-products/{id}/request-publish: status precondition and trigger payload."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.routes import data_product_routes


async def _request_publish(product, registry, scope='organization'):
    manager = SimpleNamespace(_repo=SimpleNamespace(get=lambda db, id: product))
    registry.on_request_publish.return_value = []  # the executions it ran
    with patch.object(data_product_routes, 'get_trigger_registry', return_value=registry):
        return await data_product_routes.request_publish_product(
            product_id='prod-1',
            request=MagicMock(client=None),
            db=MagicMock(),
            audit_manager=MagicMock(),
            change_log_manager=MagicMock(),
            current_user=SimpleNamespace(username='requester'),
            body={'scope': scope, 'justification': 'please'},
            manager=manager,
            _=True,
        )


@pytest.mark.asyncio
async def test_active_product_sends_its_status_to_the_workflow():
    registry = MagicMock()

    response = await _request_publish(SimpleNamespace(name='Orders', status='active'), registry)

    assert response.status_code == 202
    entity_data = registry.on_request_publish.call_args.kwargs['entity_data']
    assert entity_data['current_status'] == 'active'
    assert entity_data['requested_scope'] == 'organization'


@pytest.mark.asyncio
@pytest.mark.parametrize('status', ['draft', 'approved', 'deprecated'])
async def test_inactive_product_is_rejected_before_any_workflow_runs(status):
    registry = MagicMock()

    with pytest.raises(HTTPException) as exc:
        await _request_publish(SimpleNamespace(name='Orders', status=status), registry)

    assert exc.value.status_code == 409
    assert f"Current status: {status}" in exc.value.detail
    registry.on_request_publish.assert_not_called()


@pytest.mark.asyncio
async def test_status_is_compared_and_sent_in_lowercase():
    registry = MagicMock()

    response = await _request_publish(SimpleNamespace(name='Orders', status='ACTIVE'), registry)

    assert response.status_code == 202
    assert registry.on_request_publish.call_args.kwargs['entity_data']['current_status'] == 'active'


@pytest.mark.asyncio
async def test_requesting_scope_none_is_allowed_in_any_status():
    # Same exemption as set-publication-scope: withdrawing is always allowed.
    registry = MagicMock()

    response = await _request_publish(
        SimpleNamespace(name='Orders', status='deprecated'), registry, scope='none'
    )

    assert response.status_code == 202
    registry.on_request_publish.assert_called_once()

