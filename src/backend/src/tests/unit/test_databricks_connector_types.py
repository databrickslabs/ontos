from types import SimpleNamespace
from unittest.mock import MagicMock

from databricks.sdk.service.catalog import ColumnTypeName

from src.connectors.databricks import DatabricksConnector


def _table_with_column(column: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        table_type=None,
        columns=[column],
        table_constraints=[],
        owner="owner@example.com",
        comment="test table",
        properties={},
        full_name="main.sales.orders",
        name="orders",
        storage_location=None,
        catalog_name="main",
        schema_name="sales",
    )


def test_get_table_metadata_uses_enum_value_for_logical_type():
    ws = MagicMock()
    ws.tables.get.return_value = _table_with_column(
        SimpleNamespace(
            name="amount_usd",
            type_text=None,
            type_name=ColumnTypeName.DOUBLE,
            nullable=True,
            comment="Amount",
            partition_index=None,
        )
    )

    connector = DatabricksConnector(workspace_client=ws)
    metadata = connector._get_table_metadata(ws, "main.sales.orders")

    assert metadata is not None
    assert metadata.schema_info is not None
    col = metadata.schema_info.columns[0]
    assert col.logical_type == "DOUBLE"
    assert col.logical_type != "ColumnTypeName.DOUBLE"
    assert col.data_type == "DOUBLE"


def test_get_table_metadata_keeps_type_text_when_type_name_missing():
    ws = MagicMock()
    ws.tables.get.return_value = _table_with_column(
        SimpleNamespace(
            name="price",
            type_text="decimal(10,2)",
            type_name=None,
            nullable=False,
            comment=None,
            partition_index=None,
        )
    )

    connector = DatabricksConnector(workspace_client=ws)
    metadata = connector._get_table_metadata(ws, "main.sales.orders")

    assert metadata is not None
    assert metadata.schema_info is not None
    col = metadata.schema_info.columns[0]
    assert col.data_type == "decimal(10,2)"
    assert col.logical_type is None
