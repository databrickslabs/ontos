"""POST /api/self-service/deploy/{contract_id} applies the sandbox allowlist.

The workspace client is the shared mock: a deploy that is refused must not
create (or even look up) any catalog, schema or table.

A refused request rolls back the test's transaction (``get_db`` rolls back on
any error), so the audit entry is checked on the call, not in the database,
and each test sends at most one refused request, as its last one.
"""
import pytest
from databricks.sdk.errors import NotFound

from src.controller.audit_manager import AuditManager
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
from src.routes import self_service_routes


@pytest.fixture
def sandbox_settings(monkeypatch, test_settings):
    """Allowlist: catalogs starting with ``user_`` or named ``shared_dev``, schema ``sandbox``."""
    settings = test_settings.model_copy(update={
        'sandbox_enforce_allowlist': True,
        'sandbox_allowed_catalog_prefixes': ['user_'],
        'sandbox_allowed_catalogs': ['shared_dev'],
        'sandbox_allowed_schemas': ['sandbox'],
    })
    monkeypatch.setattr(self_service_routes, 'get_settings', lambda: settings)
    return settings


@pytest.fixture
def ws(mock_workspace_client):
    """Nothing exists yet, so every ensure/create call reaches ``create``."""
    mock_workspace_client.catalogs.get.side_effect = NotFound('no catalog')
    mock_workspace_client.schemas.get.side_effect = NotFound('no schema')
    mock_workspace_client.tables.get.side_effect = NotFound('no table')
    return mock_workspace_client


def _contract(db_session, *objects):
    """A contract with one schema object per ``(name, physical_name)``."""
    contract = DataContractDb(name='Deploy Test', version='1.0.0', status='draft')
    db_session.add(contract)
    db_session.flush()
    for name, physical_name in objects:
        db_session.add(SchemaObjectDb(
            contract_id=contract.id, name=name, physical_name=physical_name,
        ))
    db_session.flush()
    return contract.id


def _assert_nothing_created(ws):
    ws.catalogs.get.assert_not_called()
    ws.catalogs.create.assert_not_called()
    ws.schemas.get.assert_not_called()
    ws.schemas.create.assert_not_called()
    ws.tables.create.assert_not_called()


@pytest.fixture
def audit_calls(monkeypatch):
    """The keyword arguments of every ``AuditManager.log_action`` call."""
    calls = []
    original = AuditManager.log_action

    def _spy(self, db, **kwargs):
        calls.append(kwargs)
        return original(self, db, **kwargs)

    monkeypatch.setattr(AuditManager, 'log_action', _spy)
    return calls


def test_deploy_to_allowed_catalog_creates_tables(client, db_session, sandbox_settings, ws):
    contract_id = _contract(
        db_session,
        ('orders', 'user_alice.sandbox.orders'),
        ('items', 'shared_dev.sandbox.items'),
    )

    response = client.post(f'/api/self-service/deploy/{contract_id}', json={})

    assert response.status_code == 200, response.text
    assert response.json() == {
        'created': ['user_alice.sandbox.orders', 'shared_dev.sandbox.items'],
    }
    assert ws.tables.create.call_count == 2
    created_catalogs = [c.kwargs['name'] for c in ws.catalogs.create.call_args_list]
    assert created_catalogs == ['user_alice', 'shared_dev']


def test_deploy_to_refused_catalog_creates_nothing(
    client, db_session, sandbox_settings, ws, audit_calls,
):
    contract_id = _contract(db_session, ('orders', 'prod.sales.orders'))

    response = client.post(f'/api/self-service/deploy/{contract_id}', json={})

    assert response.status_code == 403, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'sandbox_location_not_allowed'
    assert detail['params'] == {'catalog': 'prod', 'schema': 'sales'}
    assert detail['message']
    _assert_nothing_created(ws)

    deploys = [c for c in audit_calls if c['action'] == 'DEPLOY']
    assert len(deploys) == 1
    assert deploys[0]['feature'] == 'self-service'
    assert deploys[0]['success'] is False
    assert deploys[0]['details']['exception']['status_code'] == 403
    assert 'created_tables' not in deploys[0]['details']


def test_allowed_catalog_with_schema_outside_allowlist_is_refused(
    client, db_session, sandbox_settings, ws,
):
    contract_id = _contract(db_session, ('orders', 'user_alice.finance.orders'))

    response = client.post(f'/api/self-service/deploy/{contract_id}', json={})

    assert response.status_code == 403, response.text
    assert response.json()['detail']['params'] == {'catalog': 'user_alice', 'schema': 'finance'}
    _assert_nothing_created(ws)


def test_mixed_objects_are_refused_as_a_whole(client, db_session, sandbox_settings, ws):
    # The allowed object comes first: it must not be created either.
    contract_id = _contract(
        db_session,
        ('orders', 'user_alice.sandbox.orders'),
        ('ledger', 'finance_prod.sandbox.ledger'),
    )

    response = client.post(f'/api/self-service/deploy/{contract_id}', json={})

    assert response.status_code == 403, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'sandbox_location_not_allowed'
    assert detail['params'] == {'catalog': 'finance_prod', 'schema': 'sandbox'}
    _assert_nothing_created(ws)


def test_defaults_path_to_allowed_catalog_deploys(client, db_session, sandbox_settings, ws):
    contract_id = _contract(db_session, ('orders', None))

    response = client.post(
        f'/api/self-service/deploy/{contract_id}',
        json={'defaultCatalog': 'user_alice', 'defaultSchema': 'sandbox'},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {'created': ['user_alice.sandbox.orders']}
    ws.tables.create.assert_called_once()


def test_defaults_path_to_refused_catalog_creates_nothing(
    client, db_session, sandbox_settings, ws,
):
    contract_id = _contract(db_session, ('orders', None))

    response = client.post(
        f'/api/self-service/deploy/{contract_id}',
        json={'defaultCatalog': 'main', 'defaultSchema': 'sandbox'},
    )

    assert response.status_code == 403, response.text
    detail = response.json()['detail']
    assert detail['code'] == 'sandbox_location_not_allowed'
    assert detail['params'] == {'catalog': 'main', 'schema': 'sandbox'}
    _assert_nothing_created(ws)


def test_empty_allowlist_refuses_every_catalog(client, db_session, sandbox_settings, ws):
    # Same as /self-service/create: enforcement on with no entries allows nothing.
    sandbox_settings.sandbox_allowed_catalog_prefixes = []
    sandbox_settings.sandbox_allowed_catalogs = []
    contract_id = _contract(db_session, ('orders', 'user_alice.sandbox.orders'))

    response = client.post(f'/api/self-service/deploy/{contract_id}', json={})

    assert response.status_code == 403, response.text
    _assert_nothing_created(ws)


def test_enforcement_off_allows_any_catalog(client, db_session, sandbox_settings, ws):
    sandbox_settings.sandbox_enforce_allowlist = False
    contract_id = _contract(db_session, ('orders', 'prod.sales.orders'))

    response = client.post(f'/api/self-service/deploy/{contract_id}', json={})

    assert response.status_code == 200, response.text
    assert response.json() == {'created': ['prod.sales.orders']}
