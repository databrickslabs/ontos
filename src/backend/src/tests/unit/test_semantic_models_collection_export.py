"""
Unit tests for SemanticModelsManager collection RDF export.

Regression coverage for the 404-on-download bug: in-app created (modifiable)
collections such as business glossaries are stored only as triples in the
rdf_triples table, never as uploaded files. Exporting must generate RDF from
those persisted triples rather than relying on a possibly-unhydrated in-memory
graph context.
"""
import pytest
from rdflib import ConjunctiveGraph

from src.controller.semantic_models_manager import SemanticModelsManager


@pytest.fixture
def manager(db_session):
    """A SemanticModelsManager backed by the in-memory test session."""
    return SemanticModelsManager(db=db_session)


class TestCollectionExport:
    def _create_glossary_with_concept(self, manager):
        collection = manager.create_collection(
            label="NEBW Export Glossary",
            collection_type="glossary",
            is_editable=True,
            created_by="tester@example.com",
        )
        iri = collection["iri"]
        manager.create_concept(
            collection_iri=iri,
            label="Customer",
            definition="A person or organization that buys goods or services.",
            created_by="tester@example.com",
        )
        return iri

    def test_export_turtle_from_persisted_triples(self, manager):
        """Turtle export reflects the persisted concept triples."""
        iri = self._create_glossary_with_concept(manager)

        ttl = manager.export_collection_as_turtle(iri)

        assert ttl and isinstance(ttl, str)
        assert "Customer" in ttl

    def test_export_survives_empty_in_memory_context(self, manager):
        """Export must not 404 when the in-memory graph context is empty/stale.

        Simulates the reported bug by wiping the in-memory graph after the
        collection is persisted; the DB triples are the source of truth so the
        export still succeeds.
        """
        iri = self._create_glossary_with_concept(manager)

        # Drop everything the manager holds in memory.
        manager._graph = ConjunctiveGraph()

        ttl = manager.export_collection_as_turtle(iri)
        assert "Customer" in ttl

        rdfxml = manager.export_collection_as_rdfxml(iri)
        assert rdfxml and "Customer" in rdfxml

    def test_export_unknown_collection_raises(self, manager):
        """A genuinely missing collection still raises (→ 404 at the route)."""
        with pytest.raises(ValueError):
            manager.export_collection_as_turtle("urn:glossary:does-not-exist")
