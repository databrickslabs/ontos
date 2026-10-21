"""Role lookups survive a database connection closed while the app was idle (#949).

SettingsManager's session lives as long as the app. When the database drops
its connection, the first role query fails; list_app_roles used to return []
then, and every permission check answered 403 until the next request.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from src.common.config import Settings
from src.controller.settings_manager import SettingsManager


def _closed_connection():
    return DBAPIError(
        'SELECT ...', {}, Exception('server closed the connection unexpectedly'),
        connection_invalidated=True,
    )


# A stored role whose defaults are already backfilled.
_ADMIN = SimpleNamespace(
    name='Admin', home_sections='["discovery"]', approval_privileges='{"CONTRACTS": true}',
)


@pytest.fixture
def manager():
    manager = SettingsManager(db=MagicMock(), settings=MagicMock(spec=Settings),
                              workspace_client=MagicMock())
    manager._map_db_to_api = lambda role_db: role_db.name
    return manager


def test_a_closed_connection_is_retried_once(manager):
    with patch.object(manager.app_role_repo, 'get_all_roles',
                      side_effect=[_closed_connection(), [_ADMIN]]) as get_all:
        roles = manager.list_app_roles()

    assert roles == ['Admin']
    assert get_all.call_count == 2
    manager._db.rollback.assert_called_once()


def test_a_connection_that_stays_closed_raises(manager):
    with patch.object(manager.app_role_repo, 'get_all_roles',
                      side_effect=[_closed_connection(), _closed_connection()]):
        with pytest.raises(DBAPIError):
            manager.list_app_roles()


def test_other_database_errors_raise_instead_of_returning_no_roles(manager):
    with patch.object(manager.app_role_repo, 'get_all_roles',
                      side_effect=SQLAlchemyError('boom')) as get_all:
        with pytest.raises(SQLAlchemyError):
            manager.list_app_roles()

    assert get_all.call_count == 1
