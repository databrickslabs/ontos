"""Format-neutral intermediate representation (IR) of an erwin data model.

Parsers (XML today; JSON and Mart later) produce an ``ErwinModel``; the
mappers (concepts, contracts, UC matching) consume it. Nothing here depends on
Ontos or on the input format.

Every object keeps its erwin object ID (``{GUID}+<suffix>``). Re-imports match
on it, so a renamed entity updates the concept or contract it created instead
of creating a new one.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, PrivateAttr


class ModelType(str, Enum):
    LOGICAL = "logical"
    PHYSICAL = "physical"
    LOGICAL_PHYSICAL = "logical_physical"


class KeyKind(str, Enum):
    PRIMARY = "PK"
    ALTERNATE = "AK"
    INVERSION = "IE"
    FOREIGN = "IF"


class RelationshipKind(str, Enum):
    IDENTIFYING = "identifying"
    NON_IDENTIFYING = "non_identifying"
    SUBTYPE = "subtype"
    MANY_TO_MANY = "many_to_many"


class ErwinDomain(BaseModel):
    id: str
    name: str
    logical_type: Optional[str] = None
    physical_type: Optional[str] = None
    definition: Optional[str] = None
    parent_id: Optional[str] = None
    valid_values: List[str] = Field(default_factory=list)
    # erwin ships built-in root domains (<default>, String, Number, ...) that
    # every model carries. They are kept for reference resolution but never
    # mapped to Ontos.
    is_builtin: bool = False


class ErwinAttribute(BaseModel):
    id: str
    name: str
    physical_name: Optional[str] = None
    logical_type: Optional[str] = None
    physical_type: Optional[str] = None
    # None = not stated in the file (e.g. "XML Standard with Min Info").
    nullable: Optional[bool] = None
    default_value: Optional[str] = None
    domain_id: Optional[str] = None
    definition: Optional[str] = None
    # Set on migrated (foreign key) attributes.
    parent_attribute_id: Optional[str] = None
    parent_relationship_id: Optional[str] = None
    valid_values: List[str] = Field(default_factory=list)
    logical_only: bool = False
    physical_only: bool = False
    udps: Dict[str, str] = Field(default_factory=dict)


class ErwinKeyGroup(BaseModel):
    id: str
    name: str
    kind: KeyKind
    # Attribute IDs in key order.
    attribute_ids: List[str] = Field(default_factory=list)


class ErwinEntity(BaseModel):
    id: str
    name: str
    physical_name: Optional[str] = None
    schema_name: Optional[str] = None
    definition: Optional[str] = None
    note: Optional[str] = None
    is_view: bool = False
    view_sql: Optional[str] = None
    logical_only: bool = False
    physical_only: bool = False
    attributes: List[ErwinAttribute] = Field(default_factory=list)
    key_groups: List[ErwinKeyGroup] = Field(default_factory=list)
    udps: Dict[str, str] = Field(default_factory=dict)

    def primary_key(self) -> Optional[ErwinKeyGroup]:
        return next((k for k in self.key_groups if k.kind == KeyKind.PRIMARY), None)


class ErwinRelationship(BaseModel):
    id: str
    name: Optional[str] = None
    kind: RelationshipKind
    parent_id: str
    child_id: str
    parent_to_child_phrase: Optional[str] = None
    child_to_parent_phrase: Optional[str] = None
    # zero_or_more | one_or_more | zero_or_one | exactly:<n> | raw value
    cardinality: Optional[str] = None
    # True when the child's foreign key may be null (optional parent).
    optional: Optional[bool] = None
    # (child attribute id, parent attribute id) pairs, in child key order.
    fk_pairs: List[List[str]] = Field(default_factory=list)
    definition: Optional[str] = None
    # Set when the kind was inferred rather than read from the file.
    kind_inferred: bool = False


class ErwinSubtypeGroup(BaseModel):
    id: str
    parent_id: str
    child_ids: List[str] = Field(default_factory=list)
    complete: Optional[bool] = None
    exclusive: Optional[bool] = None


class ErwinSubjectArea(BaseModel):
    id: str
    name: str
    definition: Optional[str] = None
    entity_ids: List[str] = Field(default_factory=list)


class ErwinModel(BaseModel):
    id: str
    name: str
    model_type: ModelType
    source_format: str
    # As written in the file (a name, or a numeric erwin code).
    target_dbms: Optional[str] = None
    target_dbms_version: Optional[str] = None
    # Mart version, when known.
    version: Optional[str] = None
    entities: List[ErwinEntity] = Field(default_factory=list)
    relationships: List[ErwinRelationship] = Field(default_factory=list)
    subtype_groups: List[ErwinSubtypeGroup] = Field(default_factory=list)
    subject_areas: List[ErwinSubjectArea] = Field(default_factory=list)
    domains: List[ErwinDomain] = Field(default_factory=list)
    udp_names: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    # Lazily built lookup indexes. The IR is treated as immutable once a parser
    # returns it, so the indexes never go stale.
    _entities_by_id: Optional[Dict[str, ErwinEntity]] = PrivateAttr(default=None)
    _attributes_by_id: Optional[Dict[str, ErwinAttribute]] = PrivateAttr(default=None)
    _entity_by_attribute: Optional[Dict[str, ErwinEntity]] = PrivateAttr(default=None)

    def entity(self, entity_id: str) -> Optional[ErwinEntity]:
        self._build_indexes()
        return self._entities_by_id.get(entity_id)

    def attribute(self, attribute_id: str) -> Optional[ErwinAttribute]:
        self._build_indexes()
        return self._attributes_by_id.get(attribute_id)

    def entity_of_attribute(self, attribute_id: str) -> Optional[ErwinEntity]:
        self._build_indexes()
        return self._entity_by_attribute.get(attribute_id)

    def domain(self, domain_id: str) -> Optional[ErwinDomain]:
        return next((d for d in self.domains if d.id == domain_id), None)

    def _build_indexes(self) -> None:
        if self._entities_by_id is not None:
            return
        self._entities_by_id = {e.id: e for e in self.entities}
        self._attributes_by_id = {a.id: a for e in self.entities for a in e.attributes}
        self._entity_by_attribute = {a.id: e for e in self.entities for a in e.attributes}
