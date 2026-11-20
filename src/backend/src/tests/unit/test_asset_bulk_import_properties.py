"""Bulk import and the stored properties of an asset it updates.

A row's properties replace the stored ones (as ``PUT /api/assets/{id}``), the
internal keys stay, and an empty properties cell keeps the stored properties
(before, it stored NULL and dropped them all).
"""
import csv
import io
import json
import uuid

from src.controller.asset_bulk_manager import AssetBulkManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.assets import METRIC_VIEW_PROPERTY

STORED = {"data_type": "DATE", "nullable": True, METRIC_VIEW_PROPERTY: {"source": "sales"}}


def _asset(db):
    asset_type = db.query(AssetTypeDb).filter(AssetTypeDb.name == "Column").first()
    if not asset_type:
        asset_type = AssetTypeDb(name="Column")
        db.add(asset_type)
        db.flush()
    asset = AssetDb(
        name="order_date", asset_type_id=asset_type.id, properties=dict(STORED),
        platform="databricks", location=f"main.sales.orders.order_date.{uuid.uuid4().hex[:6]}",
    )
    db.add(asset)
    db.flush()
    return asset


def _import(db, asset, properties_cell, by_id):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["id", "name", "asset_type", "platform", "location", "properties"])
    writer.writerow([
        str(asset.id) if by_id else "", asset.name, "Column", asset.platform, asset.location,
        properties_cell,
    ])
    result = AssetBulkManager().execute_import(
        db, file_bytes=out.getvalue().encode(), filename="assets.csv",
        current_user_id="alice@example.com",
    )
    assert (result.updated, result.errors) == (1, 0), result
    db.expire_all()
    return db.get(AssetDb, asset.id).properties


def test_an_empty_properties_cell_keeps_the_stored_properties(db_session):
    for by_id in (True, False):
        asset = _asset(db_session)
        assert _import(db_session, asset, "", by_id) == STORED


def test_a_row_with_properties_replaces_them_and_keeps_the_internal_keys(db_session):
    for by_id in (True, False):
        asset = _asset(db_session)
        stored = _import(db_session, asset, json.dumps({"nullable": False}), by_id)
        assert stored == {"nullable": False, METRIC_VIEW_PROPERTY: {"source": "sales"}}
