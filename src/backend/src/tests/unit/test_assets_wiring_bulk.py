"""Bulk import uses the wired AssetsManager, indexes committed assets in one batch and
checks row properties against the type schema."""
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi import FastAPI, Request

from src.common.errors import ValidationError
from src.controller.asset_bulk_manager import AssetBulkManager, ImportAction, ImportResult, ImportResultItem
from src.controller.assets_manager import AssetsManager, assets_manager as singleton
from src.routes import asset_bulk_routes

ASSET_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ID = "22222222-2222-2222-2222-222222222222"


def _request(app: FastAPI) -> Request:
    return Request({"type": "http", "app": app, "headers": []})


def test_bulk_manager_gets_the_startup_assets_manager():
    app = FastAPI()
    wired = AssetsManager()
    app.state.assets_manager = wired

    manager = asset_bulk_routes.get_bulk_manager(_request(app))

    assert manager._assets_manager is wired


def test_bulk_manager_without_request_falls_back_to_singleton():
    assert asset_bulk_routes.get_bulk_manager()._assets_manager is singleton


def _create_manager():
    wired = MagicMock(spec=AssetsManager)
    manager = AssetBulkManager(assets_manager=wired)
    created = MagicMock()
    created.id = ASSET_ID
    return wired, manager, created


def _run_create(wired, manager, created, csv_bytes=b"name,asset_type\nfoo,table\n"):
    with patch.object(manager, "_resolve_asset_types", return_value={"table": created.id}), \
         patch.object(manager, "_set_asset_domains"), \
         patch.object(manager._asset_repo, "get_by_identity", return_value=None), \
         patch("src.controller.asset_bulk_manager.AssetDb", return_value=created):
        return manager.execute_import(
            MagicMock(), file_bytes=csv_bytes, filename="a.csv", current_user_id="u@x.com",
        )


def test_bulk_import_does_not_index_inside_the_transaction():
    wired, manager, created = _create_manager()

    result = _run_create(wired, manager, created)

    assert result.created == 1, result.items
    wired._update_search_index.assert_not_called()
    wired.upsert_search_index_for.assert_not_called()


def test_index_committed_import_batches_created_and_updated_ids():
    wired = MagicMock(spec=AssetsManager)
    manager = AssetBulkManager(assets_manager=wired)
    db = MagicMock()
    result = ImportResult(
        created=1, updated=1,
        items=[
            ImportResultItem(row=1, action=ImportAction.CREATE, asset_id=ASSET_ID),
            ImportResultItem(row=2, action=ImportAction.UPDATE, asset_id=OTHER_ID),
            ImportResultItem(row=3, action=ImportAction.ERROR, message="bad row"),
        ],
    )

    manager.index_committed_import(db, result)

    wired.upsert_search_index_for.assert_called_once_with(db, [UUID(ASSET_ID), UUID(OTHER_ID)])


def test_index_committed_import_with_nothing_written_skips_the_index():
    wired = MagicMock(spec=AssetsManager)
    manager = AssetBulkManager(assets_manager=wired)

    manager.index_committed_import(MagicMock(), ImportResult(errors=1))

    wired.upsert_search_index_for.assert_not_called()


def test_index_committed_import_does_not_raise_when_indexing_fails():
    wired = MagicMock(spec=AssetsManager)
    wired.upsert_search_index_for.side_effect = RuntimeError("index down")
    manager = AssetBulkManager(assets_manager=wired)
    result = ImportResult(items=[ImportResultItem(row=1, action=ImportAction.CREATE, asset_id=ASSET_ID)])

    manager.index_committed_import(MagicMock(), result)

    wired.upsert_search_index_for.assert_called_once()


def test_bulk_manager_without_assets_manager_skips_indexing():
    AssetBulkManager().index_committed_import(
        MagicMock(), ImportResult(items=[ImportResultItem(row=1, action=ImportAction.CREATE, asset_id=ASSET_ID)]),
    )


def _run_update(csv_bytes, get_return, identity_return):
    wired = MagicMock(spec=AssetsManager)
    manager = AssetBulkManager(assets_manager=wired)
    updated = MagicMock()
    updated.id = ASSET_ID

    with patch.object(manager, "_resolve_asset_types", return_value={"table": updated.id}), \
         patch.object(manager, "_set_asset_domains"), \
         patch.object(manager._asset_repo, "get", return_value=get_return), \
         patch.object(manager._asset_repo, "get_by_identity", return_value=identity_return), \
         patch.object(manager._asset_repo, "update", return_value=updated):
        result = manager.execute_import(
            MagicMock(), file_bytes=csv_bytes, filename="a.csv", current_user_id="u@x.com",
        )
    return wired, updated, result


def test_bulk_import_update_by_id_reports_an_update_for_batch_indexing():
    wired, updated, result = _run_update(
        b"id,name,asset_type\n" + ASSET_ID.encode() + b",foo,table\n",
        get_return=MagicMock(), identity_return=None,
    )

    assert result.updated == 1, result.items
    assert result.items[0].action == ImportAction.UPDATE
    assert result.items[0].asset_id == str(updated.id)
    wired.upsert_search_index_for.assert_not_called()


def test_bulk_import_row_that_violates_the_type_schema_is_an_error():
    wired, manager, created = _create_manager()
    wired._validate_properties.side_effect = ValidationError(
        "Asset properties validation failed for type 'table': 5 is not of type 'string'",
    )

    result = _run_create(wired, manager, created, csv_bytes=b'name,asset_type,properties\nfoo,table,"{""owner"": 5}"\n')

    assert (result.created, result.errors) == (0, 1), result.items
    assert "validation failed" in result.items[0].message
    wired.upsert_search_index_for.assert_not_called()


def test_bulk_preview_flags_row_that_violates_the_type_schema():
    wired = MagicMock(spec=AssetsManager)
    wired._validate_properties.side_effect = ValidationError("Asset properties validation failed")
    manager = AssetBulkManager(assets_manager=wired)
    db = MagicMock()

    with patch.object(manager, "_resolve_asset_types", return_value={"table": ASSET_ID}), \
         patch.object(manager._asset_repo, "get_by_identity", return_value=None):
        preview = manager.preview_import(
            db, file_bytes=b'name,asset_type,properties\nfoo,table,"{""owner"": 5}"\n', filename="a.csv",
        )

    assert preview.errors == 1 and preview.will_create == 0, preview.items
    assert "validation failed" in preview.items[0].message


def test_bulk_import_without_wired_manager_does_not_validate():
    manager = AssetBulkManager()
    manager._validate_row_properties(MagicMock(), UUID(ASSET_ID), {"owner": 5})
