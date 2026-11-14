"""Asset writes are searchable without a rebuild, and a bulk import that does not
commit leaves nothing in the search index.

Real AssetsManager, bulk manager, SearchManager and DB session; only the
authorization manager and the ontology are stubbed.
"""
import uuid
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.common.errors import ValidationError
from src.common.features import FeatureAccessLevel
from src.controller.asset_bulk_manager import AssetBulkManager
from src.controller.assets_manager import AssetsManager
from src.controller.search_manager import SearchManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.assets import AssetCreate, AssetStatus, AssetUpdate
from src.models.users import UserInfo

USER = UserInfo(
    username="tester", email="tester@example.com", user="tester", ip=None, groups=["users"],
)


@pytest.fixture
def asset_type(db_session):
    row = AssetTypeDb(name=f"Type {uuid.uuid4().hex[:8]}", category="data")
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def auth():
    mock = Mock()
    mock.get_user_effective_permissions.return_value = {"assets": FeatureAccessLevel.READ_ONLY}
    mock.has_permission.return_value = True
    return mock


@pytest.fixture
def search_manager():
    return SearchManager(searchable_managers=[])


@pytest.fixture
def wired(search_manager):
    manager = AssetsManager()
    manager.set_search_manager(search_manager)
    return manager


def _hits(search_manager, auth, query):
    return [item.id for item in search_manager.search(query, auth, USER)]


def _create(wired, db, asset_type, name, properties=None):
    return wired.create_asset(
        db,
        asset_in=AssetCreate(name=name, asset_type_id=asset_type.id, platform="databricks",
                             properties=properties),
        current_user_id="tester@example.com",
    )


def test_created_asset_is_searchable_without_rebuild(
    db_session, asset_type, wired, search_manager, auth,
):
    name = f"orders-{uuid.uuid4().hex[:8]}"

    created = _create(wired, db_session, asset_type, name)

    assert f"asset::{created.id}" in _hits(search_manager, auth, name)


def test_deleted_asset_has_no_search_hit(
    db_session, asset_type, wired, search_manager, auth,
):
    name = f"invoices-{uuid.uuid4().hex[:8]}"
    created = _create(wired, db_session, asset_type, name)
    assert f"asset::{created.id}" in _hits(search_manager, auth, name)

    wired.delete_asset(db_session, asset_id=created.id, current_user_id="tester@example.com")

    assert f"asset::{created.id}" not in _hits(search_manager, auth, name)


def test_bulk_import_batch_index_reaches_search_after_commit(
    db_session, asset_type, wired, search_manager, auth,
):
    names = [f"bulk-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    rows = "\n".join(f"{n},{asset_type.name}" for n in names)
    csv_bytes = f"name,asset_type\n{rows}\n".encode()
    bulk = AssetBulkManager(assets_manager=wired)

    result = bulk.execute_import(db_session, file_bytes=csv_bytes, filename="a.csv",
                                 current_user_id="tester@example.com")
    assert result.created == 2, result.items
    db_session.commit()
    bulk.index_committed_import(db_session, result)

    for name in names:
        assert any(hit.startswith("asset::") for hit in _hits(search_manager, auth, name))


def test_asset_retired_by_bulk_import_has_no_search_hit(
    db_session, asset_type, wired, search_manager, auth,
):
    name = f"retire-{uuid.uuid4().hex[:8]}"
    created = _create(wired, db_session, asset_type, name)
    assert f"asset::{created.id}" in _hits(search_manager, auth, name)
    row = f"{created.id},{name},{asset_type.name},retired"
    csv_bytes = f"id,name,asset_type,status\n{row}\n".encode()
    bulk = AssetBulkManager(assets_manager=wired)

    result = bulk.execute_import(db_session, file_bytes=csv_bytes, filename="a.csv",
                                 current_user_id="tester@example.com")
    assert result.updated == 1, result.items
    db_session.commit()
    bulk.index_committed_import(db_session, result)

    assert f"asset::{created.id}" not in _hits(search_manager, auth, name)


def test_asset_retired_by_update_has_no_search_hit(
    db_session, asset_type, wired, search_manager, auth,
):
    name = f"retire-upd-{uuid.uuid4().hex[:8]}"
    created = _create(wired, db_session, asset_type, name)
    assert f"asset::{created.id}" in _hits(search_manager, auth, name)

    wired.update_asset(db_session, asset_id=created.id,
                       asset_in=AssetUpdate(status=AssetStatus.RETIRED),
                       current_user_id="tester@example.com")

    assert f"asset::{created.id}" not in _hits(search_manager, auth, name)


def test_import_that_does_not_commit_leaves_no_index_entries(
    db_session, asset_type, wired, search_manager, auth,
):
    name = f"ghost-{uuid.uuid4().hex[:8]}"
    csv_bytes = f"name,asset_type\n{name},{asset_type.name}\n".encode()
    bulk = AssetBulkManager(assets_manager=wired)

    with patch.object(bulk, "_wire_parent_relationships", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            bulk.execute_import(db_session, file_bytes=csv_bytes, filename="a.csv",
                                current_user_id="tester@example.com")
    db_session.rollback()

    assert _hits(search_manager, auth, name) == []


def test_schema_violation_is_422_single_write_and_row_error_in_bulk(
    db_session, asset_type, wired,
):
    schema_def = MagicMock()
    schema_def.json_schema = {"type": "object", "properties": {"owner": {"type": "string"}}}
    wired._ontology = MagicMock()
    wired._ontology.get_entity_type_schema.return_value = schema_def
    bad = {"owner": 5}

    with pytest.raises(ValidationError):
        _create(wired, db_session, asset_type, f"bad-{uuid.uuid4().hex[:8]}", properties=bad)

    csv_bytes = ('name,asset_type,properties\n'
                 f'row-{uuid.uuid4().hex[:8]},{asset_type.name},"{{""owner"": 5}}"\n').encode()
    result = AssetBulkManager(assets_manager=wired).execute_import(
        db_session, file_bytes=csv_bytes, filename="a.csv", current_user_id="tester@example.com",
    )
    assert (result.created, result.errors) == (0, 1), result.items
    assert "validation failed" in result.items[0].message
