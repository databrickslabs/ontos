"""Pydantic models for Policy references (the ARF justification metadata, ARF 1.2.0).

A reference is metadata only: nothing it says is enforced (#1294 decision).
"""
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from src.models.tags import AssignedTagCreate


class PolicyClause(BaseModel):
    """An optional clause label, offered as a suggestion in the AR's clause picker."""
    ref: str = Field(..., min_length=1, max_length=64)
    title: Optional[str] = Field(None, max_length=255)
    text: Optional[str] = Field(None, max_length=4000)


class AuthorityPolicyCreate(BaseModel):
    policy_key: str = Field(..., min_length=1, max_length=128, description="External id, e.g. POL-DOA-2026")
    title: str = Field(..., min_length=1, max_length=255, description="Name")
    version: str = "1"
    summary: Optional[str] = Field(None, max_length=4000, description="Description")
    owner_team_id: Optional[str] = None
    url: Optional[str] = Field(None, max_length=2048)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    clauses: List[PolicyClause] = Field(default_factory=list)
    tags: Optional[List[AssignedTagCreate]] = None


class AuthorityPolicyUpdate(BaseModel):
    """Corrections to a reference. Versions change through a new version, not here."""
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    summary: Optional[str] = Field(None, max_length=4000)
    owner_team_id: Optional[str] = None
    url: Optional[str] = Field(None, max_length=2048)
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None
    clauses: Optional[List[PolicyClause]] = None
    tags: Optional[List[AssignedTagCreate]] = None


class PolicyNewVersionRequest(BaseModel):
    new_version: str = Field(..., min_length=1, max_length=32)
    change_summary: Optional[str] = Field(None, max_length=1000)


class PolicyCitation(BaseModel):
    """What an AR cites, as stored in decision provenance (ISO strings, not documents)."""
    authority_policy_id: str
    clause_refs: List[str] = Field(default_factory=list)
    policy_key: Optional[str] = None
    version: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None
    valid_from: Optional[str] = None
    valid_to: Optional[str] = None
    expired: bool = False

