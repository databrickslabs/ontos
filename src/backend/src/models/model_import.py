"""API models for staged model imports (erwin; PRD #1718)."""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

ContractGrouping = Literal["subject_area", "schema", "table", "model"]
UdpTarget = Literal["custom_property", "tag", "classification", "critical_data_element", "ignore"]


class CatalogMapping(BaseModel):
    """Maps an erwin owner/schema to a Unity Catalog ``catalog.schema``.

    ``source`` ``*`` is the fallback for tables without (or with an unmapped)
    owner.
    """
    source: str = Field(..., min_length=1, max_length=255)
    target: str = Field(..., min_length=3, max_length=511, pattern=r"^[^.\s]+\.[^.\s]+$")


class UdpMapping(BaseModel):
    udp: str = Field(..., min_length=1, max_length=255)
    target: UdpTarget = "custom_property"


class ModelImportOptions(BaseModel):
    """What a run imports and where it lands. Every field has a safe default."""
    import_logical: bool = True
    import_physical: bool = True
    # Empty = all subject areas (the whole model). Order sets the priority when
    # a table is in several subject areas.
    subject_area_ids: List[str] = Field(default_factory=list)
    # Target knowledge collection; None = the collection used by the previous
    # import of this model, else a new one named after the model.
    collection_iri: Optional[str] = None
    contract_grouping: ContractGrouping = "subject_area"
    catalog_mappings: List[CatalogMapping] = Field(default_factory=list)
    # erwin entity id → UC table FQN, overriding the mapping for one table.
    table_overrides: Dict[str, str] = Field(default_factory=dict)
    # Source dialect override (oracle, sqlserver, ...); None = from the model.
    dbms: Optional[str] = None
    migration_mode: bool = False
    udp_mappings: List[UdpMapping] = Field(default_factory=list)
    # Subject area id (or "__model__") → data domain id for its contract.
    domain_by_group: Dict[str, str] = Field(default_factory=dict)


class ModelImportRunSummary(BaseModel):
    id: str
    status: str
    source_kind: str
    source_filename: Optional[str] = None
    source_model_name: Optional[str] = None
    source_model_version: Optional[str] = None
    progress_message: Optional[str] = None
    error: Optional[str] = None
    user_id: str
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None


class ModelImportRunDetail(ModelImportRunSummary):
    source_sha256: Optional[str] = None
    source_size_bytes: Optional[int] = None
    options: Optional[ModelImportOptions] = None
    preview: Optional[Dict[str, Any]] = None
    confirm_token: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class ConfirmModelImportRequest(BaseModel):
    confirm_token: str = Field(..., min_length=8, max_length=128)
