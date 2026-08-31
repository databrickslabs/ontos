"""
Unit tests for user-defined asset-type relationship CRUD.

Relationships were previously read-only, loaded only from the Ontos RDF. These
tests cover the new write path: user-defined relationships persist as
owl:ObjectProperty triples in a dedicated context and become visible through the
existing get_relationships() read path, while Ontos-RDF relationships stay
read-only.
"""
import pytest

from src.controller.semantic_models_manager import SemanticModelsManager
from src.controller.ontology_schema_manager import OntologySchemaManager
from src.models.ontology_schema import (
    RelationshipDefinitionCreate,
    RelationshipDefinitionUpdate,
)

ONTOS = "http://ontos.app/ontology#"
SOURCE = f"{ONTOS}DataProduct"
TARGET = f"{ONTOS}DataDomain"


@pytest.fixture
def manager(db_session):
    smm = SemanticModelsManager(db=db_session)
    return OntologySchemaManager(smm)


class TestRelationshipCrud:
    def test_create_relationship_appears_in_reads(self, manager):
        created = manager.create_relationship(
            RelationshipDefinitionCreate(
                source_type_iri=SOURCE,
                target_type_iri=TARGET,
                label="Owned By Domain",
                cardinality="0..*",
            ),
            created_by="tester@example.com",
        )
        assert created.property_iri.startswith("urn:ontos:custom-property:")
        assert created.property_name == "ownedByDomain"
        assert created.source_type_iri == SOURCE
        assert created.target_type_iri == TARGET

        # Visible as an outgoing relationship on the source type.
        rels = manager.get_relationships(SOURCE)
        assert any(r.property_iri == created.property_iri for r in rels.outgoing)
        # And as an incoming relationship on the target type.
        incoming = manager.get_relationships(TARGET)
        assert any(r.property_iri == created.property_iri for r in incoming.incoming)

        # Listed as a custom relationship.
        assert any(r.property_iri == created.property_iri for r in manager.list_custom_relationships())

    def test_create_rejects_unknown_class(self, manager):
        with pytest.raises(ValueError):
            manager.create_relationship(
                RelationshipDefinitionCreate(
                    source_type_iri=f"{ONTOS}NotARealClass",
                    target_type_iri=TARGET,
                    label="Bad",
                )
            )

    def test_update_relationship(self, manager):
        created = manager.create_relationship(
            RelationshipDefinitionCreate(
                source_type_iri=SOURCE, target_type_iri=TARGET, label="Rel One"
            )
        )
        updated = manager.update_relationship(
            created.property_iri,
            RelationshipDefinitionUpdate(label="Rel Renamed", cardinality="1..1"),
        )
        assert updated.label == "Rel Renamed"
        assert updated.cardinality == "1..1"

    def test_delete_relationship(self, manager):
        created = manager.create_relationship(
            RelationshipDefinitionCreate(
                source_type_iri=SOURCE, target_type_iri=TARGET, label="Temp Rel"
            )
        )
        manager.delete_relationship(created.property_iri)
        assert not any(
            r.property_iri == created.property_iri
            for r in manager.list_custom_relationships()
        )
        rels = manager.get_relationships(SOURCE)
        assert not any(r.property_iri == created.property_iri for r in rels.outgoing)

    def test_cannot_delete_ontos_relationship(self, manager):
        """An Ontos-RDF object property must not be deletable via this path."""
        # Grab a genuine ontology relationship, if any exist for the source type.
        rels = manager.get_relationships(SOURCE)
        ontos_rels = [r for r in rels.outgoing if r.property_iri.startswith(ONTOS)]
        if not ontos_rels:
            pytest.skip("No Ontos-RDF relationships on source type to guard against")
        with pytest.raises(ValueError):
            manager.delete_relationship(ontos_rels[0].property_iri)
