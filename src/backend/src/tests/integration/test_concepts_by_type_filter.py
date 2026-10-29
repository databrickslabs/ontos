"""Type-filtered flat concept search for selection dialogs.

``GET /api/semantic-models/concepts`` types every row as 'class' (SPARQL path),
so a "Subclass of" picker could not separate classes from SKOS concepts. The
optional ``concept_types`` param switches to ``search_concepts_by_type``,
which filters the cached concept list by real ``concept_type``.
"""
from pathlib import Path

import pytest
from rdflib import Literal, URIRef
from rdflib.namespace import OWL, RDF, RDFS, SKOS
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


SCHEME_IRI = "urn:ontology:typed"
OTHER_IRI = "urn:ontology:typed-other"
EX = "http://example.org/typed/"


def _register(manager, iri, label):
    meta = manager._graph.get_context(URIRef("urn:meta:sources"))
    coll = URIRef(iri)
    meta.add((coll, RDF.type, ONTOS.KnowledgeCollection))
    meta.add((coll, RDFS.label, Literal(label)))
    meta.add((coll, ONTOS.collectionType, Literal("ontology")))
    meta.add((coll, ONTOS.isEditable, Literal("true")))
    return manager._graph.get_context(URIRef(iri))


@pytest.fixture
def seeded(semantic_models_manager):
    m = semantic_models_manager
    ctx = _register(m, SCHEME_IRI, "Typed Ontology")
    vehicle = URIRef(EX + "Vehicle")
    ctx.add((vehicle, RDF.type, OWL.Class))
    ctx.add((vehicle, RDFS.label, Literal("Vehicle", lang="en")))
    ctx.add((vehicle, RDFS.label, Literal("Fahrzeug", lang="de")))
    ctx.add((URIRef(EX + "Region"), RDF.type, SKOS.Concept))
    ctx.add((URIRef(EX + "Region"), SKOS.prefLabel, Literal("Region")))
    ctx.add((URIRef(EX + "hasOwner"), RDF.type, OWL.ObjectProperty))
    ctx.add((URIRef(EX + "hasOwner"), RDFS.label, Literal("has owner")))
    for i in range(3):
        cls = URIRef(EX + f"Asset{i}")
        ctx.add((cls, RDF.type, OWL.Class))
        ctx.add((cls, RDFS.label, Literal(f"Asset {i}")))
    # Same class also declared in a second scheme: must be listed once.
    other = _register(m, OTHER_IRI, "Typed Other")
    other.add((vehicle, RDF.type, OWL.Class))
    other.add((vehicle, RDFS.label, Literal("Vehicle", lang="en")))
    # Grouping reads the in-memory concept cache; refresh it after seeding.
    m._cached_concepts = m._compute_all_concepts()
    return m


def _values(rows):
    return [r["value"] for r in rows]


def test_class_filter_returns_only_classes_with_real_type(seeded):
    rows = seeded.search_concepts_by_type("", ["class"], 50)
    assert _values(rows) == [EX + "Asset0", EX + "Asset1", EX + "Asset2", EX + "Vehicle"]
    assert all(r["type"] == "class" for r in rows)
    assert set(rows[0].keys()) == {"value", "label", "type", "source_context"}


def test_other_types_use_their_real_type(seeded):
    rows = seeded.search_concepts_by_type("", ["concept", "property"], 50)
    by_iri = {r["value"]: r["type"] for r in rows}
    assert by_iri == {EX + "Region": "concept", EX + "hasOwner": "property"}


def test_text_filter_matches_label_and_other_language_label(seeded):
    assert _values(seeded.search_concepts_by_type("vehic", ["class"], 50)) == [EX + "Vehicle"]
    assert _values(seeded.search_concepts_by_type("FAHRZ", ["class"], 50)) == [EX + "Vehicle"]
    assert _values(seeded.search_concepts_by_type("region", ["class"], 50)) == []


def test_deduplicates_concepts_listed_in_several_groups(seeded):
    rows = seeded.search_concepts_by_type("Vehicle", ["class"], 50)
    assert len(rows) == 1


def test_limit_truncates(seeded):
    rows = seeded.search_concepts_by_type("", ["class"], 2)
    assert _values(rows) == [EX + "Asset0", EX + "Asset1"]


def test_unknown_types_are_ignored(seeded):
    assert _values(seeded.search_concepts_by_type("", ["Class", "bogus"], 50)) == _values(
        seeded.search_concepts_by_type("", ["class"], 50)
    )
    assert seeded.search_concepts_by_type("", ["bogus"], 50) == []


def test_route_filters_by_concept_types(client, seeded):
    # Bundled system classes are listed too, so narrow by IRI to the seed.
    r = client.get("/api/semantic-models/concepts", params={"q": EX, "limit": 50, "concept_types": "class"})
    assert r.status_code == 200, r.text
    rows = r.json()
    assert _values(rows) == [EX + "Asset0", EX + "Asset1", EX + "Asset2", EX + "Vehicle"]
    assert all(row["type"] == "class" for row in rows)


def test_route_without_param_keeps_default_path(client, seeded, monkeypatch):
    # The SPARQL path cannot run its signal-based timeout off the main thread
    # (TestClient), so assert the route still delegates to search_concepts.
    calls = []
    legacy = [{"value": EX + "Region", "label": "Region", "type": "class"}]

    def _fake_search(text_filter="", limit=50):
        calls.append((text_filter, limit))
        return legacy

    monkeypatch.setattr(seeded, "search_concepts", _fake_search)
    r = client.get("/api/semantic-models/concepts", params={"q": "reg", "limit": 7})
    assert r.status_code == 200, r.text
    assert r.json() == legacy
    assert calls == [("reg", 7)]

    # A blank concept_types value falls back to the same default path.
    blank = client.get("/api/semantic-models/concepts", params={"q": "", "limit": 50, "concept_types": " , "})
    assert blank.status_code == 200
    assert blank.json() == legacy
    assert calls[-1] == ("", 50)


# --- Scheme scoping (source_context) -----------------------------------------

def _scheme_key(manager, iri):
    """Group key the seeded scheme's concepts carry (its `source_key`)."""
    for concepts in manager.get_grouped_concepts().values():
        for c in concepts:
            if c.iri == iri:
                return c.source_context
    raise AssertionError(f"{iri} not seeded")


def test_items_carry_source_context(seeded):
    rows = seeded.search_concepts_by_type(EX + "Asset", ["class"], 50)
    key = _scheme_key(seeded, EX + "Asset0")
    assert key
    assert {r["source_context"] for r in rows} == {key}


def test_source_context_keeps_only_that_scheme_and_honors_types(seeded):
    key = _scheme_key(seeded, EX + "Asset0")
    rows = seeded.search_concepts_by_type("", ["class"], 50, source_context=key)
    assert _values(rows) == [EX + "Asset0", EX + "Asset1", EX + "Asset2", EX + "Vehicle"]
    assert all(r["source_context"] == key for r in rows)
    # Type filter still applies inside the scheme.
    concepts = seeded.search_concepts_by_type("", ["concept"], 50, source_context=key)
    assert _values(concepts) == [EX + "Region"]


def test_source_context_other_scheme_and_unknown(seeded):
    key = _scheme_key(seeded, EX + "Asset0")
    other_keys = {
        c.source_context
        for concepts in seeded.get_grouped_concepts().values()
        for c in concepts
        if c.iri == EX + "Vehicle" and c.source_context != key
    }
    assert len(other_keys) == 1
    other_key = other_keys.pop()
    # The second scheme only declares Vehicle; nothing from the first leaks in.
    rows = seeded.search_concepts_by_type("", ["class"], 50, source_context=other_key)
    assert _values(rows) == [EX + "Vehicle"]
    assert rows[0]["source_context"] == other_key
    assert seeded.search_concepts_by_type("", ["class"], 50, source_context="no-such-scheme") == []


def test_route_passes_source_context(client, seeded):
    key = _scheme_key(seeded, EX + "Asset0")
    r = client.get(
        "/api/semantic-models/concepts",
        params={"q": "", "limit": 50, "concept_types": "concept", "source_context": key},
    )
    assert r.status_code == 200, r.text
    rows = r.json()
    assert _values(rows) == [EX + "Region"]
    assert rows[0]["source_context"] == key


def test_route_ignores_source_context_without_concept_types(client, seeded, monkeypatch):
    calls = []
    legacy = [{"value": EX + "Region", "label": "Region", "type": "class"}]

    def _fake_search(text_filter="", limit=50):
        calls.append((text_filter, limit))
        return legacy

    monkeypatch.setattr(seeded, "search_concepts", _fake_search)
    r = client.get("/api/semantic-models/concepts", params={"q": "", "limit": 50, "source_context": "typed"})
    assert r.status_code == 200, r.text
    assert r.json() == legacy
    assert calls == [("", 50)]
