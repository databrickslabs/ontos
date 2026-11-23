"""PUT /api/assets/{id} that changes the type checks the properties against the new type.

The stored properties are kept when the body omits ``properties``; on a type
change they must fit the new type's schema (422 otherwise). Without a type
change an omitted ``properties`` is not checked.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import ConjunctiveGraph, URIRef

from src.app import app
from src.controller.assets_manager import AssetsManager
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.assets import METRIC_VIEW_PROPERTY

TTL = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"


@pytest.fixture(scope="module")
def osm():
    graph = ConjunctiveGraph()
    graph.get_context(URIRef(OntologySchemaManager.BASE_ONTOLOGY_CONTEXT)).parse(
        str(TTL), format="turtle")
    return OntologySchemaManager(SimpleNamespace(_graph=graph))


@pytest.fixture
def wired(client, osm):
    # Plain assignment: the client fixture puts app.state back on teardown
    # (monkeypatch's undo breaks on starlette's State, see test_asset_metadata_access)
    app.state.assets_manager = AssetsManager(ontology_schema_manager=osm)


def _type(db, name):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found is None:
        found = AssetTypeDb(name=name)
        db.add(found)
        db.flush()
    return found


def _asset(db, properties):
    asset = AssetDb(name="pk", asset_type_id=_type(db, "Untyped Thing").id,
                    properties=properties, platform="databricks", location="main.s.t.pk")
    db.add(asset)
    db.commit()
    return asset


def test_a_type_change_without_properties_checks_the_kept_ones(client, db_session, wired):
    asset = _asset(db_session, {"isPrimaryKey": "yes", METRIC_VIEW_PROPERTY: {"source": "x"}})

    response = client.put(f"/api/assets/{asset.id}",
                          json={"asset_type_id": str(_type(db_session, "Column").id)})

    # The request's rollback undoes the save (and, in this test DB, the fixture rows)
    assert response.status_code == 422, response.text
    assert "validation failed for type 'Column'" in response.json()["detail"]


def test_a_type_change_keeps_properties_that_fit_the_new_type(client, db_session, wired):
    stored = {"isPrimaryKey": True, METRIC_VIEW_PROPERTY: {"source": "x"}}
    asset = _asset(db_session, dict(stored))
    column_id = _type(db_session, "Column").id

    response = client.put(f"/api/assets/{asset.id}", json={"asset_type_id": str(column_id)})

    assert response.status_code == 200, response.text
    db_session.expire_all()
    saved = db_session.get(AssetDb, asset.id)
    assert (saved.asset_type_id, saved.properties) == (column_id, stored)


def test_without_a_type_change_omitted_properties_are_not_checked(client, db_session, wired):
    """Only what an update changes is checked: a stored value the schema refuses
    doesn't block an edit of another field."""
    column = _type(db_session, "Column")
    asset = AssetDb(name="legacy", asset_type_id=column.id, properties={"isPrimaryKey": "yes"},
                    platform="databricks", location="main.s.t.legacy")
    db_session.add(asset)
    db_session.commit()

    response = client.put(f"/api/assets/{asset.id}", json={"name": "legacy2"})

    assert response.status_code == 200, response.text
