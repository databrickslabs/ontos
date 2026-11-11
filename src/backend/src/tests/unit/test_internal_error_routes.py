"""The data product and data contract routes don't send database errors to the browser.

Both answer an unexpected failure with ``HTTPException(500, detail=f"...{e}")``.
With the app's exception handler, the response carries a generic message, the
code ``internal_error`` and an error id instead of the SQL text.
"""
from unittest.mock import MagicMock

import pytest
from sqlalchemy.exc import IntegrityError, ProgrammingError

from src.app import app
from src.common.manager_dependencies import get_audit_manager
from src.routes.data_contracts_routes import get_data_contracts_manager
from src.routes.data_product_routes import get_data_products_manager

UNDEFINED_COLUMN = (
    'column data_contracts.parent_contract_id does not exist\n'
    'LINE 1: SELECT data_contracts.id, data_contracts.parent_contract_id ...'
)
CHECK_VIOLATION = (
    'new row for relation "data_products" violates check constraint "leak_test"\n'
    "DETAIL:  Failing row contains (p-1, v1.0.0, DataProduct, draft, Secret Product)."
)


@pytest.fixture
def override():
    added = []

    def _override(dependency, manager):
        app.dependency_overrides[dependency] = lambda: manager
        added.append(dependency)

    yield _override
    for dependency in added:
        app.dependency_overrides.pop(dependency, None)


def _assert_generic(response):
    assert response.status_code == 500
    body = response.json()
    assert body['code'] == 'internal_error'
    assert body['params']['errorId'] in body['detail']
    for leaked in ('SELECT', 'INSERT', 'parent_contract_id', 'Secret Product', 'psycopg2'):
        assert leaked not in response.text


def test_listing_contracts_on_a_database_missing_a_column(client, override):
    manager = MagicMock()
    manager.list_contracts_from_db.side_effect = ProgrammingError(
        'SELECT data_contracts.id, data_contracts.parent_contract_id FROM data_contracts', {},
        Exception(UNDEFINED_COLUMN),
    )
    override(get_data_contracts_manager, manager)

    _assert_generic(client.get('/api/data-contracts'))


def test_creating_a_product_that_the_database_refuses(client, override):
    manager = MagicMock()
    manager.create_product.side_effect = IntegrityError(
        'INSERT INTO data_products (id, name) VALUES (%(id)s, %(name)s)',
        {'id': 'p-1', 'name': 'Secret Product'}, Exception(CHECK_VIOLATION),
    )
    override(get_data_products_manager, manager)
    override(get_audit_manager, MagicMock())

    _assert_generic(client.post('/api/data-products', json={
        'apiVersion': 'v1.0.0', 'kind': 'DataProduct', 'id': 'p-1', 'name': 'Secret Product', 'status': 'draft',
    }))
