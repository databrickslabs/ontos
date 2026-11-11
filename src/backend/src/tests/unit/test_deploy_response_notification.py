"""A deploy approval that can't start the deployment doesn't put the exception text
in the notification to the requester."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.controller.data_contracts_manager import DataContractsManager

_SECRET = "SELECT * FROM secret_table WHERE token='abc123'"


def _approve_with_failing_deployment(caplog):
    manager = DataContractsManager(data_dir=Path('/tmp'))
    notifications = MagicMock()
    jobs = MagicMock()
    jobs.trigger_deployment.side_effect = RuntimeError(_SECRET)
    changes = MagicMock()
    changes.get_changes_for_entity.return_value = [
        SimpleNamespace(action='deploy_requested', details={'requester_email': 'req@example.com'}),
    ]
    contract = SimpleNamespace(id='c-1', name='Orders')
    with patch('src.controller.data_contracts_manager.data_contract_repo.get',
               return_value=contract), \
            patch('src.controller.change_log_manager.change_log_manager', changes), \
            caplog.at_level(logging.ERROR):
        result = manager.handle_deploy_response(
            db=MagicMock(), notifications_manager=notifications, jobs_manager=jobs,
            contract_id='c-1', approver_email='boss@example.com', decision='approve',
            execute_deployment=True,
        )
    return result, notifications.create_notification.call_args.kwargs['notification']


def test_failed_deployment_start_keeps_the_exception_text_out_of_the_notification(caplog):
    result, notification = _approve_with_failing_deployment(caplog)

    assert _SECRET not in notification.description
    assert 'could not be started' in notification.description
    assert 'error id' in notification.description
    assert 'job_id' not in result


def test_failed_deployment_start_is_logged_with_the_same_error_id(caplog):
    _, notification = _approve_with_failing_deployment(caplog)

    error_id = notification.description.split('error id ')[1].rstrip(').')
    assert any(error_id in r.getMessage() and _SECRET in r.getMessage() for r in caplog.records)
