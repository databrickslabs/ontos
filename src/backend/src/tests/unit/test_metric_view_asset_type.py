"""A Unity Catalog metric view is an asset of its own type, Metric View (#1124).

It was imported as a plain View (#1079 typed it as uc_metric but the importer
mapped it to View), so it could not be certified or deprecated as a metric view.
ontos:MetricView is a subclass of ontos:View: it keeps every relationship a view
has, and the places that treat tables and views alike include it.
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

from src.common.workflow_executor import EntityActionStepHandler, StepContext
from src.controller.assets_manager import AssetsManager
from src.controller.entity_relationships_manager import EntityRelationshipsManager
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.controller.schema_import_manager import SchemaImportManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.entity_relationships import EntityRelationshipDb
from src.models.assets import (
    AssetCreate,
    AssetMetadata,
    AssetStatus,
    AssetUpdate,
    ColumnInfo,
    SchemaInfo,
    UnifiedAssetType,
)
from src.models.schema_import import ImportDepth, ImportRequest

ONTOS = "http://ontos.app/ontology#"
TTL = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"
METRIC_VIEW = "main.sales.revenue_metrics"


@pytest.fixture(scope="module")
def osm():
    graph = ConjunctiveGraph()
    graph.get_context(URIRef(OntologySchemaManager.BASE_ONTOLOGY_CONTEXT)).parse(
        str(TTL), format="turtle")
    return OntologySchemaManager(SimpleNamespace(_graph=graph))


@pytest.fixture
def asset_types(db_session, osm):
    """Asset types seeded from the ontology, as at startup."""
    osm.sync_asset_types(db_session)
    return {t.name: t for t in db_session.query(AssetTypeDb).all()}


# --- Ontology ----------------------------------------------------------------


def test_the_ontology_has_a_metric_view_asset_class_under_view(osm):
    types = {t.local_name: t for t in osm.get_entity_types(tier="asset")}

    metric_view = types["MetricView"]
    assert metric_view.label == "Metric View"
    assert metric_view.parent_class == f"{ONTOS}View"
    assert metric_view.ui_category == "data"


def test_a_metric_view_has_the_relationships_of_a_view(osm):
    rels = osm.get_relationships(f"{ONTOS}MetricView")

    outgoing = {r.property_name for r in rels.outgoing}
    incoming = {(r.property_name, r.source_type_iri) for r in rels.incoming}
    assert {"hasColumn", "implementsContract", "ownedByTeam"} <= outgoing
    assert ("hasView", f"{ONTOS}Schema") in incoming
    assert ("portHasView", f"{ONTOS}OutputPort") in incoming


@pytest.mark.parametrize("source, relationship, target", [
    ("Schema", "hasView", "Metric View"),
    ("Metric View", "hasColumn", "Column"),
    ("OutputPort", "portHasView", "Metric View"),
    ("Metric View", "implementsContract", "DataContract"),
])
def test_relationships_by_asset_type_name_are_validated_on_the_metric_view_class(
        osm, source, relationship, target):
    # Asset type names are class labels: 'Metric View' is ontos:MetricView
    manager = EntityRelationshipsManager(osm)

    assert manager._validate_relationship(source, target, relationship)


def test_a_metric_view_in_the_hierarchy_lists_its_columns(osm):
    manager = EntityRelationshipsManager(osm)

    rels = osm.get_hierarchy_relationships(manager._normalize_entity_type("Metric View"))

    assert "hasColumn" in {r.property_name for r in rels}


def test_the_startup_sync_seeds_the_metric_view_asset_type(asset_types):
    metric_view = asset_types["Metric View"]
    assert metric_view.is_system is True
    assert metric_view.category == "data"
    assert "View" in asset_types


# --- Import ------------------------------------------------------------------


class _Connector:
    connector_type = "databricks"

    def __init__(self):
        columns = [
            ColumnInfo(name="Region", data_type="STRING"),
            ColumnInfo(name="Total Revenue", data_type="DECIMAL"),
        ]
        self._metadata = {
            "main": AssetMetadata(
                identifier="main", name="main", asset_type=UnifiedAssetType.UC_CATALOG,
                connector_type="databricks"),
            "main.sales": AssetMetadata(
                identifier="main.sales", name="sales", asset_type=UnifiedAssetType.UC_SCHEMA,
                connector_type="databricks"),
            METRIC_VIEW: AssetMetadata(
                identifier=METRIC_VIEW, name="revenue_metrics",
                asset_type=UnifiedAssetType.UC_METRIC, connector_type="databricks",
                schema_info=SchemaInfo(columns=columns)),
        }

    def get_asset_metadata(self, path):
        return self._metadata.get(path)

    def list_assets(self, options=None):
        return []

    def list_containers(self, parent_path=None):
        return []


def _importer():
    connections = MagicMock()
    connections.get_connector_for_connection.return_value = _Connector()
    return SchemaImportManager(connections, AssetsManager())


def _request():
    return ImportRequest(
        connection_id=uuid4(), selected_paths=[METRIC_VIEW], depth=ImportDepth.ONE_LEVEL)


def _assets_at(db, location):
    return db.query(AssetDb).filter(AssetDb.location == location).all()


def test_a_metric_view_is_previewed_as_a_metric_view(db_session, asset_types):
    items = {i.path: i for i in _importer().preview_import(db_session, _request())}

    assert items[METRIC_VIEW].asset_type == "Metric View"
    assert items[METRIC_VIEW].will_create is True
    assert items[f"{METRIC_VIEW}.Region"].asset_type == "Column"


def test_an_imported_metric_view_is_a_metric_view_asset_with_its_columns(
        db_session, asset_types):
    result = _importer().execute_import(db_session, _request(), current_user_id="u@x.com")

    assert result.errors == 0, result.error_messages
    [asset] = _assets_at(db_session, METRIC_VIEW)
    assert asset.asset_type.name == "Metric View"
    rels = {
        (r.source_type, r.relationship_type, r.target_type)
        for r in db_session.query(EntityRelationshipDb).all()
    }
    assert ("Schema", "hasView", "Metric View") in rels
    assert ("Metric View", "hasColumn", "Column") in rels


def test_a_metric_view_imported_earlier_as_a_view_is_reused_not_duplicated(
        db_session, asset_types):
    legacy = AssetsManager().create_asset(db_session, asset_in=AssetCreate(
        name="revenue_metrics", asset_type_id=asset_types["View"].id,
        platform="databricks", location=METRIC_VIEW,
    ), current_user_id="u@x.com")

    items = {i.path: i for i in _importer().preview_import(db_session, _request())}
    result = _importer().execute_import(db_session, _request(), current_user_id="u@x.com")

    assert items[METRIC_VIEW].asset_type == "View"
    assert items[METRIC_VIEW].will_create is False
    assert items[METRIC_VIEW].existing_asset_id == legacy.id
    assert result.errors == 0, result.error_messages
    [asset] = _assets_at(db_session, METRIC_VIEW)
    assert asset.id == legacy.id
    assert asset.asset_type.name == "View"  # not retyped


def test_a_metric_view_imports_as_a_view_until_the_type_is_seeded(db_session, asset_types):
    db_session.delete(asset_types["Metric View"])
    db_session.flush()

    result = _importer().execute_import(db_session, _request(), current_user_id="u@x.com")

    assert result.errors == 0, result.error_messages
    [asset] = _assets_at(db_session, METRIC_VIEW)
    assert asset.asset_type.name == "View"


# --- Status and certification --------------------------------------------------


def _imported_metric_view(db_session):
    _importer().execute_import(db_session, _request(), current_user_id="u@x.com")
    [asset] = _assets_at(db_session, METRIC_VIEW)
    return asset


def test_an_imported_metric_view_can_be_deprecated(db_session, asset_types):
    asset = _imported_metric_view(db_session)

    updated = AssetsManager().update_asset(
        db_session, asset_id=asset.id, asset_in=AssetUpdate(status=AssetStatus.DEPRECATED),
        current_user_id="steward@x.com")

    assert updated.asset_type_name == "Metric View"
    assert updated.status == AssetStatus.DEPRECATED


def test_an_imported_metric_view_can_be_certified_by_a_workflow(db_session, asset_types):
    asset = _imported_metric_view(db_session)
    handler = EntityActionStepHandler(
        db_session, {"action": "certify", "level_source": "fixed", "fixed_level": 2})

    result = handler.execute(StepContext(
        entity={}, entity_type="asset", entity_id=str(asset.id), entity_name=asset.name,
        user_email="steward@x.com", trigger_context=None, execution_id="x-1",
        workflow_id="w-1", workflow_name="Certify", step_results={},
    ))

    assert result.passed is True, result.error
    db_session.refresh(asset)
    assert asset.asset_type.name == "Metric View"
    assert asset.certification_level == 2
    assert asset.certified_by == "steward@x.com"


# --- Tables and views alike ----------------------------------------------------


def test_a_metric_view_infers_a_contract_schema_like_a_view(db_session, asset_types):
    asset = _imported_metric_view(db_session)

    [schema] = AssetsManager().infer_schema_from_asset(db_session, asset.id)

    assert [p["name"] for p in schema["properties"]] == ["Region", "Total Revenue"]


def test_a_contract_schema_object_links_to_its_metric_view(
        db_session, asset_types, monkeypatch):
    from src.controller import data_contracts_manager as dcm

    asset = _imported_metric_view(db_session)
    contract = SimpleNamespace(schema_objects=[
        SimpleNamespace(id="so-1", name="revenue_metrics", physical_name=METRIC_VIEW),
    ])
    monkeypatch.setattr(dcm.data_contract_repo, "get_with_all", lambda *_a, **_k: contract)
    manager = dcm.DataContractsManager.__new__(dcm.DataContractsManager)

    result = manager.auto_link_schema_to_assets(db_session, "c-1", current_user="u@x.com")

    links = [c for c in result["created"] if c["relationship_type"] == "implementsContract"]
    assert [(c["asset_id"], c["asset_type"]) for c in links] == [(str(asset.id), "Metric View")]


def test_the_physical_table_types_include_metric_views():
    from src.controller import assets_manager, data_catalog_manager, model_lineage

    assert "Metric View" in model_lineage.PHYSICAL_TABLE_TYPES
    assert "Metric View" in data_catalog_manager._TABLE_LIKE_TYPES
    assert "Metric View" in assets_manager.AssetsManager._TABLE_LIKE_TYPES
