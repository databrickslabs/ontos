"""
Pydantic models for MCP tokens API.

Models for creating, reading, and managing MCP API tokens.
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class MCPTokenCreate(BaseModel):
    """Request model for creating a new MCP token."""
    name: str = Field(..., min_length=1, max_length=255, description="Human-readable name for the token")
    scopes: List[str] = Field(default=[], description="List of allowed scopes (e.g., ['data-products:read'])")
    expires_days: Optional[int] = Field(default=90, ge=1, le=365, description="Days until expiration (null for no expiration)")
    is_keyless_default: bool = Field(default=False, description="Make this the keyless default token (resolves app-gate requests with no X-API-Key). Supersedes any existing default.")


class MCPTokenResponse(BaseModel):
    """Response model for a created token (includes plaintext token once)."""
    id: UUID
    name: str
    token: str = Field(..., description="The plaintext token - save this, it won't be shown again")
    scopes: List[str]
    created_at: datetime
    expires_at: Optional[datetime]
    
    class Config:
        from_attributes = True


class MCPTokenInfo(BaseModel):
    """Response model for token information (without the actual token)."""
    id: UUID
    name: str
    scopes: List[str]
    created_by: Optional[str]
    created_at: datetime
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    is_active: bool
    is_expired: bool
    is_keyless_default: bool = False

    class Config:
        from_attributes = True


class MCPTokenList(BaseModel):
    """Response model for listing tokens."""
    tokens: List[MCPTokenInfo]
    total: int

