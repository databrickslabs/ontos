"""Assets created by the schema importer start in their lifecycle's active stage (#1215).

The importer used to send ``status='active'``: an asset lifecycle whose
active-category stage has another key (``live``) refused the import. It now
sends no status, and the lifecycle service picks the default group's first
active stage, as for any asset created without one.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.controller import schema_import_manager as sim
from src.controller.lifecycle_service import lifecycle_service


@pytest.fixture(autouse=True)
def fresh_cache():
    lifecycle_service.invalidate()
    yield
    lifecycle_service.invalidate()


def _stage(key, category, order, initial=False):
    return {'key': key, 'label': key.title(), 'category': category, 'color': None,
            'order': order, 'is_initial': initial}


def _live_asset_group():
    """A default asset lifecycle whose active stage is ``live``."""
    return {
        'name': 'Certified tables', 'description': None, 'entity_type': 'asset',
        'is_default_for_type': True,
        'stages': [_stage('intake', 'draft', 0, True), _stage('live', 'active', 1)],
        'transitions': [{'from_key': 'intake', 'to_key': 'live'}],
    }


def test_the_system_asset_of_a_connection_is_created_without_a_status(monkeypatch):
    connection = SimpleNamespace(id=uuid.uuid4(), name='warehouse', system_asset_id=None)
    monkeypatch.setattr(sim.connections_repo, 'get', lambda db, cid: connection)
    monkeypatch.setattr(sim.asset_type_repo, 'get_by_name',
                        lambda db, name: SimpleNamespace(id=uuid.uuid4()))
    monkeypatch.setattr(sim.asset_repo, 'get_by_identity', lambda db, **kw: None)
    assets = MagicMock()
    assets.create_asset.return_value = SimpleNamespace(id=uuid.uuid4())
    manager = sim.SchemaImportManager(connections_manager=MagicMock(), assets_manager=assets)

    manager._resolve_system_asset(
        MagicMock(), connection.id, SimpleNamespace(connector_type='databricks'), 'u',
    )

    asset_in = assets.create_asset.call_args.kwargs['asset_in']
    assert asset_in.status is None


def test_an_asset_without_a_status_starts_in_the_active_stage_of_its_lifecycle(db_session):
    from src.controller.assets_manager import AssetsManager
    from src.db_models.assets import AssetTypeDb
    from src.models.assets import AssetCreate

    lifecycle_service.save_group(db_session, _live_asset_group(), 'admin')
    asset_type = AssetTypeDb(id=uuid.uuid4(), name=f'Type {uuid.uuid4().hex[:6]}')
    db_session.add(asset_type)
    db_session.commit()
    manager = AssetsManager()
    manager._update_search_index = lambda *a, **k: None

    created = manager.create_asset(
        db_session,
        asset_in=AssetCreate(name='orders', asset_type_id=str(asset_type.id), status=None),
        current_user_id='u',
    )

    assert created.status == 'live'
