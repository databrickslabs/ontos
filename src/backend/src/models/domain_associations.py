"""Pydantic shapes for polymorphic entity↔domain assignments.

Mirrors the tag-assignment models (``AssignedTag`` / ``AssignedTagCreate``) but for
Data Domain assignments backed by ``EntityDomainAssociationDb``.
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, model_validator


class AssignedDomain(BaseModel):
    """A Data Domain assigned to an entity, with primary flag and audit metadata."""

    domain_id: str = Field(..., description="ID of the assigned data domain.")
    domain_name: Optional[str] = Field(None, description="Name of the assigned data domain.")
    is_primary: bool = Field(False, description="Whether this is the entity's primary (canonical) domain.")
    assigned_by: Optional[str] = Field(None, description="User who assigned the domain.")
    assigned_at: Optional[datetime] = Field(None, description="When the domain was assigned.")

    model_config = {"from_attributes": True}


class DomainAssignmentWrite(BaseModel):
    """Write payload for setting an entity's domain assignments (replace-all).

    ``domain_ids`` is the full set of assigned domains (including the primary).
    ``primary_domain_id`` must be one of ``domain_ids`` when provided; when omitted
    and ``domain_ids`` is non-empty, the repository defaults the primary to the
    first id. An empty ``domain_ids`` leaves the entity unassigned (no primary).
    """

    domain_ids: List[str] = Field(default_factory=list, description="All assigned domain IDs, primary included.")
    primary_domain_id: Optional[str] = Field(
        None, description="Which domain_id is primary. Must be in domain_ids, or null when domain_ids is empty."
    )

    @model_validator(mode="after")
    def _validate_primary_in_set(self):
        if self.primary_domain_id is not None and self.primary_domain_id not in self.domain_ids:
            raise ValueError("primary_domain_id must be one of domain_ids")
        return self
