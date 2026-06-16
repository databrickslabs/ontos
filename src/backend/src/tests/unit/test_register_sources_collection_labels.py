"""Tests for label backfill in `_register_sources_as_collections`.

The auto-registration step also refreshes the `rdfs:label` of already-
registered, system-managed (`isEditable = "false"`) `ontos:KnowledgeCollection`
rows when the current humanizer would produce a different result. Editable
collections must be left untouched so user edits in the Collections tab never
get clobbered.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from rdflib import Literal, Namespace, RDF, RDFS, URIRef

from src.controller.semantic_models_manager import SemanticModelsManager
from src.repositories.rdf_triples_repository import rdf_triples_repo

ONTOS = Namespace("http://ontos.app/ontology#")
META_CONTEXT = "urn:meta:sources"


@pytest.fixture
def manager_no_rebuild(db_session, tmp_path):
    """Manager with the heavy graph rebuild step stubbed out."""
    with patch.object(SemanticModelsManager, "rebuild_graph_from_enabled", lambda self: None):
        yield SemanticModelsManager(db_session, data_dir=tmp_path)


def _seed_collection(
    manager: SemanticModelsManager,
    coll_iri: str,
    label: str,
    is_editable: bool,
) -> None:
    """Insert an `ontos:KnowledgeCollection` row directly into the meta graph and DB."""
    meta_context = manager._graph.get_context(URIRef(META_CONTEXT))
    coll_uri = URIRef(coll_iri)
    meta_context.add((coll_uri, RDF.type, ONTOS.KnowledgeCollection))
    meta_context.add((coll_uri, RDFS.label, Literal(label)))
    meta_context.add((coll_uri, ONTOS.isEditable, Literal("true" if is_editable else "false")))

    triples = [
        (coll_iri, str(RDF.type), str(ONTOS.KnowledgeCollection), True),
        (coll_iri, str(RDFS.label), label, False),
        (coll_iri, str(ONTOS.isEditable), "true" if is_editable else "false", False),
    ]
    for subj, pred, obj, is_uri in triples:
        rdf_triples_repo.add_triple(
            manager._db,
            subject_uri=subj,
            predicate_uri=pred,
            object_value=obj,
            object_is_uri=is_uri,
            context_name=META_CONTEXT,
            source_type="collection",
            source_identifier=coll_iri,
            created_by="test",
        )
    manager._db.commit()


def _current_label(manager: SemanticModelsManager, coll_iri: str) -> str | None:
    meta_context = manager._graph.get_context(URIRef(META_CONTEXT))
    return manager._get_literal(meta_context, URIRef(coll_iri), RDFS.label)


def _persisted_label_count(manager: SemanticModelsManager, coll_iri: str, value: str) -> int:
    """Count `rdfs:label` triples in the DB for a collection with the given object value."""
    from src.db_models.rdf_triples import RdfTripleDb

    return manager._db.query(RdfTripleDb).filter(
        RdfTripleDb.subject_uri == coll_iri,
        RdfTripleDb.predicate_uri == str(RDFS.label),
        RdfTripleDb.object_value == value,
        RdfTripleDb.context_name == META_CONTEXT,
    ).count()


def test_imported_collection_with_stale_label_is_refreshed(manager_no_rebuild):
    coll_iri = "urn:semantic-model:pizza.owl"
    _seed_collection(manager_no_rebuild, coll_iri, "Pizza.Owl", is_editable=False)

    manager_no_rebuild._register_sources_as_collections()

    assert _current_label(manager_no_rebuild, coll_iri) == "Pizza"
    assert _persisted_label_count(manager_no_rebuild, coll_iri, "Pizza") == 1
    assert _persisted_label_count(manager_no_rebuild, coll_iri, "Pizza.Owl") == 0


def test_imported_collection_with_legacy_titlecase_is_refreshed(manager_no_rebuild):
    """Pre-existing `Odcs Ontology` should become `ODCS Ontology` after acronyms were added."""
    coll_iri = "urn:taxonomy:odcs-ontology"
    _seed_collection(manager_no_rebuild, coll_iri, "Odcs Ontology", is_editable=False)

    manager_no_rebuild._register_sources_as_collections()

    assert _current_label(manager_no_rebuild, coll_iri) == "ODCS Ontology"


def test_editable_collection_label_is_left_untouched(manager_no_rebuild):
    coll_iri = "urn:taxonomy:user-edited-glossary"
    _seed_collection(
        manager_no_rebuild, coll_iri, "Pretty Glossary Title", is_editable=True
    )

    manager_no_rebuild._register_sources_as_collections()

    assert _current_label(manager_no_rebuild, coll_iri) == "Pretty Glossary Title"


def test_label_already_correct_is_noop(manager_no_rebuild):
    coll_iri = "urn:taxonomy:databricks_ontology"
    _seed_collection(manager_no_rebuild, coll_iri, "Databricks Ontology", is_editable=False)

    manager_no_rebuild._register_sources_as_collections()

    assert _current_label(manager_no_rebuild, coll_iri) == "Databricks Ontology"
    # Still exactly one persisted row for the (unchanged) label.
    assert _persisted_label_count(manager_no_rebuild, coll_iri, "Databricks Ontology") == 1


def test_uploaded_model_display_name_wins_over_humanized_suffix(manager_no_rebuild, db_session):
    """If the corresponding semantic model has an explicit display_name set, use it."""
    from src.db_models.semantic_models import SemanticModelDb
    import uuid

    db_session.add(
        SemanticModelDb(
            id=str(uuid.uuid4()),
            name="pizza.owl",
            display_name="My Custom Pizza Title",
            format="rdfs",
            content_text="",
            original_filename="pizza.owl",
            content_type=None,
            size_bytes="0",
            enabled=True,
            created_by="test",
        )
    )
    db_session.commit()

    coll_iri = "urn:semantic-model:pizza.owl"
    _seed_collection(manager_no_rebuild, coll_iri, "Pizza.Owl", is_editable=False)

    manager_no_rebuild._register_sources_as_collections()

    assert _current_label(manager_no_rebuild, coll_iri) == "My Custom Pizza Title"
