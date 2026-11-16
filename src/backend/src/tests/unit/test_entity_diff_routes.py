"""Version-diff routes: the read gate and family checks on ``/diff/{target_id}`` (PRD #1086).

Both ids must pass the same read rule as GET-by-id; a miss answers 404 with the
same body as a missing row, so the diff can't be used to probe for drafts.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from pathlib import Path

import pytest

from src.app import app
from src.common.authorization import PermissionChecker
from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb, SchemaPropertyDb
from src.routes.data_contracts_routes import contract_read_scope, get_data_contracts_manager


def _contract(db, family_id, version, *, status='active', draft_owner_id=None):
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='orders', version=version, status=status,
        version_family_id=family_id, draft_owner_id=draft_owner_id,
    )
    db.add(contract)
    db.flush()
    obj = SchemaObjectDb(id=str(uuid.uuid4()), contract_id=contract.id, name='orders',
                         logical_type='object')
    db.add(obj)
    db.flush()
    db.add(SchemaPropertyDb(id=str(uuid.uuid4()), object_id=obj.id, name='id',
                            logical_type='string', required=True))
    db.flush()
    return contract


def _scope(*, is_admin=False, email='reader@example.com'):
    return {'is_admin': is_admin, 'caller_email': email, 'caller_team_ids': set()}


@pytest.fixture
def diff_routes():
    """Let the feature-level permission pass on the diff routes; the read gate is under test."""
    permission_keys = []
    for route in app.routes:
        if '/diff/' not in getattr(route, 'path', ''):
            continue
        for dep in route.dependant.dependencies:
            if isinstance(dep.call, PermissionChecker):
                app.dependency_overrides[dep.call] = lambda: True
                permission_keys.append(dep.call)
    manager = DataContractsManager(data_dir=Path('/tmp'))
    app.dependency_overrides[get_data_contracts_manager] = lambda: manager
    yield
    for key in permission_keys:
        app.dependency_overrides.pop(key, None)
    app.dependency_overrides.pop(get_data_contracts_manager, None)
    app.dependency_overrides.pop(contract_read_scope, None)


def _as_caller(scope):
    app.dependency_overrides[contract_read_scope] = lambda: scope


class TestContractDiffReadGate:
    def test_reader_can_diff_two_published_versions(self, client, db_session, diff_routes):
        family = str(uuid.uuid4())
        v1 = _contract(db_session, family, '1.0.0')
        v2 = _contract(db_session, family, '1.0.1')
        _as_caller(_scope())

        resp = client.get(f'/api/data-contracts/{v1.id}/diff/{v2.id}')

        assert resp.status_code == 200, resp.text

    def test_reader_cannot_diff_an_unpublished_version_by_id(self, client, db_session, diff_routes):
        family = str(uuid.uuid4())
        v1 = _contract(db_session, family, '1.0.0')
        proposed = _contract(db_session, family, '1.1.0', status='proposed')
        _as_caller(_scope())

        resp = client.get(f'/api/data-contracts/{v1.id}/diff/{proposed.id}')

        assert resp.status_code == 404
        assert resp.json()['detail'] == 'Contract not found'

    def test_reader_cannot_diff_someone_elses_personal_draft(self, client, db_session, diff_routes):
        family = str(uuid.uuid4())
        v1 = _contract(db_session, family, '1.0.0')
        draft = _contract(db_session, family, '1.1.0', status='draft',
                          draft_owner_id='someone.else@example.com')
        _as_caller(_scope())

        resp = client.get(f'/api/data-contracts/{v1.id}/diff/{draft.id}')

        assert resp.status_code == 404

    def test_the_draft_owner_can_diff_their_own_draft(self, client, db_session, diff_routes):
        family = str(uuid.uuid4())
        v1 = _contract(db_session, family, '1.0.0')
        draft = _contract(db_session, family, '1.1.0', status='draft',
                          draft_owner_id='owner@example.com')
        _as_caller(_scope(email='owner@example.com'))

        resp = client.get(f'/api/data-contracts/{v1.id}/diff/{draft.id}')

        assert resp.status_code == 200, resp.text

    def test_admin_can_diff_an_unpublished_version(self, client, db_session, diff_routes):
        family = str(uuid.uuid4())
        v1 = _contract(db_session, family, '1.0.0')
        proposed = _contract(db_session, family, '1.1.0', status='proposed')
        _as_caller(_scope(is_admin=True))

        resp = client.get(f'/api/data-contracts/{v1.id}/diff/{proposed.id}')

        assert resp.status_code == 200, resp.text


class TestContractDiffFamilies:
    def test_versions_from_different_families_are_rejected(self, client, db_session, diff_routes):
        a = _contract(db_session, str(uuid.uuid4()), '1.0.0')
        b = _contract(db_session, str(uuid.uuid4()), '1.0.0')
        _as_caller(_scope())

        resp = client.get(f'/api/data-contracts/{a.id}/diff/{b.id}')

        assert resp.status_code == 400
        assert 'different version families' in resp.json()['detail']


def _product(db, family_id, version, *, status='active'):
    from src.models.data_products import DataProductCreate
    from src.repositories.data_products_repository import data_product_repo

    product = data_product_repo.create(db=db, obj_in=DataProductCreate(
        id=str(uuid.uuid4()), apiVersion='v1.0.0', kind='DataProduct', name='orders',
        version=version, status=status, version_family_id=family_id,
        outputPorts=[{'name': 'orders_table', 'version': '1.0.0', 'contractId': 'c1',
                      'type': 'table', 'server': {'location': 's3://lake/orders/v1', 'format': 'delta'},
                      'containsPii': False}],
    ))
    db.commit()
    return product


@pytest.fixture
def product_manager(db_session):
    from unittest.mock import MagicMock

    from databricks.sdk import WorkspaceClient

    from src.controller.data_products_manager import DataProductsManager
    from src.routes.data_product_routes import get_data_products_manager

    manager = DataProductsManager(db=db_session, ws_client=MagicMock(spec=WorkspaceClient))
    app.dependency_overrides[get_data_products_manager] = lambda: manager
    yield manager
    app.dependency_overrides.pop(get_data_products_manager, None)


class TestProductDiffRoutes:
    def test_product_diff_of_two_published_versions(self, client, db_session, diff_routes, product_manager):
        family = str(uuid.uuid4())
        v1 = _product(db_session, family, '1.0.0')
        v2 = _product(db_session, family, '1.0.1')

        resp = client.get(f'/api/data-products/{v1.id}/diff/{v2.id}')

        assert resp.status_code == 200, resp.text

    def test_product_diff_hides_an_unpublished_version(self, client, db_session, diff_routes, product_manager):
        family = str(uuid.uuid4())
        v1 = _product(db_session, family, '1.0.0')
        proposed = _product(db_session, family, '1.1.0', status='proposed')

        resp = client.get(f'/api/data-products/{v1.id}/diff/{proposed.id}')

        assert resp.status_code == 404
        assert resp.json()['detail'] == 'Data product not found'

    def test_product_versions_from_different_families_are_rejected(self, client, db_session, diff_routes, product_manager):
        a = _product(db_session, str(uuid.uuid4()), '1.0.0')
        b = _product(db_session, str(uuid.uuid4()), '1.0.0')

        resp = client.get(f'/api/data-products/{a.id}/diff/{b.id}')

        assert resp.status_code == 400
        assert 'different version families' in resp.json()['detail']


class TestDiffSizeCap:
    def test_an_oversized_version_answers_413(self, client, db_session, diff_routes, monkeypatch):
        from src.common.entity_diff import engine

        monkeypatch.setattr(engine, "MAX_DIFF_NODES", 5)
        family = str(uuid.uuid4())
        v1 = _contract(db_session, family, '1.0.0')
        v2 = _contract(db_session, family, '1.0.1')
        _as_caller(_scope())

        resp = client.get(f'/api/data-contracts/{v1.id}/diff/{v2.id}')

        assert resp.status_code == 413
