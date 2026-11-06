"""The product status workflow stores a notification-addressable requester."""

import asyncio
import os
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from src.models.data_products import RequestStatusChangePayload
from src.models.users import UserInfo
from src.routes.data_product_routes import request_status_change


@pytest.mark.parametrize(
    ('email', 'username', 'expected_requester'),
    [
        ('requester@example.com', 'requester', 'requester@example.com'),
        (None, 'requester@example.com', 'requester@example.com'),
    ],
)
def test_request_status_change_uses_email_with_username_fallback(
    email, username, expected_requester,
):
    manager = MagicMock()
    manager.request_status_change.return_value = {'message': 'submitted'}
    audit_manager = MagicMock()
    current_user = UserInfo(
        email=email, username=username, user=username, ip='127.0.0.1', groups=[],
    )

    result = asyncio.run(request_status_change(
        product_id='product-1',
        request=SimpleNamespace(client=SimpleNamespace(host='127.0.0.1')),
        db=MagicMock(),
        audit_manager=audit_manager,
        current_user=current_user,
        notifications=MagicMock(),
        payload=RequestStatusChangePayload(
            target_status='proposed', justification='Ready for review',
        ),
        manager=manager,
        _=True,
    ))

    assert result == {'message': 'submitted'}
    assert manager.request_status_change.call_args.kwargs['requester_email'] == expected_requester
