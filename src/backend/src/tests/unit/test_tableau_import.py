"""Importing Tableau content through the schema importer (#1312 slice 2).

Projects become Folders, workbooks Reports, views Dashboards, published data
sources Semantic Models with their fields as Columns. Lineage the connector
declares is wired to Unity Catalog assets already in Ontos; targets that are not
in Ontos are reported as import warnings.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from rdflib import ConjunctiveGraph, URIRef

from src.connectors.tableau import (
    TableauConnector,
    TableauConnectorConfig,
    clear_listing_cache,
    parse_bracketed_name,
    uc_table_name,
)
from src.connectors.tableau_client import GraphQLResult, TableauAPIError
from src.controller.assets_manager import AssetsManager
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.controller.schema_import_manager import SchemaImportManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.models.assets import UnifiedAssetType
from src.models.schema_import import ImportDepth, ImportRequest

TTL = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"

PROJECTS = [{"id": "p1", "name": "Finance"}, {"id": "p2", "name": "Shared", "parentProjectId": "p1"}]
WORKBOOKS = [{"id": "wb1", "name": "Orders Overview", "project": {"id": "p1"}, "webpageUrl": "https://t/#/site/s/workbooks/1"}]
DATASOURCES = [{"id": "ds1", "name": "TPCH Orders", "project": {"id": "p2"}}]
VIEWS = [
    {"id": "v1", "name": "Orders Overview", "contentUrl": "OrdersOverview/sheets/OrdersOverview", "workbook": {"id": "wb1"}},
    {"id": "v2", "name": "Revenue by Status", "contentUrl": "OrdersOverview/sheets/RevenuebyStatus", "workbook": {"id": "wb1"}},
]
ORDERS = {"fullName": "[samples].[tpch].[orders]", "connectionType": "databricks"}
FIELDS = [
    {"__typename": "ColumnField", "name": "Total Price", "description": "Order total", "role": "MEASURE", "dataType": "REAL",
     "columns": [{"name": "o_totalprice", "remoteType": "NUMERIC", "table": ORDERS}]},
    {"__typename": "ColumnField", "name": "Order Key", "role": "DIMENSION", "dataType": "INTEGER",
     "columns": [{"name": "o_orderkey", "remoteType": "I8", "table": ORDERS}]},
    {"__typename": "CalculatedField", "name": "Avg Order Value", "role": "MEASURE", "dataType": "REAL",
     "formula": "SUM([Total Price]) / COUNTD([Order Key])", "fields": [{"name": "Total Price"}, {"name": "Order Key"}]},
]
DS_PATH = "p~p1.p~p2.ds~ds1"
WB_PATH = "p~p1.wb~wb1"


class FakeClient:
    server_url = "https://10xx.online.tableau.com"
    site_content_url = "s"
    identity = "pat:test"

    def paginate(self, path, collection, item, params=None):
        return {"/projects": PROJECTS, "/workbooks": WORKBOOKS, "/datasources": DATASOURCES,
                "/workbooks/wb1/views": VIEWS}.get(path, [])

    def get_json(self, path, params=None):
        bodies = {
            "/workbooks/wb1": {"workbook": WORKBOOKS[0]},
            "/views/v1": {"view": VIEWS[0]},
            "/views/v2": {"view": VIEWS[1]},
            "/datasources/ds1": {"datasource": {**DATASOURCES[0], "type": "databricks"}},
        }
        if path not in bodies:
            raise TableauAPIError("not found", 404)
        return bodies[path]

    def graphql(self, query, variables=None):
        if "WorkbookViews" in query:
            return GraphQLResult({"workbooks": [{
                "upstreamTables": [ORDERS, {"fullName": "[Orders$]", "connectionType": "excel-direct"}],
                # Views read an embedded data source that proxies the published one
                "dashboards": [{"luid": "v1", "upstreamDatasources": [{"upstreamDatasources": [{"luid": "ds1"}]}]}],
                "sheets": [{"luid": "v2", "upstreamDatasources": [{"luid": "ds1"}]}],
            }]})
        return GraphQLResult({"publishedDatasources": [{
            "luid": "ds1", "upstreamTables": [{"name": "orders", "schema": "tpch", **ORDERS}], "fields": FIELDS,
        }]})


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_listing_cache()
    yield
    clear_listing_cache()


@pytest.fixture(scope="module")
def osm():
    graph = ConjunctiveGraph()
    graph.get_context(URIRef(OntologySchemaManager.BASE_ONTOLOGY_CONTEXT)).parse(str(TTL), format="turtle")
    return OntologySchemaManager(SimpleNamespace(_graph=graph))


@pytest.fixture
def asset_types(db_session, osm):
    osm.sync_asset_types(db_session)
    return {t.name: t for t in db_session.query(AssetTypeDb).all()}


@pytest.fixture
def uc_orders(db_session, asset_types):
    """The Unity Catalog table and one of its columns, imported earlier."""
    table = AssetDb(id=uuid4(), name="orders", asset_type_id=asset_types["Table"].id,
                    platform="databricks", location="samples.tpch.orders")
    column = AssetDb(id=uuid4(), name="o_totalprice", asset_type_id=asset_types["Column"].id,
                     platform="databricks", location="samples.tpch.orders.o_totalprice")
    db_session.add_all([table, column])
    db_session.flush()
    return SimpleNamespace(table=table, column=column)


class RecordingSnapshots:
    """Stands in for DashboardSnapshotManager; records which assets were captured."""

    def __init__(self, status="ok"):
        self.status = status
        self.captured = []

    def capture(self, db, *, asset, connector, current_user, force=False):
        self.captured.append(asset.location)
        return {"status": self.status, "error": "refresh token" if self.status != "ok" else None}


def _importer(snapshots=None):
    connector = TableauConnector(TableauConnectorConfig(server_url=FakeClient.server_url, site_content_url="s"), client=FakeClient())
    connections = MagicMock()
    connections.get_connector_for_connection.return_value = connector
    return SchemaImportManager(connections, AssetsManager(), snapshot_manager=snapshots or RecordingSnapshots())


def _import(db, *paths, snapshots=None):
    request = ImportRequest(connection_id=uuid4(), selected_paths=list(paths), depth=ImportDepth.FULL_RECURSIVE)
    return _importer(snapshots).execute_import(db, request, current_user_id="u@example.com")


def _asset(db, location):
    return db.query(AssetDb).filter(AssetDb.location == location, AssetDb.platform == "tableau").one()


def _edges(db):
    return {(r.source_id, r.relationship_type, r.target_id) for r in db.query(EntityRelationshipDb).all()}


# --- Name parsing ------------------------------------------------------------


@pytest.mark.parametrize("full_name,parts", [
    ("[samples].[tpch].[orders]", ["samples", "tpch", "orders"]),
    ("[tpch].[orders]", ["tpch", "orders"]),
    ("[odd]]name].[a.b]", ["odd]name", "a.b"]),
    ("[Orders$]", ["Orders$"]),
    ("", []),
])
def test_parse_bracketed_name(full_name, parts):
    assert parse_bracketed_name(full_name) == parts


def test_uc_table_name_needs_a_databricks_connection_and_a_catalog():
    assert uc_table_name(ORDERS) == "samples.tpch.orders"
    assert uc_table_name({"fullName": "[tpch].[orders]", "connectionType": "databricks"}) is None
    assert uc_table_name({"fullName": "[tpch].[orders]", "connectionType": "spark"}, "main") == "main.tpch.orders"
    assert uc_table_name({"fullName": "[Orders$]", "connectionType": "excel-direct"}, "main") is None


# --- Import ------------------------------------------------------------------


def test_preview_maps_tableau_types_to_ontos_types(db_session, asset_types):
    request = ImportRequest(connection_id=uuid4(), selected_paths=[WB_PATH, DS_PATH], depth=ImportDepth.FULL_RECURSIVE)
    items = {i.path: i.asset_type for i in _importer().preview_import(db_session, request)}

    assert items["p~p1"] == "Folder"
    assert items[WB_PATH] == "Report"
    assert items[f"{WB_PATH}.v~v1"] == "Dashboard"
    assert items[f"{WB_PATH}.v~v2"] == "Dashboard"
    assert items[DS_PATH] == "Semantic Model"
    assert items[f"{DS_PATH}.Avg Order Value"] == "Column"


def test_import_creates_hierarchy_with_tableau_properties(db_session, asset_types, uc_orders):
    result = _import(db_session, WB_PATH, DS_PATH)
    assert result.errors == 0, result.error_messages

    dashboard = _asset(db_session, f"{WB_PATH}.v~v1")
    assert dashboard.asset_type.name == "Dashboard"
    assert dashboard.properties["dashboardPlatform"] == "tableau"
    assert dashboard.properties["dashboardUrl"].endswith("/views/OrdersOverview/OrdersOverview")
    assert dashboard.properties["tableau_luid"] == "v1"

    model = _asset(db_session, DS_PATH)
    assert model.asset_type.name == "Semantic Model"
    aov = _asset(db_session, f"{DS_PATH}.Avg Order Value")
    assert aov.properties["formula"] == "SUM([Total Price]) / COUNTD([Order Key])"
    assert aov.properties["is_calculated"] is True

    edges = _edges(db_session)
    folder, report = _asset(db_session, "p~p1"), _asset(db_session, WB_PATH)
    assert (str(folder.id), "hasPart", str(report.id)) in edges
    assert (str(report.id), "hasPart", str(dashboard.id)) in edges
    assert (str(model.id), "hasColumn", str(aov.id)) in edges


def test_lineage_is_wired_to_unity_catalog_and_between_tableau_assets(db_session, asset_types, uc_orders):
    _import(db_session, WB_PATH, DS_PATH)
    edges = _edges(db_session)
    model = _asset(db_session, DS_PATH)
    price = _asset(db_session, f"{DS_PATH}.Total Price")
    aov = _asset(db_session, f"{DS_PATH}.Avg Order Value")
    dashboard = _asset(db_session, f"{WB_PATH}.v~v1")
    report = _asset(db_session, WB_PATH)

    assert (str(model.id), "consumesFrom", str(uc_orders.table.id)) in edges
    assert (str(report.id), "consumesFrom", str(uc_orders.table.id)) in edges
    assert (str(price.id), "derivedFrom", str(uc_orders.column.id)) in edges
    assert (str(aov.id), "derivedFrom", str(price.id)) in edges
    assert (str(dashboard.id), "consumesFrom", str(model.id)) in edges


def test_lineage_targets_missing_from_ontos_are_warnings(db_session, asset_types, uc_orders):
    result = _import(db_session, DS_PATH)

    assert result.errors == 0
    # o_orderkey was never imported from Unity Catalog
    assert any("samples.tpch.orders.o_orderkey" in w for w in result.warnings)
    assert not any("samples.tpch.orders.o_totalprice" in w for w in result.warnings)


def test_reimport_does_not_duplicate_assets_or_edges(db_session, asset_types, uc_orders):
    _import(db_session, WB_PATH, DS_PATH)
    edges_before = _edges(db_session)
    count_before = db_session.query(AssetDb).count()

    second = _import(db_session, WB_PATH, DS_PATH)

    assert second.created == 0
    assert db_session.query(AssetDb).count() == count_before
    assert _edges(db_session) == edges_before


def test_lineage_links_for_each_asset_kind():
    connector = TableauConnector(TableauConnectorConfig(server_url=FakeClient.server_url, site_content_url="s"), client=FakeClient())
    view_links = connector.lineage_links(f"{WB_PATH}.v~v1", connector.get_asset_metadata(f"{WB_PATH}.v~v1"))
    assert [(l.relationship_type, l.target_path) for l in view_links] == [("consumesFrom", DS_PATH)]

    wb_links = connector.lineage_links(WB_PATH, connector.get_asset_metadata(WB_PATH))
    assert [l.target_location for l in wb_links] == ["samples.tpch.orders"]  # the Excel source is not UC

    ds_links = connector.lineage_links(DS_PATH, connector.get_asset_metadata(DS_PATH))
    assert {(l.source_path.split(".")[-1], l.relationship_type, l.target_location or l.target_path) for l in ds_links} == {
        ("ds~ds1", "consumesFrom", "samples.tpch.orders"),
        ("Total Price", "derivedFrom", "samples.tpch.orders.o_totalprice"),
        ("Order Key", "derivedFrom", "samples.tpch.orders.o_orderkey"),
        ("Avg Order Value", "derivedFrom", f"{DS_PATH}.Total Price"),
        ("Avg Order Value", "derivedFrom", f"{DS_PATH}.Order Key"),
    }


def test_the_ontology_seeds_the_bi_asset_types(asset_types):
    for name in ("Folder", "Report", "Semantic Model", "Dashboard"):
        assert name in asset_types


def test_view_lineage_resolves_to_a_datasource_imported_earlier(db_session, asset_types, uc_orders):
    _import(db_session, DS_PATH)
    result = _import(db_session, WB_PATH)

    dashboard = _asset(db_session, f"{WB_PATH}.v~v1")
    model = _asset(db_session, DS_PATH)
    assert (str(dashboard.id), "consumesFrom", str(model.id)) in _edges(db_session)
    assert not any(DS_PATH in w for w in result.warnings)


def test_import_captures_snapshots_of_dashboards_only(db_session, asset_types, uc_orders):
    snapshots = RecordingSnapshots()
    _import(db_session, WB_PATH, snapshots=snapshots)
    assert snapshots.captured == [f"{WB_PATH}.v~v1"]

    dashboard = _asset(db_session, f"{WB_PATH}.v~v1")
    assert dashboard.properties["connection_id"]


def test_snapshot_failures_are_import_warnings(db_session, asset_types, uc_orders):
    result = _import(db_session, WB_PATH, snapshots=RecordingSnapshots(status="auth_expired"))
    assert result.errors == 0
    assert f"{WB_PATH}.v~v1: snapshot auth_expired (refresh token)" in result.warnings


def test_reimport_refreshes_snapshots_with_the_current_source_timestamp(db_session, asset_types, uc_orders):
    _import(db_session, WB_PATH)
    dashboard = _asset(db_session, f"{WB_PATH}.v~v1")
    dashboard.properties = {k: v for k, v in dashboard.properties.items() if k not in ("connection_id", "source_updated_at")}
    db_session.flush()

    snapshots = RecordingSnapshots()
    _import(db_session, WB_PATH, snapshots=snapshots)

    assert snapshots.captured == [f"{WB_PATH}.v~v1"]
    assert dashboard.properties["connection_id"]


def test_a_failing_snapshot_does_not_fail_the_import(db_session, asset_types, uc_orders):
    class Broken(RecordingSnapshots):
        def capture(self, db, **kwargs):
            raise RuntimeError("volume not writable")
    result = _import(db_session, WB_PATH, snapshots=Broken())
    assert result.errors == 0
    assert f"{WB_PATH}.v~v1: snapshot failed (volume not writable)" in result.warnings
