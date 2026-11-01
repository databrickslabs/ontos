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
