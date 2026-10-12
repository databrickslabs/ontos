"""
Domain Sync models.

Request/response shapes for syncing data domains between Ontos and Unity Catalog
(#761). UC domains are capped at two levels (root domains + one subdomain layer);
Ontos domains nest arbitrarily via ``parent_id``. These models describe a
preview (dry-run) and the result of applying it, in either direction.
"""

from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SyncDirection(str, Enum):
    IMPORT_FROM_UC = "import_from_uc"
    EXPORT_TO_UC = "export_to_uc"


class SyncAction(str, Enum):
    CREATE = "create"      # a new domain would be / was created on the target
    MATCH = "match"        # already exists on the target; linked (uc_domain_id backfilled)
    SKIP = "skip"          # cannot be mapped (e.g. deeper than UC's 2 levels)
    ERROR = "error"        # failed while applying


class DomainSyncNode(BaseModel):
    """One domain in a sync preview/result, annotated with the planned action."""
    name: str = Field(..., description="Domain name")
    level: int = Field(..., description="Target level: 1 = root domain, 2 = subdomain, 3+ = too deep")
    action: SyncAction = Field(..., description="What will happen / happened for this node")
    reason: Optional[str] = Field(None, description="Why it was skipped or errored")
    parent_name: Optional[str] = Field(None, description="Name of the parent domain on the target, if any")
    ontos_id: Optional[UUID] = Field(None, description="Matching/created Ontos domain id, if known")
    uc_domain_id: Optional[str] = Field(None, description="Matching/created UC domain id, if known")


class DomainSyncPreview(BaseModel):
    """Dry-run: what a sync would do. Creates nothing."""
    direction: SyncDirection
    nodes: List[DomainSyncNode] = Field(default_factory=list)
    to_create: int = 0
    to_match: int = 0
    to_skip: int = 0
    warnings: List[str] = Field(default_factory=list)


class DomainSyncResult(BaseModel):
    """Outcome of applying a sync."""
    direction: SyncDirection
    created: int = 0
    matched: int = 0
    skipped: int = 0
    errors: int = 0
    error_messages: List[str] = Field(default_factory=list)
    nodes: List[DomainSyncNode] = Field(default_factory=list)


class ImportRequest(BaseModel):
    """Import UC domains into Ontos."""
    target_root_id: Optional[UUID] = Field(
        None,
        description="Ontos domain to place imported UC roots under. If omitted, UC "
        "root domains land at the Ontos top level.",
    )


class ExportRequest(BaseModel):
    """Export Ontos domains to UC.

    The anchor's direct children become UC root domains and its grandchildren
    become UC subdomains; anything deeper is skipped (UC allows only two levels).
    """
    anchor_domain_id: Optional[UUID] = Field(
        None,
        description="Ontos domain whose children map to UC roots. If omitted, Ontos "
        "top-level domains (no parent) map to UC roots.",
    )
