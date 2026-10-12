"""
Manager for MCP token operations.

Handles token generation, validation, and scope checking for MCP API authentication.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set
from uuid import UUID

import bcrypt
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.mcp_tokens import MCPTokenDb
from src.repositories.mcp_tokens_repository import mcp_tokens_repo

logger = get_logger(__name__)

# Token prefix for easy identification
TOKEN_PREFIX = "mcp_"
TOKEN_BYTE_LENGTH = 32  # 256 bits of entropy


@dataclass
class MCPTokenInfo:
    """Information about a validated MCP token."""
    id: UUID
    name: str
    scopes: List[str]
    created_by: Optional[str]
    created_at: datetime
    expires_at: Optional[datetime]


@dataclass
class GeneratedToken:
    """Result of token generation, containing the plaintext token (shown once)."""
    id: UUID
    name: str
    token: str  # Plaintext token - only returned once
    scopes: List[str]
    created_at: datetime
    expires_at: Optional[datetime]


class MCPTokensManager:
    """
    Manager for MCP token operations.
    
    Handles:
    - Token generation with secure random values
    - Token validation using bcrypt
    - Scope checking for authorization
    - Token lifecycle management (revoke, list)
    """
    
    def __init__(self, db: Session):
        self._db = db
    
    def generate_token(
        self,
        name: str,
        scopes: List[str],
        created_by: Optional[str] = None,
        expires_days: Optional[int] = 90,
        is_keyless_default: bool = False
    ) -> GeneratedToken:
        """
        Generate a new MCP API token.

        Args:
            name: Human-readable name for the token
            scopes: List of allowed scopes (e.g., ["data-products:read", "sparql:query"])
            created_by: Email/identifier of the user creating the token
            expires_days: Number of days until expiration (None for no expiration)
            is_keyless_default: Whether this token becomes the keyless default. When
                True, the flag is cleared on any other token first (single active
                default invariant).

        Returns:
            GeneratedToken containing the plaintext token (shown only once)
        """
        # Generate secure random token
        random_bytes = secrets.token_bytes(TOKEN_BYTE_LENGTH)
        plaintext_token = TOKEN_PREFIX + secrets.token_urlsafe(TOKEN_BYTE_LENGTH)
        
        # Hash the token for storage
        token_hash = bcrypt.hashpw(
            plaintext_token.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')
        
        # Calculate expiration
        expires_at = None
        if expires_days is not None:
            expires_at = datetime.now(timezone.utc) + timedelta(days=expires_days)
        
        # A new keyless default supersedes any existing one, so clear the flag
        # elsewhere before creating this row (keeps at most one active default).
        if is_keyless_default:
            mcp_tokens_repo.clear_keyless_default(self._db)

        # Store in database
        db_token = mcp_tokens_repo.create(
            db=self._db,
            name=name,
            token_hash=token_hash,
            scopes=scopes,
            created_by=created_by,
            expires_at=expires_at,
            is_keyless_default=is_keyless_default
        )

        logger.info(
            f"Generated MCP token: id={db_token.id}, name='{name}', scopes={scopes}, "
            f"is_keyless_default={is_keyless_default}"
        )
        
        return GeneratedToken(
            id=db_token.id,
            name=name,
            token=plaintext_token,
            scopes=scopes,
            created_at=db_token.created_at,
            expires_at=expires_at
        )
    
    def validate_token(self, token: str) -> Optional[MCPTokenInfo]:
        """
        Validate an MCP token and return its info.
        
        Args:
            token: The plaintext token to validate
            
        Returns:
            MCPTokenInfo if valid, None if invalid/expired/revoked
        """
        if not token or not token.startswith(TOKEN_PREFIX):
            return None
        
        # Get all active tokens and check against each
        # This is O(n) but necessary since we can't reverse the bcrypt hash
        # For better performance with many tokens, consider using a faster
        # hash (SHA-256) for lookup with bcrypt for verification
        active_tokens = mcp_tokens_repo.list_all(
            db=self._db,
            include_inactive=False,
            limit=1000
        )
        
        for db_token in active_tokens:
            try:
                if bcrypt.checkpw(token.encode('utf-8'), db_token.token_hash.encode('utf-8')):
                    # Check expiration
                    if db_token.is_expired:
                        logger.warning(f"Token {db_token.id} has expired")
                        return None
                    
                    # Update last used timestamp
                    mcp_tokens_repo.update_last_used(self._db, db_token.id)
                    
                    logger.debug(f"Validated MCP token: id={db_token.id}, name='{db_token.name}'")
                    
                    return MCPTokenInfo(
                        id=db_token.id,
                        name=db_token.name,
                        scopes=db_token.scopes or [],
                        created_by=db_token.created_by,
                        created_at=db_token.created_at,
                        expires_at=db_token.expires_at
                    )
            except Exception as e:
                logger.error(f"Error checking token {db_token.id}: {e}")
                continue
        
        return None
    
    def resolve_keyless_default(self, forwarded_email: str) -> Optional[MCPTokenInfo]:
        """
        Resolve an app-gate-authenticated, keyless MCP request to the default token.

        Used only when a request carries no X-API-Key but has cleared the Databricks
        app proxy (so a forwarded identity is present). Returns the active keyless
        default token's info, re-stamped with the caller's forwarded email as
        ``created_by`` so audit logging attributes the call to the real user rather
        than to the shared token. Scopes are taken verbatim from the default token,
        so they bound exactly what the keyless caller may do.

        Args:
            forwarded_email: The caller's identity from the app proxy
                (X-Forwarded-Email / X-Forwarded-User). Must be non-empty.

        Returns:
            MCPTokenInfo for the keyless caller, or None if keyless access is not
            enabled (no active, non-expired default token) or no email was supplied.
        """
        if not forwarded_email:
            return None

        db_token = mcp_tokens_repo.get_keyless_default(self._db)
        if db_token is None:
            return None

        # Track usage on the shared default token like any other authentication.
        mcp_tokens_repo.update_last_used(self._db, db_token.id)

        logger.info(
            f"Resolved keyless MCP request via default token id={db_token.id} "
            f"for user '{forwarded_email}'"
        )

        return MCPTokenInfo(
            id=db_token.id,
            name=f"{db_token.name} (keyless:{forwarded_email})",
            scopes=db_token.scopes or [],
            created_by=forwarded_email,
            created_at=db_token.created_at,
            expires_at=db_token.expires_at
        )

    def set_keyless_default(self, token_id: UUID) -> bool:
        """
        Designate an existing token as the keyless default.

        Clears the flag on any other token first, so at most one active default
        exists. Returns True if the target token was found and flagged.
        """
        success = mcp_tokens_repo.set_keyless_default(self._db, token_id)
        if success:
            logger.info(f"Set keyless-default MCP token: id={token_id}")
        return success

    def clear_keyless_default(self) -> bool:
        """Clear the keyless-default flag from whichever token carries it."""
        success = mcp_tokens_repo.clear_keyless_default(self._db)
        if success:
            logger.info("Cleared keyless-default MCP token flag")
        return success

    def check_scope(self, token_info: MCPTokenInfo, required_scope: str) -> bool:
        """
        Check if a token has the required scope.
        
        Supports wildcards:
        - "*" matches all scopes (admin)
        - "data-products:*" matches all data-products scopes
        - Exact match (e.g., "data-products:read")
        
        Args:
            token_info: The validated token info
            required_scope: The scope required for the operation
            
        Returns:
            True if the token has the required scope
        """
        scopes = token_info.scopes
        
        # Admin wildcard matches everything
        if "*" in scopes:
            return True
        
        # Check for exact match
        if required_scope in scopes:
            return True
        
        # Check for prefix wildcard (e.g., "data-products:*" matches "data-products:read")
        required_prefix = required_scope.split(":")[0] if ":" in required_scope else required_scope
        wildcard = f"{required_prefix}:*"
        if wildcard in scopes:
            return True
        
        return False
    
    def revoke_token(self, token_id: UUID) -> bool:
        """
        Revoke a token, making it inactive.
        
        Args:
            token_id: The ID of the token to revoke
            
        Returns:
            True if the token was found and revoked
        """
        success = mcp_tokens_repo.revoke(self._db, token_id)
        if success:
            logger.info(f"Revoked MCP token: id={token_id}")
        return success
    
    def list_tokens(self, include_inactive: bool = False) -> List[MCPTokenDb]:
        """
        List all tokens.
        
        Args:
            include_inactive: Whether to include revoked tokens
            
        Returns:
            List of MCPTokenDb instances (without token hashes exposed)
        """
        return mcp_tokens_repo.list_all(
            db=self._db,
            include_inactive=include_inactive
        )
    
    def get_token(self, token_id: UUID) -> Optional[MCPTokenDb]:
        """Get a token by ID."""
        return mcp_tokens_repo.get_by_id(self._db, token_id)
    
    def delete_token(self, token_id: UUID) -> bool:
        """
        Permanently delete a token.
        
        Args:
            token_id: The ID of the token to delete
            
        Returns:
            True if the token was found and deleted
        """
        success = mcp_tokens_repo.delete(self._db, token_id)
        if success:
            logger.info(f"Deleted MCP token: id={token_id}")
        return success

