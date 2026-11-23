"""Installing a job decides the requests to enable it (#1527 review).

The job-enable dedup keeps one pending request per workflow until the ``handled`` marker:
installing the workflow writes it, so the request leaves My actions and a later ask (after
the job is removed again) creates a new request.
"""
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

import pytest
from sqlalchemy.orm import Session

from src.controller.jobs_manager import JobsManager
from src.controller.notifications_manager import NotificationsManager
from src.db_models.notifications import NotificationDb

ACTION = 'handle_job_enable_request'
WORKFLOW = 'compliance-checks'


def _request(workflow_id: str = WORKFLOW, read: bool = False) -> dict:
    return dict(
        id=str(uuid.uuid4()), type='action_required', title='Enable job',
        created_at=datetime(2026, 11, 1, 12, 0, 0), read=read, can_delete=False,
        recipient='Admin', recipient_role_id=None, action_type=ACTION,
        action_payload=json.dumps({'workflow_id': workflow_id,
                                   'requester_email': 'bob@example.com'}),
    )


def _insert(db: Session, rows: list) -> None:
    db.execute(NotificationDb.__table__.insert(), rows)
    db.flush()


def _notifications() -> NotificationsManager:
    settings = Mock()
    settings.list_app_roles.return_value = []
    return NotificationsManager(settings_manager=settings)


def _install(db: Session, notifications: NotificationsManager, workflow_id: str) -> None:
    settings = SimpleNamespace(DATABRICKS_HOST='https://example.cloud.databricks.com',
                               WORKSPACE_DEPLOYMENT_PATH=None)
    jobs = JobsManager(db=db, ws_client=MagicMock(), notifications_manager=notifications,
                       settings=settings)
    with patch.object(jobs, '_get_workflow_definition', return_value={'name': workflow_id}), \
            patch.object(jobs, '_build_tasks_from_definition', return_value=[]):
        jobs.install_workflow(workflow_id)


def _pending(db: Session, notifications: NotificationsManager, workflow_id: str) -> bool:
    return notifications.has_unhandled_actionable_notification(
        db, ACTION, {'workflow_id': workflow_id})


@pytest.mark.parametrize('read', [False, True], ids=['unread', 'opened'])
def test_an_undecided_request_still_deduplicates(db_session: Session, read: bool):
    _insert(db_session, [_request(read=read)])

    assert _pending(db_session, _notifications(), WORKFLOW) is True


@pytest.mark.parametrize('read', [False, True], ids=['unread', 'opened'])
def test_installing_the_job_decides_its_requests_and_lets_a_new_ask_through(
    db_session: Session, read: bool,
):
    target, other = _request(read=read), _request(workflow_id='other-job')
    _insert(db_session, [target, other])
    notifications = _notifications()

    _install(db_session, notifications, WORKFLOW)

    stored = db_session.get(NotificationDb, target['id'])
    db_session.refresh(stored)
    assert stored.read is True
    assert json.loads(stored.action_payload)['handled'] is True
    assert _pending(db_session, notifications, WORKFLOW) is False
    # Another workflow's request is not decided by this installation
    assert _pending(db_session, notifications, 'other-job') is True
