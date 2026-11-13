"""An asset edit may send the properties the Edit dialog doesn't show.

The dialog now sends a column's stored properties (``data_type``, ``nullable``,
``comment`` from a Unity Catalog import) together with the ontology fields it
edits; the ontology's JSON schema validation must accept them and the update
must keep them.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import ConjunctiveGraph, URIRef

from src.controller.assets_manager import AssetsManager
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.models.assets import METRIC_VIEW_PROPERTY, AssetUpdate

TTL = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"


@pytest.fixture(scope="module")
def osm():
    graph = ConjunctiveGraph()
    graph.get_context(URIRef(OntologySchemaManager.BASE_ONTOLOGY_CONTEXT)).parse(
        str(TTL), format="turtle")
    return OntologySchemaManager(SimpleNamespace(_graph=graph))


def _column_type(db):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == "Column").first()
    if found:
        return found
    created = AssetTypeDb(name="Column")
    db.add(created)
    db.flush()
    return created


def test_an_edit_with_imported_column_properties_is_valid_and_kept(db_session, osm):
    column = AssetDb(
        name="order_date", asset_type_id=_column_type(db_session).id,
        properties={"data_type": "DATE", "nullable": True, "comment": "Order day"},
    )
    db_session.add(column)
    db_session.flush()
    edited = {"data_type": "DATE", "nullable": True, "comment": "Order day", "isPrimaryKey": True}

    updated = AssetsManager(ontology_schema_manager=osm).update_asset(
        db_session, asset_id=column.id, asset_in=AssetUpdate(properties=edited),
        current_user_id="alice@example.com",
    )

    assert updated.properties == edited


def test_the_column_schema_is_applied(db_session, osm):
    """Guards the test above: the Column schema does validate the ontology fields."""
    from src.common.errors import ValidationError

    column = AssetDb(name="order_id", asset_type_id=_column_type(db_session).id, properties={})
    db_session.add(column)
    db_session.flush()

    with pytest.raises(ValidationError):
        AssetsManager(ontology_schema_manager=osm).update_asset(
            db_session, asset_id=column.id,
            asset_in=AssetUpdate(properties={"data_type": "BIGINT", "isPrimaryKey": "yes"}),
            current_user_id="alice@example.com",
        )


def test_an_edit_that_clears_every_property(db_session, osm):
    """The dialog sends {} when the user clears the last property: it is cleared."""
    column = AssetDb(
        name="note", asset_type_id=_column_type(db_session).id,
        properties={"classification": "internal", METRIC_VIEW_PROPERTY: {"source": "x"}},
    )
    db_session.add(column)
    db_session.flush()

    updated = AssetsManager(ontology_schema_manager=osm).update_asset(
        db_session, asset_id=column.id, asset_in=AssetUpdate(properties={}),
        current_user_id="alice@example.com",
    )

    assert not updated.properties
    # The keys Ontos keeps for itself (never sent to clients) survive
    db_session.expire_all()
    assert db_session.get(AssetDb, column.id).properties == {METRIC_VIEW_PROPERTY: {"source": "x"}}


def test_a_stored_value_the_schema_refuses_does_not_block_other_edits(db_session, osm):
    """Only the properties an update changes are validated: a legacy value that
    doesn't fit the schema doesn't block an edit of another field."""
    from src.common.errors import ValidationError

    column = AssetDb(
        name="legacy", asset_type_id=_column_type(db_session).id,
        properties={"isPrimaryKey": "yes"},
    )
    db_session.add(column)
    db_session.flush()
    manager = AssetsManager(ontology_schema_manager=osm)

    updated = manager.update_asset(
        db_session, asset_id=column.id,
        asset_in=AssetUpdate(properties={"isPrimaryKey": "yes", "isNullable": True}),
        current_user_id="alice@example.com",
    )
    assert updated.properties == {"isPrimaryKey": "yes", "isNullable": True}

    with pytest.raises(ValidationError):
        manager.update_asset(
            db_session, asset_id=column.id,
            asset_in=AssetUpdate(properties={"isPrimaryKey": "yes", "isNullable": "no"}),
            current_user_id="alice@example.com",
        )
