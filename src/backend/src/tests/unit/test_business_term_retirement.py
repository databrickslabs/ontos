"""BusinessTerm leaves the ontology; concept links are the only way to say 'described by a concept' (#970).

- The TTL no longer defines BusinessTerm, hasTerm, relatesTo or the term-only properties.
- belongsToDomain covers the entity kinds the epic lists.
- The maturity count (business_term_count, key kept for stored rules) counts semantic
  links and hasSemanticConcept rows; legacy hasTerm rows still count so existing scores hold.
- Legacy Business Term lineage nodes stay in the business lane.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from pathlib import Path
from uuid import uuid4

import pytest
from rdflib import ConjunctiveGraph, Namespace, URIRef
from rdflib.namespace import RDFS

from src.controller.entity_dict_builder import _add_relationship_counts
from src.controller.model_lineage import SYNTHETIC_LAYERS
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.db_models.entity_relationships import EntityRelationshipDb
from src.db_models.semantic_links import EntitySemanticLinkDb

TTL = Path(__file__).resolve().parents[2] / "data" / "taxonomies" / "ontos-ontology.ttl"
ONTOS = Namespace("http://ontos.app/ontology#")


@pytest.fixture(scope="module")
def graph():
    g = ConjunctiveGraph()
    g.get_context(URIRef(OntologySchemaManager.BASE_ONTOLOGY_CONTEXT)).parse(str(TTL), format="turtle")
    return g


def _mentioned(graph, term):
    return any(True for _ in graph.triples((term, None, None))) or any(True for _ in graph.triples((None, None, term)))


@pytest.mark.parametrize("local_name", ["BusinessTerm", "hasTerm", "relatesTo", "termDefinition",
                                        "synonyms", "examples"])
def test_ttl_no_longer_defines_business_term_vocabulary(graph, local_name):
    assert not _mentioned(graph, ONTOS[local_name])


def test_has_semantic_concept_and_has_owner_no_longer_name_business_term(graph):
    for prop in ("hasSemanticConcept", "hasOwner", "appliesTo"):
        domains = set(graph.objects(ONTOS[prop], RDFS.domain)) | set(graph.objects(ONTOS[prop], RDFS.range))
        assert ONTOS.BusinessTerm not in domains, prop


def test_belongs_to_domain_covers_the_epic_kinds(graph):
    domains = set(graph.objects(ONTOS.belongsToDomain, RDFS.domain))
    for kind in ("LogicalAttribute", "Dashboard", "MLModel", "APIEndpoint", "Stream", "Notebook",
                 "DataProduct", "DataContract", "Dataset", "Table", "View", "LogicalEntity"):
        assert ONTOS[kind] in domains, kind
    assert ONTOS.BusinessTerm not in domains


def test_legacy_business_term_lineage_nodes_stay_in_the_business_lane():
    assert SYNTHETIC_LAYERS["LegacyBusinessTerm"] == "business"


@pytest.fixture
def product_id():
    return str(uuid4())


def _rel(db, source_id, target_id, rel_type, *, source_type="DataProduct", target_type="OntologyConcept"):
    db.add(EntityRelationshipDb(source_type=source_type, source_id=source_id,
                                target_type=target_type, target_id=target_id,
                                relationship_type=rel_type))
    db.flush()


def test_business_term_count_counts_concept_links(db_session, product_id):
    db_session.add(EntitySemanticLinkDb(entity_id=product_id, entity_type="data_product",
                                        iri="http://example.org/concept/customer"))
    _rel(db_session, product_id, str(uuid4()), "hasSemanticConcept")
    db_session.flush()

    counts = {}
    _add_relationship_counts(db_session, counts, "DataProduct", product_id)

    assert counts["business_term_count"] == 2
    assert counts["has_business_terms"] is True


def test_business_term_count_still_counts_legacy_term_links(db_session, product_id):
    _rel(db_session, product_id, str(uuid4()), "hasTerm", target_type="LegacyBusinessTerm")

    counts = {}
    _add_relationship_counts(db_session, counts, "DataProduct", product_id)

    assert counts["business_term_count"] == 1


def test_business_term_count_is_zero_without_links(db_session, product_id):
    counts = {}
    _add_relationship_counts(db_session, counts, "DataProduct", product_id)

    assert counts["business_term_count"] == 0
    assert counts["has_business_terms"] is False


def test_concept_linked_in_both_stores_counts_once(db_session, product_id):
    iri = "http://example.org/concept/customer"
    db_session.add(EntitySemanticLinkDb(entity_id=product_id, entity_type="data_product", iri=iri))
    _rel(db_session, product_id, iri, "hasSemanticConcept")
    db_session.flush()

    counts = {}
    _add_relationship_counts(db_session, counts, "DataProduct", product_id)

    assert counts["business_term_count"] == 1
