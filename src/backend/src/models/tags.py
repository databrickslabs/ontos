from __future__ import annotations # For Tag.parent type hint
import json
from enum import Enum
from typing import List, Optional, Any, Union
from uuid import UUID
from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator, computed_field

DEFAULT_NAMESPACE_NAME = "default"
TAG_NAMESPACE_SEPARATOR = "/"

class TagStatus(str, Enum):
    ACTIVE = "active"
    DRAFT = "draft"
    CANDIDATE = "candidate"
    DEPRECATED = "deprecated"
    INACTIVE = "inactive"
    RETIRED = "retired"

class TagAccessLevel(str, Enum):
    READ_ONLY = "read_only"
    READ_WRITE = "read_write"
    ADMIN = "admin"

# --- TagNamespace Models ---
class TagNamespaceBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$",
                     description="Name of the namespace. Use letters, numbers, underscores, or hyphens.")
    description: Optional[str] = None

class TagNamespaceCreate(TagNamespaceBase):
    pass

class TagNamespaceUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")
    description: Optional[str] = None

class TagNamespace(TagNamespaceBase):
    id: UUID
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }

# --- Tag Models ---
class TagBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$",
                     description="Name of the tag. Use letters, numbers, underscores, or hyphens.")
    description: Optional[str] = None
    possible_values: Optional[List[str]] = Field(None, description="List of predefined possible values for this tag.")
    status: TagStatus = Field(TagStatus.ACTIVE, description="Lifecycle status of the tag.")
    version: Optional[str] = Field(None, description="Version of the tag, e.g., v1.0.")
    parent_id: Optional[UUID] = Field(None, description="ID of the parent tag for hierarchical structures.")

class TagCreate(TagBase):
    # For convenience, allow creating a tag by specifying namespace name or ID.
    # The manager will resolve namespace_name to namespace_id if provided.
    namespace_name: Optional[str] = Field(None, description="Name of the namespace. If not provided, 'default' is used. If namespace_id is provided, this is ignored.")
    namespace_id: Optional[UUID] = Field(None, description="ID of the namespace. Overrides namespace_name if both are provided.")

    @model_validator(mode='before')
    def handle_possible_values_input(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        possible_values = values.get('possible_values')
        if isinstance(possible_values, str):
            try:
                loaded_values = json.loads(possible_values)
                if not isinstance(loaded_values, list) or not all(isinstance(item, str) for item in loaded_values):
                    raise ValueError("'possible_values' must be a JSON string representing a list of strings.")
                values['possible_values'] = loaded_values
            except json.JSONDecodeError:
                raise ValueError("'possible_values' string is not valid JSON.")
        elif possible_values is not None and not (isinstance(possible_values, list) and all(isinstance(item, str) for item in possible_values)):
             raise ValueError("'possible_values' must be a list of strings or a JSON string representing a list of strings.")
        return values

class TagUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255, pattern=r"^[a-zA-Z0-9_-]+$")
    description: Optional[str] = None
    possible_values: Optional[Union[List[str], str]] = Field(None, description="List of predefined possible values or a JSON string of a list.")
    status: Optional[TagStatus] = None
    version: Optional[str] = None
    parent_id: Optional[UUID] = None
    namespace_id: Optional[UUID] = Field(None, description="Cannot change namespace after creation via this model. Use specific service method if needed.")

    @model_validator(mode='before')
    def handle_update_possible_values_input(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        possible_values = values.get('possible_values')
        if isinstance(possible_values, str):
            try:
                loaded_values = json.loads(possible_values)
                if not isinstance(loaded_values, list) or not all(isinstance(item, str) for item in loaded_values):
                    raise ValueError("'possible_values' must be a JSON string representing a list of strings.")
                values['possible_values'] = loaded_values
            except json.JSONDecodeError:
                raise ValueError("'possible_values' string is not valid JSON.")
        elif possible_values is not None and not (isinstance(possible_values, list) and all(isinstance(item, str) for item in possible_values)):
             raise ValueError("'possible_values' must be a list of strings or a JSON string representing a list of strings.")
        return values

class Tag(TagBase):
    id: UUID
    namespace_id: UUID
    # parent: Optional[Tag] = None # Resolved by manager if needed, or fetched with relationships
    # children: List[Tag] = []

    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    # Computed field for fully qualified name, requires namespace to be loaded/available
    # This will be populated by the manager or from a direct DB load with namespace.
    namespace_name: Optional[str] = None # Populated from ORM relationship

    @computed_field
    @property
    def fully_qualified_name(self) -> str:
        ns_name = self.namespace_name or DEFAULT_NAMESPACE_NAME
        return f"{ns_name}{TAG_NAMESPACE_SEPARATOR}{self.name}"

    model_config = {
        "from_attributes": True,
        "populate_by_name": True, # Allow population by alias
    }

# --- TagNamespacePermission Models ---
class TagNamespacePermissionBase(BaseModel):
    group_id: str = Field(..., description="Identifier of the group (e.g., Databricks group name or ID).")
    access_level: TagAccessLevel

class TagNamespacePermissionCreate(TagNamespacePermissionBase):
    namespace_id: Optional[UUID] = Field(None, description="ID of the namespace. If creating permissions via /namespaces/{ns_id}/permissions, this is not needed in body.")
    pass

class TagNamespacePermissionUpdate(BaseModel):
    group_id: Optional[str] = None
    access_level: Optional[TagAccessLevel] = None

class TagNamespacePermission(TagNamespacePermissionBase):
    id: UUID
    namespace_id: UUID
    created_by: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {
        "from_attributes": True
    }

# --- AssignedTag Models (for associating tags with entities) ---
class AssignedTagCreate(BaseModel):
    # Allow assigning by FQN or by direct ID
    tag_fqn: Optional[str] = Field(None, description=f"Fully qualified name of the tag (e.g., namespace{TAG_NAMESPACE_SEPARATOR}tag_name). Used if tag_id is not provided.")
    tag_id: Optional[UUID] = Field(None, description="Direct ID of the tag. Overrides tag_fqn if both provided.")
    assigned_value: Optional[str] = Field(None, description="Value assigned to the tag for this entity. Omitted or null keeps the value already stored for a tag the entity has; an empty string clears it.")

    @model_validator(mode='before')
    def check_tag_identifier(cls, values: Any) -> Dict[str, Any]:
        # If a string is provided, treat it as tag_fqn
        if isinstance(values, str):
            return {'tag_fqn': values}
        # If it's already an AssignedTag object, pass it through (happens during serialization)
        if hasattr(values, '__class__') and values.__class__.__name__ == 'AssignedTag':
            return values
        # Otherwise expect a dict
        if not isinstance(values, dict):
            raise ValueError("Invalid input: expected string (tag FQN), dict, or AssignedTag object")
        if not values.get('tag_fqn') and not values.get('tag_id'):
            raise ValueError("Either 'tag_fqn' or 'tag_id' must be provided.")
        return values

class AssignedTag(BaseModel):
    tag_id: UUID
    tag_name: str
    namespace_id: UUID
    namespace_name: str
    status: TagStatus
    fully_qualified_name: str
    assigned_value: Optional[str] = None
    assigned_by: Optional[str] = None
    assigned_at: datetime

    model_config = {
        "from_attributes": True # If constructed from an ORM object with these fields
    } 