"""Approval steps stored with the legacy ``approver_role`` key.

Databases that loaded the default workflows before they used ``approvers``
(Publication / Certification Request Review) store
``approver_role: "data_steward"``. The approval step must still route those
requests to the Data Steward role instead of failing with
"No approvers configured".
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest

from src.common.workflow_executor import (
    ApprovalStepHandler,
    StepContext,
    _resolve_role_to_users,
)
from src.db_models.notifications import NotificationDb
from src.db_models.settings import AppRoleDb


def _make_context() -> StepContext:
    return StepContext(
        entity={'name': 'Orders', 'status': 'active'},
        entity_type='data_product',
        entity_id='product-1',
        entity_name='Orders',
        user_email='requester@co.com',
        trigger_context=None,
        execution_id='exec-1',
        workflow_id='wf-1',
        workflow_name='Certification Request Review',
        step_results={},
    )


@pytest.fixture
def data_steward(db_session):
    role = AppRoleDb(name='Data Steward')
    db_session.add(role)
    db_session.commit()
    return role


def test_snake_case_role_name_resolves_to_app_role(db_session, data_steward):
    result = _resolve_role_to_users(db_session, 'data_steward', _make_context())

    assert result == [('Data Steward', data_steward.id)]


def test_approval_step_reads_legacy_approver_role(db_session, data_steward):
    handler = ApprovalStepHandler(db_session, {'approver_role': 'data_steward'})

    result = handler.execute(_make_context())

    assert result.passed is True
    assert result.blocking is True
    assert result.data['approvers'] == ['Data Steward']
    notifications = db_session.query(NotificationDb).all()
    assert [(n.recipient, n.recipient_role_id) for n in notifications] == [
        ('Data Steward', data_steward.id)
    ]


def test_approvers_takes_precedence_over_approver_role(db_session, data_steward):
    handler = ApprovalStepHandler(
        db_session, {'approvers': 'steward@co.com', 'approver_role': 'data_steward'}
    )

    result = handler.execute(_make_context())

    assert result.data['approvers'] == ['steward@co.com']


def test_missing_approvers_still_fails(db_session):
    result = ApprovalStepHandler(db_session, {}).execute(_make_context())

    assert result.passed is False
    assert result.error == 'No approvers configured'
