"""The spec and fingerprints of a metric view are stored on its asset (#1263, phase 1).

``AssetDb.properties['metric_view']`` is written at import, at re-import and
when the view is read from Unity Catalog through the asset route. It holds the
view's definition, so asset reads and exports leave it out, and an update
from a client (which never saw it) keeps it.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from databricks.sdk.service.catalog import TableType
from rdflib import ConjunctiveGraph, URIRef

from src.common.metric_view_fingerprint import FINGERPRINT_VERSION
from src.common.metric_views import parse_metric_view_definition
from src.controller.asset_bulk_manager import _format_properties
from src.controller.assets_manager import AssetsManager
from src.controller.metric_view_consistency_manager import (
    STORE_KEY, build_stored_metric_view, store_metric_view,
)
from src.controller.metric_views_manager import MetricViewsManager
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.controller.schema_import_manager import SchemaImportManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.assets import (
    AssetCreate, AssetMetadata, AssetRead, AssetUpdate, UnifiedAssetType, public_properties,
)
from src.models.metric_views import MetricViewLinks
from src.models.schema_import import ImportDepth, ImportRequest

TTL = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"
VIEW = "main.sales.revenue_metrics"
SPEC = """\
version: 1.1
source: main.sales.orders
measures:
  - name: Total Revenue
    expr: SUM(amount)
"""
CHANGED = SPEC.replace("SUM(amount)", "SUM(net_amount)")


@pytest.fixture(scope="module")
def osm():
    graph = ConjunctiveGraph()
    graph.get_context(URIRef(OntologySchemaManager.BASE_ONTOLOGY_CONTEXT)).parse(
        str(TTL), format="turtle")
    return OntologySchemaManager(SimpleNamespace(_graph=graph))


@pytest.fixture
def asset_types(db_session, osm):
    osm.sync_asset_types(db_session)
    return {t.name: t for t in db_session.query(AssetTypeDb).all()}


class _Connector:
    """A Unity Catalog connector whose metric view has the definition ``self.definition``."""
    connector_type = "databricks"

    def __init__(self, definition=SPEC):
        self.definition = definition

    def get_asset_metadata(self, path):
        kinds = {"main": UnifiedAssetType.UC_CATALOG, "main.sales": UnifiedAssetType.UC_SCHEMA,
                 VIEW: UnifiedAssetType.UC_METRIC}
        if path not in kinds:
            return None
        properties = {}
        if path == VIEW:
            # As the Databricks connector reports a metric view
            properties["metric_view"] = parse_metric_view_definition(self.definition)
        return AssetMetadata(
            identifier=path, name=path.rsplit(".", 1)[-1], asset_type=kinds[path],
            connector_type="databricks", properties=properties,
        )

    def list_assets(self, options=None):
        return []

    def list_containers(self, parent_path=None):
        return []


def _import(db, connector):
    connections = MagicMock()
    connections.get_connector_for_connection.return_value = connector
    result = SchemaImportManager(connections, AssetsManager()).execute_import(
        db, ImportRequest(connection_id=uuid4(), selected_paths=[VIEW],
                          depth=ImportDepth.SELECTED_ONLY),
        current_user_id="u@x.com",
    )
    assert result.errors == 0, result.error_messages
    [asset] = db.query(AssetDb).filter(AssetDb.location == VIEW).all()
    return asset


def _metric_views(db):
    links = MagicMock()
    links.list_for_metric_view.return_value = MetricViewLinks(view_entity_id=VIEW)
    return MetricViewsManager(db, links)


def _expressions(asset):
    return [m["components"]["expression"] for m in asset.properties[STORE_KEY]["measures"]]


def test_an_imported_metric_view_stores_its_spec_and_fingerprints(db_session, asset_types):
    asset = _import(db_session, _Connector())

    stored = asset.properties[STORE_KEY]
    assert asset.asset_type.name == "Metric View"
    assert stored["spec"] == parse_metric_view_definition(SPEC)
    assert stored["fingerprint_version"] == FINGERPRINT_VERSION
    [measure] = stored["measures"]
    assert measure["name"] == "Total Revenue"
    assert set(measure["digests"]) == {"expression", "scope", "full"}
    assert measure["footprint"]["columns"] == ["main.sales.orders.amount"]


def test_a_reimport_refreshes_the_stored_fingerprints(db_session, asset_types):
    asset = _import(db_session, _Connector())
    before = asset.properties[STORE_KEY]["measures"][0]["digests"]

    asset = _import(db_session, _Connector(CHANGED))

    assert _expressions(asset) == ["sum(net_amount)"]
    assert asset.properties[STORE_KEY]["measures"][0]["digests"] != before


def test_a_legacy_view_converted_on_reimport_gets_fingerprints(db_session, asset_types):
    AssetsManager().create_asset(db_session, asset_in=AssetCreate(
        name="revenue_metrics", asset_type_id=asset_types["View"].id,
        platform="databricks", location=VIEW,
    ), current_user_id="u@x.com")

    asset = _import(db_session, _Connector())

    assert asset.asset_type.name == "Metric View"
    assert _expressions(asset) == ["sum(amount)"]


def test_reading_the_metric_view_refreshes_the_stored_fingerprints(db_session, asset_types):
    asset = _import(db_session, _Connector())
    ws = MagicMock()
    ws.tables.get.return_value = SimpleNamespace(
        table_type=TableType.METRIC_VIEW, view_definition=CHANGED)

    _metric_views(db_session).get_for_asset(asset.id, ws)

    db_session.refresh(asset)
    assert _expressions(asset) == ["sum(net_amount)"]


def test_reading_a_plain_view_asset_stores_nothing(db_session, asset_types):
    asset = AssetsManager().create_asset(db_session, asset_in=AssetCreate(
        name="revenue_metrics", asset_type_id=asset_types["View"].id,
        platform="databricks", location=VIEW,
    ), current_user_id="u@x.com")
    ws = MagicMock()
    ws.tables.get.return_value = SimpleNamespace(
        table_type=TableType.METRIC_VIEW, view_definition=SPEC)

    _metric_views(db_session).get_for_asset(asset.id, ws)

    assert STORE_KEY not in (db_session.get(AssetDb, asset.id).properties or {})


def test_storing_the_same_spec_again_changes_nothing(db_session, asset_types):
    asset = _import(db_session, _Connector())
    stored_at = asset.properties[STORE_KEY]["stored_at"]

    assert store_metric_view(db_session, asset, parse_metric_view_definition(SPEC)) is False
    assert asset.properties[STORE_KEY]["stored_at"] == stored_at
    assert store_metric_view(db_session, asset, None) is False


def test_asset_reads_and_exports_leave_the_stored_definition_out(db_session, asset_types):
    asset = _import(db_session, _Connector())
    asset.properties = {**asset.properties, "owner_note": "kept"}
    db_session.flush()

    read = AssetsManager().get_asset(db_session, asset_id=asset.id)

    assert STORE_KEY not in (read.properties or {})
    assert read.properties["owner_note"] == "kept"
    assert STORE_KEY not in AssetRead.model_validate(asset).properties
    assert STORE_KEY not in _format_properties(asset.properties)
    assert public_properties(None) is None


def test_an_update_from_a_client_keeps_the_stored_definition(db_session, asset_types):
    asset = _import(db_session, _Connector())

    AssetsManager().update_asset(
        db_session, asset_id=asset.id,
        asset_in=AssetUpdate(properties={"owner_note": "new"}), current_user_id="u@x.com",
    )

    db_session.refresh(asset)
    assert asset.properties["owner_note"] == "new"
    assert _expressions(asset) == ["sum(amount)"]


def test_without_a_spec_nothing_is_built():
    assert build_stored_metric_view(None) is None
