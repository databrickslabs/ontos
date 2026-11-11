"""Relationship rows store ontology local names for their entity types.

Regression: rows were stored with the spelling the writer used, label or local name
("Logical Entity" or "LogicalEntity", "Metric View" or "MetricView"). Lookups compare
type strings exactly, so the asset pages, which ask for local names, didn't show
links written with labels (by API clients, the schema importer and asset retyping).
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from rdflib import ConjunctiveGraph, URIRef

from src.common.errors import ConflictError
from src.common.ontology_type_names import canonical_type_name
from src.controller.entity_relationships_manager import EntityRelationshipsManager
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.db_models.entity_relationships import EntityRelationshipDb
from src.models.entity_relationships import EntityRelationshipCreate
from src.repositories.entity_relationships_repository import entity_relationship_repo

TTL = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"


@pytest.fixture(scope="module")
def osm():
    graph = ConjunctiveGraph()
    graph.get_context(URIRef(OntologySchemaManager.BASE_ONTOLOGY_CONTEXT)).parse(str(TTL), format="turtle")
    return OntologySchemaManager(SimpleNamespace(_graph=graph))


@pytest.mark.parametrize("value, expected", [
    ("Logical Entity", "LogicalEntity"),
    ("LogicalEntity", "LogicalEntity"),
    ("Metric View", "MetricView"),
    (" API  Endpoint ", "APIEndpoint"),
    ("http://ontos.app/ontology#DataDomain", "DataDomain"),
    ("https://example.com/ns#Thing", "https://example.com/ns#Thing"),
    ("Concept", "Concept"),
])
def test_canonical_type_name(value, expected):
    assert canonical_type_name(value) == expected


def test_rows_store_local_names_whoever_writes_them(db_session):
    db_session.add(EntityRelationshipDb(
        source_type="Metric View", source_id="v1", target_type="Column",
        target_id="c1", relationship_type="hasColumn",
    ))
    db_session.flush()

    row = db_session.query(EntityRelationshipDb).one()
    assert (row.source_type, row.target_type) == ("MetricView", "Column")

    row.target_type = "Logical Attribute"
    db_session.flush()
    assert db_session.query(EntityRelationshipDb).one().target_type == "LogicalAttribute"


def test_a_relationship_created_with_labels_shows_on_the_asset_page(db_session, osm):
    manager = EntityRelationshipsManager(osm)

    created = manager.create_relationship(db_session, EntityRelationshipCreate(
        source_type="Logical Entity", source_id="le1", target_type="Logical Attribute",
        target_id="la1", relationship_type="hasLogicalAttribute",
    ), current_user_id="u@example.com")

    assert (created.source_type, created.target_type) == ("LogicalEntity", "LogicalAttribute")
    # The asset page asks with the local name, the incoming side too.
    assert [r.id for r in manager.get_all_for_entity(db_session, "LogicalEntity", "le1").outgoing] == [created.id]
    assert [r.id for r in manager.get_all_for_entity(db_session, "LogicalAttribute", "la1").incoming] == [created.id]
    # A caller that still sends the label finds it too, on the right side.
    assert [r.id for r in manager.get_outgoing(db_session, "Logical Entity", "le1")] == [created.id]
    by_label = manager.get_all_for_entity(db_session, "Logical Entity", "le1")
    assert ([r.id for r in by_label.outgoing], by_label.incoming) == ([created.id], [])


def test_the_same_link_in_another_spelling_is_a_duplicate(db_session, osm):
    manager = EntityRelationshipsManager(osm)
    manager.create_relationship(db_session, EntityRelationshipCreate(
        source_type="LogicalEntity", source_id="le1", target_type="LogicalAttribute",
        target_id="la1", relationship_type="hasLogicalAttribute",
    ), current_user_id="u@example.com")

    with pytest.raises(ConflictError):
        manager.create_relationship(db_session, EntityRelationshipCreate(
            source_type="Logical Entity", source_id="le1", target_type="Logical Attribute",
            target_id="la1", relationship_type="hasLogicalAttribute",
        ), current_user_id="u@example.com")


def test_repository_filters_accept_either_spelling(db_session):
    db_session.add(EntityRelationshipDb(
        source_type="DeliveryChannel", source_id="d1", target_type="System",
        target_id="s1", relationship_type="belongsToSystem",
    ))
    db_session.flush()

    assert entity_relationship_repo.find_existing(
        db_session, source_type="Delivery Channel", source_id="d1", target_type="System",
        target_id="s1", relationship_type="belongsToSystem",
    ) is not None
    assert len(entity_relationship_repo.query_filtered(db_session, source_type="Delivery Channel")) == 1
    assert len(entity_relationship_repo.get_by_source(db_session, source_type="Delivery Channel", source_id="d1")) == 1


def test_a_concept_link_reads_back_with_its_label(db_session, osm):
    manager = EntityRelationshipsManager(osm)
    iri = "urn:glossary:retail/customer"
    manager.create_relationship(db_session, EntityRelationshipCreate(
        source_type="LogicalEntity", source_id="le1", target_type="OntologyConcept",
        target_id=iri, relationship_type="hasSemanticConcept", properties={"target_label": "Customer"},
    ), current_user_id="u@example.com")

    [link] = manager.get_all_for_entity(db_session, "LogicalEntity", "le1").outgoing

    assert (link.target_type, link.target_name) == ("OntologyConcept", "Customer")


def test_a_concept_link_without_a_label_falls_back_to_the_concept_name(db_session, osm):
    manager = EntityRelationshipsManager(osm)
    iri = "urn:glossary:retail/customer-address"
    manager.create_relationship(db_session, EntityRelationshipCreate(
        source_type="LogicalEntity", source_id="le1", target_type="OntologyConcept",
        target_id=iri, relationship_type="hasSemanticConcept",
    ), current_user_id="u@example.com")

    [link] = manager.get_all_for_entity(db_session, "LogicalEntity", "le1").outgoing

    # Resolved like a lineage concept node: semantic-link label, else the IRI's last segment.
    assert link.target_name == "customer-address"
    assert manager._resolve_entity(db_session, "OntologyConcept", iri)["name"] == "customer-address"
