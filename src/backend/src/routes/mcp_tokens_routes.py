"""
FastAPI routes for MCP token management.

Endpoints for creating, listing, and revoking MCP API tokens.
These endpoints require admin permissions.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.common.authorization import require_ontos_admin
from src.common.dependencies import CurrentUserDep, DBSessionDep, AuditManagerDep, AuditCurrentUserDep
from src.common.logging import get_logger
from src.controller.mcp_tokens_manager import MCPTokensManager
from src.models.mcp_tokens import (
    MCPTokenCreate,
    MCPTokenInfo,
    MCPTokenList,
    MCPTokenResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/mcp-tokens", tags=["MCP Tokens"])


def register_routes(app):
    """Register MCP tokens routes with the FastAPI app."""
    app.include_router(router)


# MCP token management is admin-only. Gated on Ontos admin role membership
# (AppRole.is_admin=True), not on settings:ADMIN — see #404 for context.
require_admin = require_ontos_admin


@router.post(
    "",
    response_model=MCPTokenResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create MCP Token",
    description="Create a new MCP API token. The plaintext token is only shown once."
)
async def create_mcp_token(
    request: Request,
    token_data: MCPTokenCreate,
    current_user: AuditCurrentUserDep,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    _: bool = Depends(require_admin)
):
    """Create a new MCP API token."""
    logger.info(f"Creating MCP token: name='{token_data.name}', scopes={token_data.scopes}")
    
    # Get current user email
    created_by = current_user.email if current_user else None
    
    manager = MCPTokensManager(db=db)
    
    try:
        generated = manager.generate_token(
            name=token_data.name,
            scopes=token_data.scopes,
            created_by=created_by,
            expires_days=token_data.expires_days
        )
        
        db.commit()
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='mcp-tokens',
            action='CREATE',
            success=True,
            details={
                'token_id': str(generated.id),
                'token_name': generated.name,
                'scopes': generated.scopes
            }
        )
        
        logger.info(f"Created MCP token: id={generated.id}, name='{generated.name}'")
        
        return MCPTokenResponse(
            id=generated.id,
            name=generated.name,
            token=generated.token,
            scopes=generated.scopes,
            created_at=generated.created_at,
            expires_at=generated.expires_at
        )
        
    except Exception as e:
        logger.error(f"Error creating MCP token: {e}", exc_info=True)
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create token: {str(e)}"
        )


@router.get(
    "",
    response_model=MCPTokenList,
    summary="List MCP Tokens",
    description="List all MCP API tokens (without revealing the actual tokens)."
)
async def list_mcp_tokens(
    request: Request,
    db: DBSessionDep,
    include_inactive: bool = False,
    _: bool = Depends(require_admin)
):
    """List all MCP API tokens."""
    logger.debug(f"Listing MCP tokens (include_inactive={include_inactive})")
    
    manager = MCPTokensManager(db=db)
    
    tokens = manager.list_tokens(include_inactive=include_inactive)
    
    token_infos = [
        MCPTokenInfo(
            id=t.id,
            name=t.name,
            scopes=t.scopes or [],
            created_by=t.created_by,
            created_at=t.created_at,
            last_used_at=t.last_used_at,
            expires_at=t.expires_at,
            is_active=t.is_active,
            is_expired=t.is_expired
        )
        for t in tokens
    ]
    
    return MCPTokenList(tokens=token_infos, total=len(token_infos))


@router.get(
    "/{token_id}",
    response_model=MCPTokenInfo,
    summary="Get MCP Token",
    description="Get information about a specific MCP API token."
)
async def get_mcp_token(
    token_id: UUID,
    db: DBSessionDep,
    _: bool = Depends(require_admin)
):
    """Get information about a specific MCP token."""
    manager = MCPTokensManager(db=db)
    
    token = manager.get_token(token_id)
    
    if not token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token {token_id} not found"
        )
    
    return MCPTokenInfo(
        id=token.id,
        name=token.name,
        scopes=token.scopes or [],
        created_by=token.created_by,
        created_at=token.created_at,
        last_used_at=token.last_used_at,
        expires_at=token.expires_at,
        is_active=token.is_active,
        is_expired=token.is_expired
    )


@router.delete(
    "/{token_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke MCP Token",
    description="Revoke an MCP API token, making it inactive."
)
async def revoke_mcp_token(
    request: Request,
    token_id: UUID,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(require_admin)
):
    """Revoke an MCP API token."""
    logger.info(f"Revoking MCP token: id={token_id}")
    
    manager = MCPTokensManager(db=db)
    
    # Get token info before revoking for audit
    token = manager.get_token(token_id)
    token_name = token.name if token else 'unknown'
    
    success = manager.revoke_token(token_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token {token_id} not found"
        )
    
    db.commit()
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='mcp-tokens',
        action='REVOKE',
        success=True,
        details={'token_id': str(token_id), 'token_name': token_name}
    )
    
    logger.info(f"Revoked MCP token: id={token_id}")


@router.delete(
    "/{token_id}/permanent",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete MCP Token",
    description="Permanently delete an MCP API token."
)
async def delete_mcp_token(
    request: Request,
    token_id: UUID,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    _: bool = Depends(require_admin)
):
    """Permanently delete an MCP API token."""
    logger.info(f"Deleting MCP token: id={token_id}")
    
    manager = MCPTokensManager(db=db)
    
    # Get token info before deleting for audit
    token = manager.get_token(token_id)
    token_name = token.name if token else 'unknown'
    
    success = manager.delete_token(token_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Token {token_id} not found"
        )
    
    db.commit()
    
    audit_manager.log_action(
        db=db,
        username=current_user.username if current_user else 'unknown',
        ip_address=request.client.host if request.client else None,
        feature='mcp-tokens',
        action='DELETE',
        success=True,
        details={'token_id': str(token_id), 'token_name': token_name}
    )
    
    logger.info(f"Deleted MCP token: id={token_id}")

