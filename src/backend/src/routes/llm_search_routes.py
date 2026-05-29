"""
LLM Search Routes

API endpoints for conversational LLM search functionality.

Note: These routes do not use PermissionChecker, following the pattern of the
existing /api/search endpoint. Access control is handled internally by the
LLM tools which filter results based on user permissions.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.common.dependencies import (
    DBSessionDep,
    AuditManagerDep,
    AuditCurrentUserDep,
    CurrentUserDep
)
from src.common.workspace_client import get_obo_workspace_client
from src.models.llm_search import (
    ChatMessageCreate, ChatResponse, ConversationSession,
    SessionSummary, LLMSearchStatus
)
from src.models.users import UserInfo
from src.controller.llm_search_manager import LLMSearchManager

from src.common.logging import get_logger

logger = get_logger(__name__)


def _derive_effective_role_label(request: Request, user: UserInfo) -> Optional[str]:
    """Derive a single human-readable Ontos role label for the user.

    Strategy:

    1. Pull the ``AuthorizationManager`` + ``SettingsManager`` off
       ``request.app.state`` (the route doesn't take them as
       dependencies — keeping the chat endpoint footprint small).
    2. Intersect ``user.groups`` (lowercase, case-insensitive) with
       the ``assigned_groups`` of each configured app role.
    3. If multiple roles match, join their names with commas in
       declaration order — the prompt is a tone hint, not an authz
       gate, so we don't need to pick a "winner".
    4. Any exception logs and returns ``None`` so the chat call
       proceeds rather than 500ing because of a context glitch.
    """
    try:
        settings_manager = getattr(request.app.state, "settings_manager", None)
        if settings_manager is None:
            return None
        all_roles = settings_manager.list_app_roles()
        if not all_roles:
            return None

        user_groups_lower = set(g.lower() for g in (user.groups or []))
        if not user_groups_lower:
            return None

        matched: List[str] = []
        for role in all_roles:
            role_groups_lower = set(g.lower() for g in (role.assigned_groups or []))
            if user_groups_lower & role_groups_lower:
                matched.append(role.name)

        if not matched:
            return None
        return ", ".join(matched)
    except Exception as e:
        logger.warning(f"Effective-role lookup failed; falling back to role=None: {e}")
        return None

router = APIRouter(prefix="/api/llm-search", tags=["LLM Search"])


# ============================================================================
# Dependency for LLMSearchManager
# ============================================================================

async def get_llm_search_manager(request: Request, db: DBSessionDep) -> LLMSearchManager:
    """Get the LLMSearchManager instance with fresh manager references.
    
    Uses OBO (On-Behalf-Of) workspace client so UC operations run with the
    user's permissions, ensuring proper access control and audit trail.
    """
    from src.common.config import get_settings
    settings = get_settings()
    
    # Always get fresh manager references from app state
    # This ensures we use the properly initialized managers
    data_products_manager = getattr(request.app.state, 'data_products_manager', None)
    data_contracts_manager = getattr(request.app.state, 'data_contracts_manager', None)
    semantic_models_manager = getattr(request.app.state, 'semantic_models_manager', None)
    search_manager = getattr(request.app.state, 'search_manager', None)
    
    # Get OBO workspace client - uses user's token for proper access control
    # Falls back to SP client if OBO token not available (local dev)
    obo_ws_client = get_obo_workspace_client(request, settings)
    
    # Create new instance for each request with current db session
    # (Don't cache because we need fresh db session and OBO client)
    return LLMSearchManager(
        db=db,
        settings=settings,
        data_products_manager=data_products_manager,
        data_contracts_manager=data_contracts_manager,
        semantic_models_manager=semantic_models_manager,
        search_manager=search_manager,
        workspace_client=obo_ws_client
    )


LLMSearchManagerDep = Depends(get_llm_search_manager)


# ============================================================================
# Routes
# ============================================================================

@router.get("/status", response_model=LLMSearchStatus)
async def get_llm_search_status(
    manager: LLMSearchManager = LLMSearchManagerDep
) -> LLMSearchStatus:
    """
    Get the status of LLM search functionality.
    
    Returns whether LLM search is enabled and the configured endpoint.
    """
    return manager.get_status()


@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    message: ChatMessageCreate,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: LLMSearchManager = LLMSearchManagerDep
) -> ChatResponse:
    """
    Send a chat message and receive the assistant's response.

    The assistant can search for data products, glossary terms, costs,
    and execute analytics queries to answer your questions.

    Provide a session_id to continue an existing conversation.

    Phase 3 personalization: ``page_name`` / ``page_url`` / ``feature_id``
    / ``selected_entity`` are picked up from the request body and
    passed to the manager. The user's effective Ontos role(s) are
    derived server-side (NOT from the client) by intersecting the
    user's group membership with role assignments — this is the
    "what the user can actually do today" view that the copilot
    should tailor its tone to.
    """
    success = False
    details = {
        "params": {
            "session_id": message.session_id,
            "message_length": len(message.content),
            "page_name": message.page_name,
        }
    }

    try:
        logger.info(
            f"LLM chat request from user {current_user.email}, "
            f"session={message.session_id}, page={message.page_name}"
        )

        # Derive a single role label by intersecting the user's groups
        # with role assignments via the AuthorizationManager. Multiple
        # roles -> comma-separated; none -> None. The label is purely
        # a tone-of-voice hint to the LLM (not an authz boundary), so
        # we deliberately fail open: any lookup error logs and the
        # request proceeds with role=None.
        role_label = _derive_effective_role_label(request, current_user)

        # ``selected_entity`` is a Pydantic model on the way in; the
        # manager + prompt code expects a plain dict so we dump it
        # here (Pydantic v2 ``model_dump`` returns a dict).
        selected_entity_dict = (
            message.selected_entity.model_dump(exclude_none=True)
            if message.selected_entity is not None
            else None
        )

        # Note: manager already has OBO workspace client from get_llm_search_manager dependency
        response = await manager.chat(
            user_message=message.content,
            user_id=current_user.email,
            session_id=message.session_id,
            debug=message.debug,
            role=role_label,
            page_name=message.page_name,
            page_url=message.page_url,
            feature_id=message.feature_id,
            selected_entity=selected_entity_dict,
        )

        success = True
        details["session_id"] = response.session_id
        details["tool_calls"] = response.tool_calls_executed

        return response
        
    except Exception as e:
        logger.error(f"Error in LLM chat: {e}", exc_info=True)
        details["error"] = str(e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Chat processing failed: {str(e)}"
        )
    finally:
        audit_manager.log_action(
            db=db,
            username=audit_user.username,
            ip_address=audit_user.ip,
            feature="llm-search",
            action="CHAT",
            success=success,
            details=details
        )


@router.get("/sessions", response_model=List[SessionSummary])
async def list_sessions(
    current_user: CurrentUserDep,
    manager: LLMSearchManager = LLMSearchManagerDep
) -> List[SessionSummary]:
    """
    List conversation sessions for the current user.
    
    Sessions are ordered by last update time (most recent first).
    """
    return manager.list_sessions(current_user.email)


@router.get("/sessions/{session_id}", response_model=ConversationSession)
async def get_session(
    session_id: str,
    current_user: CurrentUserDep,
    manager: LLMSearchManager = LLMSearchManagerDep
) -> ConversationSession:
    """
    Get a specific conversation session with full message history.
    """
    session = manager.get_session(session_id, current_user.email)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )
    return session


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    audit_manager: AuditManagerDep,
    audit_user: AuditCurrentUserDep,
    manager: LLMSearchManager = LLMSearchManagerDep
):
    """
    Delete a conversation session.
    """
    success = manager.delete_session(session_id, current_user.email)
    
    audit_manager.log_action(
        db=db,
        username=audit_user.username,
        ip_address=audit_user.ip,
        feature="llm-search",
        action="DELETE_SESSION",
        success=success,
        details={"session_id": session_id}
    )
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Session not found"
        )


# ============================================================================
# Route Registration
# ============================================================================

def register_routes(app):
    """Register LLM search routes with the FastAPI app."""
    app.include_router(router)

