"""Asset tags live on the shared tag store (entity_tag_associations, entity_type 'asset') (#1422).

Create, update, the search index, delete and the CSV round trip read and write the
associations; the ``assets.tags`` column is gone. An unknown tag namespace is refused
(422) before anything is written, never a 500.
"""
import uuid

import pytest

from src.common.errors import ValidationError
from src.controller.asset_bulk_manager import AssetBulkManager
from src.controller.assets_manager import AssetsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.tags import EntityTagAssociationDb, TagDb, TagNamespaceDb
from src.models.assets import AssetCreate, AssetUpdate
from src.models.tags import AssignedTag


@pytest.fixture
def asset_type(db_session):
    row = AssetTypeDb(name=f'Type {uuid.uuid4().hex[:8]}', category='data')
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def default_namespace(db_session):
    row = TagNamespaceDb(name='default', description='Default system namespace')
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def governance(db_session):
    row = TagNamespaceDb(name='governance', description='Governance')
    db_session.add(row)
    db_session.flush()
    return row


def _tag(db, namespace, name, possible_values=None):
    row = TagDb(name=name, namespace_id=namespace.id, status='active', possible_values=possible_values)
    db.add(row)
    db.flush()
    return row


def _names(tags):
    return {(t.namespace_name, t.tag_name): t.assigned_value for t in tags}


def _associations(db, asset_id):
    return db.query(EntityTagAssociationDb).filter_by(entity_type='asset', entity_id=str(asset_id)).all()


def test_create_assigns_tags_and_values_through_the_shared_store(db_session, asset_type, default_namespace, governance):
    _tag(db_session, default_namespace, 'pii')
    _tag(db_session, governance, 'classified')
    manager = AssetsManager()

    read = manager.create_asset(
        db_session,
        asset_in=AssetCreate(
            name='customers', asset_type_id=asset_type.id,
            tags=[{'tag_fqn': 'pii'}, {'tag_fqn': 'governance/classified', 'assigned_value': 'high'}],
        ),
        current_user_id='alice@example.com',
    )

    assert all(isinstance(t, AssignedTag) for t in read.tags)
    assert _names(read.tags) == {('default', 'pii'): None, ('governance', 'classified'): 'high'}
    assert {a.entity_type for a in _associations(db_session, read.id)} == {'asset'}


def test_create_refuses_an_unknown_namespace_before_writing(db_session, asset_type):
    manager = AssetsManager()

    with pytest.raises(ValidationError, match="nosuch"):
        manager.create_asset(
            db_session,
            asset_in=AssetCreate(name='orphan', asset_type_id=asset_type.id, tags=[{'tag_fqn': 'nosuch/x'}]),
            current_user_id='alice@example.com',
        )
    assert db_session.query(AssetDb).filter_by(name='orphan').count() == 0


def test_update_replaces_tags_and_keeps_them_when_omitted(db_session, asset_type, default_namespace):
    _tag(db_session, default_namespace, 'pii')
    _tag(db_session, default_namespace, 'lookup')
    manager = AssetsManager()
    read = manager.create_asset(
        db_session,
        asset_in=AssetCreate(name='t', asset_type_id=asset_type.id, tags=[{'tag_fqn': 'pii'}]),
        current_user_id='alice@example.com',
    )

    kept = manager.update_asset(db_session, asset_id=read.id,
                                asset_in=AssetUpdate(description='new'), current_user_id='alice@example.com')
    assert _names(kept.tags) == {('default', 'pii'): None}

    replaced = manager.update_asset(
        db_session, asset_id=read.id,
        asset_in=AssetUpdate(tags=[{'tag_fqn': 'lookup'}]), current_user_id='alice@example.com',
    )
    assert _names(replaced.tags) == {('default', 'lookup'): None}
    assert len(_associations(db_session, read.id)) == 1


def test_search_index_item_carries_the_tag_names(db_session, asset_type, default_namespace):
    _tag(db_session, default_namespace, 'pii')
    manager = AssetsManager()
    read = manager.create_asset(
        db_session,
        asset_in=AssetCreate(name='indexed', asset_type_id=asset_type.id, tags=[{'tag_fqn': 'pii'}]),
        current_user_id='alice@example.com',
    )
    db_asset = db_session.get(AssetDb, read.id)

    item = manager._build_search_index_item(db_asset)

    assert 'pii' in item.tags


def test_delete_removes_the_asset_tag_associations(db_session, asset_type, default_namespace):
    _tag(db_session, default_namespace, 'pii')
    manager = AssetsManager()
    read = manager.create_asset(
        db_session,
        asset_in=AssetCreate(name='doomed', asset_type_id=asset_type.id, tags=[{'tag_fqn': 'pii'}]),
        current_user_id='alice@example.com',
    )
    assert len(_associations(db_session, read.id)) == 1

    manager._remove_asset_with_data(db_session, read.id)
    db_session.flush()

    assert _associations(db_session, read.id) == []


def test_csv_round_trip_keeps_tags_and_values(db_session, asset_type, default_namespace, governance):
    _tag(db_session, default_namespace, 'pii')
    _tag(db_session, governance, 'classified')
    manager = AssetsManager()
    read = manager.create_asset(
        db_session,
        asset_in=AssetCreate(
            name='round', asset_type_id=asset_type.id,
            tags=[{'tag_fqn': 'pii'}, {'tag_fqn': 'governance/classified', 'assigned_value': 'high'}],
        ),
        current_user_id='alice@example.com',
    )
    bulk = AssetBulkManager()

    exported, _, _ = bulk.export_assets(db_session, fmt='csv', asset_ids=[read.id])
    text = exported.decode('utf-8')
    assert 'pii;governance/classified=high' in text

    # Re-import the same file: the update path keeps what the file says
    result = bulk.execute_import(
        db_session, file_bytes=exported.replace(b'pii;governance/classified=high', b'governance/classified=low'),
        filename='assets.csv', current_user_id='alice@example.com',
    )
    assert result.errors == 0, result.error_messages
    db_session.flush()
    after = AssetsManager().get_asset(db_session, read.id)
    assert _names(after.tags) == {('governance', 'classified'): 'low'}


def test_csv_import_refuses_an_unknown_namespace_for_the_row(db_session, asset_type):
    csv_bytes = (
        "name,asset_type,status,tags\n"
        f"bad,{asset_type.name},draft,nosuch/x\n"
    ).encode('utf-8')

    result = AssetBulkManager().execute_import(
        db_session, file_bytes=csv_bytes, filename='assets.csv', current_user_id='alice@example.com',
    )

    assert result.errors == 1
    assert result.created == 0
    assert db_session.query(AssetDb).filter_by(name='bad').count() == 0
    assert 'nosuch' in result.items[0].message


def test_create_refuses_a_tag_without_a_name(db_session, asset_type, default_namespace):
    _tag(db_session, default_namespace, 'pii')

    with pytest.raises(ValidationError, match="default/"):
        AssetsManager().create_asset(
            db_session,
            asset_in=AssetCreate(name='nameless', asset_type_id=asset_type.id, tags=[{'tag_fqn': 'default/'}]),
            current_user_id='alice@example.com',
        )
    assert db_session.query(AssetDb).filter_by(name='nameless').count() == 0


def test_csv_refuses_a_tag_without_a_name(db_session, asset_type):
    csv_bytes = f"name,asset_type,status,tags\nnameless,{asset_type.name},draft,default/\n".encode('utf-8')

    result = AssetBulkManager().execute_import(
        db_session, file_bytes=csv_bytes, filename='assets.csv', current_user_id='alice@example.com',
    )

    assert result.errors == 1
    assert db_session.query(AssetDb).filter_by(name='nameless').count() == 0


def test_csv_refuses_a_value_outside_the_possible_values_before_writing(db_session, asset_type, default_namespace):
    _tag(db_session, default_namespace, 'lookup', possible_values=['gold'])
    csv_bytes = f"name,asset_type,status,tags\ncheck,{asset_type.name},draft,lookup=silver\n".encode('utf-8')

    result = AssetBulkManager().execute_import(
        db_session, file_bytes=csv_bytes, filename='assets.csv', current_user_id='alice@example.com',
    )

    assert result.errors == 1
    assert 'silver' in result.items[0].message
    assert db_session.query(AssetDb).filter_by(name='check').count() == 0
