"""Approval flows find the requester in the change log.

Four request / approval flows (three in DataContractsManager, one in
DataProductsManager) call ``change_log_manager.get_changes_for_entity`` and
read ``change.details``; neither existed, the AttributeError was swallowed,
and the requester was never told about the decision. The behavioural test
covers one flow, the approved contract publication. The other three share the
same accessor, which is tested directly (ordering, parsed details, and the
``action`` filter that finds an old request on an entity with a long history).
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

from src.controller.change_log_manager import change_log_manager
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.change_log import ChangeLogDb
from src.db_models.data_contracts import DataContractDb


def _log(db, entity_id, action, details, days_ago=0):
    entry = change_log_manager.log_change_with_details(
        db, entity_type='data_contract', entity_id=entity_id, action=action,
        username='alice', details=details,
    )
    entry.timestamp = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.flush()


def test_changes_come_newest_first_with_parsed_details(db_session):
    _log(db_session, 'c1', 'publish_requested', {'requester_email': 'old@x'}, days_ago=2)
    _log(db_session, 'c1', 'publish_requested', {'requester_email': 'new@x'}, days_ago=1)

    changes = change_log_manager.get_changes_for_entity(db_session, 'data_contract', 'c1')

    assert [c.details['requester_email'] for c in changes] == ['new@x', 'old@x']


def test_the_action_filter_finds_an_old_request_behind_many_newer_entries(db_session):
    _log(db_session, 'c2', 'publish_requested', {'requester_email': 'old@x'}, days_ago=30)
    for i in range(120):
        _log(db_session, 'c2', 'comment_added', {'n': i}, days_ago=1)

    # The default limit of 100 only sees the newer entries ...
    unfiltered = change_log_manager.get_changes_for_entity(db_session, 'data_contract', 'c2')
    assert not any(c.action == 'publish_requested' for c in unfiltered)

    # ... the filter is applied in SQL, so the old request is still found.
    found = change_log_manager.get_changes_for_entity(
        db_session, 'data_contract', 'c2', action='publish_requested', limit=1,
    )
    assert [c.details['requester_email'] for c in found] == ['old@x']


def test_an_approved_publish_request_finds_a_requester_behind_many_newer_entries(db_session):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status='approved',
        version_family_id=str(uuid.uuid4()), publication_scope='none',
    )
    db_session.add(contract)
    db_session.flush()
    _log(db_session, contract.id, 'publish_requested',
         {'requester_email': 'requester@example.com', 'requested_scope': 'domain'}, days_ago=30)
    for i in range(120):
        _log(db_session, contract.id, 'comment_added', {'n': i}, days_ago=1)
    notifications = MagicMock()

    DataContractsManager(data_dir=Path('/tmp')).handle_publish_response(
        db_session, notifications, contract.id, 'approver@example.com', 'approve',
    )

    recipients = [c.kwargs['notification'].recipient
                  for c in notifications.create_notification.call_args_list]
    assert 'requester@example.com' in recipients


def test_details_tolerates_missing_or_invalid_json():
    assert ChangeLogDb(details_json=None).details == {}
    assert ChangeLogDb(details_json='not json').details == {}
    assert ChangeLogDb(details_json='[1, 2]').details == {}


def test_an_approved_publish_request_notifies_the_requester(db_session):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='c', version='1.0.0', status='approved',
        version_family_id=str(uuid.uuid4()), publication_scope='none',
    )
    db_session.add(contract)
    db_session.flush()
    _log(db_session, contract.id, 'publish_requested',
         {'requester_email': 'requester@example.com', 'requested_scope': 'domain'})
    notifications = MagicMock()

    DataContractsManager(data_dir=Path('/tmp')).handle_publish_response(
        db_session, notifications, contract.id, 'approver@example.com', 'approve',
    )

    recipients = [c.kwargs['notification'].recipient
                  for c in notifications.create_notification.call_args_list]
    assert 'requester@example.com' in recipients
    db_session.refresh(contract)
    assert contract.publication_scope == 'domain'
