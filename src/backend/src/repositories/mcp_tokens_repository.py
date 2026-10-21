"""
Repository for MCP token database operations.

Provides CRUD operations for MCP tokens used in API key authentication.
"""

from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.mcp_tokens import MCPTokenDb

logger = get_logger(__name__)


class MCPTokensRepository:
    """Repository for MCP token database operations."""
    
    def create(
        self,
        db: Session,
        *,
        name: str,
        token_hash: str,
        scopes: List[str],
        created_by: Optional[str] = None,
        expires_at: Optional[datetime] = None,
        is_keyless_default: bool = False
    ) -> MCPTokenDb:
        """
        Create a new MCP token.

        Args:
            db: Database session
            name: Human-readable name for the token
            token_hash: bcrypt hash of the token value
            scopes: List of allowed scopes
            created_by: Email/identifier of the creator
            expires_at: Optional expiration datetime
            is_keyless_default: Whether this token is the keyless default

        Returns:
            The created MCPTokenDb instance
        """
        token = MCPTokenDb(
            name=name,
            token_hash=token_hash,
            scopes=scopes,
            created_by=created_by,
            expires_at=expires_at,
            is_keyless_default=is_keyless_default
        )
        db.add(token)
        db.flush()
        logger.info(f"Created MCP token: id={token.id}, name='{name}'")
        return token
    
    def get_by_id(self, db: Session, token_id: UUID) -> Optional[MCPTokenDb]:
        """Get a token by its ID."""
        return db.query(MCPTokenDb).filter(MCPTokenDb.id == token_id).first()
    
    def get_by_hash(self, db: Session, token_hash: str) -> Optional[MCPTokenDb]:
        """Get a token by its hash."""
        return db.query(MCPTokenDb).filter(MCPTokenDb.token_hash == token_hash).first()
    
    def get_active_by_hash(self, db: Session, token_hash: str) -> Optional[MCPTokenDb]:
        """Get an active, non-expired token by its hash."""
        token = db.query(MCPTokenDb).filter(
            and_(
                MCPTokenDb.token_hash == token_hash,
                MCPTokenDb.is_active == True
            )
        ).first()
        
        if token and token.is_expired:
            return None
        
        return token
    
    def list_all(
        self,
        db: Session,
        *,
        include_inactive: bool = False,
        limit: int = 100
    ) -> List[MCPTokenDb]:
        """
        List all tokens.
        
        Args:
            db: Database session
            include_inactive: Whether to include inactive tokens
            limit: Maximum number of tokens to return
            
        Returns:
            List of MCPTokenDb instances
        """
        query = db.query(MCPTokenDb)
        
        if not include_inactive:
            query = query.filter(MCPTokenDb.is_active == True)
        
        return query.order_by(MCPTokenDb.created_at.desc()).limit(limit).all()
    
    def update_last_used(self, db: Session, token_id: UUID) -> None:
        """Update the last_used_at timestamp for a token."""
        db.query(MCPTokenDb).filter(MCPTokenDb.id == token_id).update(
            {"last_used_at": datetime.now(timezone.utc)}
        )

    def get_keyless_default(self, db: Session) -> Optional[MCPTokenDb]:
        """
        Get the active keyless-default token, if one exists and is still valid.

        Returns the single active token flagged ``is_keyless_default``, or None if
        there is none or the flagged token has expired. This is the token used to
        resolve app-gate-authenticated MCP requests that carry no X-API-Key.
        """
        token = db.query(MCPTokenDb).filter(
            and_(
                MCPTokenDb.is_keyless_default == True,
                MCPTokenDb.is_active == True
            )
        ).first()

        if token and token.is_expired:
            return None

        return token

    def set_keyless_default(self, db: Session, token_id: UUID) -> bool:
        """
        Designate a token as the keyless default, clearing the flag on any other.

        Enforces the single-active-default invariant in code: the flag is cleared
        on every other row before being set on the target, so at most one token
        ever carries it.

        Returns:
            True if the target token was found and flagged, False otherwise.
        """
        target = db.query(MCPTokenDb).filter(MCPTokenDb.id == token_id).first()
        if target is None:
            return False

        # Clear the flag everywhere else first, then set it on the target.
        db.query(MCPTokenDb).filter(
            and_(
                MCPTokenDb.is_keyless_default == True,
                MCPTokenDb.id != token_id
            )
        ).update({"is_keyless_default": False})

        target.is_keyless_default = True
        db.flush()
        return True

    def clear_keyless_default(self, db: Session) -> bool:
        """
        Clear the keyless-default flag from whichever token carries it.

        Returns:
            True if a token was found and cleared, False if none was flagged.
        """
        result = db.query(MCPTokenDb).filter(
            MCPTokenDb.is_keyless_default == True
        ).update({"is_keyless_default": False})
        db.flush()
        return result > 0
    
    def revoke(self, db: Session, token_id: UUID) -> bool:
        """
        Revoke a token by setting is_active to False.
        
        Returns:
            True if the token was found and revoked, False otherwise
        """
        result = db.query(MCPTokenDb).filter(MCPTokenDb.id == token_id).update(
            {"is_active": False}
        )
        db.flush()
        return result > 0
    
    def delete(self, db: Session, token_id: UUID) -> bool:
        """
        Permanently delete a token.
        
        Returns:
            True if the token was found and deleted, False otherwise
        """
        result = db.query(MCPTokenDb).filter(MCPTokenDb.id == token_id).delete()
        db.flush()
        return result > 0


# Singleton instance
mcp_tokens_repo = MCPTokensRepository()

