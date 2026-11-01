"""A Unity Catalog metric view is an asset of its own type, Metric View (#1124).

It was imported as a plain View (#1079 typed it as uc_metric but the importer
mapped it to View), so it could not be certified or deprecated as a metric view.
ontos:MetricView is a subclass of ontos:View: it keeps every relationship a view
has, and the places that treat tables and views alike include it.
"""
import json
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
from src.db_models.change_log import ChangeLogDb
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
from src.models.entity_relationships import EntityRelationshipCreate
from src.models.schema_import import ImportDepth, ImportRequest

ONTOS = "http://ontos.app/ontology#"
TTL = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"
METRIC_VIEW = "main.sales.revenue_metrics"
PLAIN_VIEW = "main.sales.v_orders"


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
            PLAIN_VIEW: AssetMetadata(
                identifier=PLAIN_VIEW, name="v_orders",
                asset_type=UnifiedAssetType.UC_VIEW, connector_type="databricks",
                schema_info=SchemaInfo(columns=[ColumnInfo(name="id", data_type="INT")])),
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


def _legacy_view(db, asset_types, location=METRIC_VIEW):
    """A metric view imported as a View before the Metric View type, with its links."""
    name = location.rsplit(".", 1)[-1]
    legacy = AssetsManager().create_asset(db, asset_in=AssetCreate(
        name=name, asset_type_id=asset_types["View"].id,
        platform="databricks", location=location,
    ), current_user_id="u@x.com")
    vid = str(legacy.id)
    for source, relationship, target in (
        (("Schema", "schema-1"), "hasView", ("View", vid)),
        (("View", vid), "hasColumn", ("Column", "column-1")),
        (("OutputPort", "port-1"), "portHasView", ("View", vid)),
        (("View", vid), "implementsContract", ("DataContract", "contract-1")),
    ):
        db.add(EntityRelationshipDb(
            source_type=source[0], source_id=source[1], target_type=target[0],
            target_id=target[1], relationship_type=relationship))
    db.flush()
    return legacy


def _links_of(db, asset_id):
    aid = str(asset_id)
    return sorted(
        (r.source_type, r.relationship_type, r.target_type)
        for r in db.query(EntityRelationshipDb).all()
        if aid in (r.source_id, r.target_id)
    )


def _retyped_entries(db, asset_id):
    return [c for c in db.query(ChangeLogDb).filter_by(
        entity_type="asset", entity_id=str(asset_id), action="retyped").all()]


def test_a_metric_view_imported_earlier_as_a_view_is_previewed_as_the_same_asset(
        db_session, asset_types):
    legacy = _legacy_view(db_session, asset_types)

    items = {i.path: i for i in _importer().preview_import(db_session, _request())}

    assert items[METRIC_VIEW].asset_type == "Metric View"
    assert items[METRIC_VIEW].will_create is False
    assert items[METRIC_VIEW].existing_asset_id == legacy.id
    db_session.refresh(db_session.get(AssetDb, legacy.id))
    assert db_session.get(AssetDb, legacy.id).asset_type.name == "View"  # preview only


def test_a_legacy_view_reimported_as_a_metric_view_is_converted_with_its_links(
        db_session, asset_types):
    legacy = _legacy_view(db_session, asset_types)

    result = _importer().execute_import(db_session, _request(), current_user_id="u@x.com")

    assert result.errors == 0, result.error_messages
    [asset] = _assets_at(db_session, METRIC_VIEW)
    assert asset.id == legacy.id  # converted, not duplicated
    assert asset.asset_type.name == "Metric View"
    links = _links_of(db_session, asset.id)
    assert ("Metric View", "hasColumn", "Column") in links
    assert ("Metric View", "implementsContract", "DataContract") in links
    assert ("OutputPort", "portHasView", "Metric View") in links
    assert ("Schema", "hasView", "Metric View") in links
    assert not [link for link in links if "View" in (link[0], link[2])]
    [entry] = _retyped_entries(db_session, asset.id)
    assert entry.username == "u@x.com"
    assert json.loads(entry.details_json) == {
        "location": METRIC_VIEW, "from_type": "View", "to_type": "Metric View",
        "relationships_rewritten": 4,
    }


def test_a_second_import_of_a_converted_metric_view_changes_nothing(db_session, asset_types):
    legacy = _legacy_view(db_session, asset_types)
    _importer().execute_import(db_session, _request(), current_user_id="u@x.com")
    links = _links_of(db_session, legacy.id)

    result = _importer().execute_import(db_session, _request(), current_user_id="u@x.com")

    assert result.errors == 0, result.error_messages
    [asset] = _assets_at(db_session, METRIC_VIEW)
    assert asset.asset_type.name == "Metric View"
    assert _links_of(db_session, asset.id) == links
    assert len(_retyped_entries(db_session, asset.id)) == 1


def test_a_plain_view_and_views_outside_the_import_are_untouched(db_session, asset_types):
    plain = _legacy_view(db_session, asset_types, location=PLAIN_VIEW)
    outside = _legacy_view(db_session, asset_types, location="main.sales.other_view")
    request = ImportRequest(connection_id=uuid4(), selected_paths=[METRIC_VIEW, PLAIN_VIEW],
                            depth=ImportDepth.ONE_LEVEL)

    result = _importer().execute_import(db_session, request, current_user_id="u@x.com")

    assert result.errors == 0, result.error_messages
    for view in (plain, outside):
        asset = db_session.get(AssetDb, view.id)
        assert asset.asset_type.name == "View"
        assert ("View", "hasColumn", "Column") in _links_of(db_session, view.id)
        assert _retyped_entries(db_session, view.id) == []


def test_a_legacy_view_stays_a_view_without_the_seeded_type(db_session, asset_types):
    legacy = _legacy_view(db_session, asset_types)
    links = _links_of(db_session, legacy.id)
    db_session.delete(asset_types["Metric View"])
    db_session.flush()

    items = {i.path: i for i in _importer().preview_import(db_session, _request())}
    result = _importer().execute_import(db_session, _request(), current_user_id="u@x.com")

    assert items[METRIC_VIEW].asset_type == "View"
    assert result.errors == 0, result.error_messages
    [asset] = _assets_at(db_session, METRIC_VIEW)
    assert asset.asset_type.name == "View"
    assert set(links) <= set(_links_of(db_session, asset.id))  # still typed View
    assert _retyped_entries(db_session, asset.id) == []


def test_a_failed_conversion_is_an_item_error_and_the_import_goes_on(
        db_session, asset_types, monkeypatch):
    legacy = _legacy_view(db_session, asset_types)
    links = _links_of(db_session, legacy.id)
    importer = _importer()
    real_retype = importer._assets.retype_asset

    def _retype_then_fail(db, **kwargs):
        real_retype(db, **kwargs)  # writes the conversion, then something breaks
        raise RuntimeError("secret: connection reset by db.internal:5432")

    monkeypatch.setattr(importer._assets, "retype_asset", _retype_then_fail)

    result = importer.execute_import(db_session, _request(), current_user_id="u@x.com")

    assert result.errors == 1
    [error] = [i for i in result.items if i.action == "error"]
    assert error.path == METRIC_VIEW
    assert error.error == "The existing View asset could not be converted to a Metric View."
    assert "secret" not in " ".join(result.error_messages)
    # The partial conversion was rolled back with its savepoint
    asset = db_session.get(AssetDb, legacy.id)
    db_session.refresh(asset)
    assert asset.asset_type.name == "View"
    assert set(links) <= set(_links_of(db_session, legacy.id))
    assert not [link for link in _links_of(db_session, legacy.id) if "Metric View" in link]
    assert _retyped_entries(db_session, legacy.id) == []
    # The rest of the import went on: the columns were created
    assert {a.name for a in _assets_at(db_session, f"{METRIC_VIEW}.Region")} == {"Region"}


def test_the_conversion_in_an_import_does_not_commit(db_session, asset_types, monkeypatch):
    legacy = _legacy_view(db_session, asset_types)
    commits = []
    real_retype = AssetsManager.retype_asset

    def _spy(self, db, **kwargs):
        monkeypatch.setattr(db, "commit", lambda: commits.append("commit"))
        try:
            return real_retype(self, db, **kwargs)
        finally:
            monkeypatch.undo()

    monkeypatch.setattr(AssetsManager, "retype_asset", _spy)

    result = _importer().execute_import(db_session, _request(), current_user_id="u@x.com")

    assert result.errors == 0, result.error_messages
    assert commits == []
    assert db_session.get(AssetDb, legacy.id).asset_type.name == "Metric View"
    assert len(_retyped_entries(db_session, legacy.id)) == 1


def test_a_link_that_already_exists_under_the_new_type_is_merged(db_session, asset_types):
    legacy = _legacy_view(db_session, asset_types)
    vid = str(legacy.id)
    # The same hasColumn link, already written once with the new type name
    db_session.add(EntityRelationshipDb(
        source_type="Metric View", source_id=vid, target_type="Column",
        target_id="column-1", relationship_type="hasColumn"))
    db_session.flush()
    manager = AssetsManager()

    rewritten = manager.retype_asset(
        db_session, asset_id=legacy.id, from_type="View", to_type="Metric View",
        current_user_id="u@x.com")

    assert rewritten == 4
    column_links = [
        r for r in db_session.query(EntityRelationshipDb).all()
        if r.source_id == vid and r.relationship_type == "hasColumn"
    ]
    assert [(r.source_type, r.target_id) for r in column_links] == [("Metric View", "column-1")]
    assert not [link for link in _links_of(db_session, legacy.id) if "View" in link]
    assert manager.retype_asset(
        db_session, asset_id=legacy.id, from_type="View", to_type="Metric View",
        current_user_id="u@x.com") == -1


def test_a_converted_metric_view_works_in_the_hierarchy_and_on_ports(
        db_session, asset_types, osm):
    legacy = _legacy_view(db_session, asset_types)
    _importer().execute_import(db_session, _request(), current_user_id="u@x.com")
    manager = EntityRelationshipsManager(osm)

    tree = manager.get_entity_hierarchy(db_session, "Metric View", str(legacy.id))
    link = manager.create_relationship(db_session, EntityRelationshipCreate(
        source_type="OutputPort", source_id="port-2", target_type="Metric View",
        target_id=str(legacy.id), relationship_type="portHasView",
    ), current_user_id="u@x.com")

    assert tree is not None
    column_children = [c for c in tree.children if c.entity_type == "Column"]
    assert {c.name for c in column_children} >= {"Region", "Total Revenue"}
    assert link.target_type == "Metric View"


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
