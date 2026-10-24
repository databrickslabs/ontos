"""A created concept scheme is typed BOTH ontos:KnowledgeCollection and
skos:ConceptScheme, without producing duplicate collections or a phantom
concept row for the scheme itself."""
import uuid
from pathlib import Path

import pytest
from rdflib import URIRef
from rdflib.namespace import RDF, SKOS
from sqlalchemy.orm import Session

from src.controller.semantic_models_manager import SemanticModelsManager, ONTOS
from src.repositories.rdf_triples_repository import rdf_triples_repo


@pytest.fixture
def smm(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    return SemanticModelsManager(db=db_session, data_dir=data_dir)


def test_create_collection_adds_skos_concept_scheme_type(smm, db_session):
    label = f"Scheme {uuid.uuid4().hex[:8]}"
    coll = smm.create_collection(label=label, collection_type="glossary")
    iri = coll["iri"]

    # In-memory graph: both types on the scheme subject.
    meta = smm._graph.get_context(URIRef("urn:meta:sources"))
    types = set(meta.objects(URIRef(iri), RDF.type))
    assert ONTOS.KnowledgeCollection in types
    assert SKOS.ConceptScheme in types

    # Persisted rows: both rdf:type triples are stored.
    rows = rdf_triples_repo.list_by_context(db_session, "urn:meta:sources")
    persisted = {r.object_value for r in rows
                 if r.subject_uri == iri and r.predicate_uri == str(RDF.type)}
    assert {str(ONTOS.KnowledgeCollection), str(SKOS.ConceptScheme)} <= persisted

    # Exactly one collection entry for it; the scheme is not a concept.
    assert [c["iri"] for c in smm.get_collections()].count(iri) == 1
    smm.create_concept(collection_iri=iri, label="Customer", created_by="a@example.com")
    grouped = smm.get_grouped_concepts()
    all_iris = {c.iri if hasattr(c, "iri") else c.get("iri")
                for concepts in grouped.values() for c in concepts}
    assert iri not in all_iris
