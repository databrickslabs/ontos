"""Asset types the ontology drops are retired, never deleted with their assets (#970).

``sync_asset_types`` used to delete every system asset type missing from the ontology,
and ``AssetTypeDb.assets`` cascades, so removing BusinessTerm from the TTL would have
deleted every BusinessTerm asset at startup. A type that still has assets is kept and
marked retired; the built-in Legacy Business Term type is always present and retired.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from rdflib import ConjunctiveGraph, URIRef

from src.controller.ontology_schema_manager import OntologySchemaManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.repositories.assets_repository import asset_type_repo

TTL = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"
LEGACY = "Legacy Business Term"


@pytest.fixture(scope="module")
def osm():
    graph = ConjunctiveGraph()
    graph.get_context(URIRef(OntologySchemaManager.BASE_ONTOLOGY_CONTEXT)).parse(
        str(TTL), format="turtle")
    return OntologySchemaManager(SimpleNamespace(_graph=graph))


def _system_type(db, name):
    """A system type the ontology does not define, as left behind by a removed class."""
    t = AssetTypeDb(id=uuid4(), name=name, category="data", is_system=True, status="active",
                    created_by="test")
    db.add(t)
    db.flush()
    return t


def _asset(db, asset_type, name):
    a = AssetDb(id=uuid4(), name=name, asset_type_id=asset_type.id, status="active")
    db.add(a)
    db.flush()
    return a


def test_stale_type_with_assets_is_kept_and_retired(db_session, osm):
    osm.sync_asset_types(db_session)
    gone = _system_type(db_session, "Removed Class")
    asset = _asset(db_session, gone, "kept asset")

    osm.sync_asset_types(db_session)

    db_session.expire_all()
    kept_type = db_session.get(AssetTypeDb, gone.id)
    kept_asset = db_session.get(AssetDb, asset.id)
    assert kept_type is not None
    assert kept_type.status == "retired"
    assert kept_asset is not None
    assert kept_asset.asset_type_id == gone.id


def test_business_term_assets_survive_the_class_leaving_the_ontology(db_session, osm):
    osm.sync_asset_types(db_session)
    term_type = _system_type(db_session, "Business Term")
    terms = [_asset(db_session, term_type, f"term {i}") for i in range(3)]

    osm.sync_asset_types(db_session)

    db_session.expire_all()
    assert db_session.get(AssetTypeDb, term_type.id).status == "retired"
    for term in terms:
        assert db_session.get(AssetDb, term.id).asset_type_id == term_type.id


def test_stale_type_without_assets_is_still_removed(db_session, osm):
    osm.sync_asset_types(db_session)
    empty = _system_type(db_session, "Empty Removed Class")

    osm.sync_asset_types(db_session)

    db_session.expire_all()
    assert db_session.get(AssetTypeDb, empty.id) is None


def test_legacy_business_term_type_is_present_retired_and_not_removed(db_session, osm):
    osm.sync_asset_types(db_session)
    osm.sync_asset_types(db_session)

    legacy = asset_type_repo.get_by_name(db_session, name=LEGACY)
    assert legacy is not None
    assert legacy.status == "retired"
    assert legacy.is_system is True


def test_retired_types_are_hidden_from_asset_type_lists_by_default(db_session, osm):
    osm.sync_asset_types(db_session)
    legacy = asset_type_repo.get_by_name(db_session, name=LEGACY)

    visible = asset_type_repo.get_multi_filtered(db_session)
    everything = asset_type_repo.get_multi_filtered(db_session, include_retired=True)

    assert legacy.id not in {t.id for t in visible}
    assert legacy.id in {t.id for t in everything}
    assert legacy.id in {t.id for t in asset_type_repo.get_multi_filtered(db_session, status="retired")}


def test_new_assets_cannot_use_a_retired_type(db_session, osm):
    from src.common.errors import ValidationError
    from src.controller.assets_manager import AssetsManager
    from src.models.assets import AssetCreate

    osm.sync_asset_types(db_session)
    legacy = asset_type_repo.get_by_name(db_session, name=LEGACY)

    with pytest.raises(ValidationError) as exc:
        AssetsManager().create_asset(db_session, asset_in=AssetCreate(
            name="new legacy term", asset_type_id=legacy.id,
        ), current_user_id="u@x.com")
    assert exc.value.status_code == 422
    assert exc.value.detail == {
        "code": "asset_type_retired",
        "message": f"Asset type '{LEGACY}' is retired and cannot be used for new assets.",
        "params": {"name": LEGACY},
    }


def test_moving_an_asset_to_a_retired_type_is_refused_with_a_code(db_session, osm):
    from src.common.errors import ValidationError
    from src.controller.assets_manager import AssetsManager
    from src.models.assets import AssetCreate, AssetUpdate

    osm.sync_asset_types(db_session)
    legacy = asset_type_repo.get_by_name(db_session, name=LEGACY)
    scratch = _system_type(db_session, "Scratch Type")
    asset = AssetsManager().create_asset(db_session, asset_in=AssetCreate(
        name="orders", asset_type_id=scratch.id,
    ), current_user_id="u@x.com")

    with pytest.raises(ValidationError) as exc:
        AssetsManager().update_asset(db_session, asset_id=asset.id, asset_in=AssetUpdate(
            asset_type_id=legacy.id,
        ), current_user_id="u@x.com")
    assert exc.value.detail["code"] == "asset_type_retired"
    assert exc.value.detail["params"] == {"name": LEGACY}


def test_retired_is_a_readable_asset_type_status():
    from src.models.assets import AssetTypeStatus

    assert AssetTypeStatus("retired") is AssetTypeStatus.RETIRED


def test_retired_type_the_ontology_defines_again_is_reactivated(db_session, osm):
    osm.sync_asset_types(db_session)
    table = asset_type_repo.get_by_name(db_session, name="Table")
    table.status = "retired"
    db_session.flush()

    osm.sync_asset_types(db_session)

    db_session.expire_all()
    assert asset_type_repo.get_by_name(db_session, name="Table").status == "active"


def test_empty_ontology_retires_nothing(db_session):
    empty = OntologySchemaManager(SimpleNamespace(_graph=ConjunctiveGraph()))
    in_use = _system_type(db_session, "Table")
    asset = _asset(db_session, in_use, "still here")

    empty.sync_asset_types(db_session)

    db_session.expire_all()
    assert db_session.get(AssetTypeDb, in_use.id).status == "active"
    assert db_session.get(AssetDb, asset.id) is not None
