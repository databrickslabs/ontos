"""The "Infer from Asset" action maps each column's physical type to its ODCS logical type.

Before, every inferred column got ``logicalType: string`` unless the column
asset stored a ``logical_type``.
"""
import pytest

from src.common.odcs_logical_types import odcs_logical_type
from src.controller.assets_manager import AssetsManager
from src.db_models.assets import AssetDb, AssetRelationshipDb, AssetTypeDb


@pytest.mark.parametrize(
    "physical, logical",
    [
        ("DATE", "date"),
        ("TIMESTAMP", "timestamp"),
        ("timestamp_ntz", "timestamp"),
        ("TIMESTAMP_LTZ", "timestamp"),
        ("TINYINT", "integer"),
        ("SMALLINT", "integer"),
        ("INT", "integer"),
        ("BIGINT", "integer"),
        ("long", "integer"),
        ("FLOAT", "number"),
        ("DOUBLE", "number"),
        ("DECIMAL(10,2)", "number"),
        ("decimal", "number"),
        ("BOOLEAN", "boolean"),
        ("STRING", "string"),
        ("VARCHAR(255)", "string"),
        ("CHAR(2)", "string"),
        ("ARRAY<STRING>", "array"),
        ("STRUCT<a: INT>", "object"),
        ("MAP<STRING, INT>", "object"),
        ("VARIANT", "object"),
        ("INTERVAL DAY", "string"),
        ("BINARY", "string"),
        ("", "string"),
        (None, "string"),
    ],
)
def test_odcs_logical_type(physical, logical):
    assert odcs_logical_type(physical) == logical


def _type(db, name):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found:
        return found
    created = AssetTypeDb(name=name)
    db.add(created)
    db.flush()
    return created


def _table_with_columns(db, columns):
    table = AssetDb(name="orders", asset_type_id=_type(db, "Table").id, location="c.s.orders")
    db.add(table)
    db.flush()
    for name, props in columns:
        col = AssetDb(name=name, asset_type_id=_type(db, "Column").id, properties=props)
        db.add(col)
        db.flush()
        db.add(AssetRelationshipDb(
            source_asset_id=table.id, target_asset_id=col.id, relationship_type="hasColumn",
        ))
    db.flush()
    db.expire_all()
    return table


def test_infer_schema_maps_column_types(db_session):
    table = _table_with_columns(db_session, [
        ("order_date", {"data_type": "DATE"}),
        ("order_id", {"data_type": "BIGINT"}),
        ("amount", {"data_type": "DECIMAL(12,2)"}),
        ("city", {"data_type": "STRING"}),
        # A stored logical type wins over the mapping
        ("code", {"data_type": "INT", "logical_type": "string"}),
    ])

    [schema] = AssetsManager().infer_schema_from_asset(db_session, table.id)

    types = {p["name"]: (p["physicalType"], p["logicalType"]) for p in schema["properties"]}
    assert types == {
        "order_date": ("DATE", "date"),
        "order_id": ("BIGINT", "integer"),
        "amount": ("DECIMAL(12,2)", "number"),
        "city": ("STRING", "string"),
        "code": ("INT", "string"),
    }


def test_infer_schema_maps_the_stored_schema_columns(db_session):
    table = AssetDb(
        name="events", asset_type_id=_type(db_session, "Table").id,
        properties={"schema": {"columns": [
            {"name": "ts", "data_type": "TIMESTAMP"},
            {"name": "ok", "data_type": "BOOLEAN"},
        ]}},
    )
    db_session.add(table)
    db_session.flush()

    [schema] = AssetsManager().infer_schema_from_asset(db_session, table.id)

    assert [(p["name"], p["logicalType"]) for p in schema["properties"]] == [
        ("ts", "timestamp"), ("ok", "boolean"),
    ]
