"""AuditManager stores details holding UUIDs and datetimes instead of dropping the row."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from src.controller import audit_manager
from src.controller.audit_manager import AuditManager
from src.db_models.audit_log import AuditLogDb
from src.repositories.audit_log_repository import audit_log_repository

POLICY_ID = uuid.UUID('11111111-2222-3333-4444-555555555555')
WHEN = datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def manager(db_session, monkeypatch):
    @contextmanager
    def factory():
        yield db_session

    monkeypatch.setattr(audit_manager, 'get_session_factory', lambda: factory)
    # Skip __init__, which would reconfigure the audit file logger
    instance = AuditManager.__new__(AuditManager)
    instance.repository = audit_log_repository
    return instance


def _details():
    return {'policy_id': POLICY_ID, 'when': WHEN, 'name': 'Policy'}


def _assert_stored(db_session, action):
    row = db_session.query(AuditLogDb).filter(AuditLogDb.action == action).one()
    assert row.details == {
        'policy_id': str(POLICY_ID), 'when': WHEN.isoformat(), 'name': 'Policy',
    }


def test_log_action_stores_details_with_a_uuid_and_a_datetime(manager, db_session):
    manager.log_action(
        MagicMock(), username='alice', ip_address=None, feature='compliance',
        action='CREATE_POLICY', success=True, details=_details(),
    )

    _assert_stored(db_session, 'CREATE_POLICY')


def test_log_action_background_stores_details_with_a_uuid_and_a_datetime(manager, db_session):
    asyncio.run(manager.log_action_background(
        username='alice', ip_address=None, feature='compliance',
        action='CREATE_POLICY_BG', success=True, details=_details(),
    ))

    _assert_stored(db_session, 'CREATE_POLICY_BG')


def test_details_the_encoder_rejects_are_stored_as_text(manager, db_session):
    manager.log_action(
        MagicMock(), username='alice', ip_address=None, feature='compliance',
        action='CREATE_POLICY_BYTES', success=True, details={'raw': b'\xff'},
    )

    row = db_session.query(AuditLogDb).filter(AuditLogDb.action == 'CREATE_POLICY_BYTES').one()
    assert row.details == {'raw': str(b'\xff')}
