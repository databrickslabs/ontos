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


def _table_with_columns_and_constraints(columns, table_constraints):
    return SimpleNamespace(
        table_type=None,
        columns=columns,
        table_constraints=table_constraints,
        owner="owner@example.com",
        comment="test table",
        properties={},
        full_name="main.sales.orders",
        name="orders",
        storage_location=None,
        catalog_name="main",
        schema_name="sales",
    )


def test_get_table_metadata_extracts_primary_and_foreign_keys():
    """PK/FK from UC table_constraints land on schema_info and the columns."""
    columns = [
        SimpleNamespace(name="order_id", type_text="bigint", type_name=None,
                        nullable=False, comment=None, partition_index=None),
        SimpleNamespace(name="customer_id", type_text="bigint", type_name=None,
                        nullable=False, comment=None, partition_index=None),
        SimpleNamespace(name="amount", type_text="double", type_name=None,
                        nullable=True, comment=None, partition_index=None),
    ]
    table_constraints = [
        SimpleNamespace(
            primary_key_constraint=SimpleNamespace(name="pk_orders", child_columns=["order_id"]),
            foreign_key_constraint=None,
            named_table_constraint=None,
        ),
        SimpleNamespace(
            primary_key_constraint=None,
            foreign_key_constraint=SimpleNamespace(
                name="fk_customer",
                child_columns=["customer_id"],
                parent_table="main.sales.customers",
                parent_columns=["id"],
            ),
            named_table_constraint=None,
        ),
    ]

    ws = MagicMock()
    ws.tables.get.return_value = _table_with_columns_and_constraints(columns, table_constraints)

    connector = DatabricksConnector(workspace_client=ws)
    metadata = connector._get_table_metadata(ws, "main.sales.orders")

    si = metadata.schema_info
    assert si.primary_key == ["order_id"]
    assert len(si.foreign_keys) == 1
    fk = si.foreign_keys[0]
    assert fk.columns == ["customer_id"]
    assert fk.parent_table == "main.sales.customers"
    assert fk.parent_columns == ["id"]

    by_name = {c.name: c for c in si.columns}
    assert by_name["order_id"].is_primary_key is True
    assert by_name["order_id"].is_foreign_key is False
    assert by_name["customer_id"].is_foreign_key is True
    assert by_name["customer_id"].is_primary_key is False
    assert by_name["amount"].is_primary_key is False


def test_get_table_metadata_no_constraints_leaves_keys_empty():
    ws = MagicMock()
    ws.tables.get.return_value = _table_with_column(
        SimpleNamespace(name="x", type_text="int", type_name=None,
                        nullable=True, comment=None, partition_index=None)
    )

    connector = DatabricksConnector(workspace_client=ws)
    metadata = connector._get_table_metadata(ws, "main.sales.orders")

    si = metadata.schema_info
    assert si.primary_key is None
    assert si.foreign_keys == []
    assert si.columns[0].is_primary_key is False
    assert si.columns[0].is_foreign_key is False


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
