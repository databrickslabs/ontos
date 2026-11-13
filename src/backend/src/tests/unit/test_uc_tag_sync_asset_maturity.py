"""uc_tag_sync publishes the maturity level of table and view assets (#1316).

Covers the ``{ASSET.MATURITY}`` / ``{ASSET.MATURITY_ORDER}`` variables, the default
``maturity`` entry, the reader of the latest asset level, the skip reasons counted in
the run output, and that the level is a table tag only (no schema or catalog tag).
UC is an in-memory tag store: the Spark tag functions are patched.
"""

import importlib.util
import sys
import types
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from src.db_models.maturity import MaturityLevelDb, MaturitySnapshotDb

_JOB_DIR = Path(__file__).resolve().parents[2] / "workflows" / "uc_tag_sync"
TABLE = "main.sales.orders"
MATURITY_CFG = {
    "entity_type": "asset", "mapping": "maturity", "enabled": True,
    "tag_key_format": "ontos_context_tier", "tag_value_format": "{ASSET.MATURITY}",
}
TYPE_CFG = {
    "entity_type": "asset", "enabled": True,
    "tag_key_format": "ontos_asset_type", "tag_value_format": "{ASSET.TYPE}",
}


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
    spec = importlib.util.spec_from_file_location("uc_tag_sync_maturity_under_test",
                                                  _JOB_DIR / "uc_tag_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in added:
        sys.modules.pop(name, None)


def _dataset(tag_sync, fqn=TABLE, asset_id="a-1", asset_type="Table", **extra):
    cat, sch, tbl = fqn.split(".")
    return tag_sync.DatasetTagInfo(
        fqn=fqn, catalog=cat, schema=sch, table=tbl,
        contract_id=None, contract_name=None, contract_version=None, contract_status=None,
        product_id=None, product_name=None, product_version=None, product_status=None,
        domain_id=None, domain_name=None, semantic_links=[],
        asset_id=asset_id, asset_type_name=asset_type, **extra,
    )


def _asset_row(asset_id, location, asset_type="Table"):
    return {"asset_id": asset_id, "asset_name": location, "physical_name": location,
            "asset_type_name": asset_type}


# --- Configuration and variables --------------------------------------------------


def test_the_default_maturity_entry_is_an_asset_mapping_that_ships_disabled():
    workflow = yaml.safe_load((_JOB_DIR / "uc_tag_sync.yaml").read_text())
    param = next(p for p in workflow["configurable_parameters"]
                 if p["name"] == "tag_sync_configs")
    entry = next(e for e in param["default"] if e.get("mapping") == "maturity")

    assert entry == {
        "entity_type": "asset", "mapping": "maturity", "enabled": False,
        "tag_key_format": "ontos_maturity", "tag_value_format": "{ASSET.MATURITY}",
    }
    assert "asset" in param["entity_types"]


def test_the_level_name_and_order_are_tag_values(tag_sync):
    d = _dataset(tag_sync, asset_maturity_name="2 stars", asset_maturity_order=3)
    order_cfg = {**MATURITY_CFG, "tag_key_format": "ontos_tier_order",
                 "tag_value_format": "{ASSET.MATURITY_ORDER}"}

    desired = tag_sync.build_desired_for_dataset(d, [MATURITY_CFG, order_cfg, TYPE_CFG])

    assert desired == {"ontos_context_tier": "2 stars", "ontos_tier_order": "3",
                       "ontos_asset_type": "Table"}


def test_an_asset_without_a_level_gets_no_maturity_tag(tag_sync):
    desired = tag_sync.build_desired_for_dataset(_dataset(tag_sync), [MATURITY_CFG, TYPE_CFG])

    assert desired == {"ontos_asset_type": "Table"}


@pytest.mark.parametrize("configs, expected", [
    ([MATURITY_CFG], True),
    ([{**MATURITY_CFG, "enabled": False}], False),
    ([TYPE_CFG], False),
    # A maturity variable only means something on an asset entry
    ([{**MATURITY_CFG, "entity_type": "data_product"}], False),
    ([{**TYPE_CFG, "tag_key_format": "ontos_tier_{ASSET.MATURITY_ORDER}"}], True),
])
def test_levels_are_read_only_when_an_enabled_asset_entry_uses_them(tag_sync, configs,
                                                                     expected):
    assert tag_sync.maturity_configured(configs) is expected


def test_a_contract_dataset_of_the_same_table_keeps_the_asset_level(tag_sync):
    contract = _dataset(tag_sync, fqn="Main.Sales.Orders", asset_id=None, asset_type=None)
    contract.contract_name = "orders"
    asset = _dataset(tag_sync, asset_maturity_name="1 star", asset_maturity_order=2)

    [merged] = tag_sync.merge_dataset_tag_infos([contract], [asset])

    assert (merged.asset_maturity_name, merged.asset_maturity_order) == ("1 star", 2)
    assert merged.contract_name == "orders"


# --- Table tag only ---------------------------------------------------------------


@pytest.fixture
def uc(tag_sync, monkeypatch):
    """In-memory UC tags: (object_type, fqn) -> {tag key: value}."""
    store = {}

    def existing(_spark, object_type, name, prefix):
        tags = store.get((object_type, name), {})
        return {k: v for k, v in tags.items() if k.startswith(prefix)}

    def assign(_spark, object_type, name, key, value):
        store.setdefault((object_type, name), {})[key] = value

    def unassign(_spark, object_type, name, key):
        store.get((object_type, name), {}).pop(key, None)

    monkeypatch.setattr(tag_sync, "get_existing_prefixed_tags", existing)
    monkeypatch.setattr(tag_sync, "assign_tag", assign)
    monkeypatch.setattr(tag_sync, "unassign_tag", unassign)
    monkeypatch.setattr(tag_sync, "ensure_tag_key", lambda _ws, _key: None)
    return store


def _sync(tag_sync, datasets, previous=None):
    return tag_sync.sync_tags(
        MagicMock(), MagicMock(), datasets, tag_sync.DirectLinkInfos(),
        [MATURITY_CFG, TYPE_CFG], "ontos_", previous=previous,
    )


def test_the_level_is_written_on_the_table_only(tag_sync, uc):
    datasets = [
        _dataset(tag_sync, asset_maturity_name="2 stars", asset_maturity_order=3),
        _dataset(tag_sync, fqn="main.sales.items", asset_id="a-2",
                 asset_maturity_name="Prerequisite", asset_maturity_order=1),
    ]

    result = _sync(tag_sync, datasets)

    assert result.errors == []
    assert uc[("TABLE", TABLE)] == {"ontos_context_tier": "2 stars",
                                    "ontos_asset_type": "Table"}
    assert uc[("TABLE", "main.sales.items")]["ontos_context_tier"] == "Prerequisite"
    # The asset type is still aggregated to the parents; the level isn't.
    assert uc[("SCHEMA", "main.sales")] == {"ontos_asset_type": "Table"}
    assert uc[("CATALOG", "main")] == {"ontos_asset_type": "Table"}


def test_a_table_that_loses_its_level_loses_the_tag(tag_sync, uc):
    first = _sync(tag_sync, [_dataset(tag_sync, asset_maturity_name="1 star",
                                      asset_maturity_order=2)])

    second = _sync(tag_sync, [_dataset(tag_sync)], previous=first.delivered)

    assert uc[("TABLE", TABLE)] == {"ontos_asset_type": "Table"}
    assert second.removed == 1


# --- Skip reasons ---------------------------------------------------------------


def test_assets_without_a_level_are_skipped_with_a_counted_reason(tag_sync, capsys):
    tagged_id, metric_id, no_level_id = (str(uuid.uuid4()) for _ in range(3))
    rows = [
        _asset_row(tagged_id, TABLE),
        _asset_row(tagged_id, TABLE),  # one row per semantic link: counted once
        _asset_row("a-unqualified", "orders_only"),
        _asset_row(metric_id, "main.sales.revenue", asset_type="Metric View"),
        _asset_row(no_level_id, "main.sales.items", asset_type="View"),
    ]
    datasets = tag_sync.build_asset_tag_infos(rows, None, None)
    # Keys as the reader returns them: no hyphens, lower case
    maturity = {
        tagged_id.replace("-", ""): ("2 stars", 3),
        metric_id.replace("-", ""): ("1 star", 2),
    }

    skipped = tag_sync.attach_asset_maturity(rows, datasets, maturity)
    total = tag_sync.report_maturity_skips(skipped, tagged=1)

    by_fqn = {d.fqn: d for d in datasets}
    assert by_fqn[TABLE].asset_maturity_name == "2 stars"
    assert by_fqn[TABLE].asset_maturity_order == 3
    assert by_fqn["main.sales.revenue"].asset_maturity_name is None
    assert skipped == {
        tag_sync.MATURITY_SKIP_NO_UC_NAME: ["asset a-unqualified"],
        tag_sync.MATURITY_SKIP_ASSET_TYPE: ["main.sales.revenue"],
        tag_sync.MATURITY_SKIP_NO_LEVEL: ["main.sales.items"],
    }
    assert total == 3
    out = capsys.readouterr().out
    assert "Asset maturity: 1 asset(s) with a level, 3 skipped" in out
    assert f"1 skipped: {tag_sync.MATURITY_SKIP_NO_UC_NAME}" in out


# --- Reader against the test database ---------------------------------------------


class _SessionEngine:
    """Runs the reader on the test session's connection, so it sees its rows."""

    def __init__(self, session):
        self._session = session

    @contextmanager
    def connect(self):
        yield self._session.connection()


def _level(db, order, name, entity_type="Asset"):
    db.add(MaturityLevelDb(level_order=order, name=name, entity_type=entity_type))
    db.flush()


def _snapshot(db, entity_id, order, name, minutes_ago, entity_type="Asset"):
    db.add(MaturitySnapshotDb(
        entity_type=entity_type, entity_id=entity_id, achieved_level_order=order,
        achieved_level_name=name, total_levels=4,
        evaluated_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    ))
    db.flush()


def test_the_reader_returns_the_latest_level_by_its_current_name(tag_sync, db_session):
    _level(db_session, 1, "Prerequisite")
    _level(db_session, 2, "Described")  # renamed after the evaluation below
    _level(db_session, 3, "2 stars")
    _level(db_session, 4, "Trusted", entity_type="DataProduct")
    latest, renamed, dropped, gone, product = (str(uuid.uuid4()) for _ in range(5))
    _snapshot(db_session, latest, 1, "Prerequisite", minutes_ago=30)
    _snapshot(db_session, latest, 3, "2 stars", minutes_ago=5)
    _snapshot(db_session, renamed, 2, "1 star", minutes_ago=5)
    # Reached a level before; the latest evaluation reached none
    _snapshot(db_session, dropped, 2, "1 star", minutes_ago=30)
    _snapshot(db_session, dropped, None, None, minutes_ago=5)
    # Its level was deleted since
    _snapshot(db_session, gone, 7, "Old level", minutes_ago=5)
    _snapshot(db_session, product, 4, "Trusted", minutes_ago=5, entity_type="DataProduct")

    levels = tag_sync.read_asset_maturity(_SessionEngine(db_session))

    assert levels == {
        latest.replace("-", ""): ("2 stars", 3),
        renamed.replace("-", ""): ("Described", 2),
    }
