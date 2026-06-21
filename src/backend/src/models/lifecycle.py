"""Shared lifecycle enums and models used across all entity types.

Provides:
- EntityStatus: unified lifecycle status enum (replaces DataProductStatus, ContractStatus, etc.)
- PublicationScope: scoped publication visibility
- CertificationInfo / PublicationInfo: embedded metadata models
- VALID_TRANSITIONS: per-entity-type transition maps
"""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class EntityStatus(str, Enum):
    """Unified lifecycle status for all governed entities."""
    DRAFT = "draft"
    SANDBOX = "sandbox"
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    APPROVED = "approved"
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class PublicationScope(str, Enum):
    """Visibility scope when an entity is published."""
    NONE = "none"
    DOMAIN = "domain"
    ORGANIZATION = "organization"
    EXTERNAL = "external"


# Per-entity-type transition maps (status -> list of allowed next statuses)
DATA_PRODUCT_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["sandbox", "proposed", "deprecated"],
    "sandbox": ["draft", "proposed", "deprecated"],
    "proposed": ["draft", "under_review", "deprecated"],
    "under_review": ["draft", "approved", "deprecated"],
    "approved": ["active", "draft", "deprecated"],
    "active": ["deprecated"],
    "deprecated": ["retired", "active"],
    "retired": [],
}

DATA_CONTRACT_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["proposed", "deprecated"],
    # A steward can approve directly from "proposed" (the approve endpoint is
    # documented as PROPOSED/UNDER_REVIEW -> APPROVED). "under_review" stays an
    # optional intermediate step rather than a mandatory one.
    "proposed": ["draft", "under_review", "approved", "deprecated"],
    "under_review": ["draft", "approved", "deprecated"],
    "approved": ["active", "draft", "deprecated"],
    "active": ["deprecated"],
    "deprecated": ["retired", "active"],
    "retired": [],
}

DATASET_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["active", "deprecated"],
    "active": ["deprecated"],
    "deprecated": ["retired", "active"],
    "retired": [],
}

ASSET_TRANSITIONS: dict[str, list[str]] = {
    "draft": ["active", "deprecated"],
    "active": ["deprecated"],
    "deprecated": ["retired", "active"],
    "retired": [],
}


class CertificationInfo(BaseModel):
    """Certification metadata embedded in entity responses."""
    certification_level: Optional[int] = Field(None, description="Ordinal of the certification level")
    inherited_certification_level: Optional[int] = Field(None, description="Inherited via relationships")
    certified_at: Optional[datetime] = None
    certified_by: Optional[str] = None
    certification_expires_at: Optional[datetime] = None
    certification_notes: Optional[str] = None

    model_config = {"from_attributes": True}


class PublicationInfo(BaseModel):
    """Publication metadata embedded in entity responses."""
    publication_scope: PublicationScope = PublicationScope.NONE
    published_at: Optional[datetime] = None
    published_by: Optional[str] = None

    model_config = {"from_attributes": True}
