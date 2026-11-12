"""Collection concept counts use the same source key as concept grouping.

Concepts are bucketed by ``_extract_source_context``, which maps most
scheme IRIs to their suffix ("urn:glossary:plain" -> "plain") but maps the
demo context ``urn:demo`` to the fixed name "Demo Data". The collection
counter must use the same mapping, otherwise the demo scheme reports
``concept_count: 0`` while its concepts exist. Each collection also exposes
the key as ``source_key`` so the UI can match it to its concept group.
"""
from pathlib import Path

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import RDF, RDFS, SKOS
from sqlalchemy.orm import Session

from src.app import app
from src.common.app_state import set_app_state_manager
from src.controller.semantic_models_manager import ONTOS, SemanticModelsManager


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)
    yield manager
    if hasattr(app.state, "semantic_models_manager"):
        delattr(app.state, "semantic_models_manager")


DEMO_IRI = "urn:demo"
PLAIN_IRI = "urn:glossary:plain"


def _seed_scheme(manager, iri, label, n_concepts, parent_iri=None):
    meta = manager._graph.get_context(URIRef("urn:meta:sources"))
    coll = URIRef(iri)
    meta.add((coll, RDF.type, ONTOS.KnowledgeCollection))
    meta.add((coll, RDFS.label, Literal(label)))
    meta.add((coll, ONTOS.collectionType, Literal("glossary")))
    meta.add((coll, ONTOS.isEditable, Literal("true")))
    if parent_iri:
        meta.add((coll, ONTOS.parentCollection, URIRef(parent_iri)))
    ctx = manager._graph.get_context(URIRef(iri))
    for i in range(n_concepts):
        concept = URIRef(f"http://example.org/{label.replace(' ', '_')}/c{i}")
        ctx.add((concept, RDF.type, SKOS.Concept))
        ctx.add((concept, SKOS.prefLabel, Literal(f"{label} {i}")))


@pytest.fixture
def seeded(semantic_models_manager):
    m = semantic_models_manager
    _seed_scheme(m, DEMO_IRI, "Demo Glossary", 4)
    _seed_scheme(m, PLAIN_IRI, "Plain Glossary", 3, parent_iri=DEMO_IRI)
    # Grouping reads the in-memory concept cache; refresh it after seeding.
    m._cached_concepts = m._compute_all_concepts()
    return m


def _by_iri(collections):
    return {c["iri"]: c for c in collections}


def test_demo_scheme_counts_concepts_under_fixed_bucket(seeded):
    grouped = seeded.get_grouped_concepts()
    assert len(grouped.get("Demo Data", [])) == 4
    assert len(grouped.get("plain", [])) == 3

    colls = _by_iri(seeded.get_collections())
    assert colls[DEMO_IRI]["concept_count"] == 4
    assert colls[DEMO_IRI]["source_key"] == "Demo Data"
    assert colls[PLAIN_IRI]["concept_count"] == 3
    assert colls[PLAIN_IRI]["source_key"] == "plain"


def test_get_collection_carries_source_key(seeded):
    coll = seeded.get_collection(DEMO_IRI)
    assert coll["source_key"] == "Demo Data"
    assert coll["concept_count"] == 4


def test_hierarchy_keeps_source_key_on_children(seeded):
    roots = _by_iri(seeded.get_collections_with_hierarchy())
    demo = roots[DEMO_IRI]
    assert demo["source_key"] == "Demo Data"
    assert demo["concept_count"] == 4
    children = _by_iri(demo["child_collections"])
    assert children[PLAIN_IRI]["source_key"] == "plain"
    assert children[PLAIN_IRI]["concept_count"] == 3
