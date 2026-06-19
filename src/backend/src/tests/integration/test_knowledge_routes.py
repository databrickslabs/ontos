"""Integration tests for the Concepts feature: /api/knowledge/*, related
endpoints under /api/semantic-models/*, /api/ontology/save-to-collection, and
/api/semantic-links/.

These tests exercise the cache-freshness, prefix-handling, and
broadcast-after-rebuild behaviours that broke in production. They are
written TDD-style and target the bugs documented in
docs/research/concepts-bugs/repro-summary.md.

A per-test SemanticModelsManager is instantiated against the in-memory
SQLite db_session and registered on app.state so the route dependencies
resolve correctly. We use a temp data_dir so persistent JSON cache files
don't bleed between tests.
"""
import os
import time
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.controller.semantic_models_manager import SemanticModelsManager
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.common.app_state import set_app_state_manager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def semantic_models_manager(db_session: Session, tmp_path: Path):
    """Build a SemanticModelsManager backed by the test session + tmp data dir.

    The manager is published on `app.state.semantic_models_manager` and via
    the `app_state` registry so both the FastAPI dependency and the
    `SemanticLinksManager` fallback locator can find it.
    """
    data_dir = tmp_path / "sm_data"
    (data_dir / "cache").mkdir(parents=True, exist_ok=True)
    (data_dir / "taxonomies").mkdir(parents=True, exist_ok=True)

    manager = SemanticModelsManager(db=db_session, data_dir=data_dir)

    app.state.semantic_models_manager = manager
    set_app_state_manager("semantic_models_manager", manager)

    # OntologySchemaManager is touched by /refresh-graph; provide a benign stub.
    class _NoopOSM:
        def sync_asset_types(self, *_args, **_kwargs):
            return {"created": 0, "updated": 0}

    app.state.ontology_schema_manager = _NoopOSM()

    # Audit manager is required by semantic-links routes; a no-op stub is enough.
    class _NoopAudit:
        def log_action(self, *_args, **_kwargs):
            return None
        def log_event(self, *_args, **_kwargs):
            return None

    app.state.audit_manager = _NoopAudit()

    yield manager

    for attr in ("semantic_models_manager", "ontology_schema_manager", "audit_manager"):
        if hasattr(app.state, attr):
            delattr(app.state, attr)


@pytest.fixture
def make_collection(client: TestClient, semantic_models_manager):
    """Factory that creates a fresh, uniquely-named collection and returns it."""

    def _make(label_prefix: str = "Test Coll", collection_type: str = "glossary",
              description: str = "made by test"):
        label = f"{label_prefix} {uuid.uuid4().hex[:8]}"
        payload = {
            "label": label,
            "collection_type": collection_type,
            "scope_level": "enterprise",
            "description": description,
        }
        r = client.post("/api/knowledge/collections", json=payload)
        assert r.status_code == 200, r.text
        return r.json()

    return _make


# ---------------------------------------------------------------------------
# Collections CRUD
# ---------------------------------------------------------------------------


class TestKnowledgeCollections:
    def test_list_collections_returns_envelope(self, client: TestClient, semantic_models_manager):
        r = client.get("/api/knowledge/collections")
        assert r.status_code == 200
        body = r.json()
        assert "collections" in body
        assert isinstance(body["collections"], list)

    def test_create_glossary_collection(self, client: TestClient, semantic_models_manager):
        payload = {
            "label": "Created Glossary",
            "collection_type": "glossary",
            "scope_level": "enterprise",
            "description": "for unit test",
        }
        r = client.post("/api/knowledge/collections", json=payload)
        assert r.status_code == 200, r.text
        c = r.json()
        assert c["iri"] == "urn:glossary:created-glossary"
        assert c["label"] == "Created Glossary"
        assert c["collection_type"] == "glossary"
        assert c["is_editable"] is True
        assert c["concept_count"] == 0

    def test_create_taxonomy_and_ontology_collections(self, client: TestClient, semantic_models_manager):
        for ctype, prefix in (("taxonomy", "urn:taxonomy:"),
                              ("ontology", "urn:ontology:")):
            r = client.post("/api/knowledge/collections", json={
                "label": f"{ctype} test",
                "collection_type": ctype,
            })
            assert r.status_code == 200
            assert r.json()["iri"].startswith(prefix)

    def test_get_collection_by_iri(self, client: TestClient, make_collection):
        created = make_collection("Single Get")
        r = client.get(f"/api/knowledge/collections/{created['iri']}")
        assert r.status_code == 200
        assert r.json()["iri"] == created["iri"]

    def test_create_duplicate_collection_returns_400(self, client: TestClient, make_collection):
        first = make_collection("Dup Test")
        # Re-post with the SAME label → same generated IRI → must conflict.
        r = client.post("/api/knowledge/collections", json={
            "label": first["label"],
            "collection_type": first["collection_type"],
        })
        assert r.status_code == 400, r.text

    def test_update_collection_label_and_description(self, client: TestClient, make_collection):
        c = make_collection("Original Label")
        r = client.patch(f"/api/knowledge/collections/{c['iri']}", json={
            "label": "Renamed Label",
            "description": "updated",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["label"] == "Renamed Label"
        assert body["description"] == "updated"

    def test_delete_collection(self, client: TestClient, make_collection):
        c = make_collection("Delete Me")
        r = client.delete(f"/api/knowledge/collections/{c['iri']}")
        assert r.status_code == 200
        assert r.json()["success"] is True
        # Subsequent GET should 404.
        r2 = client.get(f"/api/knowledge/collections/{c['iri']}")
        assert r2.status_code == 404

    def test_collection_appears_in_hierarchy_listing(self, client: TestClient, make_collection):
        c = make_collection("Hierarchy Test")
        r = client.get("/api/knowledge/collections?hierarchical=true")
        assert r.status_code == 200
        irirs = [coll["iri"] for coll in r.json()["collections"]]
        assert c["iri"] in irirs


# ---------------------------------------------------------------------------
# Concept CRUD
# ---------------------------------------------------------------------------


class TestKnowledgeConcepts:
    def test_create_concept_in_collection(self, client: TestClient, make_collection):
        c = make_collection("Concept Container")
        r = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "First Concept",
            "definition": "A first test concept",
            "concept_type": "concept",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["iri"] == f"{c['iri']}/first-concept"
        assert body["label"] == "First Concept"
        assert body["status"] == "draft"

    def test_get_concept_returns_full_payload(self, client: TestClient, make_collection):
        c = make_collection("Get Concept Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Beta",
        }).raise_for_status()
        r = client.get(f"/api/knowledge/concepts/{c['iri']}/beta")
        assert r.status_code == 200
        assert r.json()["label"] == "Beta"

    def test_update_concept_label_and_synonyms(self, client: TestClient, make_collection):
        c = make_collection("Patch Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "OldName",
        }).raise_for_status()
        iri = f"{c['iri']}/oldname"
        r = client.patch(f"/api/knowledge/concepts/{iri}", json={
            "label": "NewName",
            "synonyms": ["alias-a", "alias-b"],
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["label"] == "NewName"
        assert sorted(body["synonyms"]) == ["alias-a", "alias-b"]

    def test_concept_detail_endpoint_returns_synonyms_examples_related(
        self, client: TestClient, make_collection
    ):
        """Regression: synonyms/examples/related created on a concept must be
        returned by BOTH the knowledge CRUD endpoint and the semantic-models
        detail endpoint (the one the concept detail page + edit dialog consume).

        Previously ``get_concept_details`` dropped them, so synonyms vanished
        from the detail view and the edit dialog, and were silently wiped on the
        next save (the form re-PATCHed an empty list).
        """
        c = make_collection("Synonym Coll")
        # A sibling concept to point skos:related at.
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Retention",
        }).raise_for_status()
        related_iri = f"{c['iri']}/retention"

        create = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "Customer Churn",
            "definition": "When a customer stops doing business.",
            "concept_type": "concept",
            "synonyms": ["Customer Attrition", "Churn"],
            "examples": ["monthly churn rate"],
            "related_iris": [related_iri],
        })
        assert create.status_code == 200, create.text
        iri = f"{c['iri']}/customer-churn"

        # The detail endpoint backing the concept detail page + edit dialog.
        detail = client.get(f"/api/semantic-models/concepts/{iri}")
        assert detail.status_code == 200, detail.text
        concept = detail.json()["concept"]
        assert sorted(concept["synonyms"]) == ["Churn", "Customer Attrition"]
        assert concept["examples"] == ["monthly churn rate"]
        assert concept["related_concepts"] == [related_iri]
        assert concept["status"] == "draft"

        # Parity with the knowledge CRUD endpoint.
        crud = client.get(f"/api/knowledge/concepts/{iri}")
        assert crud.status_code == 200, crud.text
        crud_body = crud.json()
        assert sorted(crud_body["synonyms"]) == ["Churn", "Customer Attrition"]
        assert crud_body["examples"] == ["monthly churn rate"]
        assert crud_body["related_concepts"] == [related_iri]

    def test_delete_draft_concept(self, client: TestClient, make_collection):
        c = make_collection("Delete Concept Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Doomed",
        }).raise_for_status()
        iri = f"{c['iri']}/doomed"
        r = client.delete(f"/api/knowledge/concepts/{iri}")
        assert r.status_code == 200
        assert client.get(f"/api/knowledge/concepts/{iri}").status_code == 404


# ---------------------------------------------------------------------------
# Non-Concept concept types — property / class / individual / term
# ---------------------------------------------------------------------------
#
# Regression: ``POST /api/knowledge/concepts`` used to write ``skos:Concept``
# for every concept_type, so custom properties (and classes, individuals,
# terms) showed the wrong badge on the detail page and lost their
# domain/range/property_type fields entirely. These tests pin the round-trip
# for each supported user-facing type.


class TestKnowledgeConceptTypes:
    def test_create_object_property_round_trips(
        self, client: TestClient, make_collection
    ):
        c = make_collection("Prop Coll")
        r = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "hasOwner",
            "definition": "Links a resource to its owner",
            "concept_type": "property",
            "property_type": "object",
            "domain": "https://schema.org/Thing",
            "range": "https://schema.org/Person",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["concept_type"] == "property"
        assert body["property_type"] == "object"
        assert body["domain"] == "https://schema.org/Thing"
        assert body["range"] == "https://schema.org/Person"

        # Knowledge CRUD read endpoint
        iri = body["iri"]
        crud = client.get(f"/api/knowledge/concepts/{iri}").json()
        assert crud["concept_type"] == "property"
        assert crud["property_type"] == "object"
        assert crud["domain"] == "https://schema.org/Thing"
        assert crud["range"] == "https://schema.org/Person"

        # Detail endpoint backing the concept-detail page + edit dialog
        detail = client.get(f"/api/semantic-models/concepts/{iri}").json()["concept"]
        assert detail["concept_type"] == "property"
        assert detail["property_type"] == "object"
        assert detail["domain"] == "https://schema.org/Thing"
        assert detail["range"] == "https://schema.org/Person"

    def test_create_datatype_property_round_trips(
        self, client: TestClient, make_collection
    ):
        c = make_collection("DT Prop Coll")
        r = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "name",
            "concept_type": "property",
            "property_type": "datatype",
            "range": "http://www.w3.org/2001/XMLSchema#string",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["concept_type"] == "property"
        assert body["property_type"] == "datatype"
        assert body["range"] == "http://www.w3.org/2001/XMLSchema#string"

    def test_create_annotation_property_round_trips(
        self, client: TestClient, make_collection
    ):
        c = make_collection("Anno Prop Coll")
        r = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "deprecatedReason",
            "concept_type": "property",
            "property_type": "annotation",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["concept_type"] == "property"
        assert body["property_type"] == "annotation"

    def test_create_class_concept_round_trips(
        self, client: TestClient, make_collection
    ):
        c = make_collection("Class Coll")
        r = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "Vehicle",
            "concept_type": "class",
        })
        assert r.status_code == 200, r.text
        assert r.json()["concept_type"] == "class"

    def test_create_individual_concept_round_trips(
        self, client: TestClient, make_collection
    ):
        c = make_collection("Indiv Coll")
        r = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "Earth",
            "concept_type": "individual",
        })
        assert r.status_code == 200, r.text
        assert r.json()["concept_type"] == "individual"

    def test_create_term_concept_round_trips(
        self, client: TestClient, make_collection
    ):
        """A "term" is stored as ``skos:Concept`` plus an ``ontos:conceptType``
        annotation; the read path must restore the original "term" label so the
        UI badge matches what the user picked."""
        c = make_collection("Term Coll")
        r = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "MRR",
            "concept_type": "term",
        })
        assert r.status_code == 200, r.text
        assert r.json()["concept_type"] == "term"

    def test_default_concept_type_is_concept(
        self, client: TestClient, make_collection
    ):
        """Concepts created without a concept_type (the dialog default) must
        keep their ``skos:Concept`` typing and read back as 'concept', not
        'individual'."""
        c = make_collection("Default Coll")
        r = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Quality",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["concept_type"] == "concept"
        # property_type is irrelevant for non-property concepts
        assert body.get("property_type") is None
        assert body.get("domain") is None
        assert body.get("range") is None

    def test_patch_property_updates_property_type_and_domain_range(
        self, client: TestClient, make_collection
    ):
        c = make_collection("Patch Prop Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "score",
            "concept_type": "property",
            "property_type": "object",
            "domain": "https://schema.org/Thing",
            "range": "https://schema.org/Number",
        }).raise_for_status()
        iri = f"{c['iri']}/score"

        # Switch object → datatype property and replace range
        r = client.patch(f"/api/knowledge/concepts/{iri}", json={
            "concept_type": "property",
            "property_type": "datatype",
            "range": "http://www.w3.org/2001/XMLSchema#decimal",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["concept_type"] == "property"
        assert body["property_type"] == "datatype"
        assert body["range"] == "http://www.w3.org/2001/XMLSchema#decimal"
        # Domain was not in the PATCH; the previous value should survive.
        assert body["domain"] == "https://schema.org/Thing"

    def test_patch_property_domain_only_preserves_property_type(
        self, client: TestClient, make_collection
    ):
        """Sending only ``domain`` (a common case when the user edits an
        existing property in the dialog without re-picking the subtype) must
        keep the existing ``property_type`` instead of silently demoting it."""
        c = make_collection("Partial Patch Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "ownedBy",
            "concept_type": "property",
            "property_type": "object",
            "domain": "https://schema.org/Thing",
            "range": "https://schema.org/Person",
        }).raise_for_status()
        iri = f"{c['iri']}/ownedby"

        r = client.patch(f"/api/knowledge/concepts/{iri}", json={
            "domain": "https://schema.org/Organization",
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["concept_type"] == "property"
        assert body["property_type"] == "object"
        assert body["domain"] == "https://schema.org/Organization"

    def test_concepts_grouped_listing_reports_property_subtype(
        self, client: TestClient, make_collection
    ):
        """The grouped-concepts listing (powers tree views and the concepts
        page) must surface ``property_type`` so the right icon is rendered
        for object/datatype/annotation properties."""
        c = make_collection("Grouped Prop Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"],
            "label": "publishedAt",
            "concept_type": "property",
            "property_type": "datatype",
            "range": "http://www.w3.org/2001/XMLSchema#dateTime",
        }).raise_for_status()

        groups = client.get(
            "/api/semantic-models/concepts-grouped"
        ).json()["grouped_concepts"]
        slug = c["iri"].rsplit(":", 1)[-1]
        assert slug in groups
        matches = [g for g in groups[slug] if g.get("label") == "publishedAt"]
        assert matches, f"Expected a 'publishedAt' entry in {slug}"
        assert matches[0]["concept_type"] == "property"
        assert matches[0]["property_type"] == "datatype"


# ---------------------------------------------------------------------------
# Bug 1 + 2 — cache freshness for collections + concepts
# ---------------------------------------------------------------------------


class TestCollectionConceptCountFreshness:
    """After create-collection + create-concept, the count and the
    `concepts-grouped` payload must reflect the new data WITHOUT requiring
    an app restart or an explicit /refresh-graph call.
    """

    def test_collection_concept_count_updates_after_concept_create(
        self, client: TestClient, make_collection
    ):
        c = make_collection("Count Coll")
        # Initial count = 0
        coll = client.get(f"/api/knowledge/collections/{c['iri']}").json()
        assert coll["concept_count"] == 0

        # Add one concept
        r = client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Email",
        })
        assert r.status_code == 200, r.text

        # Count must now be 1 — without rebuild
        coll = client.get(f"/api/knowledge/collections/{c['iri']}").json()
        assert coll["concept_count"] == 1, (
            f"Expected concept_count=1 immediately after creation, got {coll['concept_count']}. "
            "Likely cause: stale self._cached_concepts in SemanticModelsManager."
        )

    def test_concepts_grouped_includes_new_concept(
        self, client: TestClient, make_collection
    ):
        c = make_collection("Grouped Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Phone",
        }).raise_for_status()

        r = client.get("/api/semantic-models/concepts-grouped")
        assert r.status_code == 200
        groups = r.json()["grouped_concepts"]

        # Source key for urn:glossary:<slug> must be the slug.
        slug = c["iri"].rsplit(":", 1)[-1]
        assert slug in groups, (
            f"Expected source-context group '{slug}' in concepts-grouped, "
            f"got keys={list(groups.keys())}. Cache likely stale."
        )
        labels = [item.get("label") for item in groups[slug]]
        assert "Phone" in labels


# ---------------------------------------------------------------------------
# Bug 4 — ontology generator save-to-collection
# ---------------------------------------------------------------------------


_TINY_TURTLE = """@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix ex: <http://example.org/onto/> .

ex:Person a owl:Class ; rdfs:label "Person" .
ex:Animal a owl:Class ; rdfs:label "Animal" .
"""


class TestOntologyGeneratorSave:
    def test_save_to_collection_creates_listed_collection_with_concepts(
        self, client: TestClient, semantic_models_manager
    ):
        r = client.post("/api/ontology/save-to-collection", json={
            "collection_name": "Generator Test",
            "collection_description": "from test",
            "owl_content": _TINY_TURTLE,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        assert body["collection_iri"] == "urn:ontology:generator-test"
        assert body["triples_imported"] >= 4

        # The new collection must show in the list with the concept count.
        listing = client.get("/api/knowledge/collections").json()["collections"]
        match = next((c for c in listing if c["iri"] == "urn:ontology:generator-test"), None)
        assert match is not None
        assert match["concept_count"] >= 2, (
            f"Generated ontology collection should report >=2 concepts, got {match['concept_count']}. "
            "Likely cause: source_context not stripped for urn:ontology: prefix."
        )

        # And the concepts should appear under the right source key.
        groups = client.get("/api/semantic-models/concepts-grouped").json()["grouped_concepts"]
        assert "generator-test" in groups, (
            f"Expected 'generator-test' key in concepts-grouped, got {list(groups.keys())}. "
            "Concepts likely fell into the 'Unassigned' bucket."
        )
        assert "Unassigned" not in groups or all(
            c.get("source_context") != "Unassigned" for c in groups.get("Unassigned", [])
            if "generator-test" in (c.get("iri") or "")
        )

    def test_save_to_collection_recovers_from_truncated_turtle(
        self, client: TestClient, semantic_models_manager
    ):
        """Regression: LLM-generated Turtle is often cut off mid-statement.

        Previously this raised ``IndexError: string index out of range`` deep
        inside rdflib's notation3 ``path()`` and surfaced as a 500. The route
        must now apply the truncation cleanup heuristic and import only the
        complete prefix of the payload.
        """
        truncated_payload = (
            _TINY_TURTLE
            + "ex:Vehicle a owl:Class ;\n"
            + "    rdfs:label \"Vehic"
        )
        r = client.post("/api/ontology/save-to-collection", json={
            "collection_name": "Truncated Onto",
            "owl_content": truncated_payload,
        })
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        # Person + Animal definitely import; the Vehicle fragment is dropped.
        assert body["triples_imported"] >= 4

        groups = client.get("/api/semantic-models/concepts-grouped").json()["grouped_concepts"]
        assert "truncated-onto" in groups
        labels = {c.get("label") for c in groups["truncated-onto"]}
        assert "Person" in labels
        assert "Animal" in labels
        assert "Vehic" not in labels  # truncated fragment must not leak through

    def test_save_to_collection_returns_400_for_unparseable_content(
        self, client: TestClient, semantic_models_manager
    ):
        """Garbage that cannot be salvaged should be a clean 400, not a 500."""
        r = client.post("/api/ontology/save-to-collection", json={
            "collection_name": "Garbage Onto",
            "owl_content": "not turtle at all <<< >>> {{{",
        })
        assert r.status_code == 400, r.text
        assert "invalid" in r.json().get("detail", "").lower() or "turtle" in r.json().get("detail", "").lower()


# ---------------------------------------------------------------------------
# Bug 3 — semantic links to concepts
# ---------------------------------------------------------------------------


class TestSemanticLinksAgainstConcepts:
    def test_create_link_persists_and_is_listable(
        self, client: TestClient, make_collection
    ):
        c = make_collection("Link Source Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Customer",
        }).raise_for_status()
        concept_iri = f"{c['iri']}/customer"

        entity_id = f"prod-{uuid.uuid4().hex[:8]}"
        r = client.post("/api/semantic-links/", json={
            "entity_id": entity_id,
            "entity_type": "data_product",
            "iri": concept_iri,
            "label": "Customer",
        })
        assert r.status_code == 200, r.text
        link_id = r.json()["id"]

        # Lookup by entity
        by_entity = client.get(
            f"/api/semantic-links/entity/data_product/{entity_id}"
        ).json()
        assert any(item["id"] == link_id for item in by_entity)

        # Lookup by IRI
        by_iri = client.get(f"/api/semantic-links/iri/{concept_iri}").json()
        assert any(item["id"] == link_id for item in by_iri)

    def test_delete_link_round_trip(
        self, client: TestClient, make_collection, db_session: Session
    ):
        from src.controller.semantic_links_manager import SemanticLinksManager

        c = make_collection("Link Delete Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Order",
        }).raise_for_status()
        concept_iri = f"{c['iri']}/order"

        entity_id = f"prod-{uuid.uuid4().hex[:8]}"
        link = client.post("/api/semantic-links/", json={
            "entity_id": entity_id,
            "entity_type": "data_product",
            "iri": concept_iri,
        }).json()

        # NOTE: deleting via the HTTP route hits a pre-existing PG_UUID/SQLite
        # incompatibility in CRUDBase.remove (unrelated to this feature). We
        # call the manager directly with a UUID-typed id so this test exercises
        # the right code path on SQLite.
        manager = SemanticLinksManager(db_session, semantic_models_manager=None)
        ok = manager.remove(uuid.UUID(link["id"]), removed_by="tester")
        assert ok is True

        rest = client.get(
            f"/api/semantic-links/entity/data_product/{entity_id}"
        ).json()
        assert all(item["id"] != link["id"] for item in rest)

    def test_link_create_invalidates_concept_cache(
        self, client: TestClient, make_collection, semantic_models_manager
    ):
        """After a semantic link is created, the manager's cached concepts
        must be re-read on the next call so any IRI-based queries reflect
        the link in the in-memory graph."""
        c = make_collection("Link Cache Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Address",
        }).raise_for_status()
        concept_iri = f"{c['iri']}/address"

        # Warm the cache
        client.get("/api/semantic-models/concepts-grouped").raise_for_status()
        cached_before = semantic_models_manager._cached_concepts

        client.post("/api/semantic-links/", json={
            "entity_id": "prod-cache-1",
            "entity_type": "data_product",
            "iri": concept_iri,
        }).raise_for_status()

        # The mutation must have invalidated (or refreshed) the cache.
        assert semantic_models_manager._cached_concepts is None or (
            semantic_models_manager._cached_concepts is not cached_before
        ), "Semantic-link mutation must invalidate the concepts cache."


# ---------------------------------------------------------------------------
# Bug 5 — Rebuild Graph end-to-end
# ---------------------------------------------------------------------------


class TestRebuildGraph:
    def test_rebuild_graph_endpoint_returns_success(
        self, client: TestClient, semantic_models_manager
    ):
        r = client.post("/api/semantic-models/refresh-graph")
        assert r.status_code == 200, r.text
        assert "message" in r.json()

    def test_rebuild_graph_makes_new_concepts_visible(
        self, client: TestClient, make_collection, semantic_models_manager
    ):
        """End-to-end: even without the in-line cache fix, a Rebuild Graph
        call MUST leave the API returning the latest counts."""
        c = make_collection("Rebuild Coll")
        client.post("/api/knowledge/concepts", json={
            "collection_iri": c["iri"], "label": "Rebuilt",
        }).raise_for_status()

        # Force rebuild
        r = client.post("/api/semantic-models/refresh-graph")
        assert r.status_code == 200

        coll = client.get(f"/api/knowledge/collections/{c['iri']}").json()
        assert coll["concept_count"] == 1

        groups = client.get("/api/semantic-models/concepts-grouped").json()["grouped_concepts"]
        slug = c["iri"].rsplit(":", 1)[-1]
        assert slug in groups

    def test_rebuild_graph_resolves_ontology_collection_source_context(
        self, client: TestClient, semantic_models_manager
    ):
        """Generator-created ontology collections must group concepts under
        the collection slug (not 'Unassigned') after a rebuild."""
        client.post("/api/ontology/save-to-collection", json={
            "collection_name": "Rebuild Onto",
            "owl_content": _TINY_TURTLE,
        }).raise_for_status()

        client.post("/api/semantic-models/refresh-graph").raise_for_status()

        groups = client.get("/api/semantic-models/concepts-grouped").json()["grouped_concepts"]
        assert "rebuild-onto" in groups, (
            f"After rebuild, ontology collection concepts must group under their slug. "
            f"Got keys={list(groups.keys())}."
        )

    def test_rebuild_graph_clears_in_memory_caches_atomically(
        self, semantic_models_manager
    ):
        """Defensive contract: a rebuild must never leave a stale
        in-memory cache pointer alive on partial failure."""
        # Pre-load a sentinel value so we can detect whether rebuild reset it.
        semantic_models_manager._cached_concepts = ["SENTINEL"]
        semantic_models_manager._cached_taxonomies = ["SENTINEL"]
        semantic_models_manager._cached_stats = "SENTINEL"

        semantic_models_manager.rebuild_graph_from_enabled()

        assert semantic_models_manager._cached_concepts != ["SENTINEL"]
        assert semantic_models_manager._cached_taxonomies != ["SENTINEL"]
        assert semantic_models_manager._cached_stats != "SENTINEL"
