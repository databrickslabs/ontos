from datetime import datetime
from typing import Optional, List, Dict, Any, Union, TYPE_CHECKING

from pydantic import BaseModel, Field

from .tags import AssignedTag, AssignedTagCreate

if TYPE_CHECKING:
    pass  # Used to avoid circular imports if needed


# ODCS v3.1.0 relationship model (schema-level and property-level)
class SchemaRelationship(BaseModel):
    """ODCS v3.1.0 relationship (foreign key) at schema or property level."""
    id: Optional[str] = None  # internal DB id (populated on read)
    type: str = "foreignKey"
    # from is a reserved word in Python; use Field alias
    from_value: Optional[Union[str, List[str]]] = Field(None, alias='from')
    to: Union[str, List[str]] = ""
    customProperties: Optional[List[Dict[str, Any]]] = None

    class Config:
        populate_by_name = True


# ODCS-compliant schema models
class ColumnProperty(BaseModel):
    name: str
    logicalType: str = Field(alias='logical_type')
    stableId: Optional[str] = None  # ODCS v3.1.0 StableId
    required: Optional[bool] = False
    unique: Optional[bool] = False
    primaryKey: Optional[bool] = Field(False, alias='primary_key')
    primaryKeyPosition: Optional[int] = Field(-1, alias='primary_key_position')
    partitioned: Optional[bool] = False
    partitionKeyPosition: Optional[int] = Field(-1, alias='partition_key_position')
    description: Optional[str] = None
    physicalType: Optional[str] = Field(None, alias='physical_type')
    classification: Optional[str] = None
    logicalTypeOptions: Optional[Dict[str, Any]] = Field(None, alias='logical_type_options')

    # String constraints
    minLength: Optional[int] = None
    maxLength: Optional[int] = None
    pattern: Optional[str] = None

    # Number/Integer constraints
    minimum: Optional[Union[int, float]] = None
    maximum: Optional[Union[int, float]] = None
    multipleOf: Optional[Union[int, float]] = None
    precision: Optional[int] = None

    # Date constraints
    format: Optional[str] = None
    timezone: Optional[str] = None
    customFormat: Optional[str] = None

    # Array constraints
    itemType: Optional[str] = None
    minItems: Optional[int] = None
    maxItems: Optional[int] = None

    # Semantic concepts for business glossary integration
    semanticConcepts: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    authoritativeDefinitions: Optional[List[Dict[str, Any]]] = Field(default_factory=list)

    # ODCS additional property fields
    businessName: Optional[str] = None
    encryptedName: Optional[str] = None
    criticalDataElement: Optional[bool] = None
    transformLogic: Optional[str] = None
    # ODCS v3.1.0 defines transformSourceObjects as an array of strings; accept a
    # plain string for backward compatibility with earlier Ontos uploads.
    transformSourceObjects: Optional[Union[List[str], str]] = None
    transformDescription: Optional[str] = None

    # ODCS v3.1.0 relationships (property-level FKs)
    relationships: Optional[List[SchemaRelationship]] = None

    class Config:
        # Accept both JSON keys: "logicalType" (field name) and "logical_type" (alias)
        populate_by_name = True
        extra = "allow"  # Allow extra fields from wizard that we don't explicitly define


class SchemaObject(BaseModel):
    name: str
    stableId: Optional[str] = None  # ODCS v3.1.0 StableId
    physicalName: Optional[str] = None
    properties: List[ColumnProperty] = Field(default_factory=list)
    propertyCount: Optional[int] = Field(0, description="Total number of properties (columns) in this schema object")

    # ODCS additional schema object fields
    businessName: Optional[str] = None
    physicalType: Optional[str] = None  # table, view, etc.
    description: Optional[str] = None
    dataGranularityDescription: Optional[str] = None
    tags: Optional[List[AssignedTagCreate]] = Field(default_factory=list)
    authoritativeDefinitions: Optional[List['AuthoritativeDefinition']] = Field(default_factory=list)
    customProperties: Optional[List[Dict[str, Any]]] = Field(default_factory=list)
    quality: Optional[List['QualityRule']] = Field(default_factory=list)  # ODCS quality rules are schema-nested

    # ODCS v3.1.0 relationships (schema-level FKs)
    relationships: Optional[List[SchemaRelationship]] = None

    class Config:
        populate_by_name = True
        by_alias = False  # Use field names (physicalName) not aliases (physical_name) for serialization
        extra = "allow"  # Allow extra fields from wizard


class ContractDescription(BaseModel):
    usage: Optional[str] = None
    purpose: Optional[str] = None
    limitations: Optional[str] = None


class QualityRule(BaseModel):
    # Core fields
    name: Optional[str] = None
    description: Optional[str] = None
    level: Optional[str] = None  # 'object' or 'property'
    enabled: bool = True

    # ODCS quality framework fields
    dimension: Optional[str] = None  # accuracy, completeness, conformity, consistency, coverage, timeliness, uniqueness
    business_impact: Optional[str] = None  # operational, regulatory
    severity: Optional[str] = None  # info, warning, error

    # Type and engine configuration
    type: str = "library"  # text, library, sql, custom
    method: Optional[str] = None
    schedule: Optional[str] = None
    scheduler: Optional[str] = None
    unit: Optional[str] = None
    tags: Optional[str] = None

    # Type-specific fields
    rule: Optional[str] = None  # for library type
    query: Optional[str] = None  # for sql type
    engine: Optional[str] = None  # for custom type
    implementation: Optional[str] = None  # for custom type (JSON string)

    # Comparators for all types
    must_be: Optional[str] = None
    must_not_be: Optional[str] = None
    must_be_gt: Optional[str] = None
    must_be_ge: Optional[str] = None
    must_be_lt: Optional[str] = None
    must_be_le: Optional[str] = None
    must_be_between_min: Optional[str] = None
    must_be_between_max: Optional[str] = None

    # Legacy support
    threshold: Optional[float] = None


class TeamMember(BaseModel):
    """ODCS Team Member"""
    # Core ODCS fields
    username: str  # Required by ODCS - maps to email/identifier
    role: str  # 'steward', 'consumer', 'expert', 'admin', etc.
    name: Optional[str] = None
    description: Optional[str] = None
    dateIn: Optional[str] = None  # ISO date format
    dateOut: Optional[str] = None  # ISO date format
    replacedByUsername: Optional[str] = None
    
    # Legacy/convenience field (will be aliased to username for backward compatibility)
    email: Optional[str] = None
    
    class Config:
        populate_by_name = True
        
    def __init__(self, **data):
        # If email is provided but not username, copy email to username
        if 'email' in data and 'username' not in data:
            data['username'] = data['email']
        # If username is provided but not email, copy username to email (for backward compatibility)
        elif 'username' in data and 'email' not in data:
            data['email'] = data['username']
        super().__init__(**data)


class AccessControl(BaseModel):
    read_groups: List[str] = Field(default_factory=list, alias='readGroups')
    write_groups: List[str] = Field(default_factory=list, alias='writeGroups') 
    admin_groups: List[str] = Field(default_factory=list, alias='adminGroups')
    classification: Optional[str] = 'internal'
    contains_pii: bool = Field(False, alias='containsPii')
    requires_encryption: bool = Field(False, alias='requiresEncryption')


class SupportChannel(BaseModel):
    """ODCS Support Channel"""
    channel: str
    url: str
    description: Optional[str] = None
    tool: Optional[str] = None  # slack, email, etc.
    scope: Optional[str] = None
    invitationUrl: Optional[str] = None

    class Config:
        populate_by_name = True


class SupportChannels(BaseModel):
    """Legacy support structure - kept for backward compatibility"""
    email: Optional[str] = None
    slack: Optional[str] = None
    documentation: Optional[str] = None


class PricingInfo(BaseModel):
    """ODCS Pricing Information"""
    priceAmount: Optional[Union[int, float]] = None
    priceCurrency: Optional[str] = None  # USD, EUR, etc.
    priceUnit: Optional[str] = None  # megabyte, record, etc.

    class Config:
        populate_by_name = True


class ContractRole(BaseModel):
    """ODCS Role Definition"""
    role: str
    description: Optional[str] = None
    access: Optional[str] = None  # read, write, etc.
    firstLevelApprovers: Optional[str] = None
    secondLevelApprovers: Optional[str] = None
    customProperties: Optional[Dict[str, Any]] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


class AuthoritativeDefinition(BaseModel):
    url: str
    type: str  # businessDefinition, transformationImplementation, videoTutorial, tutorial, implementation


class SLAProperty(BaseModel):
    """ODCS SLA Property"""
    property: str
    value: Union[str, int, float]
    valueExt: Optional[Union[str, int, float]] = None
    unit: Optional[str] = None
    element: Optional[str] = None
    driver: Optional[str] = None  # regulatory, analytics, operational

    class Config:
        populate_by_name = True


class SLARequirements(BaseModel):
    """Legacy SLA structure - kept for backward compatibility"""
    uptime_target: Optional[float] = Field(None, alias='uptimeTarget')  # percentage
    max_downtime_minutes: Optional[int] = Field(None, alias='maxDowntimeMinutes')
    query_response_time_ms: Optional[int] = Field(None, alias='queryResponseTimeMs')
    data_freshness_minutes: Optional[int] = Field(None, alias='dataFreshnessMinutes')


# ODCS Server Types
ODCS_SERVER_TYPES = [
    "api", "athena", "azure", "bigquery", "clickhouse", "databricks", "denodo", "dremio",
    "duckdb", "glue", "cloudsql", "db2", "informix", "kafka", "kinesis", "local",
    "mysql", "oracle", "postgresql", "postgres", "presto", "pubsub",
    "redshift", "s3", "sftp", "snowflake", "sqlserver", "synapse", "trino", "vertica", "custom"
]

class ServerConfig(BaseModel):
    server: Optional[str] = None  # identifier
    type: str  # ODCS server type
    description: Optional[str] = None
    environment: Optional[str] = None  # prod, dev, staging, test

    # Common server properties (stored as key-value pairs)
    host: Optional[str] = None
    port: Optional[int] = None
    database: Optional[str] = None
    database_schema: Optional[str] = Field(None, alias="schema")
    catalog: Optional[str] = None
    project: Optional[str] = None
    account: Optional[str] = None
    region: Optional[str] = None
    location: Optional[str] = None

    # Additional properties for specific server types
    properties: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


# Full ODCS Contract Structure
class ODCSContract(BaseModel):
    """ODCS v3.1.0 compliant contract structure"""
    kind: str = 'DataContract'  # Required by ODCS
    apiVersion: str = Field('v3.1.0', alias='api_version')  # Required by ODCS
    id: str  # Required by ODCS
    version: str  # Required by ODCS
    status: str  # Required by ODCS

    # Metadata section
    name: str  # Required for app usability
    tenant: Optional[str] = None
    domain: Optional[str] = None
    dataProduct: Optional[str] = Field(None, alias='data_product')
    owner_team_id: Optional[str] = None  # No alias - always serializes as owner_team_id
    description: Optional[ContractDescription] = None

    # ODCS top-level fields
    tags: Optional[List[AssignedTag]] = Field(default_factory=list)
    contractCreatedTs: Optional[str] = None  # ISO datetime string

    # Schema section
    contract_schema: List[SchemaObject] = Field(default_factory=list, alias="schema")

    # SLA section (ODCS structure)
    slaDefaultElement: Optional[str] = None
    slaProperties: Optional[List[SLAProperty]] = Field(default_factory=list)
    sla: Optional[SLARequirements] = None  # Legacy structure

    # Pricing section
    price: Optional[PricingInfo] = None

    # Team and Roles section
    team: List[TeamMember] = Field(default_factory=list)
    roles: Optional[List[ContractRole]] = Field(default_factory=list)  # ODCS roles
    access_control: Optional[AccessControl] = Field(None, alias='accessControl')  # Legacy

    # Support section (ODCS structure)
    support: Union[List[SupportChannel], SupportChannels, None] = None

    # Infrastructure section
    servers: List[ServerConfig] = Field(default_factory=list)

    # Authoritative definitions
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(default_factory=list)

    # Custom properties
    customProperties: Optional[Dict[str, Any]] = Field(default_factory=dict)

    class Config:
        populate_by_name = True


class DataContractBase(BaseModel):
    name: str  # Required for app usability
    version: str = Field('1.0.0')
    status: str = Field('draft')
    owner_team_id: Optional[str] = None  # No alias - always serializes as owner_team_id
    project_id: Optional[str] = None  # Project association
    kind: str = Field('DataContract')  # Required by ODCS
    apiVersion: str = Field('v3.1.0', alias='api_version')  # Required by ODCS
    domainId: Optional[str] = Field(None, alias='domain_id')
    tenant: Optional[str] = None
    dataProduct: Optional[str] = Field(None, alias='data_product')
    descriptionUsage: Optional[str] = Field(None, alias='description_usage')
    descriptionPurpose: Optional[str] = Field(None, alias='description_purpose')
    descriptionLimitations: Optional[str] = Field(None, alias='description_limitations')


class DataContractCreate(DataContractBase):
    # Additional ODCS fields for wizard
    domain: Optional[str] = None
    domainId: Optional[str] = None  # Domain ID for direct domain assignment
    tenant: Optional[str] = None
    dataProduct: Optional[str] = Field(None, alias='data_product')
    description: Optional[ContractDescription] = None
    contract_schema: Optional[List[SchemaObject]] = Field(None, alias="schema")

    # ODCS top-level fields
    tags: Optional[List[AssignedTagCreate]] = Field(default_factory=list)
    contractCreatedTs: Optional[str] = None

    # SLA section (ODCS structure)
    slaDefaultElement: Optional[str] = None
    slaProperties: Optional[List[SLAProperty]] = Field(default_factory=list)
    sla: Optional[SLARequirements] = None  # Legacy structure

    # Pricing section
    price: Optional[PricingInfo] = None

    # Team and Roles section
    team: Optional[List[TeamMember]] = Field(None)
    roles: Optional[List[ContractRole]] = Field(default_factory=list)
    access_control: Optional[AccessControl] = Field(None, alias='accessControl')  # Legacy

    # Support section (ODCS structure)
    support: Union[List[SupportChannel], SupportChannels, None] = None

    # Infrastructure section
    servers: List[ServerConfig] = Field(default_factory=list)

    # Authoritative definitions
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(default_factory=list)

    # Custom properties
    customProperties: Optional[Dict[str, Any]] = Field(default_factory=dict)

    # Legacy fields (kept for backward compatibility)
    quality_rules: Optional[List[QualityRule]] = Field(None, alias='qualityRules')
    
    def to_odcs_contract(self) -> ODCSContract:
        """Convert to full ODCS contract structure"""
        return ODCSContract(
            name=self.name,
            version=self.version,
            status=self.status,
            owner_team_id=self.owner_team_id,
            domain=self.domain,
            tenant=self.tenant,
            dataProduct=self.dataProduct,
            description=self.description,
            contract_schema=self.contract_schema or [],
        )


class DataContractUpdate(BaseModel):
    name: Optional[str] = None
    version: Optional[str] = None
    status: Optional[str] = None
    owner_team_id: Optional[str] = None  # No alias - always serializes as owner_team_id
    project_id: Optional[str] = None  # Project association
    kind: Optional[str] = None
    apiVersion: Optional[str] = Field(None, alias='api_version')
    domainId: Optional[str] = Field(None, alias='domain_id')
    tenant: Optional[str] = None
    dataProduct: Optional[str] = Field(None, alias='data_product')
    description: Optional[ContractDescription] = None  # Nested description object (flattened in manager)
    descriptionUsage: Optional[str] = Field(None, alias='description_usage')
    descriptionPurpose: Optional[str] = Field(None, alias='description_purpose')
    descriptionLimitations: Optional[str] = Field(None, alias='description_limitations')
    tags: Optional[List[AssignedTagCreate]] = Field(None)  # Tags to assign to the contract
    # Add schema and semantic links support for updates from wizard
    contract_schema: Optional[List[SchemaObject]] = Field(None, alias="schema")
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(None)
    qualityRules: Optional[List[QualityRule]] = Field(None)
    serverConfigs: Optional[List[ServerConfig]] = Field(None)
    sla: Optional[SLARequirements] = None
    team: Optional[List[TeamMember]] = None  # ODCS team members
    customProperties: Optional[Dict[str, Any]] = None  # Custom properties for team assignment metadata

    # Semantic versioning fields
    parent_contract_id: Optional[str] = Field(None, alias='parentContractId')
    # Canonical family grouping key. Defaults to self.id on initial create;
    # carried forward unchanged on every clone. Optional here so the
    # initial-create path can omit it (repo will default it).
    version_family_id: Optional[str] = Field(None, alias='versionFamilyId')
    base_name: Optional[str] = Field(None, alias='baseName')
    change_summary: Optional[str] = Field(None, alias='changeSummary')

    class Config:
        populate_by_name = True


class DataContractRead(BaseModel):
    id: str  # Required by ODCS
    name: str  # Required for app usability
    version: str  # Required by ODCS
    status: str  # Required by ODCS
    owner_team_id: Optional[str] = None  # No alias - always serializes as owner_team_id
    owner_team_name: Optional[str] = None  # Resolved at query time
    project_id: Optional[str] = None  # Project association
    project_name: Optional[str] = None  # Resolved at query time
    kind: str = Field('DataContract')  # Required by ODCS
    # Ensure JSON uses camelCase key 'apiVersion' so frontend reads it
    apiVersion: str = Field('v3.1.0', alias='apiVersion')  # Required by ODCS
    tenant: Optional[str] = None
    domain: Optional[str] = None
    domainId: Optional[str] = None
    dataProduct: Optional[str] = Field(None, alias='data_product')
    description: Optional[ContractDescription] = None

    # ODCS top-level fields
    tags: Optional[List[AssignedTag]] = Field(default_factory=list)  # Read model returns AssignedTag, not AssignedTagCreate
    contractCreatedTs: Optional[str] = None

    # Schema section
    contract_schema: List[SchemaObject] = Field(default_factory=list, alias="schema")

    # SLA section (ODCS structure)
    slaDefaultElement: Optional[str] = None
    slaProperties: Optional[List[SLAProperty]] = Field(default_factory=list)
    sla: Optional[SLARequirements] = None  # Legacy structure

    # Pricing section
    price: Optional[PricingInfo] = None

    # Team and Roles section
    team: List[TeamMember] = Field(default_factory=list)
    roles: Optional[List[ContractRole]] = Field(default_factory=list)
    access_control: Optional[AccessControl] = Field(None, alias='accessControl')  # Legacy

    # Support section (ODCS structure)
    support: Union[List[SupportChannel], SupportChannels, None] = None

    # Infrastructure section
    servers: List[ServerConfig] = Field(default_factory=list)

    # Authoritative definitions
    authoritativeDefinitions: Optional[List[AuthoritativeDefinition]] = Field(default_factory=list)

    # Custom properties
    customProperties: Optional[Dict[str, Any]] = Field(default_factory=dict)

    # Legacy fields (kept for backward compatibility)
    quality_rules: List[QualityRule] = Field(default_factory=list, alias='qualityRules')

    # Timestamps
    created: Optional[str] = None
    updated: Optional[str] = None

    # Semantic versioning fields
    parentContractId: Optional[str] = Field(None, alias='parent_contract_id')
    versionFamilyId: Optional[str] = Field(None, alias='version_family_id')
    baseName: Optional[str] = Field(None, alias='base_name')
    changeSummary: Optional[str] = Field(None, alias='change_summary')

    # Personal draft visibility (three-tier model)
    # Tier 1: draft_owner_id set = personal draft, only owner can see
    # Tier 2: draft_owner null, publication_scope none = team/project visible
    # Tier 3: publication_scope not none = marketplace visible to all
    draftOwnerId: Optional[str] = Field(None, alias='draft_owner_id')

    # Publication (canonical; replaces legacy boolean `published` column)
    publication_scope: str = "none"
    published_at: Optional[str] = None
    published_by: Optional[str] = None

    class Config:
        populate_by_name = True
        # Allow validating directly from ORM rows. Pre-existing endpoints
        # (e.g. POST /data-contracts/{id}/clone) call
        # ``DataContractRead.model_validate(db_row)`` and were returning 400
        # under Pydantic v2 because this flag was missing.
        from_attributes = True


class DataContractSummary(BaseModel):
    """Lightweight contract model for list endpoints -- no schema, quality, or comments."""
    id: str
    name: str
    version: str
    status: str
    owner_team_id: Optional[str] = None
    owner_team_name: Optional[str] = None
    project_id: Optional[str] = None
    project_name: Optional[str] = None
    kind: str = Field('DataContract')
    apiVersion: str = Field('v3.1.0', alias='apiVersion')
    tenant: Optional[str] = None
    domain: Optional[str] = None
    domainId: Optional[str] = None
    dataProduct: Optional[str] = Field(None, alias='data_product')
    description: Optional[ContractDescription] = None
    tags: Optional[List[AssignedTag]] = Field(default_factory=list)
    created: Optional[str] = None
    updated: Optional[str] = None
    parentContractId: Optional[str] = Field(None, alias='parent_contract_id')
    versionFamilyId: Optional[str] = Field(None, alias='version_family_id')
    baseName: Optional[str] = Field(None, alias='base_name')
    changeSummary: Optional[str] = Field(None, alias='change_summary')
    draftOwnerId: Optional[str] = Field(None, alias='draft_owner_id')
    schema_object_count: int = Field(0, alias='schemaObjectCount')
    publication_scope: str = "none"
    published_at: Optional[str] = None
    published_by: Optional[str] = None

    class Config:
        populate_by_name = True


class DataContractCommentCreate(BaseModel):
    message: str


class DataContractCommentRead(BaseModel):
    id: str
    author: str
    message: str
    created_at: Optional[str] = None


# ===== Data Contract Tag Models (ODCS Top-Level Tags) =====
class ContractTagCreate(BaseModel):
    """Create a simple tag for a data contract (ODCS top-level tags)"""
    name: str = Field(..., min_length=1, max_length=255, description="Tag name")


class ContractTagUpdate(BaseModel):
    """Update a contract tag"""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="New tag name")


class ContractTagRead(BaseModel):
    """Response model for contract tag"""
    id: str
    contract_id: str
    name: str

    class Config:
        from_attributes = True


# ===== Custom Properties Models (ODCS customProperties) =====
class CustomPropertyCreate(BaseModel):
    """Create a custom property for a data contract"""
    property: str = Field(..., min_length=1, max_length=255, description="Property key")
    value: Optional[str] = Field(None, description="Property value")


class CustomPropertyUpdate(BaseModel):
    """Update a custom property"""
    property: Optional[str] = Field(None, min_length=1, max_length=255, description="Property key")
    value: Optional[str] = Field(None, description="Property value")


class CustomPropertyRead(BaseModel):
    """Response model for custom property"""
    id: str
    contract_id: str
    property: str
    value: Optional[str] = None

    class Config:
        from_attributes = True


# ===== Support Channel Models (ODCS support[]) =====
class SupportChannelCreate(BaseModel):
    """Create a support channel for a data contract"""
    channel: str = Field(..., min_length=1, max_length=255, description="Support channel type (e.g., email, slack, teams)")
    url: str = Field(..., min_length=1, description="Support channel URL")
    description: Optional[str] = Field(None, description="Channel description")
    tool: Optional[str] = Field(None, max_length=255, description="Tool name (e.g., Slack, JIRA)")
    scope: Optional[str] = Field(None, max_length=255, description="Support scope (e.g., technical, business)")
    invitation_url: Optional[str] = Field(None, description="Invitation or join URL")


class SupportChannelUpdate(BaseModel):
    """Update a support channel"""
    channel: Optional[str] = Field(None, min_length=1, max_length=255, description="Support channel type")
    url: Optional[str] = Field(None, min_length=1, description="Support channel URL")
    description: Optional[str] = Field(None, description="Channel description")
    tool: Optional[str] = Field(None, max_length=255, description="Tool name")
    scope: Optional[str] = Field(None, max_length=255, description="Support scope")
    invitation_url: Optional[str] = Field(None, description="Invitation or join URL")


class SupportChannelRead(BaseModel):
    """Response model for support channel"""
    id: str
    contract_id: str
    channel: str
    url: str
    description: Optional[str] = None
    tool: Optional[str] = None
    scope: Optional[str] = None
    invitation_url: Optional[str] = None

    class Config:
        from_attributes = True


# ===== Pricing Models (ODCS price) - Singleton Pattern =====
class PricingUpdate(BaseModel):
    """Update pricing for a data contract (singleton - one per contract)"""
    price_amount: Optional[str] = Field(None, description="Price amount")
    price_currency: Optional[str] = Field(None, max_length=10, description="Currency code (e.g., USD, EUR)")
    price_unit: Optional[str] = Field(None, max_length=50, description="Price unit (e.g., per GB, per query)")


class PricingRead(BaseModel):
    """Response model for pricing"""
    id: str
    contract_id: str
    price_amount: Optional[str] = None
    price_currency: Optional[str] = None
    price_unit: Optional[str] = None

    class Config:
        from_attributes = True


# ===== Role Models (ODCS roles[]) - With Nested Properties =====
class RolePropertyCreate(BaseModel):
    """Create a custom property for a role"""
    property: str = Field(..., min_length=1, max_length=255, description="Property key")
    value: Optional[str] = Field(None, description="Property value")


class RolePropertyRead(BaseModel):
    """Response model for role property"""
    id: str
    role_id: str
    property: str
    value: Optional[str] = None

    class Config:
        from_attributes = True


class RoleCreate(BaseModel):
    """Create a role for a data contract (with optional nested properties)"""
    role: str = Field(..., min_length=1, max_length=255, description="Role name (e.g., Data Steward, Consumer)")
    description: Optional[str] = Field(None, description="Role description")
    access: Optional[str] = Field(None, max_length=255, description="Access level or permissions")
    first_level_approvers: Optional[str] = Field(None, description="Comma-separated list of first-level approvers")
    second_level_approvers: Optional[str] = Field(None, description="Comma-separated list of second-level approvers")
    custom_properties: Optional[List[RolePropertyCreate]] = Field(default_factory=list, description="Custom properties for the role")


class RoleUpdate(BaseModel):
    """Update a role"""
    role: Optional[str] = Field(None, min_length=1, max_length=255, description="Role name")
    description: Optional[str] = Field(None, description="Role description")
    access: Optional[str] = Field(None, max_length=255, description="Access level or permissions")
    first_level_approvers: Optional[str] = Field(None, description="First-level approvers")
    second_level_approvers: Optional[str] = Field(None, description="Second-level approvers")
    custom_properties: Optional[List[RolePropertyCreate]] = Field(None, description="Custom properties (replaces existing)")


class RoleRead(BaseModel):
    """Response model for role (with nested properties)"""
    id: str
    contract_id: str
    role: str
    description: Optional[str] = None
    access: Optional[str] = None
    first_level_approvers: Optional[str] = None
    second_level_approvers: Optional[str] = None
    custom_properties: List[RolePropertyRead] = []

    class Config:
        from_attributes = True


# ===== Authoritative Definition Models (ODCS authoritativeDefinitions[]) - 3 Levels =====
class AuthoritativeDefinitionCreate(BaseModel):
    """Create an authoritative definition (works for all 3 levels: contract, schema, property)"""
    url: str = Field(..., min_length=1, description="URL to the authoritative source")
    type: str = Field(..., min_length=1, max_length=255, description="Type of authority (e.g., glossary, standard, documentation)")


class AuthoritativeDefinitionUpdate(BaseModel):
    """Update an authoritative definition"""
    url: Optional[str] = Field(None, min_length=1, description="URL to the authoritative source")
    type: Optional[str] = Field(None, min_length=1, max_length=255, description="Type of authority")


class AuthoritativeDefinitionRead(BaseModel):
    """Response model for authoritative definition (universal for all 3 levels)"""
    id: str
    url: str
    type: str
    # Context fields (only one will be populated depending on level)
    contract_id: Optional[str] = None  # For contract-level
    schema_object_id: Optional[str] = None  # For schema-level
    property_id: Optional[str] = None  # For property-level

    class Config:
        from_attributes = True


# ===== Personal Draft Commit Models =====
class CommitDraftRequest(BaseModel):
    """Request to commit a personal draft to team/project visibility"""
    new_version: str = Field(..., description="New semver version (e.g., '1.1.0')")
    change_summary: str = Field(..., description="Summary of changes in this version")


class CommitDraftResponse(BaseModel):
    """Response after committing a personal draft"""
    id: str
    name: str
    version: str
    status: str
    message: str = "Draft committed successfully"


class DiffFromParentResponse(BaseModel):
    """Response from diff-from-parent endpoint"""
    parent_version: str
    parent_status: str
    suggested_bump: str  # "major", "minor", "patch"
    suggested_version: str
    analysis: Dict[str, Any]  # Full analysis from ContractChangeAnalyzer


# ===== ODCS v3.1.0 Team Metadata Models =====
class TeamMetadataUpdate(BaseModel):
    """Update team-level metadata (ODCS v3.1.0 Team object fields)."""
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    customProperties: Optional[List[Dict[str, Any]]] = None
    authoritativeDefinitions: Optional[List[Dict[str, Any]]] = None


class TeamMetadataRead(BaseModel):
    """Response model for team metadata."""
    id: str
    contract_id: str
    stable_id: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    customProperties: Optional[List[Dict[str, Any]]] = None
    authoritativeDefinitions: Optional[List[Dict[str, Any]]] = None

    class Config:
        from_attributes = True


# ===== ODCS v3.1.0 Relationship CRUD Models =====
class SchemaRelationshipCreate(BaseModel):
    """Create a schema-level or property-level relationship."""
    type: str = "foreignKey"
    from_value: Optional[Union[str, List[str]]] = Field(None, alias='from')
    to: Union[str, List[str]] = ""
    customProperties: Optional[List[Dict[str, Any]]] = None

    class Config:
        populate_by_name = True


class SchemaRelationshipUpdate(BaseModel):
    """Update a relationship."""
    type: Optional[str] = None
    from_value: Optional[Union[str, List[str]]] = Field(None, alias='from')
    to: Optional[Union[str, List[str]]] = None
    customProperties: Optional[List[Dict[str, Any]]] = None

    class Config:
        populate_by_name = True


class SchemaRelationshipRead(BaseModel):
    """Response model for a relationship."""
    id: str
    type: str
    from_value: Optional[Union[str, List[str]]] = Field(None, alias='from')
    to: Union[str, List[str]] = ""
    customProperties: Optional[List[Dict[str, Any]]] = None
    schema_object_id: Optional[str] = None
    property_id: Optional[str] = None

    class Config:
        populate_by_name = True
        from_attributes = True


# Rebuild models to resolve forward references
SchemaObject.model_rebuild()
ODCSContract.model_rebuild()
DataContractCreate.model_rebuild()
DataContractRead.model_rebuild()
DataContractSummary.model_rebuild()