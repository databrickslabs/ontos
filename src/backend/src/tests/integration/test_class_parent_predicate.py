"""Parent links use the OWL/RDFS predicate for classes.

An owl:Class authored in Ontos must link to its parent with rdfs:subClassOf
(not skos:broader); SKOS concepts/terms keep skos:broader; properties use
rdfs:subPropertyOf. Every reader (concept detail, hierarchy, list, version
snapshot) must report the parent regardless of which predicate carries it, so
legacy classes stored with skos:broader keep showing their parent.
"""
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from rdflib import URIRef
from rdflib.namespace import RDFS, SKOS
from sqlalchemy.orm import Session

from src.app import app
from src.common.app_state import set_app_state_manager
from src.controller.semantic_models_manager import SemanticModelsManager
from src.repositories.rdf_triples_repository import rdf_triples_repo


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)
    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)
    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)

    class _Noop:
        def sync_asset_types(self, *a, **k):
            return {"created": 0, "updated": 0}

        def log_action(self, *a, **k):
            return None

        def log_event(self, *a, **k):
            return None

    app.state.ontology_schema_manager = _Noop()
    app.state.audit_manager = _Noop()
    yield manager
    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture
def collection(semantic_models_manager):
    # Created on the manager the tests use. Going through the API would hit the
    # manager the TestClient's startup installed on app.state, which is a
    # different instance whenever this fixture ran before `client`.
    return semantic_models_manager.create_collection(
        label=f"ClassParent {uuid.uuid4().hex[:8]}",
        collection_type="glossary",
        scope_level="enterprise",
        description="class parent predicate test",
    )["iri"]


def _db_parent_preds(db, concept_iri):
    """{predicate_uri: [object_value, ...]} of parent-link rows for a subject."""
    out = {}
    for t in rdf_triples_repo.list_by_subject(db, concept_iri):
        if t.predicate_uri in (str(SKOS.broader), str(RDFS.subClassOf), str(RDFS.subPropertyOf)):
            out.setdefault(t.predicate_uri, []).append(t.object_value)
    return out


def test_create_class_with_parent_writes_subclassof(semantic_models_manager, collection, db_session):
    m = semantic_models_manager
    parent = m.create_concept(collection, "Party", concept_type="class")
    child = m.create_concept(
        collection, "Customer", concept_type="class", broader_iris=[parent["iri"]]
    )
    preds = _db_parent_preds(db_session, child["iri"])
    assert preds == {str(RDFS.subClassOf): [parent["iri"]]}, preds

    ctx = m._graph.get_context(URIRef(collection))
    c = URIRef(child["iri"])
    assert (c, RDFS.subClassOf, URIRef(parent["iri"])) in ctx
    assert (c, SKOS.broader, None) not in ctx

    # Concept detail payload reports the parent (once).
    assert m.get_concept(child["iri"])["parent_concepts"] == [parent["iri"]]


def test_create_skos_concept_keeps_broader(semantic_models_manager, collection, db_session):
    m = semantic_models_manager
    parent = m.create_concept(collection, "Animal")
    child = m.create_concept(collection, "Dog", broader_iris=[parent["iri"]])
    assert _db_parent_preds(db_session, child["iri"]) == {str(SKOS.broader): [parent["iri"]]}

    term_parent = m.create_concept(collection, "Revenue", concept_type="term")
    term = m.create_concept(
        collection, "Net Revenue", concept_type="term", broader_iris=[term_parent["iri"]]
    )
    assert _db_parent_preds(db_session, term["iri"]) == {str(SKOS.broader): [term_parent["iri"]]}


def test_create_property_with_parent_writes_subpropertyof(semantic_models_manager, collection, db_session):
    m = semantic_models_manager
    parent = m.create_concept(collection, "relatedTo", concept_type="property")
    child = m.create_concept(
        collection, "ownedBy", concept_type="property", broader_iris=[parent["iri"]]
    )
    assert _db_parent_preds(db_session, child["iri"]) == {str(RDFS.subPropertyOf): [parent["iri"]]}
    assert m.get_concept(child["iri"])["parent_concepts"] == [parent["iri"]]


def test_update_class_parent_replaces_and_normalises(semantic_models_manager, collection, db_session):
    m = semantic_models_manager
    a = m.create_concept(collection, "Party", concept_type="class")
    b = m.create_concept(collection, "Organisation", concept_type="class")
    child = m.create_concept(collection, "Supplier", concept_type="class", broader_iris=[a["iri"]])

    # Inject a legacy skos:broader to A as well (both DB and graph): an update
    # must leave ONE type-consistent set.
    rdf_triples_repo.add_triple(
        db_session, subject_uri=child["iri"], predicate_uri=str(SKOS.broader),
        object_value=a["iri"], object_is_uri=True, context_name=collection,
        source_type="concept", source_identifier=child["iri"],
    )
    ctx = m._graph.get_context(URIRef(collection))
    ctx.add((URIRef(child["iri"]), SKOS.broader, URIRef(a["iri"])))

    updated = m.update_concept(child["iri"], broader_iris=[b["iri"]])
    assert updated["parent_concepts"] == [b["iri"]]
    assert _db_parent_preds(db_session, child["iri"]) == {str(RDFS.subClassOf): [b["iri"]]}
    c = URIRef(child["iri"])
    assert set(ctx.objects(c, RDFS.subClassOf)) == {URIRef(b["iri"])}
    assert (c, SKOS.broader, None) not in ctx


def test_type_change_repredicates_existing_parent(semantic_models_manager, collection, db_session):
    m = semantic_models_manager
    parent = m.create_concept(collection, "Vehicle", concept_type="class")
    child = m.create_concept(collection, "Car", broader_iris=[parent["iri"]])  # skos concept
    assert _db_parent_preds(db_session, child["iri"]) == {str(SKOS.broader): [parent["iri"]]}

    m.update_concept(child["iri"], concept_type="class")
    assert _db_parent_preds(db_session, child["iri"]) == {str(RDFS.subClassOf): [parent["iri"]]}
    assert m.get_concept(child["iri"])["parent_concepts"] == [parent["iri"]]


def test_class_parent_visible_in_details_hierarchy_list_and_snapshot(
    semantic_models_manager, collection, db_session
):
    m = semantic_models_manager
    parent = m.create_concept(collection, "Asset", concept_type="class")
    child = m.create_concept(collection, "Pump", concept_type="class", broader_iris=[parent["iri"]])

    details = m.get_concept_details(child["iri"])
    assert list(details.parent_concepts) == [parent["iri"]]
    parent_details = m.get_concept_details(parent["iri"])
    assert child["iri"] in parent_details.child_concepts

    # Hierarchy (also backs the MCP get_concept_hierarchy tool): the class
    # parent drives parent_concepts and sibling discovery.
    sibling = m.create_concept(collection, "Valve", concept_type="class", broader_iris=[parent["iri"]])
    hierarchy = m.get_concept_hierarchy(child["iri"])
    assert list(hierarchy.concept.parent_concepts) == [parent["iri"]]
    assert sibling["iri"] in [s.iri for s in hierarchy.siblings]

    listed = next(c for c in m._compute_all_concepts() if c.iri == child["iri"])
    assert list(listed.parent_concepts) == [parent["iri"]]
    listed_parent = next(c for c in m._compute_all_concepts() if c.iri == parent["iri"])
    assert child["iri"] in listed_parent.child_concepts

    v1 = m.get_concept_version_detail(child["iri"], 1)
    assert v1["broader"] == [parent["iri"]]

    # Publishing a parent change keeps the class predicate on the new version.
    other = m.create_concept(collection, "Equipment", concept_type="class")
    m.publish_concept_version(child["iri"], changes={"broader_iris": [other["iri"]]})
    v2 = m.get_concept_version_detail(child["iri"], 2)
    assert v2["broader"] == [other["iri"]]
    assert m.get_concept_version_detail(child["iri"], 1)["broader"] == [parent["iri"]]
    current_rows = [
        t for t in rdf_triples_repo.list_current_by_subject(db_session, child["iri"])
        if t.predicate_uri in (str(SKOS.broader), str(RDFS.subClassOf))
    ]
    assert [(t.predicate_uri, t.object_value) for t in current_rows] == [
        (str(RDFS.subClassOf), other["iri"])
    ]
    assert m.get_concept(child["iri"])["parent_concepts"] == [other["iri"]]


def test_legacy_class_with_skos_broader_still_shows_parent(
    semantic_models_manager, collection, db_session
):
    m = semantic_models_manager
    parent = m.create_concept(collection, "Location", concept_type="class")
    child = m.create_concept(collection, "Site", concept_type="class")
    # Legacy data: class linked to its parent with skos:broader.
    rdf_triples_repo.add_triple(
        db_session, subject_uri=child["iri"], predicate_uri=str(SKOS.broader),
        object_value=parent["iri"], object_is_uri=True, context_name=collection,
        source_type="concept", source_identifier=child["iri"],
    )
    ctx = m._graph.get_context(URIRef(collection))
    ctx.add((URIRef(child["iri"]), SKOS.broader, URIRef(parent["iri"])))

    assert m.get_concept(child["iri"])["parent_concepts"] == [parent["iri"]]
    assert list(m.get_concept_details(child["iri"]).parent_concepts) == [parent["iri"]]
    assert child["iri"] in m.get_concept_details(parent["iri"]).child_concepts
    listed = next(c for c in m._compute_all_concepts() if c.iri == child["iri"])
    assert list(listed.parent_concepts) == [parent["iri"]]


def test_extract_changes_reads_all_parent_predicates():
    from rdflib import Graph
    from rdflib.namespace import OWL, RDF
    from src.controller.concept_diff import _extract_changes

    g = Graph()
    cls, par = URIRef("urn:t:Pump"), URIRef("urn:t:Asset")
    g.add((cls, RDF.type, OWL.Class))
    g.add((cls, RDFS.subClassOf, par))
    g.add((cls, RDFS.subClassOf, OWL.Thing))
    changes = _extract_changes(g, str(cls))
    assert changes["broader_iris"] == [str(par)]
    assert changes["_parent_predicates"] == {str(par): [str(RDFS.subClassOf)]}


def _narrower_rows(db, concept_iri):
    return [
        t.object_value for t in rdf_triples_repo.list_by_subject(db, concept_iri)
        if t.predicate_uri == str(SKOS.narrower)
    ]


def test_class_never_gets_skos_narrower(semantic_models_manager, collection, db_session):
    """OWL has no subclass inverse: children live on the child (rdfs:subClassOf).
    The editor echoes current children back as narrower_iris on save, which used
    to stamp skos:narrower onto classes."""
    m = semantic_models_manager
    parent = m.create_concept(collection, "Asset", concept_type="class")
    child = m.create_concept(
        collection, "Pump", concept_type="class", broader_iris=[parent["iri"]]
    )
    other = m.create_concept(
        collection, "Valve", concept_type="class", narrower_iris=[child["iri"]]
    )
    assert _narrower_rows(db_session, other["iri"]) == []

    m.update_concept(parent["iri"], narrower_iris=[child["iri"]])
    assert _narrower_rows(db_session, parent["iri"]) == []
    # The child still points at its parent via rdfs:subClassOf.
    assert _db_parent_preds(db_session, child["iri"]) == {str(RDFS.subClassOf): [parent["iri"]]}

    # SKOS concepts keep skos:narrower.
    animal = m.create_concept(collection, "Animal")
    dog = m.create_concept(collection, "Dog")
    m.update_concept(animal["iri"], narrower_iris=[dog["iri"]])
    assert _narrower_rows(db_session, animal["iri"]) == [dog["iri"]]


# --- Imported / LLM-generated ontologies (import_rdf_to_collection path) -------

_ONTOLOGY_TTL = """
@prefix ex:   <http://example.org/plant#> .
@prefix owl:  <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix skos: <http://www.w3.org/2004/02/skos/core#> .

ex:Asset a owl:Class ; rdfs:label "Asset" .
ex:Valve a owl:Class ; rdfs:label "Valve" ; rdfs:subClassOf ex:Asset .
ex:Pump  a owl:Class ; rdfs:label "Pump" ;
    rdfs:subClassOf ex:Asset ,
        [ a owl:Restriction ; owl:onProperty ex:hasPart ; owl:someValuesFrom ex:Valve ] .
ex:Legacy a owl:Class ; rdfs:label "Legacy" ; skos:broader ex:Asset .
ex:hasPart a owl:ObjectProperty ; rdfs:label "has part" ;
    rdfs:domain ex:Asset ; rdfs:range ex:Asset .
ex:Top a skos:Concept ; skos:prefLabel "Top" .
ex:Sub a skos:Concept ; skos:prefLabel "Sub" ; skos:broader ex:Top .
"""
EX = "http://example.org/plant#"


def _all_preds(db, iri):
    out = {}
    for t in rdf_triples_repo.list_by_subject(db, iri):
        out.setdefault(t.predicate_uri, []).append(t.object_value)
    return out


def _editor_save(m, iri, **changes):
    """Mimic concept-editor-dialog: it always re-sends current parents/children."""
    c = m.get_concept(iri)
    payload = {
        "broader_iris": list(c.get("parent_concepts") or []),
        "narrower_iris": list(c.get("child_concepts") or []),
    }
    payload.update(changes)
    return m.update_concept(iri, **payload)


def test_imported_ontology_round_trip(semantic_models_manager, collection, db_session):
    from rdflib import Graph

    m = semantic_models_manager
    # Same call the RDF upload and LLM "save to scheme" paths use.
    m.import_rdf_to_collection(collection, _ONTOLOGY_TTL, default_status="draft")

    pump = m.get_concept(EX + "Pump")
    assert EX + "Asset" in pump["parent_concepts"]
    assert not any(p.startswith("urn:ontos:bnode") or p.startswith("_:") for p in pump["parent_concepts"])
    assert EX + "Asset" in m.get_concept(EX + "Legacy")["parent_concepts"]  # legacy skos:broader
    assert m.get_concept(EX + "Sub")["parent_concepts"] == [EX + "Top"]

    # Re-uploading the unchanged file reports nothing modified.
    preview = m.preview_upload(collection, Graph().parse(data=_ONTOLOGY_TTL, format="turtle"))
    assert preview["summary"]["modified"] == 0, preview.get("modified")

    # Editor-style save of an imported class (label only): parent + restriction survive,
    # nothing SKOS leaks in.
    _editor_save(m, EX + "Pump", label="Pump (centrifugal)")
    preds = _all_preds(db_session, EX + "Pump")
    sub = preds.get(str(RDFS.subClassOf), [])
    assert EX + "Asset" in sub
    assert any(not v.startswith("http") for v in sub), "owl:Restriction blank node lost"
    assert str(SKOS.broader) not in preds and str(SKOS.narrower) not in preds

    # Editor-style save of the parent class (children echoed back): no skos:narrower.
    _editor_save(m, EX + "Asset", definition="Physical equipment")
    assert str(SKOS.narrower) not in _all_preds(db_session, EX + "Asset")
    assert EX + "Asset" in m.get_concept(EX + "Valve")["parent_concepts"]

    # Re-parent an imported class.
    _editor_save(m, EX + "Pump", broader_iris=[EX + "Valve"])
    sub = _all_preds(db_session, EX + "Pump").get(str(RDFS.subClassOf), [])
    assert EX + "Valve" in sub and EX + "Asset" not in sub
    assert any(not v.startswith("http") for v in sub), "owl:Restriction blank node lost"

    # Editing the legacy class normalises it to rdfs:subClassOf.
    _editor_save(m, EX + "Legacy", definition="old")
    lp = _all_preds(db_session, EX + "Legacy")
    assert lp.get(str(RDFS.subClassOf)) == [EX + "Asset"] and str(SKOS.broader) not in lp

    # SKOS concept in the same file stays SKOS.
    _editor_save(m, EX + "Sub", definition="child")
    sp = _all_preds(db_session, EX + "Sub")
    assert sp.get(str(SKOS.broader)) == [EX + "Top"] and str(RDFS.subClassOf) not in sp

    # Re-upload of the original file: only the concepts we actually edited differ.
    preview = m.preview_upload(collection, Graph().parse(data=_ONTOLOGY_TTL, format="turtle"))
    modified = {x["iri"] for x in preview["modified"]}
    assert EX + "hasPart" not in modified and EX + "Top" not in modified
    assert EX + "Pump" in modified
