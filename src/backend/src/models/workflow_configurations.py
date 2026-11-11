"""
Pydantic models for workflow configurations.

Defines the schema for configurable workflow parameters.
"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class WorkflowParameterDefinition(BaseModel):
    """Definition of a configurable parameter in a workflow YAML"""
    name: str = Field(..., description="Parameter name")
    type: str = Field(..., description="Parameter type: string, integer, boolean, select, entity_patterns")
    default: Optional[Any] = Field(None, description="Default value for the parameter")
    description: str = Field("", description="Human-readable description")
    required: bool = Field(False, description="Whether parameter is required")
    
    # Type-specific constraints
    options: Optional[List[str]] = Field(None, description="Available options for select type")
    min_value: Optional[float] = Field(None, description="Minimum value for integer/float types")
    max_value: Optional[float] = Field(None, description="Maximum value for integer/float types")
    pattern: Optional[str] = Field(None, description="Regex pattern for string validation")
    entity_types: Optional[List[str]] = Field(None, description="Entity types for entity_patterns type")

    class Config:
        json_schema_extra = {
            "example": {
                "name": "entity_patterns",
                "type": "entity_patterns",
                "description": "Tag patterns for discovering entities",
                "required": True,
                "entity_types": ["contract", "product", "domain"]
            }
        }


class EntityPatternConfig(BaseModel):
    """Configuration for a single entity pattern (used in entity_patterns parameter type)"""
    entity_type: str = Field(..., description="Entity type: contract, product, domain, etc.")
    enabled: bool = Field(True, description="Whether this entity type is enabled for discovery")
    
    # Filter pattern (optional, for scoping which objects to consider)
    filter_source: Optional[str] = Field(None, description="Source for filter: key or value")
    filter_pattern: Optional[str] = Field(None, description="Regex pattern for filtering")
    
    # Key pattern (required, to match tag keys)
    key_pattern: str = Field(..., description="Regex pattern to match tag keys")
    
    # Value extraction (required, to extract entity name)
    value_extraction_source: str = Field(..., description="Source for extraction: key or value")
    value_extraction_pattern: str = Field(..., description="Regex pattern with capture group to extract name")

    class Config:
        json_schema_extra = {
            "example": {
                "entity_type": "contract",
                "enabled": True,
                "key_pattern": "^data-contract-(.+)$",
                "value_extraction_source": "key",
                "value_extraction_pattern": "^data-contract-(.+)$"
            }
        }


class WorkflowConfiguration(BaseModel):
    """Workflow configuration with parameter values"""
    workflow_id: str = Field(..., description="Workflow identifier")
    configuration: Dict[str, Any] = Field(..., description="Parameter name to value mapping")

    class Config:
        json_schema_extra = {
            "example": {
                "workflow_id": "uc_bulk_import",
                "configuration": {
                    "entity_patterns": [
                        {
                            "entity_type": "contract",
                            "enabled": True,
                            "key_pattern": "^data-contract-(.+)$",
                            "value_extraction_source": "key",
                            "value_extraction_pattern": "^data-contract-(.+)$"
                        }
                    ],
                    "conflict_strategy": "skip"
                }
            }
        }


class TagSyncConfig(BaseModel):
    """Configuration for a single tag sync entity type (used in tag_sync_configs parameter type)"""
    entity_type: str = Field(..., description="Entity type: semantic_assignment, data_domain, data_contract, data_product")
    enabled: bool = Field(True, description="Whether syncing is enabled for this entity type")
    tag_key_format: str = Field(..., description="Format string for tag key with {VARIABLE} placeholders")
    tag_value_format: str = Field(..., description="Format string for tag value with {VARIABLE} placeholders")
    mapping: Optional[str] = Field(
        None,
        description=(
            "Id of a named mapping, e.g. 'lifecycle_status'. A YAML default entry with an id"
            " is added to saved configurations without an entry of that entity type and id."
        ),
    )

    @staticmethod
    def validate_tag_key(key: str) -> None:
        """Validate tag key against UC governed tag constraints.

        Tag keys cannot contain: commas, periods, colons, hyphens, forward slashes,
        backticks, equals signs, or leading/trailing spaces.
        """
        invalid_chars = [',', '.', ':', '-', '/', '`', '=']
        for char in invalid_chars:
            if char in key:
                raise ValueError(f"Tag key cannot contain '{char}': {key}")
        if key != key.strip():
            raise ValueError(f"Tag key cannot have leading/trailing spaces: '{key}'")
        if not key:
            raise ValueError("Tag key cannot be empty")

    class Config:
        json_schema_extra = {
            "example": {
                "entity_type": "semantic_assignment",
                "enabled": True,
                "tag_key_format": "ontos_semantic_{LINK.SLUG}",
                "tag_value_format": "{LINK.IRI}"
            }
        }


class WorkflowConfigurationUpdate(BaseModel):
    """Update workflow configuration"""
    configuration: Dict[str, Any] = Field(..., description="Parameter name to value mapping")

    class Config:
        json_schema_extra = {
            "example": {
                "configuration": {
                    "entity_patterns": [],
                    "conflict_strategy": "update"
                }
            }
        }


class WorkflowConfigurationResponse(BaseModel):
    """Response model for workflow configuration"""
    id: str
    workflow_id: str
    configuration: Dict[str, Any]
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

