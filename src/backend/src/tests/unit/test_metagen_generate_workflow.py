"""Unit tests for the metagen_generate job's pure logic.

pyspark isn't installed locally, so the pyspark modules are stubbed and Spark
is replaced by a fake whose ``sql(...).collect()`` returns canned rows. Covers
selection expansion, DESCRIBE TABLE EXTENDED parsing and how dbxmetagen's log
rows are attributed to this run.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[2] / "workflows" / "metagen_generate" / "metagen_generate.py"


class Row(dict):
    """Row-like: supports row["name"] and row[0]."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


@pytest.fixture(scope="module")
def job():
    stubs = {}
    for name in ("pyspark", "pyspark.sql", "pyspark.sql.types"):
        if name not in sys.modules:
            stubs[name] = ModuleType(name)
    if "pyspark.sql" in stubs:
        stubs["pyspark.sql"].SparkSession = MagicMock()
    if "pyspark.sql.types" in stubs:
        for t in ("StringType", "StructField", "StructType", "TimestampType"):
            setattr(stubs["pyspark.sql.types"], t, MagicMock())
    sys.modules.update(stubs)
    try:
        spec = importlib.util.spec_from_file_location("metagen_generate_under_test", _MODULE_PATH)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        for name in stubs:
            sys.modules.pop(name, None)


class FakeSpark:
    def __init__(self, responses):
        self.responses = responses  # list of (sql substring, rows)
        self.queries = []

    def sql(self, query):
        self.queries.append(query)
        for needle, rows in self.responses:
            if needle in query:
                result = MagicMock()
                result.collect.return_value = rows
                return result
        raise AssertionError(f"unexpected query: {query}")


def test_expand_selection_expands_and_dedupes(job):
    spark = FakeSpark([
        ("SHOW SCHEMAS IN `main`", [Row(databaseName="sales"), Row(databaseName="information_schema")]),
        ("SHOW TABLES IN `main`.`sales`", [
            Row(database="sales", tableName="orders", isTemporary=False),
            Row(database="sales", tableName="tmp", isTemporary=True),
        ]),
    ])
    tables = job.expand_selection(spark, ["main", "MAIN.sales.orders", "main.sales.customers"])
    assert tables == ["main.sales.orders", "main.sales.customers"]
    assert not any("information_schema" in q for q in spark.queries)


def test_describe_table_reads_comments_and_view_type(job):
    spark = FakeSpark([("DESCRIBE TABLE EXTENDED", [
        Row(col_name="country_code", data_type="string", comment=None),
        Row(col_name="revenue", data_type="decimal", comment="Revenue"),
        Row(col_name="", data_type="", comment=""),
        Row(col_name="# Detailed Table Information", data_type="", comment=""),
        Row(col_name="Type", data_type="VIEW", comment=""),
        Row(col_name="Comment", data_type="By country", comment=""),
    ])])
    object_type, table_comment, columns = job.describe_table(spark, "main.sales.revenue")
    assert object_type == "view"
    assert table_comment == "By country"
    assert columns == {"country_code": None, "revenue": "Revenue"}


def test_describe_table_stops_at_partition_section(job):
    spark = FakeSpark([("DESCRIBE TABLE EXTENDED", [
        Row(col_name="id", data_type="bigint", comment=None),
        Row(col_name="# Partition Information", data_type="", comment=""),
        Row(col_name="# col_name", data_type="data_type", comment="comment"),
        Row(col_name="id", data_type="bigint", comment="dup"),
        Row(col_name="Type", data_type="MANAGED", comment=""),
    ])])
    object_type, table_comment, columns = job.describe_table(spark, "main.sales.orders")
    assert (object_type, table_comment, columns) == ("table", None, {"id": None})


def test_is_fully_described(job):
    assert job.is_fully_described("T", {"a": "x"})
    assert not job.is_fully_described(None, {"a": "x"})
    assert not job.is_fully_described("T", {"a": None})


def test_read_generated_attributes_rows_to_this_run(job):
    spark = FakeSpark([("metadata_generation_log", [
        Row(table="main.sales.orders", catalog="main", schema="sales", table_name="orders",
            ddl_type="table", column_name="orders", column_content="Old text", model="m", _created_at=1),
        Row(table="main.sales.orders", catalog="main", schema="sales", table_name="orders",
            ddl_type="table", column_name="orders", column_content="Orders.", model="m", _created_at=2),
        Row(table="orders", catalog="MAIN", schema="Sales", table_name="Orders",
            ddl_type="column", column_name="id", column_content="Order id.", model="m", _created_at=3),
        Row(table="main.sales.orders", catalog="main", schema="sales", table_name="orders",
            ddl_type="column", column_name="note", column_content="   ", model="m", _created_at=4),
        Row(table="main.other.thing", catalog="main", schema="other", table_name="thing",
            ddl_type="table", column_name=None, column_content="Not ours.", model="m", _created_at=5),
    ])])
    generated = job.read_generated(spark, "app.app.metadata_generation_log", 123456, {"main.sales.orders": "main.sales.orders"})
    assert generated == {
        ("main.sales.orders", None): ("Orders.", "m", 2),
        ("main.sales.orders", "id"): ("Order id.", "m", 3),
    }
    assert "unix_micros(_created_at) >= 123456" in spark.queries[0]


def test_quote_fqn_escapes_backticks(job):
    assert job.quote_fqn("a.b`c.d") == "`a`.`b``c`.`d`"


RUN_ID = "11111111-2222-3333-4444-555555555555"


class MainFakeSpark(FakeSpark):
    """FakeSpark that also supports first() and captures DataFrame writes."""

    def __init__(self, responses):
        super().__init__(responses)
        self.written = []

    def sql(self, query):
        if query.startswith("DELETE") or "unix_micros(current_timestamp())" in query:
            self.queries.append(query)
            result = MagicMock()
            result.first.return_value = Row(us=1000)
            return result
        return super().sql(query)

    def createDataFrame(self, rows, schema):
        self.written.append(list(rows))
        return MagicMock()


def _describe(rows):
    return [Row(col_name=c, data_type="string", comment=comment) for c, comment in rows]


def _main_spark():
    return MainFakeSpark([
        ("SHOW TABLES IN `main`.`sales`", [
            Row(database="sales", tableName="orders", isTemporary=False),
            Row(database="sales", tableName="customers", isTemporary=False),
            Row(database="sales", tableName="revenue", isTemporary=False),
        ]),
        ("DESCRIBE TABLE EXTENDED `main`.`sales`.`orders`",
         _describe([("id", None), ("amount", "Total amount")]) + [Row(col_name="Type", data_type="MANAGED", comment="")]),
        ("DESCRIBE TABLE EXTENDED `main`.`sales`.`customers`",
         _describe([("id", "Customer id")]) + [Row(col_name="", data_type="", comment=""),
                                                 Row(col_name="Comment", data_type="Customers", comment="")]),
        ("DESCRIBE TABLE EXTENDED `main`.`sales`.`revenue`",
         _describe([("country", None)]) + [Row(col_name="", data_type="", comment=""),
                                            Row(col_name="Type", data_type="VIEW", comment="")]),
        ("metadata_generation_log", [
            Row(table="main.sales.orders", catalog="main", schema="sales", table_name="orders",
                ddl_type="table", column_name=None, column_content="Orders.", model="m", _created_at=1),
            Row(table="main.sales.orders", catalog="main", schema="sales", table_name="orders",
                ddl_type="column", column_name="id", column_content="Order id.", model="m", _created_at=2),
            Row(table="main.sales.orders", catalog="main", schema="sales", table_name="orders",
                ddl_type="column", column_name="ghost", column_content="Not a column.", model="m", _created_at=3),
            Row(table="main.sales.revenue", catalog="main", schema="sales", table_name="revenue",
                ddl_type="table", column_name=None, column_content="Revenue by country.", model="m", _created_at=4),
        ]),
    ])


def _run_main(job, monkeypatch, spark, *extra_args):
    calls = []
    dbxmetagen_main_module = ModuleType("dbxmetagen.main")
    dbxmetagen_main_module.main = calls.append
    monkeypatch.setitem(sys.modules, "dbxmetagen", ModuleType("dbxmetagen"))
    monkeypatch.setitem(sys.modules, "dbxmetagen.main", dbxmetagen_main_module)
    session = MagicMock()
    session.builder.getOrCreate.return_value = spark
    monkeypatch.setattr(job, "SparkSession", session)
    monkeypatch.setattr(sys, "argv", [
        "metagen_generate.py", "--ontos_run_id", RUN_ID, "--table_names", "main.sales",
        "--output_catalog", "app", "--output_schema", "ontos", "--model", "endpoint-x", *extra_args,
    ])
    job.main()
    return calls


def test_main_generates_only_for_undescribed_objects_and_writes_normalized_rows(job, monkeypatch):
    spark = _main_spark()
    calls = _run_main(job, monkeypatch, spark)

    [kwargs] = calls
    assert kwargs["table_names"] == "main.sales.orders,main.sales.revenue"  # customers fully described
    assert (kwargs["catalog_name"], kwargs["schema_name"]) == ("app", "ontos")
    assert kwargs["model"] == "endpoint-x"
    assert kwargs["apply_ddl"] == "false" and kwargs["allow_data"] == "false"
    assert kwargs["add_metadata"] is True
    assert any(q.startswith("DELETE") and RUN_ID in q for q in spark.queries)

    rows = spark.written[-1]
    assert [(r[0], r[1], r[2], r[3], r[4], r[5]) for r in rows] == [
        (RUN_ID, "table", "main.sales.orders", None, None, "Orders."),
        (RUN_ID, "column", "main.sales.orders", "id", None, "Order id."),
        (RUN_ID, "view", "main.sales.revenue", None, None, "Revenue by country."),
    ]  # 'ghost' isn't a column of orders and is dropped


def test_main_regenerate_existing_includes_described_tables(job, monkeypatch):
    calls = _run_main(job, monkeypatch, _main_spark(), "--regenerate_existing", "true")
    assert calls[0]["table_names"] == "main.sales.orders,main.sales.customers,main.sales.revenue"


def test_main_passes_sampling_and_metadata_switches(job, monkeypatch):
    calls = _run_main(
        job, monkeypatch, _main_spark(),
        "--allow_data", "true", "--sample_size", "7", "--add_metadata", "false",
    )
    kwargs = calls[0]
    assert (kwargs["allow_data"], kwargs["sample_size"]) == ("true", "7")
    # A real bool: dbxmetagen doesn't parse add_metadata, so "false" would be truthy
    assert kwargs["add_metadata"] is False


def test_main_fails_when_the_selection_exceeds_the_table_limit(job, monkeypatch):
    spark = _main_spark()
    with pytest.raises(SystemExit):
        _run_main(job, monkeypatch, spark, "--max_tables", "2")
    assert not spark.written  # nothing generated or written


def test_main_rejects_a_non_uuid_run_id(job, monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "metagen_generate.py", "--ontos_run_id", "x' OR '1'='1", "--table_names", "main.sales",
        "--output_catalog", "app", "--output_schema", "ontos", "--model", "m",
    ])
    with pytest.raises(ValueError):
        job.main()


def test_job_definition_declares_every_parameter_the_app_passes():
    import yaml
    from pathlib import Path

    from src.controller.metadata_generation_manager import JOB_PARAMETERS

    yaml_path = Path(__file__).resolve().parents[2] / "workflows" / "metagen_generate" / "metagen_generate.yaml"
    spec = yaml.safe_load(yaml_path.read_text())
    assert set(spec["parameters"]) == set(JOB_PARAMETERS)
    args = spec["tasks"][0]["spark_python_task"]["parameters"]
    assert {a[2:] for a in args if a.startswith("--")} == set(JOB_PARAMETERS)
