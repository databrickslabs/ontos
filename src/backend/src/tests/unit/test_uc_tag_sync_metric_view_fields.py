"""uc_tag_sync leaves concept links on metric view fields untagged.

Unity Catalog documents no column tag DDL for metric view dimensions and measures,
so a ``uc_column`` link on one is skipped with a reason instead of failing every run.
UC is replaced by an in-memory tag store and a fake ``tables.get``; nothing is called.
"""

import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "uc_tag_sync" / "uc_tag_sync.py"
)

PREFIX = "ontos_"
SEMANTIC_CFG = [
    {
        "entity_type": "semantic_assignment",
        "enabled": True,
        "tag_key_format": "ontos_semantic_{LINK.SLUG}",
        "tag_value_format": "{LINK.IRI}",
    }
]
REVENUE = "urn:glossary:finance/net-revenue"
REVENUE_KEY = "ontos_semantic_net_revenue"
METRIC_VIEW = "main.sales.revenue_metrics"
TABLE = "main.sales.orders"
MEASURE = f"{METRIC_VIEW}.total revenue"
DIMENSION = f"{METRIC_VIEW}.region"
TABLE_COLUMN = f"{TABLE}.amount"


@pytest.fixture(scope="module")
def tag_sync():
    """Load the job script by path; pyspark is stubbed when missing."""
    added = []
    if "pyspark.sql" not in sys.modules:
        try:
            import pyspark.sql  # noqa: F401
        except ImportError:
            pyspark = types.ModuleType("pyspark")
            pyspark_sql = types.ModuleType("pyspark.sql")
            pyspark_sql.SparkSession = object
            pyspark.sql = pyspark_sql
            sys.modules["pyspark"] = pyspark
            sys.modules["pyspark.sql"] = pyspark_sql
            added = ["pyspark", "pyspark.sql"]
    spec = importlib.util.spec_from_file_location("uc_tag_sync_metric_view_under_test",
                                                  _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in added:
        sys.modules.pop(name, None)


@pytest.fixture
def uc(tag_sync, monkeypatch):
    """In-memory UC tags; a tag statement on a metric view field is refused."""
    store = {}

    def existing(_spark, object_type, name, prefix):
        tags = store.get((object_type, name), {})
        return {k: v for k, v in tags.items() if k.startswith(prefix)}

    def assign(_spark, object_type, name, key, value):
        if name.startswith(f"{METRIC_VIEW}."):
            raise RuntimeError("[INVALID_PARAMETER] refused on a metric view column")
        store.setdefault((object_type, name), {})[key] = value

    def unassign(_spark, object_type, name, key):
        store.get((object_type, name), {}).pop(key, None)

    monkeypatch.setattr(tag_sync, "get_existing_prefixed_tags", existing)
    monkeypatch.setattr(tag_sync, "assign_tag", assign)
    monkeypatch.setattr(tag_sync, "unassign_tag", unassign)
    monkeypatch.setattr(tag_sync, "ensure_tag_key", lambda _ws, _key: None)
    return store


def _ws(table_types):
    """Workspace client whose ``tables.get`` answers the given table types."""
    ws = MagicMock()

    def get(full_name):
        value = table_types[full_name]
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(table_type=SimpleNamespace(value=value))

    ws.tables.get.side_effect = get
    return ws


def _row(entity_id, iri=REVENUE):
    return {"entity_type": "uc_column", "entity_id": entity_id, "iri": iri, "label": None}


def _sync(tag_sync, ws, rows, previous=None):
    direct = tag_sync.build_direct_link_infos(rows, None, None)
    return tag_sync.sync_tags(ws, MagicMock(), [], direct, SEMANTIC_CFG, PREFIX,
                              previous=previous)


def test_metric_view_fields_are_skipped_and_table_columns_tagged(tag_sync, uc):
    ws = _ws({METRIC_VIEW: "METRIC_VIEW", TABLE: "MANAGED"})

    result = _sync(tag_sync, ws, [_row(MEASURE), _row(DIMENSION), _row(TABLE_COLUMN)])

    assert result.errors == []
    reason = tag_sync.METRIC_VIEW_FIELD_SKIP_REASON
    assert sorted(result.skipped) == [f"COLUMN {DIMENSION}: {reason}",
                                      f"COLUMN {MEASURE}: {reason}"]
    assert uc == {("COLUMN", TABLE_COLUMN): {REVENUE_KEY: REVENUE}}
    assert result.updated == 1
    assert set(result.delivered["COLUMN"]) == {TABLE_COLUMN}
    # One table type lookup per table, not per field
    looked_up = [c.kwargs["full_name"] for c in ws.tables.get.call_args_list]
    assert sorted(looked_up) == sorted([METRIC_VIEW, TABLE])


def test_a_table_column_is_tagged_when_the_table_type_cant_be_read(tag_sync, uc):
    ws = _ws({TABLE: RuntimeError("PERMISSION_DENIED")})

    result = _sync(tag_sync, ws, [_row(TABLE_COLUMN)])

    assert (result.errors, result.skipped) == ([], [])
    assert uc == {("COLUMN", TABLE_COLUMN): {REVENUE_KEY: REVENUE}}


def test_tags_an_earlier_run_delivered_on_a_skipped_field_are_kept(tag_sync, uc):
    uc[("COLUMN", MEASURE)] = {REVENUE_KEY: REVENUE}
    previous = {"COLUMN": {MEASURE: {REVENUE_KEY: REVENUE}}}

    result = _sync(tag_sync, _ws({METRIC_VIEW: "METRIC_VIEW"}), [_row(MEASURE)], previous)

    assert result.errors == [] and result.removed == 0
    assert result.delivered["COLUMN"] == {MEASURE: {REVENUE_KEY: REVENUE}}
    assert uc[("COLUMN", MEASURE)] == {REVENUE_KEY: REVENUE}


def test_a_run_with_a_metric_view_field_link_does_not_fail(tag_sync, uc, monkeypatch,
                                                           capsys):
    ws = _ws({METRIC_VIEW: "METRIC_VIEW", TABLE: "MANAGED"})
    saved = {}
    monkeypatch.setattr(tag_sync, "WorkspaceClient", lambda **_kw: ws)
    monkeypatch.setattr(tag_sync, "create_engine_from_params", lambda **_kw: MagicMock())
    monkeypatch.setattr(tag_sync, "SparkSession", MagicMock())
    for reader in ("read_contracts_and_links", "read_output_ports_without_contract",
                   "read_assets_and_links"):
        monkeypatch.setattr(tag_sync, reader, lambda _engine, limit=None: [])
    monkeypatch.setattr(tag_sync, "read_direct_uc_links",
                        lambda _engine, limit=None: [_row(MEASURE), _row(TABLE_COLUMN)])
    monkeypatch.setattr(tag_sync, "read_delivery_state", lambda _engine: {})
    monkeypatch.setattr(tag_sync, "save_delivery_state",
                        lambda _engine, delivered, *_a, **_kw: saved.update(delivered))
    monkeypatch.setattr(tag_sync, "handle_legacy_tag_cleanup", lambda *_a, **_kw: (0, []))
    monkeypatch.setattr(sys, "argv", [
        "uc_tag_sync.py", "--tag_sync_configs",
        '[{"entity_type": "semantic_assignment", "enabled": true, '
        '"tag_key_format": "ontos_semantic_{LINK.SLUG}", '
        '"tag_value_format": "{LINK.IRI}"}]',
        "--lakebase_instance_name", "x", "--postgres_host", "h", "--postgres_db", "d",
    ])

    tag_sync.main()  # a SystemExit(1) here would mark the job run failed

    out = capsys.readouterr().out
    assert "errors=0 skipped=1" in out
    assert f"COLUMN {MEASURE}: {tag_sync.METRIC_VIEW_FIELD_SKIP_REASON}" in out
    assert uc == {("COLUMN", TABLE_COLUMN): {REVENUE_KEY: REVENUE}}
    assert set(saved["COLUMN"]) == {TABLE_COLUMN}
