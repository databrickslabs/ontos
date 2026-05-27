"""
ODPS v1.0.0 (Open Data Product Standard) API Models

This module implements Pydantic models for the Bitol ODPS v1.0.0 specification.
Schema: https://github.com/bitol-io/open-data-product-standard/blob/main/schema/odps-json-schema-v1.0.0.json

These models are used for API request/response validation and serialization.
"""

from datetime import datetime, date
from enum import Enum
from typing import List, Optional, Dict, Any, Union
import json

from pydantic import BaseModel, Field, field_serializer, field_validator

from .tags import AssignedTag, AssignedTagCreate

from src.common.logging import get_logger
logger = get_logger(__name__)


# ============================================================================
# ODPS v1.0.0 Enums
# ============================================================================

class DataProductStatus(str, Enum):
    """ODPS lifecycle status values. Alias for EntityStatus; kept for backward compatibility.
    Note: CERTIFIED removed — certification is now a separate dimension (see lifecycle.py).
    """
    DRAFT = "draft"
    SANDBOX = "sandbox"
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


# ============================================================================
# Shared Validators
# ============================================================================

def parse_json_if_string(v: Any) -> Any:
    """Parses input if it's a string, returns original otherwise."""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            pass
    return v


# ============================================================================
# Consumer Principal (typed identity reference)
# ============================================================================

class ConsumerPrincipal(BaseModel):
    """Typed principal for ``consumer_principals``.

    Default ``type="group"`` keeps the common case (workspace group display
    names) terse, but the shape is intentionally extensible to non-group
    identity methods (service principals, IdP roles, OAuth scopes) without a
    future breaking migration.
    """
    type: str = Field("group", description="Principal type: 'group' (default), 'service_principal', 'role', 'scope', etc.")
    value: str = Field(..., description="Principal identifier (group display name, SP applicationId, role name, scope, ...)")

    model_config = {"from_attributes": True}


# ============================================================================
# ODPS v1.0.0 Core Models
# ============================================================================

class AuthoritativeDefinition(BaseModel):
    """ODPS v1.0.0 Authoritative Definition"""
    type: str = Field(..., description="Type of definition (businessDefinition, transformationImplementation, etc.)")
    url: str = Field(..., description="URL to the authoritative source")
    description: Optional[str] = Field(None, description="Optional description")

    model_config = {"from_attributes": True}


class CustomProperty(BaseModel):
    """ODPS v1.0.0 Custom Property"""
    property: str = Field(..., description="Property name in camelCase")
    value: Any = Field(..., description="Property value (can be any type)")
    description: Optional[str] = Field(None, description="Optional description")

    model_config = {"from_attributes": True}


class Description(BaseModel):
    """ODPS v1.0.0 Structured Description"""
    purpose: Optional[str] = Field(None, description="Intended purpose for the provided data")
    limitations: Optional[str] = Field(None, description="Technical, compliance, and legal limitations for data use")
    usage: Optional[str] = Field(None, description="Recommended usage of the data")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None, description="Links to authoritative sources")
    customProperties: Optional[List[CustomProperty]] = Field(None, description="Custom properties for description")

    model_config = {"from_attributes": True}


# ============================================================================
# ODPS v1.0.0 Port Models
# ============================================================================

class InputPort(BaseModel):
    """ODPS v1.0.0 Input Port"""
    # ODPS required fields
    name: str = Field(..., description="Name of the input port")
    version: str = Field(..., description="Version of the input port")
    contractId: str = Field(..., alias="contract_id", description="Contract ID for the input port (REQUIRED in ODPS)")

    # ODPS optional fields
    tags: Optional[List[str]] = Field(None, description="Tags for categorization")
    customProperties: Optional[List[CustomProperty]] = Field(None, description="Custom properties")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None, description="Authoritative definitions")

    # Databricks extensions
    assetType: Optional[str] = Field(None, alias="asset_type", description="Type of Databricks asset (table, notebook, job)")
    assetIdentifier: Optional[str] = Field(None, alias="asset_identifier", description="Unique identifier for the asset")

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


class SBOM(BaseModel):
    """ODPS v1.0.0 Software Bill of Materials"""
    type: str = Field("external", description="Type of SBOM")
    url: str = Field(..., description="URL to the SBOM")

    model_config = {"from_attributes": True}


class InputContract(BaseModel):
    """ODPS v1.0.0 Input Contract (Dependency)"""
    id: str = Field(..., alias="contract_id", description="Contract ID or contractId")
    version: str = Field(..., alias="contract_version", description="Version of the input contract")

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


class Server(BaseModel):
    """Databricks extension - Connection details for output ports"""
    project: Optional[str] = Field(None, description="Project name (BigQuery)")
    dataset: Optional[str] = Field(None, description="Dataset name (BigQuery)")
    account: Optional[str] = Field(None, description="Account name (Snowflake)")
    database: Optional[str] = Field(None, description="Database name (Snowflake, Postgres)")
    schema_name: Optional[str] = Field(None, alias="schema", description="Schema name (Snowflake, Postgres)")
    host: Optional[str] = Field(None, description="Host name (Kafka)")
    topic: Optional[str] = Field(None, description="Topic name (Kafka)")
    location: Optional[str] = Field(None, description="Location URL (S3)")
    delimiter: Optional[str] = Field(None, description="Delimiter (S3)")
    format: Optional[str] = Field(None, description="Format of the data (S3)")
    table: Optional[str] = Field(None, description="Table name (Postgres)")
    view: Optional[str] = Field(None, description="View name (Postgres)")
    share: Optional[str] = Field(None, description="Share name (Databricks)")
    additionalProperties: Optional[str] = Field(None, description="Additional server properties")

    _parse_server_json = field_validator('*', mode='before')(parse_json_if_string)

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


class OutputPort(BaseModel):
    """ODPS v1.0.0 Output Port"""
    # Stable ID (exposed so entity relationships can reference this port)
    id: Optional[str] = Field(None, description="Stable port ID (preserved across updates)")

    # ODPS required fields
    name: str = Field(..., description="Name of the output port")
    version: str = Field(..., description="Version of the output port")

    # ODPS optional fields
    description: Optional[str] = Field(None, description="Description of the output port")
    type: Optional[str] = Field(None, alias="port_type", description="Type of output port")
    contractId: Optional[str] = Field(None, alias="contract_id", description="Contract ID for the output port")
    contractName: Optional[str] = Field(None, alias="contract_name", description="Contract name (resolved at query time)")
    sbom: Optional[List[SBOM]] = Field(None, description="Software Bill of Materials")
    inputContracts: Optional[List[InputContract]] = Field(None, alias="input_contracts", description="Input contract dependencies")
    tags: Optional[List[str]] = Field(None, description="Tags for categorization")
    customProperties: Optional[List[CustomProperty]] = Field(None, description="Custom properties")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None, description="Authoritative definitions")

    # Delivery method
    deliveryMethodId: Optional[str] = Field(None, alias="delivery_method_id", description="Delivery method reference")
    deliveryMethodName: Optional[str] = Field(None, description="Delivery method name (resolved at query time)")

    # Databricks extensions
    assetType: Optional[str] = Field(None, alias="asset_type", description="Type of Databricks asset")
    assetIdentifier: Optional[str] = Field(None, alias="asset_identifier", description="Unique identifier for the asset")
    status: Optional[str] = Field(None, description="Status of the output port")
    server: Optional[Server] = Field(None, description="Connection details")
    containsPii: bool = Field(False, alias="contains_pii", description="Contains PII flag")
    autoApprove: bool = Field(False, alias="auto_approve", description="Auto-approve flag")

    _parse_server_json = field_validator('server', mode='before')(parse_json_if_string)

    @field_validator('deliveryMethodId', mode='before')
    @classmethod
    def _coerce_delivery_method_id_to_str(cls, v):
        # The DB column `delivery_method_id` is PG `UUID(as_uuid=True)`, so
        # SQLAlchemy hands back `uuid.UUID` instances when this model is
        # loaded via `from_attributes=True`. Pydantic v2 refuses to coerce
        # `UUID(...)` against the declared `Optional[str]` type, returning
        # 500 on POST and 400 on PUT for `/api/data-products` whenever an
        # output port carries a delivery method.
        #
        # Coerce on input so the validator accepts UUID instances; the
        # Pydantic field TYPE intentionally stays `Optional[str]` — flipping
        # it to `Optional[UUID]` would change the wire format and break
        # clients that depend on a JSON string. See @field_serializer below
        # for defense in depth on the response side.
        import uuid as _uuid
        if isinstance(v, _uuid.UUID):
            return str(v)
        return v

    @field_serializer('deliveryMethodId')
    def _serialize_delivery_method_id(self, v):
        # Defense in depth: if a UUID somehow reaches the serializer (e.g.,
        # bypassing validation via `model_construct`), still emit a string.
        return str(v) if v is not None else None

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


# ============================================================================
# ODPS v1.0.0 Management Port (NEW)
# ============================================================================

class ManagementPort(BaseModel):
    """ODPS v1.0.0 Management Port - For observability, control, etc."""
    # ODPS required fields
    name: str = Field(..., description="Endpoint identifier or unique name")
    content: str = Field(..., description="Content type (discoverability, observability, control, dictionary)")

    # ODPS optional fields
    type: str = Field("rest", alias="port_type", description="Type (rest or topic)")
    url: Optional[str] = Field(None, description="URL to access the endpoint")
    channel: Optional[str] = Field(None, description="Channel to communicate with the data product")
    description: Optional[str] = Field(None, description="Purpose and usage")
    tags: Optional[List[str]] = Field(None, description="Tags")
    customProperties: Optional[List[CustomProperty]] = Field(None, description="Custom properties")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None, description="Authoritative definitions")

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


# ============================================================================
# ODPS v1.0.0 Support Channel
# ============================================================================

class Support(BaseModel):
    """ODPS v1.0.0 Support Channel"""
    # ODPS required fields
    channel: str = Field(..., description="Channel name or identifier")
    url: str = Field(..., description="Access URL")

    # ODPS optional fields
    description: Optional[str] = Field(None, description="Description of the channel")
    tool: Optional[str] = Field(None, description="Tool name (email, slack, teams, discord, ticket, other)")
    scope: Optional[str] = Field(None, description="Scope (interactive, announcements, issues)")
    invitationUrl: Optional[str] = Field(None, alias="invitation_url", description="Invitation URL")
    tags: Optional[List[str]] = Field(None, description="Tags")
    customProperties: Optional[List[CustomProperty]] = Field(None, description="Custom properties")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None, description="Authoritative definitions")

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


# ============================================================================
# ODPS v1.0.0 Team
# ============================================================================

class TeamMember(BaseModel):
    """ODPS v1.0.0 Team Member"""
    # ODPS required fields
    username: str = Field(..., description="User's username or email")

    # ODPS optional fields
    name: Optional[str] = Field(None, description="User's name")
    description: Optional[str] = Field(None, description="User's description")
    role: Optional[str] = Field(None, description="User's role (owner, data steward, etc.)")
    dateIn: Optional[date] = Field(None, alias="date_in", description="Date when user joined")
    dateOut: Optional[date] = Field(None, alias="date_out", description="Date when user left")
    replacedByUsername: Optional[str] = Field(None, alias="replaced_by_username", description="Replacement username")
    tags: Optional[List[str]] = Field(None, description="Tags")
    customProperties: Optional[List[CustomProperty]] = Field(None, description="Custom properties")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None, description="Authoritative definitions")

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


class Team(BaseModel):
    """ODPS v1.0.0 Team"""
    name: Optional[str] = Field(None, description="Team name")
    description: Optional[str] = Field(None, description="Team description")
    members: Optional[List[TeamMember]] = Field(None, description="List of team members")
    tags: Optional[List[str]] = Field(None, description="Tags")
    customProperties: Optional[List[CustomProperty]] = Field(None, description="Custom properties")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None, description="Authoritative definitions")

    model_config = {"from_attributes": True}


# ============================================================================
# ODPS v1.0.0 Data Product (Main Model)
# ============================================================================

class DataProduct(BaseModel):
    """ODPS v1.0.0 Data Product"""
    # ODPS v1.0.0 required fields
    apiVersion: str = Field("v1.0.0", alias="api_version", description="Version of the ODPS standard")
    kind: str = Field("DataProduct", description="Resource type")
    id: str = Field(..., description="Unique identifier")
    status: str = Field(..., description="Status (proposed, draft, active, deprecated, retired)")

    # ODPS v1.0.0 optional fields
    name: Optional[str] = Field(None, description="Name of the data product")
    version: Optional[str] = Field(None, description="Version of the data product")
    domain: Optional[str] = Field(None, description="Business domain")
    tenant: Optional[str] = Field(None, description="Organization identifier")
    owner_team_id: Optional[str] = Field(None, description="Owner team UUID")
    owner_team_name: Optional[str] = Field(None, description="Owner team name (resolved at query time)")
    project_id: Optional[str] = Field(None, description="Project association")
    project_name: Optional[str] = Field(None, description="Project name (resolved at query time)")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None, alias="authoritative_definitions", description="Authoritative definitions")
    description: Optional[Description] = Field(None, description="Structured description")
    customProperties: Optional[List[CustomProperty]] = Field(None, alias="custom_properties", description="Custom properties")
    tags: Optional[List[Union[AssignedTag, AssignedTagCreate]]] = Field(default_factory=list, description="List of assigned tags (full metadata or IDs for creation)")
    inputPorts: Optional[List[InputPort]] = Field(None, alias="input_ports", description="Input ports")
    outputPorts: Optional[List[OutputPort]] = Field(None, alias="output_ports", description="Output ports")
    managementPorts: Optional[List[ManagementPort]] = Field(None, alias="management_ports", description="Management ports")
    support: Optional[List[Support]] = Field(None, alias="support_channels", description="Support channels")
    team: Optional[Team] = Field(None, description="Team information")
    productCreatedTs: Optional[datetime] = Field(None, alias="product_created_ts", description="Product creation timestamp")

    # Metadata inheritance
    max_level_inheritance: int = Field(99, ge=0, le=999, description="Maximum metadata level to inherit from contracts")

    # Typed list of principals representing the expected consumers of this
    # product. Default ``type="group"`` covers the common case; the shape is
    # extensible to service principals, roles, scopes, etc. Surfaced in the
    # publish form and exposed to webhook bodies via
    # ``${entity.consumer_principals}``.
    consumer_principals: Optional[List[ConsumerPrincipal]] = Field(default_factory=list, description="Typed principals (groups by default) representing expected consumers")

    # Audit fields (not in ODPS, but useful)
    created_at: Optional[datetime] = Field(None, description="Record creation timestamp")
    updated_at: Optional[datetime] = Field(None, description="Record update timestamp")

    # Versioning fields
    draft_owner_id: Optional[str] = Field(None, alias="draftOwnerId", description="Personal draft owner - if set, visible only to owner")
    parent_product_id: Optional[str] = Field(None, alias="parentProductId", description="Parent version ID for version lineage")
    # Canonical family grouping key (PRD #442). One indexed equality lookup
    # returns every version of the family. Defaults to self.id on initial
    # create; carried forward unchanged on every clone.
    version_family_id: Optional[str] = Field(None, alias="versionFamilyId", description="Canonical family grouping key shared across every version of the family")
    base_name: Optional[str] = Field(None, alias="baseName", description="Legacy base name; superseded by versionFamilyId. Kept for back-compat.")
    change_summary: Optional[str] = Field(None, alias="changeSummary", description="Summary of changes in this version")
    # Count of versions in this row's family that are visible to the caller.
    # Only populated by the collapsed list view; None on detail responses
    # and on the expanded list view. See PRD #442.
    version_count: Optional[int] = Field(None, alias="versionCount", description="Number of visible versions in this family (collapsed list view only)")

    # Publication fields
    publication_scope: Optional[str] = Field("none", description="Publication scope: none, domain, organization, external")
    published_at: Optional[datetime] = Field(None, description="When published")
    published_by: Optional[str] = Field(None, description="Who published")

    # Certification fields
    certification_level: Optional[int] = Field(None, description="Ordinal of assigned certification level")
    inherited_certification_level: Optional[int] = Field(None, description="Inherited certification level via relationships")
    certified_at: Optional[datetime] = Field(None, description="When certification was granted")
    certified_by: Optional[str] = Field(None, description="Who granted certification")
    certification_expires_at: Optional[datetime] = Field(None, description="When certification expires")
    certification_notes: Optional[str] = Field(None, description="Certification notes")

    # consumer_principals is stored as JSON-encoded TEXT in DB. Decode to a
    # list of dicts at read time so Pydantic can build ConsumerPrincipal
    # entries. Accepts:
    #   * already-decoded list of ConsumerPrincipal (passthrough)
    #   * list of dicts {type, value}
    #   * legacy list of strings (any local dev DB written before the
    #     rename) — coerced to {type: "group", value: <str>}
    #   * raw JSON string from a TEXT column (any of the above shapes)
    @field_validator('consumer_principals', mode='before')
    def parse_consumer_principals(cls, value):
        if value is None or value == '':
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return []
        if not isinstance(value, list):
            return []
        # Coerce legacy strings to {type: "group", value: s}
        coerced: List[Any] = []
        for item in value:
            if isinstance(item, str):
                coerced.append({"type": "group", "value": item})
            else:
                coerced.append(item)
        return coerced

    # Field validators to parse JSON strings from database
    @field_validator('tags', mode='before')
    def parse_tags(cls, value):
        if value is None:
            return []
        # If it's already a list of AssignedTag objects, return as-is
        if isinstance(value, list) and value and hasattr(value[0], 'tag_id'):
            return value
        # Handle list of strings (tag FQNs or simple names) - pass directly to AssignedTagCreate
        # AssignedTagCreate's model_validator handles string -> {'tag_fqn': string} conversion
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value
        # Legacy support for JSON strings (should not be used anymore)
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list):
                    # Handle if parsed is a list of strings - pass directly
                    if parsed and isinstance(parsed[0], str):
                        return parsed
                    return parsed
            except (json.JSONDecodeError, ValueError):
                pass
            return []
        return value or []

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


# ============================================================================
# Request/Response Models
# ============================================================================

class GenieSpaceRequest(BaseModel):
    """Request model for initiating Genie Space creation."""
    product_ids: List[str] = Field(..., description="List of Data Product IDs to include in the Genie Space")


class NewVersionRequest(BaseModel):
    """Request model for creating a new version of a Data Product."""
    new_version: str = Field(..., description="The new version string (e.g., 1.1.0, 2.0.0)")


# ============================================================================
# Create/Update Models
# ============================================================================

class DataProductCreate(BaseModel):
    """Create model for Data Products"""
    # ODPS v1.0.0 required
    apiVersion: str = Field("v1.0.0", description="ODPS version")
    kind: str = Field("DataProduct", description="Resource type")
    id: str = Field(..., description="Unique identifier")
    status: str = Field("draft", description="Initial status")

    # ODPS optional
    name: Optional[str] = Field(None, description="Product name")
    version: Optional[str] = Field(None, description="Product version")
    domain: Optional[str] = Field(None, description="Domain")
    tenant: Optional[str] = Field(None, description="Tenant")
    owner_team_id: Optional[str] = Field(None, description="Owner team UUID")
    project_id: Optional[str] = Field(None, description="Project association")
    description: Optional[Description] = Field(None, description="Description")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None, description="Authoritative definitions")
    customProperties: Optional[List[CustomProperty]] = Field(None, description="Custom properties")
    tags: Optional[List[Union[AssignedTag, AssignedTagCreate]]] = Field(None, description="Tags (IDs or full objects)")
    inputPorts: Optional[List[InputPort]] = Field(None, alias="input_ports", description="Input ports")
    outputPorts: Optional[List[OutputPort]] = Field(None, alias="output_ports", description="Output ports")
    managementPorts: Optional[List[ManagementPort]] = Field(None, alias="management_ports", description="Management ports")
    support: Optional[List[Support]] = Field(None, alias="support_channels", description="Support channels")
    team: Optional[Team] = Field(None, description="Team")

    # Versioning
    parent_product_id: Optional[str] = Field(None, alias="parentProductId", description="Parent version ID for version lineage")
    # Optional on create — repo defaults to self.id if omitted. Managers
    # explicitly pass source.version_family_id when cloning new versions.
    version_family_id: Optional[str] = Field(None, alias="versionFamilyId", description="Canonical family grouping key; defaults to self.id on initial create")
    # The following three columns exist on DataProductDb but were missing
    # from the create schema, so Pydantic v2 silently stripped them from
    # incoming POSTs (model_config does not set extra="allow"). The
    # repository's getattr() fallback then returned None on every
    # create. Declaring them here makes the create round-trip honor
    # the input. No DB migration needed — columns already exist.
    draft_owner_id: Optional[str] = Field(None, description="Creator / single-user owner email for personal drafts and non-team-owned products")
    base_name: Optional[str] = Field(None, description="Stable base name shared across versions of the same product family")
    change_summary: Optional[str] = Field(None, description="Free-text summary of changes in this version")

    # Metadata inheritance
    max_level_inheritance: int = Field(99, ge=0, le=999, description="Maximum metadata level to inherit from contracts")

    # Typed consumer principals (default type="group")
    consumer_principals: Optional[List[ConsumerPrincipal]] = Field(default_factory=list, description="Typed principals (groups by default) representing expected consumers")

    # Field validator to handle string IDs from frontend
    @field_validator('tags', mode='before')
    def parse_tags(cls, value):
        if value is None:
            return None
        # If it's already a list of tag objects, return as-is
        if isinstance(value, list) and value and (hasattr(value[0], 'tag_id') or isinstance(value[0], dict)):
            return value
        # Handle list of strings (tag FQNs or simple names) - pass directly to AssignedTagCreate
        # AssignedTagCreate's model_validator handles string -> {'tag_fqn': string} conversion
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value
        return value

    @field_validator('consumer_principals', mode='before')
    def parse_consumer_principals(cls, value):
        if value is None or value == '':
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return []
        if not isinstance(value, list):
            return []
        coerced: List[Any] = []
        for item in value:
            if isinstance(item, str):
                coerced.append({"type": "group", "value": item})
            else:
                coerced.append(item)
        return coerced

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


class DataProductUpdate(BaseModel):
    """Update model for Data Products"""
    name: Optional[str] = None
    version: Optional[str] = None
    status: Optional[str] = None
    domain: Optional[str] = None
    tenant: Optional[str] = None
    owner_team_id: Optional[str] = None
    project_id: Optional[str] = None
    description: Optional[Description] = None
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = None
    customProperties: Optional[List[CustomProperty]] = None
    tags: Optional[List[Union[AssignedTag, AssignedTagCreate]]] = None
    inputPorts: Optional[List[InputPort]] = Field(None, alias="input_ports")
    outputPorts: Optional[List[OutputPort]] = Field(None, alias="output_ports")
    managementPorts: Optional[List[ManagementPort]] = Field(None, alias="management_ports")
    support: Optional[List[Support]] = Field(None, alias="support_channels")
    team: Optional[Team] = None
    max_level_inheritance: Optional[int] = Field(None, ge=0, le=999)
    # Mirror of DataProductCreate — these columns exist on DataProductDb
    # but were missing from the update schema, so PUTs that included them
    # were silently stripped. No DB migration needed.
    draft_owner_id: Optional[str] = Field(None, description="Creator / single-user owner email; clearing this promotes a personal draft")
    base_name: Optional[str] = Field(None, description="Stable base name shared across versions of the same product family")
    change_summary: Optional[str] = Field(None, description="Free-text summary of changes in this version")
    # Typed consumer principals (default type="group")
    consumer_principals: Optional[List[ConsumerPrincipal]] = Field(None, description="Typed principals (groups by default) representing expected consumers")

    # Field validator to handle string IDs from frontend
    @field_validator('tags', mode='before')
    def parse_tags(cls, value):
        if value is None:
            return None
        # If it's already a list of tag objects, return as-is
        if isinstance(value, list) and value and (hasattr(value[0], 'tag_id') or isinstance(value[0], dict)):
            return value
        # Handle list of strings (tag FQNs or simple names) - pass directly to AssignedTagCreate
        # AssignedTagCreate's model_validator handles string -> {'tag_fqn': string} conversion
        if isinstance(value, list) and value and isinstance(value[0], str):
            return value
        return value

    @field_validator('consumer_principals', mode='before')
    def parse_consumer_principals(cls, value):
        if value is None:
            return None
        if value == '':
            return []
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                return []
        if not isinstance(value, list):
            return []
        coerced: List[Any] = []
        for item in value:
            if isinstance(item, str):
                coerced.append({"type": "group", "value": item})
            else:
                coerced.append(item)
        return coerced

    model_config = {
        "from_attributes": True,
        "populate_by_name": True
    }


# ============================================================================
# Subscription Models
# ============================================================================

class OnBehalfOf(BaseModel):
    """Subscribe-on-behalf-of payload ().

    Allows a user to request a subscription on behalf of a Databricks group
    or service principal. ``type=user`` accepts any string (covers new hires
    not yet indexed in SCIM); ``type=group`` and ``type=service_principal``
    are validated against the workspace SCIM directory before persisting.
    """
    type: str = Field(..., description="Principal type: 'user', 'group', or 'service_principal'")
    value: str = Field(..., description="Principal identifier (email for user, displayName for group, applicationId or displayName for SP)")


class SubscriptionCreate(BaseModel):
    """Request model for creating a subscription."""
    reason: Optional[str] = Field(None, description="Optional reason for subscribing")
    on_behalf_of: Optional[OnBehalfOf] = Field(
        None,
        description="Optional: subscribe on behalf of a group or service principal (validated against workspace SCIM)",
    )


class Subscription(BaseModel):
    """Subscription model representing a user's subscription to a data product."""
    id: str = Field(..., description="Unique subscription ID")
    product_id: str = Field(..., description="ID of the subscribed product")
    subscriber_email: str = Field(..., description="Email of the subscriber")
    subscribed_at: datetime = Field(..., description="When the subscription was created")
    subscription_reason: Optional[str] = Field(None, description="Optional reason for subscribing")
    # subscribe-on-behalf-of (approval workflow OBO)
    on_behalf_of_type: Optional[str] = Field(None, description="Principal type when subscribed on behalf of another principal")
    on_behalf_of_value: Optional[str] = Field(None, description="Principal identifier when subscribed on behalf of another principal")

    model_config = {"from_attributes": True}


class SubscriptionResponse(BaseModel):
    """Response model for subscription operations."""
    subscribed: bool = Field(..., description="Whether the user is currently subscribed")
    subscription: Optional[Subscription] = Field(None, description="Subscription details if subscribed")


class SubscriberInfo(BaseModel):
    """Information about a subscriber (for listing subscribers)."""
    email: str = Field(..., description="Subscriber's email address")
    subscribed_at: datetime = Field(..., description="When they subscribed")
    reason: Optional[str] = Field(None, description="Their subscription reason")

    model_config = {"from_attributes": True}


class SubscribersListResponse(BaseModel):
    """Response model for listing subscribers."""
    product_id: str = Field(..., description="Product ID")
    subscriber_count: int = Field(..., description="Total number of subscribers")
    subscribers: List[SubscriberInfo] = Field(default_factory=list, description="List of subscribers")


# ============================================================================
# Status Change Request/Response Models
# ============================================================================

class ChangeStatusPayload(BaseModel):
    """Payload for direct status change (admin/owner)."""
    new_status: str = Field(..., description="Target status")


class RequestStatusChangePayload(BaseModel):
    """Payload for requesting a status change (approval workflow)."""
    target_status: str = Field(..., description="Requested target status")
    justification: str = Field(..., description="Justification for the status change")
    current_status: Optional[str] = Field(None, description="Current status (for reference)")


class HandleStatusChangePayload(BaseModel):
    """Payload for handling a status change request (approve/deny)."""
    decision: str = Field(..., description="Decision: 'approve', 'deny', or 'clarify'")
    target_status: str = Field(..., description="The target status that was requested")
    requester_email: str = Field(..., description="Email of the original requester")
    message: Optional[str] = Field(None, description="Optional message from approver")


class CommitDraftRequest(BaseModel):
    """Request to commit a personal draft to team visibility."""
    new_version: str = Field(..., description="Version number for the committed product")
    change_summary: str = Field(..., description="Summary of changes made")


class CommitDraftResponse(BaseModel):
    """Response from committing a personal draft."""
    id: str = Field(..., description="Product ID")
    name: Optional[str] = Field(None, description="Product name")
    version: Optional[str] = Field(None, description="New version")
    status: str = Field(..., description="Product status")
    draft_owner_id: Optional[str] = Field(None, alias="draftOwnerId", description="Draft owner (null after commit)")

    model_config = {"from_attributes": True, "populate_by_name": True}


class DiffFromParentResponse(BaseModel):
    """Response containing diff analysis from parent version."""
    parent_version: str = Field(..., description="Parent version string")
    suggested_bump: str = Field(..., description="Suggested semver bump: major, minor, or patch")
    suggested_version: str = Field(..., description="Suggested new version string")
    analysis: Dict[str, Any] = Field(..., description="Detailed diff analysis")
