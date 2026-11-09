"""
SQLAlchemy model for MCP tokens.

MCP tokens are used for API key authentication when accessing the MCP endpoint.
Each token has a set of scopes that determine which tools it can access.
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import uuid4

from sqlalchemy import Boolean, Column, DateTime, JSON, String
from sqlalchemy.dialects.postgresql import UUID

from src.common.database import Base


class MCPTokenDb(Base):
    """
    MCP token model for API key authentication.
    
    Attributes:
        id: Unique identifier for the token
        name: Human-readable name for the token (e.g., "Production API Key")
        token_hash: bcrypt hash of the actual token value
        scopes: JSON array of allowed scopes (e.g., ["data-products:read", "sparql:query"])
        created_by: Email/identifier of the user who created this token
        created_at: When the token was created
        last_used_at: When the token was last used for authentication
        expires_at: When the token expires (null for no expiration)
        is_active: Whether the token is active (can be revoked)
        is_keyless_default: Whether this token is the keyless default, used to
            resolve app-gate-authenticated MCP requests that carry no X-API-Key.
            At most one active token should carry this flag (enforced in code).
    """
    __tablename__ = "mcp_tokens"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    token_hash = Column(String(255), nullable=False, unique=True, index=True)
    scopes = Column(JSON, nullable=False, default=list)
    created_by = Column(String(255), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, index=True)
    is_keyless_default = Column(Boolean, nullable=False, default=False, index=True)
    
    def __repr__(self) -> str:
        return f"<MCPTokenDb(id={self.id}, name='{self.name}', is_active={self.is_active})>"
    
    @property
    def is_expired(self) -> bool:
        """Check if the token has expired."""
        if self.expires_at is None:
            return False
        # Postgres round-trips tz-aware datetimes, but some backends (e.g. SQLite)
        # drop the tzinfo. Treat a naive expires_at as UTC so the comparison never
        # raises on offset-naive vs offset-aware.
        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) > expires_at
    
    @property
    def is_valid(self) -> bool:
        """Check if the token is both active and not expired."""
        return self.is_active and not self.is_expired

