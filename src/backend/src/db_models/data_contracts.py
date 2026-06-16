from uuid import uuid4
from sqlalchemy import (
    Column,
    String,
    DateTime,
    Text,
    Boolean,
    Integer,
    ForeignKey,
    UniqueConstraint,
    event,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from src.common.database import Base


class DataContractDb(Base):
    """ODCS-style data contract: version, status, schema objects, servers, roles, SLA; used by DataContractsManager and linked to datasets/output ports."""
    __tablename__ = "data_contracts"

    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    name = Column(String, nullable=False, index=True)  # Required for app usability
    kind = Column(String, nullable=False, default="DataContract")
    api_version = Column(String, nullable=False, default="v3.1.0")
    version = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="draft", index=True)
    # Deprecated: legacy marketplace flag; use publication_scope. Column retained for DB compatibility.
    published = Column(Boolean, nullable=False, default=False, index=True)
    owner_team_id = Column(String, ForeignKey('teams.id'), nullable=True, index=True)  # Team UUID reference
    tenant = Column(String, nullable=True)
    data_product = Column(String, nullable=True)
    domain_id = Column(String, ForeignKey("data_domains.id"), nullable=True, index=True)

    # Project relationship (nullable for backward compatibility)
    project_id = Column(String, ForeignKey('projects.id'), nullable=True, index=True)

    # Top-level description fields
    description_usage = Column(Text, nullable=True)
    description_purpose = Column(Text, nullable=True)
    description_limitations = Column(Text, nullable=True)

    # ODCS additional top-level fields
    sla_default_element = Column(String, nullable=True)  # ODCS slaDefaultElement field
    contract_created_ts = Column(DateTime(timezone=True), nullable=True)  # ODCS contractCreatedTs field

    # Semantic versioning fields
    parent_contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="SET NULL"), nullable=True, index=True)  # Parent version reference (lineage)
    # Canonical, immutable family grouping key. Copied from parent on every
    # clone, or set to self.id on first creation. Single indexed equality
    # lookup returns every version of the family. See PRD #442 in GH.
    version_family_id = Column(String, nullable=False, index=True)
    base_name = Column(String, nullable=True, index=True)  # Legacy base name; superseded by version_family_id. Kept for back-compat, no longer queried.
    change_summary = Column(Text, nullable=True)  # Summary of changes in this version

    # Personal draft visibility field
    draft_owner_id = Column(String, nullable=True, index=True)

    # Publication scope (replaces boolean `published`)
    publication_scope = Column(String, nullable=False, default="none", index=True)
    published_at = Column(DateTime(timezone=True), nullable=True)
    published_by = Column(String, nullable=True)

    # Certification
    certification_level = Column(Integer, nullable=True, index=True)
    inherited_certification_level = Column(Integer, nullable=True)
    certified_at = Column(DateTime(timezone=True), nullable=True)
    certified_by = Column(String, nullable=True)
    certification_expires_at = Column(DateTime(timezone=True), nullable=True)
    certification_notes = Column(Text, nullable=True)

    # ==================== Maturity ====================
    maturity_level_order = Column(Integer, nullable=True)
    maturity_evaluated_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
    created_by = Column(String, nullable=True)
    updated_by = Column(String, nullable=True)

    # Relationships
    # Lightweight relationships: selectin is fine, always needed for list views
    tags = relationship("DataContractTagDb", back_populates="contract", cascade="all, delete-orphan", lazy="selectin")
    servers = relationship("DataContractServerDb", back_populates="contract", cascade="all, delete-orphan", lazy="selectin")
    roles = relationship("DataContractRoleDb", back_populates="contract", cascade="all, delete-orphan", lazy="selectin")
    team = relationship("DataContractTeamDb", back_populates="contract", cascade="all, delete-orphan", lazy="selectin")
    support = relationship("DataContractSupportDb", back_populates="contract", cascade="all, delete-orphan", lazy="selectin")
    pricing = relationship("DataContractPricingDb", back_populates="contract", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    authoritative_defs = relationship("DataContractAuthoritativeDefinitionDb", back_populates="contract", cascade="all, delete-orphan", lazy="selectin")
    custom_properties = relationship("DataContractCustomPropertyDb", back_populates="contract", cascade="all, delete-orphan", lazy="selectin")
    sla_properties = relationship("DataContractSlaPropertyDb", back_populates="contract", cascade="all, delete-orphan", lazy="selectin")
    team_metadata = relationship("DataContractTeamMetadataDb", back_populates="contract", uselist=False, cascade="all, delete-orphan", lazy="selectin")
    # Heavy relationships: lazy="select" to prevent auto-loading on list queries
    owner_team = relationship("TeamDb", foreign_keys=[owner_team_id], lazy="select")
    parent_contract = relationship("DataContractDb", remote_side=[id], foreign_keys=[parent_contract_id], lazy="select")
    schema_objects = relationship("SchemaObjectDb", back_populates="contract", cascade="all, delete-orphan", lazy="select")
    comments = relationship("DataContractCommentDb", back_populates="contract", cascade="all, delete-orphan", lazy="select")
    profiling_runs = relationship("DataProfilingRunDb", back_populates="contract", cascade="all, delete-orphan", lazy="select")
    suggested_quality_checks = relationship("SuggestedQualityCheckDb", back_populates="contract", cascade="all, delete-orphan", lazy="select")


@event.listens_for(DataContractDb, "before_insert")
def _seed_contract_version_family_id(_mapper, _connection, target):
    """Guarantee the version_family_id NOT NULL invariant regardless of
    insert path (repository, direct ORM construction, demo loader, etc.).

    Roots get themselves as family root; clones must explicitly carry the
    source's family id (see ContractCloner / DataContractsManager) — this
    listener only fires when the caller forgot.
    """
    if not getattr(target, "id", None):
        target.id = str(uuid4())
    if not getattr(target, "version_family_id", None):
        target.version_family_id = target.id


class DataContractTagDb(Base):
    """Tag name on a data contract (unique per contract_id, name)."""
    __tablename__ = "data_contract_tags"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String, nullable=False)
    contract = relationship("DataContractDb", back_populates="tags")
    __table_args__ = (UniqueConstraint("contract_id", "name", name="uq_contract_tag"),)


class DataContractServerDb(Base):
    """Server/environment entry for a contract: type, environment; used by dataset instances and deployment targets."""
    __tablename__ = "data_contract_servers"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    server = Column(String, nullable=True)  # identifier
    type = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    environment = Column(String, nullable=True)
    contract = relationship("DataContractDb", back_populates="servers")
    properties = relationship("DataContractServerPropertyDb", back_populates="server_row", cascade="all, delete-orphan")


class DataContractServerPropertyDb(Base):
    """Key/value properties for a contract server (e.g. connection details)."""
    __tablename__ = "data_contract_server_properties"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    server_id = Column(String, ForeignKey("data_contract_servers.id", ondelete="CASCADE"), nullable=False, index=True)
    key = Column(String, nullable=False)
    value = Column(String, nullable=True)
    server_row = relationship("DataContractServerDb", back_populates="properties")


class DataContractRoleDb(Base):
    """Access role definition on a contract: role name, access, approvers; used for contract-level access control."""
    __tablename__ = "data_contract_roles"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    role = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    access = Column(String, nullable=True)
    first_level_approvers = Column(String, nullable=True)
    second_level_approvers = Column(String, nullable=True)
    contract = relationship("DataContractDb", back_populates="roles")
    custom_properties = relationship("DataContractRolePropertyDb", back_populates="role_row", cascade="all, delete-orphan")


class DataContractRolePropertyDb(Base):
    """Custom key/value properties for a contract role."""
    __tablename__ = "data_contract_role_properties"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    role_id = Column(String, ForeignKey("data_contract_roles.id", ondelete="CASCADE"), nullable=False, index=True)
    property = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    role_row = relationship("DataContractRoleDb", back_populates="custom_properties")


class DataContractTeamDb(Base):
    """Team member on a contract: username, role, date_in/out; contract-level team assignment."""
    __tablename__ = "data_contract_team"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    name = Column(String, nullable=True)  # ODCS TeamMember name field
    username = Column(String, nullable=False)
    role = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    date_in = Column(String, nullable=True)  # ISO date string
    date_out = Column(String, nullable=True)
    replaced_by_username = Column(String, nullable=True)
    contract = relationship("DataContractDb", back_populates="team")


class DataContractSupportDb(Base):
    """Support channel for a contract: channel, url, tool, scope (e.g. slack, email)."""
    __tablename__ = "data_contract_support"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    channel = Column(String, nullable=False)
    url = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    tool = Column(String, nullable=True)
    scope = Column(String, nullable=True)
    invitation_url = Column(String, nullable=True)
    contract = relationship("DataContractDb", back_populates="support")


class DataContractPricingDb(Base):
    """Pricing info for a contract: amount, currency, unit (ODCS pricing)."""
    __tablename__ = "data_contract_pricing"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    price_amount = Column(String, nullable=True)
    price_currency = Column(String, nullable=True)
    price_unit = Column(String, nullable=True)
    contract = relationship("DataContractDb", back_populates="pricing")


class DataContractAuthoritativeDefinitionDb(Base):
    """ODCS contract-level authoritative definitions"""
    __tablename__ = "data_contract_authoritative_definitions"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    url = Column(String, nullable=False)
    type = Column(String, nullable=False)
    contract = relationship("DataContractDb", back_populates="authoritative_defs")


class DataContractCustomPropertyDb(Base):
    """Custom key/value property on a data contract."""
    __tablename__ = "data_contract_custom_properties"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    property = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    contract = relationship("DataContractDb", back_populates="custom_properties")


class DataContractSlaPropertyDb(Base):
    """SLA property on a contract: property, value, unit, element, driver (ODCS SLA)."""
    __tablename__ = "data_contract_sla_properties"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    property = Column(String, nullable=False)
    value = Column(String, nullable=True)
    value_ext = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    element = Column(String, nullable=True)
    driver = Column(String, nullable=True)
    contract = relationship("DataContractDb", back_populates="sla_properties")


class SchemaObjectDb(Base):
    """Schema object (table/view) in a contract: name, logical/physical type, granularity; has properties and quality checks."""
    __tablename__ = "data_contract_schema_objects"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    name = Column(String, nullable=False)
    logical_type = Column(String, nullable=False, default="object")
    physical_name = Column(String, nullable=True)
    data_granularity_description = Column(Text, nullable=True)

    # ODCS additional schema object fields
    business_name = Column(String, nullable=True)  # ODCS businessName field
    physical_type = Column(String, nullable=True)  # ODCS physicalType field (table, view, etc.)
    tags = Column(Text, nullable=True)  # ODCS schema-level tags (JSON array stored as text)
    description = Column(Text, nullable=True)  # ODCS description field

    contract = relationship("DataContractDb", back_populates="schema_objects")
    properties = relationship("SchemaPropertyDb", back_populates="schema_object", cascade="all, delete-orphan")
    quality_checks = relationship("DataQualityCheckDb", back_populates="schema_object", cascade="all, delete-orphan")
    authoritative_definitions = relationship("SchemaObjectAuthoritativeDefinitionDb", back_populates="schema_object", cascade="all, delete-orphan")
    custom_properties = relationship("SchemaObjectCustomPropertyDb", back_populates="schema_object", cascade="all, delete-orphan")
    relationships = relationship("SchemaObjectRelationshipDb", back_populates="schema_object", cascade="all, delete-orphan")


class SchemaPropertyDb(Base):
    """Column/property of a schema object: name, types, required, unique, PK, partition, transform, examples; hierarchical via parent_property_id."""
    __tablename__ = "data_contract_schema_properties"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    object_id = Column(String, ForeignKey("data_contract_schema_objects.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    parent_property_id = Column(String, ForeignKey("data_contract_schema_properties.id", ondelete="CASCADE"), nullable=True, index=True)
    name = Column(String, nullable=False)
    logical_type = Column(String, nullable=True)
    physical_type = Column(String, nullable=True)
    required = Column(Boolean, nullable=False, default=False)
    unique = Column(Boolean, nullable=False, default=False)
    primary_key = Column(Boolean, nullable=False, default=False)
    partitioned = Column(Boolean, nullable=False, default=False)
    primary_key_position = Column(Integer, nullable=False, default=-1)
    partition_key_position = Column(Integer, nullable=False, default=-1)
    classification = Column(String, nullable=True)
    encrypted_name = Column(String, nullable=True)
    transform_source_objects = Column(Text, nullable=True)  # comma-separated
    transform_logic = Column(Text, nullable=True)
    transform_description = Column(Text, nullable=True)
    examples = Column(Text, nullable=True)  # comma-separated or JSON-like string
    critical_data_element = Column(Boolean, nullable=False, default=False)
    logical_type_options_json = Column(Text, nullable=True)  # JSON string of ODCS type-specific options
    items_logical_type = Column(String, nullable=True)  # for arrays
    business_name = Column(String, nullable=True)  # ODCS businessName field at property level
    schema_object = relationship("SchemaObjectDb", back_populates="properties")
    parent_property = relationship("SchemaPropertyDb", remote_side=[id])
    authoritative_definitions = relationship("SchemaPropertyAuthoritativeDefinitionDb", back_populates="property", cascade="all, delete-orphan")
    relationships = relationship("SchemaPropertyRelationshipDb", back_populates="property", cascade="all, delete-orphan")


class DataQualityCheckDb(Base):
    """Quality checks for data contracts. Can be object-level (table) or property-level (column).
    - object-level: property_id is NULL, check applies to entire table
    - property-level: property_id is set, check applies to specific column
    """
    __tablename__ = "data_contract_quality_checks"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    object_id = Column(String, ForeignKey("data_contract_schema_objects.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    property_id = Column(String, ForeignKey("data_contract_schema_properties.id", ondelete="CASCADE"), nullable=True, index=True)
    level = Column(String, nullable=True)  # optional, e.g., object/property
    name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    dimension = Column(String, nullable=True)  # ODCS quality dimensions: accuracy, completeness, conformity, consistency, coverage, timeliness, uniqueness
    business_impact = Column(String, nullable=True)  # ODCS business impact: operational, regulatory
    method = Column(String, nullable=True)
    schedule = Column(String, nullable=True)
    scheduler = Column(String, nullable=True)
    severity = Column(String, nullable=True)  # ODCS severity: info, warning, error
    type = Column(String, nullable=False, default="library")  # text|library|sql|custom
    unit = Column(String, nullable=True)
    tags = Column(Text, nullable=True)

    # Type-specific fields
    rule = Column(String, nullable=True)  # library
    query = Column(Text, nullable=True)   # sql
    engine = Column(String, nullable=True)  # custom
    implementation = Column(Text, nullable=True)  # custom impl string/json

    # Comparators
    must_be = Column(String, nullable=True)
    must_not_be = Column(String, nullable=True)
    must_be_gt = Column(String, nullable=True)
    must_be_ge = Column(String, nullable=True)
    must_be_lt = Column(String, nullable=True)
    must_be_le = Column(String, nullable=True)
    must_be_between_min = Column(String, nullable=True)
    must_be_between_max = Column(String, nullable=True)
    must_not_between_min = Column(String, nullable=True)
    must_not_between_max = Column(String, nullable=True)

    schema_object = relationship("SchemaObjectDb", back_populates="quality_checks")
    property = relationship("SchemaPropertyDb", foreign_keys=[property_id])


class DataProfilingRunDb(Base):
    """Track data profiling/quality analysis runs on contracts (DQX, LLM, manual)"""
    __tablename__ = "data_profiling_runs"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String, nullable=False, index=True)  # 'dqx', 'llm', 'manual', etc.
    schema_names = Column(Text, nullable=True)  # JSON array of schema names profiled
    status = Column(String, nullable=False, default="pending", index=True)  # pending, running, completed, failed
    summary_stats = Column(Text, nullable=True)  # JSON profiling summary/metadata
    run_id = Column(String, nullable=True)  # Databricks job run_id if applicable
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String, nullable=True)  # Username
    
    contract = relationship("DataContractDb", back_populates="profiling_runs")
    suggestions = relationship("SuggestedQualityCheckDb", back_populates="profile_run", cascade="all, delete-orphan")


class SuggestedQualityCheckDb(Base):
    """Quality check suggestions from profiling runs (DQX, LLM, etc.)"""
    __tablename__ = "suggested_quality_checks"
    
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    profile_run_id = Column(String, ForeignKey("data_profiling_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    source = Column(String, nullable=False, index=True)  # 'dqx', 'llm', 'manual', etc.
    schema_name = Column(String, nullable=False, index=True)  # Which schema/table
    property_name = Column(String, nullable=True, index=True)  # For property-level checks
    status = Column(String, nullable=False, default="pending", index=True)  # pending, accepted, rejected
    
    # Quality check definition fields (matching DataQualityCheckDb structure)
    name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    level = Column(String, nullable=True)  # object/property
    dimension = Column(String, nullable=True)  # accuracy, completeness, conformity, etc.
    business_impact = Column(String, nullable=True)  # operational, regulatory
    severity = Column(String, nullable=True)  # info, warning, error
    type = Column(String, nullable=False, default="library")  # text, library, sql, custom
    method = Column(String, nullable=True)
    schedule = Column(String, nullable=True)
    scheduler = Column(String, nullable=True)
    unit = Column(String, nullable=True)
    tags = Column(Text, nullable=True)
    
    # Type-specific fields
    rule = Column(String, nullable=True)  # library
    query = Column(Text, nullable=True)  # sql
    engine = Column(String, nullable=True)  # custom
    implementation = Column(Text, nullable=True)  # custom impl
    
    # Comparators
    must_be = Column(String, nullable=True)
    must_not_be = Column(String, nullable=True)
    must_be_gt = Column(String, nullable=True)
    must_be_ge = Column(String, nullable=True)
    must_be_lt = Column(String, nullable=True)
    must_be_le = Column(String, nullable=True)
    must_be_between_min = Column(String, nullable=True)
    must_be_between_max = Column(String, nullable=True)
    
    # AI/confidence fields
    confidence_score = Column(String, nullable=True)  # For AI-generated suggestions
    rationale = Column(Text, nullable=True)  # Explanation for the suggestion
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    
    profile_run = relationship("DataProfilingRunDb", back_populates="suggestions")
    contract = relationship("DataContractDb", back_populates="suggested_quality_checks")


class DataContractCommentDb(Base):
    """Comment on a data contract: author, message, created_at; used in contract discussion/feedback."""
    __tablename__ = "data_contract_comments"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, index=True)
    author = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    contract = relationship("DataContractDb", back_populates="comments")


class SchemaObjectAuthoritativeDefinitionDb(Base):
    """ODCS schema-level authoritative definitions"""
    __tablename__ = "data_contract_schema_object_authoritative_definitions"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    schema_object_id = Column(String, ForeignKey("data_contract_schema_objects.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    url = Column(String, nullable=False)
    type = Column(String, nullable=False)
    schema_object = relationship("SchemaObjectDb", back_populates="authoritative_definitions")


class SchemaObjectCustomPropertyDb(Base):
    """ODCS schema-level custom properties"""
    __tablename__ = "data_contract_schema_object_custom_properties"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    schema_object_id = Column(String, ForeignKey("data_contract_schema_objects.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    property = Column(String, nullable=False)
    value = Column(Text, nullable=True)
    schema_object = relationship("SchemaObjectDb", back_populates="custom_properties")


class SchemaPropertyAuthoritativeDefinitionDb(Base):
    """ODCS property-level authoritative definitions"""
    __tablename__ = "data_contract_schema_property_authoritative_definitions"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    property_id = Column(String, ForeignKey("data_contract_schema_properties.id", ondelete="CASCADE"), nullable=False, index=True)
    stable_id = Column(String, nullable=True)  # ODCS v3.1.0 StableId
    url = Column(String, nullable=False)
    type = Column(String, nullable=False)
    property = relationship("SchemaPropertyDb", back_populates="authoritative_definitions")


class SchemaObjectRelationshipDb(Base):
    """ODCS v3.1.0 schema-level relationship (foreign key) on a schema object."""
    __tablename__ = "data_contract_schema_object_relationships"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    schema_object_id = Column(String, ForeignKey("data_contract_schema_objects.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type = Column(String, nullable=False, default="foreignKey")
    from_value = Column(Text, nullable=False)  # JSON-serialized: string or array
    to_value = Column(Text, nullable=False)    # JSON-serialized: string or array
    custom_properties_json = Column(Text, nullable=True)  # JSON array of {property, value}
    schema_object = relationship("SchemaObjectDb", back_populates="relationships")


class SchemaPropertyRelationshipDb(Base):
    """ODCS v3.1.0 property-level relationship (foreign key) on a schema property."""
    __tablename__ = "data_contract_schema_property_relationships"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    property_id = Column(String, ForeignKey("data_contract_schema_properties.id", ondelete="CASCADE"), nullable=False, index=True)
    relationship_type = Column(String, nullable=False, default="foreignKey")
    to_value = Column(Text, nullable=False)  # JSON-serialized: string or array
    custom_properties_json = Column(Text, nullable=True)
    property = relationship("SchemaPropertyDb", back_populates="relationships")


class DataContractTeamMetadataDb(Base):
    """ODCS v3.1.0 Team object metadata (name, description, tags, customProperties, authoritativeDefinitions)."""
    __tablename__ = "data_contract_team_metadata"
    id = Column(String, primary_key=True, default=lambda: str(uuid4()))
    contract_id = Column(String, ForeignKey("data_contracts.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    stable_id = Column(String, nullable=True)
    name = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    tags_json = Column(Text, nullable=True)  # JSON array
    custom_properties_json = Column(Text, nullable=True)  # JSON array of {property, value}
    authoritative_definitions_json = Column(Text, nullable=True)  # JSON array of {url, type}
    contract = relationship("DataContractDb", back_populates="team_metadata")


