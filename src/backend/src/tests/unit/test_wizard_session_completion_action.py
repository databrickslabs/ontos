"""Only the subscription wizard may complete with 'subscribe'.

``for_approval_response`` is open to any authenticated user (#971), and a
session's ``completion_action`` comes from the client, so a session on that
workflow with ``completion_action='subscribe'`` subscribed users who can't
subscribe.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.routes.approvals_routes import CreateSessionBody, create_approval_session


def _create(trigger_type, completion_action):
    wizard_manager = MagicMock()
    wizard_manager.create_session.return_value = {'session_id': 's1'}
    body = CreateSessionBody(
        workflow_id='wf-1', entity_type='data_product', entity_id='p1',
        completion_action=completion_action,
    )
    with patch('src.routes.approvals_routes._resolve_trigger_type_for_workflow',
               return_value=trigger_type), \
            patch('src.routes.approvals_routes.enforce_wizard_permission', new=AsyncMock()):
        result = asyncio.run(create_approval_session(
            request=MagicMock(), db=MagicMock(), body=body,
            current_user=MagicMock(email='u@example.com'),
            wizard_manager=wizard_manager, user_details=MagicMock(),
        ))
    return result, wizard_manager


@pytest.mark.parametrize('trigger_type', ['for_approval_response', 'for_request_access', None])
def test_subscribe_is_rejected_outside_the_subscription_wizard(trigger_type):
    with pytest.raises(HTTPException) as exc:
        _create(trigger_type, 'subscribe')

    assert exc.value.status_code == 400


def test_the_subscription_wizard_can_subscribe():
    result, wizard_manager = _create('for_subscribe', 'subscribe')

    assert result == {'session_id': 's1'}
    assert wizard_manager.create_session.call_args.kwargs['completion_action'] == 'subscribe'


def test_other_wizards_without_completion_action_still_work():
    result, _ = _create('for_approval_response', None)

    assert result == {'session_id': 's1'}
