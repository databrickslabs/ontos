from datetime import datetime
from enum import Enum
from typing import Any, Optional, List
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

class CloudType(str, Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"

class SyncStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"

class ConnectionType(str, Enum):
    DELTA_SHARE = "delta_share"
    DATABASE = "database"

class SharingResourceType(str, Enum):
    DATA_PRODUCT = "data_product"
    DATA_CONTRACT = "data_contract"
    BUSINESS_TERM = "business_term"
    DATA_DOMAIN = "data_domain"
    CONCEPT = "concept"

# Resource type names used before the PRD (#143) vocabulary; still accepted on input.
LEGACY_RESOURCE_TYPES = {"business_glossary": SharingResourceType.BUSINESS_TERM.value}

class SharingPolicyDirection(str, Enum):
    EXPORT = "export"
    IMPORT = "import"

class SharingRuleOperator(str, Enum):
    EQUALS = "equals"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"
    REGEX = "regex"

class SharingRule(BaseModel):
    filter_type: str = Field(..., description="Type of filter (e.g., 'tag', 'domain', 'status', 'name')")
    operator: SharingRuleOperator = Field(..., description="Operator for the filter")
    filter_value: str = Field(..., description="Value to filter by")

class SharingPolicy(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = Field(None, description="Unique identifier for the sharing policy, can be auto-generated")
    name: str = Field(..., description="Name of the sharing policy")
    description: Optional[str] = Field(None, description="Description of the sharing policy")
    resource_type: SharingResourceType = Field(..., description="Type of resource the policy selects (data product, contract, business term, domain, concept)")
    rules: List[SharingRule] = Field(default_factory=list, description="List of rules that define the policy")
    is_enabled: bool = Field(True, description="Whether the sharing policy is enabled")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")

    @field_validator('resource_type', mode='before')
    @classmethod
    def _map_legacy_resource_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            return LEGACY_RESOURCE_TYPES.get(value, value)
        return value

class Estate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = Field(None, description="Unique identifier for the estate")
    name: str = Field(..., description="Name of the estate")
    description: str = Field(..., description="Description of the estate")
    workspace_url: str = Field(..., description="URL of the Databricks workspace")
    cloud_type: CloudType = Field(..., description="Cloud provider type")
    metastore_name: str = Field(..., description="Name of the metastore")
    connection_type: ConnectionType = Field(ConnectionType.DELTA_SHARE, description="Type of connection to this estate for metadata sharing")
    export_policies: List[SharingPolicy] = Field(default_factory=list, description="Policies selecting what this instance shares with the estate")
    import_policies: List[SharingPolicy] = Field(default_factory=list, description="Policies selecting what this instance accepts from the estate")
    is_enabled: bool = Field(True, description="Whether the estate sync is enabled")
    sync_schedule: str = Field("0 0 * * *", description="Cron expression for sync schedule")
    last_sync_time: Optional[datetime] = Field(None, description="Timestamp of last successful sync")
    last_sync_status: Optional[SyncStatus] = Field(None, description="Status of last sync attempt")
    last_sync_error: Optional[str] = Field(None, description="Error message from last failed sync")
    created_at: datetime = Field(default_factory=datetime.utcnow, description="Creation timestamp")
    updated_at: datetime = Field(default_factory=datetime.utcnow, description="Last update timestamp")

    @model_validator(mode='before')
    @classmethod
    def _accept_legacy_sharing_policies(cls, data: Any) -> Any:
        """Accept the single ``sharing_policies`` list of older clients as export policies."""
        if isinstance(data, dict) and 'sharing_policies' in data:
            data = dict(data)
            legacy = data.pop('sharing_policies') or []
            if not data.get('export_policies'):
                data['export_policies'] = legacy
        return data
