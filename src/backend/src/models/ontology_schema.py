"""Pydantic models for the ontology-driven schema API.

These models represent entity type definitions, field schemas, and
relationship rules extracted from the RDF ontology by OntologySchemaService.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EntityFieldDefinition(BaseModel):
    """A single field (data property) for an entity type, extracted from the ontology."""
    iri: str = Field(..., description="Full IRI of the data property")
    name: str = Field(..., description="Local name (e.g. 'physicalPath')")
    label: str = Field(..., description="Human-readable label from rdfs:label")
    comment: Optional[str] = Field(None, description="Description from rdfs:comment")
    range_type: str = Field("string", description="XSD range type mapped to a simple string (string, boolean, integer, date, datetime, uri)")
    field_type: str = Field("text", description="UI widget type from ontos:uiFieldType")
    field_order: int = Field(100, description="Sort order from ontos:uiFieldOrder")
    is_required: bool = Field(False, description="Whether the field is required from ontos:isRequired")
    field_group: str = Field("basic", description="Logical form section from ontos:uiFieldGroup")
    select_options: Optional[List[str]] = Field(None, description="Allowed values for select/multiselect fields")


class EntityTypeDefinition(BaseModel):
    """An entity type (class) defined in the ontology with its UI metadata."""
    model_config = {"protected_namespaces": ()}

    iri: str = Field(..., description="Full IRI of the class (e.g. http://ontos.app/ontology#Dataset)")
    local_name: str = Field(..., description="Short name (e.g. 'Dataset')")
    label: str = Field(..., description="Human-readable label from rdfs:label")
    comment: Optional[str] = Field(None, description="Description from rdfs:comment")
    model_tier: str = Field(..., description="'dedicated' or 'asset'")
    ui_icon: Optional[str] = Field(None, description="Lucide icon name")
    ui_category: Optional[str] = Field(None, description="Grouping category: data, governance, analytics, integration, system")
    ui_display_order: Optional[int] = Field(None, description="Sort order within category")
    persona_visibility: Optional[List[str]] = Field(None, description="List of persona IDs that can see this type")
    parent_class: Optional[str] = Field(None, description="IRI of the direct parent class")
    parent_class_label: Optional[str] = Field(None, description="Label of the direct parent class")


class EntityTypeSchema(BaseModel):
    """Complete field schema for an entity type, suitable for driving a dynamic form."""
    model_config = {"protected_namespaces": ()}

    type_iri: str
    type_label: str
    model_tier: str
    fields: List[EntityFieldDefinition] = Field(default_factory=list)
    json_schema: Optional[Dict[str, Any]] = Field(None, description="JSON Schema representation for validation")


class RelationshipDefinition(BaseModel):
    """A valid relationship (object property) for an entity type."""
    property_iri: str = Field(..., description="Full IRI of the object property")
    property_name: str = Field(..., description="Local name (e.g. 'hasDataset')")
    label: str = Field(..., description="Human-readable label from ontos:uiLabel or rdfs:label")
    inverse_label: Optional[str] = Field(None, description="Label for the reverse direction")
    source_type_iri: str = Field(..., description="IRI of the domain class")
    source_type_label: Optional[str] = None
    target_type_iri: str = Field(..., description="IRI of the range class")
    target_type_label: Optional[str] = None
    cardinality: str = Field("0..*", description="Cardinality constraint (0..1, 1..1, 0..*, 1..*)")
    display_context: str = Field("tab", description="Where to render: detail-page, sidebar, tab, inline")
    direction: str = Field("outgoing", description="'outgoing' (domain match) or 'incoming' (range match)")


class EntityRelationships(BaseModel):
    """All relationships for an entity type (both outgoing and incoming)."""
    type_iri: str
    outgoing: List[RelationshipDefinition] = Field(default_factory=list)
    incoming: List[RelationshipDefinition] = Field(default_factory=list)


class EntityHierarchyNode(BaseModel):
    """A node in the class hierarchy tree."""
    model_config = {"protected_namespaces": ()}

    iri: str
    label: str
    model_tier: Optional[str] = None
    ui_icon: Optional[str] = None
    children: List["EntityHierarchyNode"] = Field(default_factory=list)


class AssetTypeSyncResult(BaseModel):
    """Result of syncing ontology asset types to the database."""
    created: List[str] = Field(default_factory=list)
    updated: List[str] = Field(default_factory=list)
    unchanged: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class RelationshipDefinitionCreate(BaseModel):
    """Payload to create a user-defined relationship (object property).

    Source and target may be any class in the ontology graph (custom asset types
    or built-in Ontos classes). Only user-defined relationships can be created,
    updated, or deleted; Ontos-RDF relationships remain read-only.
    """
    source_type_iri: str = Field(..., description="IRI of the domain (source) class")
    target_type_iri: str = Field(..., description="IRI of the range (target) class")
    label: str = Field(..., min_length=1, description="Human-readable label for the relationship")
    inverse_label: Optional[str] = Field(None, description="Label for the reverse direction")
    property_name: Optional[str] = Field(
        None,
        description="Optional local name for the property; derived from the label if omitted.",
    )
    cardinality: str = Field("0..*", description="Cardinality constraint (0..1, 1..1, 0..*, 1..*)")
    display_context: str = Field("tab", description="Where to render: detail-page, sidebar, tab, inline")


class RelationshipDefinitionUpdate(BaseModel):
    """Editable attributes of a user-defined relationship. Domain/range are immutable."""
    label: Optional[str] = Field(None, min_length=1)
    inverse_label: Optional[str] = None
    cardinality: Optional[str] = None
    display_context: Optional[str] = None
