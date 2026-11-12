"""Pydantic models for Authority Policies (the ARF justification basis)."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from src.models.tags import AssignedTagCreate


class PolicyClauseLimits(BaseModel):
    amount: Optional[float] = None
    currency: Optional[str] = None


class PolicyClause(BaseModel):
    """One citable clause, e.g. ``§7.1`` "CPO may award up to EUR 2m"."""
    ref: str = Field(..., min_length=1, max_length=64)
    title: Optional[str] = None
    text: Optional[str] = None
    limits: Optional[PolicyClauseLimits] = None
    conditions: List[str] = Field(default_factory=list)


class AuthorityPolicyCreate(BaseModel):
    policy_key: str = Field(..., min_length=1, max_length=128)
    title: str = Field(..., min_length=1, max_length=255)
    version: str = "1"
    policy_type: str = "DOA"
    summary: Optional[str] = None
    owner_team_id: Optional[str] = None
    jurisdiction: Optional[Dict[str, Any]] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    clauses: List[PolicyClause] = Field(default_factory=list)
    tags: Optional[List[AssignedTagCreate]] = None


class AuthorityPolicyUpdate(BaseModel):
    """Edits apply to drafts only; an approved policy changes through a new version."""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    policy_type: Optional[str] = None
    summary: Optional[str] = None
    owner_team_id: Optional[str] = None
    jurisdiction: Optional[Dict[str, Any]] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    clauses: Optional[List[PolicyClause]] = None
    tags: Optional[List[AssignedTagCreate]] = None


class PolicyNewVersionRequest(BaseModel):
    new_version: str = Field(..., min_length=1, max_length=32)
    change_summary: Optional[str] = None


class PolicyStatusRequest(BaseModel):
    """``approved`` needs an effective date (here or on the policy); the approver
    defaults to the caller. ``withdrawn`` takes an optional reason."""
    status: str
    approved_by: Optional[str] = None
    effective_from: Optional[datetime] = None
    effective_to: Optional[datetime] = None
    approval_evidence_document_id: Optional[str] = None
    reason: Optional[str] = None
