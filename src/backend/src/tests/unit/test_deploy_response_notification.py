"""A deploy approval records the decision and deploys nothing; ``execute_deployment``
is accepted, ignored and answered with a warning (#1151 item 1)."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import inspect
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.controller.data_contracts_manager import (
    DEPLOYMENT_NOT_AVAILABLE_CODE,
    DataContractsManager,
)


def _decide(caplog, decision='approve', execute_deployment=False):
    manager = DataContractsManager(data_dir=Path('/tmp'))
    notifications = MagicMock()
    changes = MagicMock()
    changes.get_changes_for_entity.return_value = [
        SimpleNamespace(action='deploy_requested', details={'requester_email': 'req@example.com'}),
    ]
    contract = SimpleNamespace(id='c-1', name='Orders')
    with patch('src.controller.data_contracts_manager.data_contract_repo.get',
               return_value=contract), \
            patch('src.controller.change_log_manager.change_log_manager', changes), \
            caplog.at_level(logging.WARNING):
        result = manager.handle_deploy_response(
            db=MagicMock(), notifications_manager=notifications,
            contract_id='c-1', approver_email='boss@example.com', decision=decision,
            execute_deployment=execute_deployment,
        )
    notification = notifications.create_notification.call_args.kwargs['notification']
    return result, notification, changes


def test_the_manager_has_no_jobs_manager_to_deploy_with():
    params = inspect.signature(DataContractsManager.handle_deploy_response).parameters
    assert 'jobs_manager' not in params
    assert 'execute_deployment' in params


def test_execute_deployment_is_ignored_with_a_coded_warning(caplog):
    result, notification, _ = _decide(caplog, execute_deployment=True)

    assert result['warnings'] == [{
        'code': DEPLOYMENT_NOT_AVAILABLE_CODE,
        'message': result['warnings'][0]['message'],
        'params': {},
    }]
    assert 'job_id' not in result
    assert result['message'] == "Deploy decision 'approve' recorded successfully"
    assert notification.title == 'Contract Deployment Approved'
    assert notification.description == "Your contract 'Orders' deployment was approved."
    assert any(
        r.levelno == logging.WARNING and 'c-1' in r.getMessage() and 'ignored' in r.getMessage()
        for r in caplog.records
    )


def test_an_approval_without_execute_deployment_has_no_warning(caplog):
    result, notification, _ = _decide(caplog)

    assert 'warnings' not in result
    assert notification.title == 'Contract Deployment Approved'
    assert not any(r.levelno == logging.WARNING for r in caplog.records)


def test_a_denial_with_execute_deployment_is_still_a_denial(caplog):
    result, notification, changes = _decide(caplog, decision='deny', execute_deployment=True)

    assert result['warnings'][0]['code'] == DEPLOYMENT_NOT_AVAILABLE_CODE
    assert notification.title == 'Contract Deployment Denied'
    details = changes.log_change_with_details.call_args.kwargs['details']
    assert details['decision'] == 'deny'
    assert details['execute_deployment'] is True


class TestDeployRequestApprover:
    """``deploy_request_access``: a recipient of the contract's undecided request."""

    def _notification(self, db, contract_id, recipient, role_id=None, handled=False):
        import json as _json
        import uuid as _uuid
        from datetime import datetime as _dt
        from src.db_models.notifications import NotificationDb

        db.add(NotificationDb(
            id=str(_uuid.uuid4()), type='action_required', title='Contract Deployment Request',
            recipient=recipient, recipient_role_id=role_id, created_at=_dt.utcnow(),
            action_type='handle_deploy_request', can_delete=False, read=True,
            action_payload=_json.dumps(
                {'contract_id': contract_id, **({'handled': True} if handled else {})},
            ),
        ))
        db.flush()

    def _check(self, db, contract_id, user, roles, access='pending'):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from src.controller.data_contracts_manager import DataContractsManager
        from src.controller.notifications_manager import NotificationsManager
        from src.models.users import UserInfo

        settings = Mock()
        settings.list_app_roles.return_value = [
            SimpleNamespace(id=f'role-{n}', name=n, assigned_groups=g) for n, g in roles
        ]
        info = UserInfo(
            email=user[0], username=user[0], user=user[0], ip='127.0.0.1', groups=user[1],
        )
        manager = DataContractsManager.__new__(DataContractsManager)
        return manager.deploy_request_access(
            db, NotificationsManager(settings_manager=settings), contract_id, info,
        ) == access

    ROLES = [('Admin', ['admins']), ('Release', ['release'])]

    def test_admins_decide_the_request_to_the_admin_role(self, db_session):
        self._notification(db_session, 'c1', 'Admin')
        assert self._check(db_session, 'c1', ('a@x.com', ['admins']), self.ROLES) is True

    def test_an_editor_outside_the_recipients_does_not(self, db_session):
        self._notification(db_session, 'c1', 'Admin')
        assert self._check(db_session, 'c1', ('e@x.com', ['editors']), self.ROLES) is False

    def test_group_role_and_user_recipients(self, db_session):
        self._notification(db_session, 'c1', 'group:Ops')
        self._notification(db_session, 'c2', 'Release', role_id='role-Release')
        self._notification(db_session, 'c3', 'user:pat')
        assert self._check(db_session, 'c1', ('o@x.com', ['ops']), self.ROLES) is True
        assert self._check(db_session, 'c2', ('r@x.com', ['release']), self.ROLES) is True
        assert self._check(db_session, 'c3', ('pat', []), self.ROLES) is True
        # Another contract's request decides nothing here
        assert self._check(db_session, 'c2', ('o@x.com', ['ops']), self.ROLES) is False

    def test_no_request_no_approver_not_even_an_admin(self, db_session):
        assert self._check(db_session, 'c9', ('a@x.com', ['admins']), self.ROLES) is False

    def test_a_decided_request_is_decided_not_pending(self, db_session):
        """Read (the fixture's notifications are read) is not decided; handled is."""
        self._notification(db_session, 'c1', 'Admin', handled=True)
        admin = ('a@x.com', ['admins'])
        assert self._check(db_session, 'c1', admin, self.ROLES, access='decided') is True
        self._notification(db_session, 'c1', 'Admin')
        assert self._check(db_session, 'c1', admin, self.ROLES) is True

    def test_a_broadcast_request_decides_nothing(self, db_session):
        self._notification(db_session, 'c1', None)
        assert self._check(db_session, 'c1', ('e@x.com', ['editors']), self.ROLES) is False


def test_a_refused_decision_records_and_audits_nothing():
    """The approver check runs before anything is written."""
    import asyncio
    import pytest
    from fastapi import HTTPException
    from src.routes.data_contracts_routes import (
        HandleDeployPayload, handle_deploy_request_response,
    )

    manager = MagicMock()
    manager.deploy_request_access.return_value = None
    audit = MagicMock()
    notifications = MagicMock()

    with pytest.raises(HTTPException) as refused:
        asyncio.run(handle_deploy_request_response(
            contract_id='c1', request=MagicMock(), db=MagicMock(), audit_manager=audit,
            current_user=SimpleNamespace(email='e@x.com', username='e'),
            notifications=notifications,
            payload=HandleDeployPayload(decision='approve'), manager=manager, _=True,
        ))

    assert refused.value.status_code == 403
    assert refused.value.detail['code'] == 'deploy_request_not_an_approver'
    manager.handle_deploy_response.assert_not_called()
    audit.log_action.assert_not_called()
    notifications.handle_actionable_notification.assert_not_called()
    notifications.create_notification.assert_not_called()
