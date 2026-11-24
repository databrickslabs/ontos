"""The stored-name lookup of the approval notices (#1687 review).

On Postgres a failed SELECT aborts the whole transaction: every later statement of the
step fails with InFailedSqlTransaction until a rollback. The lookup therefore runs in a
savepoint, so a failure rolls back only that.
"""
from unittest.mock import MagicMock

from sqlalchemy.exc import OperationalError

from src.common.workflow_executor import _server_entity_name


def _failing_session():
    session = MagicMock()
    session.query.side_effect = OperationalError('SELECT', {}, Exception('boom'))
    return session


def test_a_failed_lookup_is_rolled_back_to_its_savepoint():
    session = _failing_session()

    assert _server_entity_name(session, 'data_product', 'p1') is None

    session.begin_nested.assert_called_once_with()
    # The savepoint's context saw the error, so it rolled back
    exit_args = session.begin_nested.return_value.__exit__.call_args.args
    assert exit_args[0] is OperationalError


def test_a_found_name_is_returned_from_inside_the_savepoint():
    session = MagicMock()
    session.query.return_value.filter.return_value.scalar.return_value = 'Orders'

    assert _server_entity_name(session, 'data_product', 'p1') == 'Orders'
    session.begin_nested.assert_called_once_with()
