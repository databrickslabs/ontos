"""Deleting an asset removes what is stored for it (#1343).

Both delete paths (``DELETE /api/assets/{id}`` and the cascade delete) remove
the asset's domain associations, notes, links, documents (rows and volume
files), shared-asset attachments and cost items. Rows of other assets, and
rows of other entity types with the same ``entity_id`` text, stay.
"""
import json
import uuid
from datetime import date

import pytest

from src.controller import assets_manager as assets_manager_module
from src.db_models.assets import AssetDb, AssetRelationshipDb, AssetTypeDb
from src.db_models.change_log import ChangeLogDb
from src.db_models.costs import CostItemDb
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.metadata import (
    DocumentMetadataDb, LinkMetadataDb, MetadataAttachmentDb, RichTextMetadataDb,
)

MODELS = (
    RichTextMetadataDb, LinkMetadataDb, DocumentMetadataDb, MetadataAttachmentDb, CostItemDb,
    EntityDomainAssociationDb,
)


@pytest.fixture
def asset_type(db_session):
    row = AssetTypeDb(name=f'Type {uuid.uuid4().hex[:8]}', category='data')
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def make_asset(db_session, asset_type):
    def _make(name: str) -> AssetDb:
        row = AssetDb(name=name, asset_type_id=asset_type.id, platform='databricks')
        db_session.add(row)
        db_session.flush()
        return row
    return _make


def _seed(db, entity_type: str, entity_id: str) -> str:
    """One row of each kind for an entity; returns the volume path of its document."""
    path = f'/Volumes/c/s/v/uploads/{entity_type}/{entity_id}/{uuid.uuid4().hex}.txt'
    db.add_all([
        RichTextMetadataDb(entity_type=entity_type, entity_id=entity_id, title='Note',
                           content_markdown='Body'),
        LinkMetadataDb(entity_type=entity_type, entity_id=entity_id, title='Link',
                       url='https://example.com'),
        DocumentMetadataDb(entity_type=entity_type, entity_id=entity_id, title='Doc',
                           original_filename='a.txt', storage_path=path),
        MetadataAttachmentDb(entity_type=entity_type, entity_id=entity_id,
                             asset_type='rich_text', asset_id=str(uuid.uuid4())),
        CostItemDb(entity_type=entity_type, entity_id=entity_id, cost_center='OTHER',
                   amount_cents=100, currency='USD', start_month=date(2026, 1, 1)),
        EntityDomainAssociationDb(domain_id=str(uuid.uuid4()), entity_type=entity_type,
                                  entity_id=entity_id, is_primary=True),
    ])
    db.flush()
    return path


def _counts(db, entity_type: str, entity_id: str) -> dict:
    return {
        model.__name__: db.query(model).filter(
            model.entity_type == entity_type, model.entity_id == entity_id,
        ).count()
        for model in MODELS
    }


NONE_LEFT = {model.__name__: 0 for model in MODELS}
ONE_EACH = {model.__name__: 1 for model in MODELS}
REMOVED = {
    'domains': 1, 'rich_texts': 1, 'links': 1, 'documents': 1, 'attachments': 1,
    'cost_items': 1,
}


def _deleted_details(db, asset_id) -> dict:
    entry = db.query(ChangeLogDb).filter(
        ChangeLogDb.entity_type == 'asset', ChangeLogDb.entity_id == str(asset_id),
        ChangeLogDb.action == 'deleted',
    ).one()
    return json.loads(entry.details_json)


@pytest.fixture
def files(mock_workspace_client):
    """The volume: the app's workspace client is the conftest's mock."""
    mock_workspace_client.files.delete.reset_mock()
    mock_workspace_client.files.delete.side_effect = None
    return mock_workspace_client.files


def _deleted_paths(files) -> set:
    return {call.args[0] for call in files.delete.call_args_list}


def test_delete_removes_the_asset_data_and_files(client, db_session, make_asset, files):
    asset, other = make_asset('orders'), make_asset('customers')
    path = _seed(db_session, 'asset', str(asset.id))
    _seed(db_session, 'asset', str(other.id))
    # Another entity type with the same id text.
    _seed(db_session, 'data_product', str(asset.id))

    response = client.delete(f'/api/assets/{asset.id}')

    assert response.status_code == 200, response.text
    assert _counts(db_session, 'asset', str(asset.id)) == NONE_LEFT
    assert _counts(db_session, 'asset', str(other.id)) == ONE_EACH
    assert _counts(db_session, 'data_product', str(asset.id)) == ONE_EACH
    assert _deleted_paths(files) == {path}
    assert _deleted_details(db_session, asset.id)['removed'] == REMOVED


def test_a_failing_file_delete_does_not_stop_the_asset_delete(
        client, db_session, make_asset, files):
    asset = make_asset('orders')
    _seed(db_session, 'asset', str(asset.id))
    files.delete.side_effect = RuntimeError('volume unavailable')

    response = client.delete(f'/api/assets/{asset.id}')

    assert response.status_code == 200, response.text
    assert db_session.query(AssetDb).filter(AssetDb.id == asset.id).count() == 0
    assert _counts(db_session, 'asset', str(asset.id)) == NONE_LEFT
    files.delete.assert_called_once()


def test_cascade_delete_removes_the_data_of_every_asset(client, db_session, make_asset, files):
    parent, child, other = make_asset('schema'), make_asset('table'), make_asset('dashboard')
    db_session.add(AssetRelationshipDb(
        source_asset_id=parent.id, target_asset_id=child.id, relationship_type='hasTable',
    ))
    paths = {_seed(db_session, 'asset', str(a.id)) for a in (parent, child)}
    _seed(db_session, 'asset', str(other.id))
    _seed(db_session, 'data_contract', str(child.id))

    response = client.post('/api/assets/cascade-delete',
                           json={'asset_ids': [str(parent.id), str(child.id)]})

    assert response.status_code == 200, response.text
    assert len(response.json()['deleted']) == 2, response.text
    for asset in (parent, child):
        # Domain associations included: the cascade path didn't remove them before.
        assert _counts(db_session, 'asset', str(asset.id)) == NONE_LEFT
        assert _deleted_details(db_session, asset.id)['removed'] == REMOVED
    assert _counts(db_session, 'asset', str(other.id)) == ONE_EACH
    assert _counts(db_session, 'data_contract', str(child.id)) == ONE_EACH
    assert _deleted_paths(files) == paths


# --- The files go only once the transaction commits -------------------------
# A rollback of the request's session also rolls back the test's own data (see
# test_asset_metadata_access.py), so these tests check the volume calls only.

@pytest.fixture
def change_log_rolls_back_for(monkeypatch):
    """The change-log write of the given assets fails and rolls the session back.

    It is the commit point of each deleted asset (``log_change`` commits).
    """
    failing = set()
    real = assets_manager_module.change_log_manager.log_change_with_details

    def log_change_with_details(db, **kwargs):
        if kwargs.get('entity_id') in failing:
            db.rollback()
            raise RuntimeError('commit failed')
        return real(db, **kwargs)

    monkeypatch.setattr(assets_manager_module.change_log_manager, 'log_change_with_details',
                        log_change_with_details)
    return failing


def test_a_rolled_back_delete_keeps_the_files(
        client, db_session, make_asset, files, change_log_rolls_back_for):
    asset = make_asset('orders')
    _seed(db_session, 'asset', str(asset.id))
    change_log_rolls_back_for.add(str(asset.id))

    client.delete(f'/api/assets/{asset.id}')

    files.delete.assert_not_called()


def test_a_cascade_that_rolls_back_a_later_asset_keeps_its_files(
        client, db_session, make_asset, files, change_log_rolls_back_for):
    """The first asset is committed (its files go); the second rolls back (its files stay)."""
    first, second = make_asset('first'), make_asset('second')
    first_path = _seed(db_session, 'asset', str(first.id))
    _seed(db_session, 'asset', str(second.id))
    change_log_rolls_back_for.add(str(second.id))

    client.post('/api/assets/cascade-delete',
                json={'asset_ids': [str(first.id), str(second.id)]})

    assert _deleted_paths(files) == {first_path}
