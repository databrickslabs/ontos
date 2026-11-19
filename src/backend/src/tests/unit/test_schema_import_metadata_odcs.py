"""``GET /api/schema-import/metadata`` returns ODCS logical types with ``odcs=true``.

The Databricks connector stores the Unity Catalog type name (``LONG``) as a column's
``logical_type``; "Infer from Catalog" put it into the contract as is.
"""
import asyncio
from unittest.mock import MagicMock
from uuid import uuid4

from src.models.assets import (
    AssetMetadata, ColumnInfo, SchemaInfo, UnifiedAssetType,
)
from src.routes.schema_import_routes import get_asset_metadata

COLUMNS = [
    ("id", "bigint", "LONG"), ("amt", "decimal(10,2)", "DECIMAL"),
    ("ts", "timestamp", "TIMESTAMP"), ("t", "time", "TIME"), ("s", "string", "STRING"),
]


def _metadata() -> AssetMetadata:
    return AssetMetadata(
        identifier="c.s.t", name="t", asset_type=UnifiedAssetType.UC_TABLE,
        connector_type="databricks",
        schema_info=SchemaInfo(columns=[
            ColumnInfo(name=n, data_type=d, logical_type=lt) for n, d, lt in COLUMNS
        ]),
    )


def _call(odcs, api_version=None):
    connector = MagicMock()
    connector.get_asset_metadata.return_value = _metadata()
    manager = MagicMock()
    manager._connections.get_connector_for_connection.return_value = connector
    result = asyncio.run(get_asset_metadata(
        connection_id=uuid4(), path="c.s.t", odcs=odcs, api_version=api_version,
        db=None, manager=manager, _=True,
    ))
    return {c.name: c.logical_type for c in result.schema_info.columns}


def test_raw_connector_types_without_odcs():
    assert _call(False)["id"] == "LONG"


def test_odcs_logical_types():
    assert _call(True) == {
        "id": "integer", "amt": "number", "ts": "timestamp", "t": "time", "s": "string",
    }


def test_odcs_logical_types_below_v31():
    types = _call(True, "v3.0.2")
    assert types["ts"] == "date" and types["t"] == "string" and types["id"] == "integer"
