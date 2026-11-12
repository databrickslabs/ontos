"""uc_tag_sync tags a Metric View asset exactly like a View asset (#1124).

Metric views were imported as View and picked up by the job's asset reader. Imported as
Metric View, they must still be read and get the same tags through their contract and
output port, with the same object type in reconciliation (the DDL is unchanged; ALTER
VIEW is phase 4 of the UC semantic view lifecycle PRD).
"""

import importlib.util
import json
import sys
import types
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml
from sqlalchemy import text

from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb, OutputPortDb
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.entity_relationships import EntityRelationshipDb

_JOB_DIR = Path(__file__).resolve().parents[2] / "workflows" / "uc_tag_sync"


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
                                                  _JOB_DIR / "uc_tag_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in added:
        sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def default_configs():
    workflow = yaml.safe_load((_JOB_DIR / "uc_tag_sync.yaml").read_text())
    param = next(p for p in workflow["configurable_parameters"]
                 if p["name"] == "tag_sync_configs")
    return param["default"]


class _ArrayAgg:
    """SQLite stand-in for Postgres array_agg; returns the list as JSON text."""

    def __init__(self):
        self.items = []

    def step(self, value):
        if value is not None:
            self.items.append(value)

    def finalize(self):
        return json.dumps(self.items) if self.items else None


# SQLite stores a UUID as 32 hex digits; Postgres' a.id::text gives the dashed form
_UUID_TEXT = ("(substr(a.id, 1, 8) || '-' || substr(a.id, 9, 4) || '-' || substr(a.id, 13, 4)"
              " || '-' || substr(a.id, 17, 4) || '-' || substr(a.id, 21))")


class _SqliteConnection:
    """Runs the job's Postgres SQL on the test session's SQLite connection."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, statement, params=None):
        sql = str(statement).replace("a.id::text", _UUID_TEXT)
        return self._connection.execute(text(sql), params or {})


class _SessionEngine:
    def __init__(self, session):
        self._session = session

    @contextmanager
    def connect(self):
        yield _SqliteConnection(self._session.connection())


@pytest.fixture
def engine(db_session):
    raw = db_session.connection().connection.driver_connection
    raw.create_aggregate("array_agg", 1, _ArrayAgg)
    return _SessionEngine(db_session)


def _asset_type(db, name):
    asset_type = db.query(AssetTypeDb).filter_by(name=name).first()
    if asset_type is None:
        asset_type = AssetTypeDb(name=name, category="data", is_system=True, status="active")
        db.add(asset_type)
        db.flush()
    return asset_type


def _governed_asset(db, type_name, fqn):
    """An asset of the given type that implements a contract behind an active product."""
    asset = AssetDb(name=fqn.rsplit(".", 1)[-1], asset_type_id=_asset_type(db, type_name).id,
                    platform="databricks", location=fqn, status="active")
    contract = DataContractDb(id=f"c-{uuid.uuid4().hex[:6]}", name="revenue",
                              version="1.0", status="active")
    product = DataProductDb(id=f"p-{uuid.uuid4().hex[:6]}", api_version="v1.0.0",
                            kind="DataProduct", status="deprecated", name="sales",
                            version="1.0")
    db.add_all([asset, contract, product])
    db.flush()
    db.add(EntityRelationshipDb(source_type=type_name, source_id=str(asset.id),
                                target_type="DataContract", target_id=contract.id,
                                relationship_type="implementsContract"))
    db.add(OutputPortDb(product_id=product.id, name="sales-port", version="1",
                        contract_id=contract.id, asset_type="view", asset_identifier=fqn))
    domain = DataDomain(name=f"Sales-{uuid.uuid4().hex[:6]}", created_by="t@example.com")
    db.add(domain)
    db.flush()
    db.add(EntityDomainAssociationDb(domain_id=domain.id, entity_id=str(asset.id),
                                     entity_type="asset", is_primary=True))
    db.flush()
    return asset


def _row_for(tag_sync, engine, fqn):
    rows = [r for r in tag_sync.read_assets_and_links(engine) if r["physical_name"] == fqn]
    assert len(rows) == 1, rows
    return rows[0]


_PER_ASSET = {"asset_id", "asset_name", "physical_name", "asset_type_name", "contract_id",
              "product_id", "domain_id", "domain_name"}


def test_a_metric_view_asset_is_read_and_tagged_like_a_view(tag_sync, engine, db_session,
                                                           default_configs):
    view_fqn = f"main.sales.v_{uuid.uuid4().hex[:6]}"
    metric_fqn = f"main.sales.m_{uuid.uuid4().hex[:6]}"
    _governed_asset(db_session, "View", view_fqn)
    _governed_asset(db_session, "Metric View", metric_fqn)

    view_row = _row_for(tag_sync, engine, view_fqn)
    metric_row = _row_for(tag_sync, engine, metric_fqn)

    # Same contract, product and lifecycle data reach the metric view
    assert metric_row["contract_name"] == view_row["contract_name"] == "revenue"
    assert metric_row["product_status"] == view_row["product_status"] == "deprecated"
    assert metric_row["domain_name"] is not None
    assert {k: v for k, v in metric_row.items() if k not in _PER_ASSET} == {
        k: v for k, v in view_row.items() if k not in _PER_ASSET}

    [view_info] = tag_sync.build_asset_tag_infos([view_row], None, None)
    [metric_info] = tag_sync.build_asset_tag_infos([metric_row], None, None)
    view_tags = tag_sync.build_desired_for_dataset(view_info, default_configs)
    metric_tags = tag_sync.build_desired_for_dataset(metric_info, default_configs)
    assert metric_tags["ontos_lifecycle_status"] == "deprecated"
    assert set(metric_tags) == set(view_tags)

    # Reconciled with the same object type as a view (no DDL change)
    desired = tag_sync._build_desired_set([view_info, metric_info], tag_sync.DirectLinkInfos())
    assert desired == {("TABLE", view_fqn.lower()): True, ("TABLE", metric_fqn.lower()): True}
