"""The Catalog Commander's column schema uses the shared ODCS logical type map.

Its own substring map typed timestamps as ``date`` and ``INTERVAL`` as
``integer`` (the ``int`` in "interval"); Infer from Asset and the Catalog
Commander now give the same logical type for the same column.
"""
from src.common.odcs_logical_types import odcs_logical_type
from src.controller.catalog_commander_manager import CatalogCommanderManager

COLUMNS = [
    ("d", "date"), ("ts", "timestamp"), ("ts_ntz", "timestamp_ntz"), ("n", "bigint"),
    ("amt", "decimal(12,2)"), ("ok", "boolean"), ("tags", "array<string>"),
    ("attrs", "struct<a:int>"), ("dur", "interval day"), ("s", "string"),
]


def _logical_types():
    manager = CatalogCommanderManager.__new__(CatalogCommanderManager)
    table = {"columns": [{"name": n, "type_text": t} for n, t in COLUMNS]}
    return {c["name"]: c["logicalType"] for c in manager._extract_schema(table)}


def test_column_logical_types():
    assert _logical_types() == {
        "d": "date", "ts": "timestamp", "ts_ntz": "timestamp", "n": "integer",
        "amt": "number", "ok": "boolean", "tags": "array", "attrs": "object",
        "dur": "string", "s": "string",
    }


def test_same_map_as_infer_from_asset():
    assert _logical_types() == {n: odcs_logical_type(t) for n, t in COLUMNS}
