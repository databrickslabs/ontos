"""Migration u5 archives BusinessTerm assets as Legacy Business Term without losing any (#970)."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

PATH = Path(__file__).resolve().parents[3] / "alembic" / "versions" / "u5_legacy_business_term.py"

BT = "bt-type"
LE = "le-type"
LEGACY = "legacy-type"
SCHEMA = '{"name": {"type": "string"}}'


@pytest.fixture
def migration():
    spec = importlib.util.spec_from_file_location("u5_legacy_business_term", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def engine():
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE asset_types (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT, category TEXT,
                icon TEXT, required_fields TEXT, optional_fields TEXT, allowed_relationships TEXT,
                is_system BOOLEAN NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'active',
                created_by TEXT, created_at TIMESTAMP, updated_at TIMESTAMP
            )
        """))
        conn.execute(text("""
            CREATE TABLE assets (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, asset_type_id TEXT NOT NULL,
                properties TEXT, tags TEXT, status TEXT NOT NULL DEFAULT 'active'
            )
        """))
        conn.execute(text("""
            CREATE TABLE entity_relationships (
                id TEXT PRIMARY KEY, source_type TEXT NOT NULL, source_id TEXT NOT NULL,
                target_type TEXT NOT NULL, target_id TEXT NOT NULL, relationship_type TEXT NOT NULL,
                UNIQUE (source_type, source_id, target_type, target_id, relationship_type)
            )
        """))
    return engine


def _seed(engine, *, business_term_type=True, legacy_type=False):
    with engine.begin() as conn:
        if business_term_type:
            conn.execute(text(
                "INSERT INTO asset_types (id, name, description, category, icon, required_fields, "
                "optional_fields, is_system, status) VALUES (:id, 'Business Term', 'Glossary term', "
                "'governance', 'BookOpen', :schema, NULL, 1, 'active')"
            ), {"id": BT, "schema": SCHEMA})
        conn.execute(text(
            "INSERT INTO asset_types (id, name, is_system, status) VALUES (:id, 'Logical Entity', 1, 'active')"
        ), {"id": LE})
        if legacy_type:
            conn.execute(text(
                "INSERT INTO asset_types (id, name, is_system, status) "
                "VALUES (:id, 'Legacy Business Term', 1, 'retired')"
            ), {"id": LEGACY})
        for aid, name, type_id in [
            ("a-customer", "Customer", BT),
            ("a-transaction", "Transaction", BT),
            ("a-entity", "Customer Entity", LE),
        ]:
            conn.execute(text(
                "INSERT INTO assets (id, name, asset_type_id, properties, tags) "
                "VALUES (:id, :name, :t, '{\"definition\": \"buyer\"}', '[\"core\"]')"
            ), {"id": aid, "name": name, "t": type_id})
        for rid, src, sid, tgt, tid, rel in [
            ("r1", "BusinessTerm", "a-customer", "LogicalEntity", "a-entity", "relatesTo"),
            ("r2", "DataProduct", "dp-1", "BusinessTerm", "a-transaction", "hasTerm"),
            ("r3", "DataProduct", "dp-1", "LogicalEntity", "a-entity", "hasLogicalEntity"),
        ]:
            conn.execute(text(
                "INSERT INTO entity_relationships VALUES (:id, :s, :sid, :t, :tid, :rel)"
            ), {"id": rid, "s": src, "sid": sid, "t": tgt, "tid": tid, "rel": rel})


def _run(engine, migration):
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()


def _assets(engine):
    with engine.connect() as conn:
        return {r.id: (r.name, r.asset_type_id, r.properties, r.tags, r.status) for r in conn.execute(
            text("SELECT id, name, asset_type_id, properties, tags, status FROM assets"))}


def _relationships(engine):
    with engine.connect() as conn:
        return {r.id: (r.source_type, r.source_id, r.target_type, r.target_id, r.relationship_type)
                for r in conn.execute(text("SELECT * FROM entity_relationships"))}


def _legacy_type(engine):
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT id, is_system, status, required_fields FROM asset_types WHERE name = 'Legacy Business Term'"
        )).first()


def test_moves_every_business_term_asset_and_keeps_its_data(engine, migration):
    _seed(engine)
    before_assets = _assets(engine)

    _run(engine, migration)

    after_assets = _assets(engine)
    assert set(after_assets) == set(before_assets)
    legacy = _legacy_type(engine)
    for aid in ("a-customer", "a-transaction"):
        name, type_id, props, tags, status = after_assets[aid]
        assert type_id == legacy.id
        assert (name, props, tags, status) == before_assets[aid][0:1] + before_assets[aid][2:]
    assert after_assets["a-entity"] == before_assets["a-entity"]


def test_rewrites_relationships_of_moved_assets_and_leaves_others(engine, migration):
    _seed(engine)
    _run(engine, migration)

    rels = _relationships(engine)
    assert rels["r1"] == ("LegacyBusinessTerm", "a-customer", "LogicalEntity", "a-entity", "relatesTo")
    assert rels["r2"] == ("DataProduct", "dp-1", "LegacyBusinessTerm", "a-transaction", "hasTerm")
    assert rels["r3"] == ("DataProduct", "dp-1", "LogicalEntity", "a-entity", "hasLogicalEntity")
    assert len(rels) == 3


def test_legacy_type_is_retired_system_and_copies_the_term_schema(engine, migration):
    _seed(engine)
    _run(engine, migration)

    legacy = _legacy_type(engine)
    assert legacy.is_system
    assert legacy.status == "retired"
    assert legacy.required_fields == SCHEMA


def test_reuses_an_existing_legacy_type(engine, migration):
    _seed(engine, legacy_type=True)
    _run(engine, migration)

    with engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM asset_types WHERE name = 'Legacy Business Term'")).scalar()
    assert count == 1
    after = _assets(engine)
    assert {after["a-customer"][1], after["a-transaction"][1]} == {LEGACY}


def test_no_business_term_assets_changes_nothing(engine, migration):
    _seed(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE assets SET asset_type_id = :le WHERE asset_type_id = :bt"), {"le": LE, "bt": BT})
    before_rels = _relationships(engine)

    _run(engine, migration)

    assert _legacy_type(engine) is None
    assert _relationships(engine) == before_rels


def test_missing_business_term_type_is_a_no_op(engine, migration):
    _seed(engine, business_term_type=False)
    _run(engine, migration)
    assert _legacy_type(engine) is None


ONTOS = "http://ontos.app/ontology#"
ONTOLOGY_CONTEXT = "urn:taxonomy:ontos-ontology"


def _triples_table(engine, triples):
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE rdf_triples (subject_uri TEXT NOT NULL, predicate_uri TEXT NOT NULL, "
            "object_value TEXT NOT NULL, context_name TEXT NOT NULL)"
        ))
        for s, p, o, ctx in triples:
            conn.execute(text("INSERT INTO rdf_triples VALUES (:s, :p, :o, :c)"),
                         {"s": s, "p": p, "o": o, "c": ctx})


def _remaining_triples(engine):
    with engine.connect() as conn:
        return {(r.subject_uri, r.predicate_uri, r.object_value, r.context_name) for r in conn.execute(
            text("SELECT subject_uri, predicate_uri, object_value, context_name FROM rdf_triples"))}


def test_prunes_the_removed_ontology_terms_from_the_stored_ontology(engine, migration):
    _seed(engine)
    rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    domain = "http://www.w3.org/2000/01/rdf-schema#domain"
    keep = {
        (ONTOS + "Dashboard", rdf_type, ONTOS + "Class", ONTOLOGY_CONTEXT),
        (ONTOS + "belongsToDomain", domain, ONTOS + "Table", ONTOLOGY_CONTEXT),
        (ONTOS + "Table", rdf_type, ONTOS + "Class", ONTOLOGY_CONTEXT),
    }
    _triples_table(engine, [
        (ONTOS + "BusinessTerm", rdf_type, ONTOS + "Class", ONTOLOGY_CONTEXT),
        (ONTOS + "BusinessTerm", "http://www.w3.org/2000/01/rdf-schema#label", "Business Term", ONTOLOGY_CONTEXT),
        (ONTOS + "hasTerm", rdf_type, ONTOS + "ObjectProperty", ONTOLOGY_CONTEXT),
        (ONTOS + "relatesTo", rdf_type, ONTOS + "ObjectProperty", ONTOLOGY_CONTEXT),
        (ONTOS + "synonyms", rdf_type, ONTOS + "DatatypeProperty", ONTOLOGY_CONTEXT),
        (ONTOS + "belongsToDomain", domain, ONTOS + "BusinessTerm", ONTOLOGY_CONTEXT),
        (ONTOS + "hasOwner", domain, ONTOS + "BusinessTerm", ONTOLOGY_CONTEXT),
        (ONTOS + "BusinessTerm", "urn:term", "x", "urn:taxonomy:other"),
    ] + list(keep))

    _run(engine, migration)

    assert _remaining_triples(engine) == keep | {
        (ONTOS + "BusinessTerm", "urn:term", "x", "urn:taxonomy:other"),
    }


def test_pruning_is_a_no_op_without_a_triple_store(engine, migration):
    _seed(engine)
    _run(engine, migration)
    assert _legacy_type(engine) is not None
