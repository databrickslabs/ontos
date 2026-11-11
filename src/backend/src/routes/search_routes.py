from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from src.controller.search_manager import SearchManager
# Import the search interfaces
from src.common.search_interfaces import SearchableAsset, SearchIndexItem
# Import Permission Checker class (not the non-existent getter)
from src.common.authorization import PermissionChecker, resolve_effective_permissions
# Import correct dependencies using Annotated types from dependencies.py
from src.common.dependencies import (
    CurrentUserDep, 
    AuthorizationManagerDep,
    SettingsManagerDep,
    AuditManagerDep,
    AuditCurrentUserDep,
    DBSessionDep,
)

# Configure logging
from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Search"])

# --- Manager Dependency ---
# Remove unused global variable
# _search_manager_instance: Optional[SearchManager] = None

async def get_search_manager(
    request: Request # Inject Request object
) -> SearchManager:
    """Dependency to retrieve the SearchManager singleton instance from app.state."""
    search_manager = getattr(request.app.state, 'search_manager', None)
    if search_manager is None:
        # This should not happen if startup was successful
        logger.critical("SearchManager instance not found in app.state!")
        raise HTTPException(status_code=500, detail="Search service is not available.")
    return search_manager

# --- Routes ---
@router.get("/search", response_model=List[SearchIndexItem])
async def search_items(
    search_term: str,
    request: Request,
    # Reorder parameters: non-defaults first
    auth_manager: AuthorizationManagerDep,
    current_user: CurrentUserDep,
    settings_manager: SettingsManagerDep,
    manager: SearchManager = Depends(get_search_manager) 
) -> List[SearchIndexItem]:
    """Search across indexed items, filtered by user permissions."""
    if not search_term:
        raise HTTPException(status_code=400, detail="Query parameter (search_term) is required")
    try:
        # The same permissions every check uses: applied role override, else groups,
        # email and team roles (#1245)
        effective_permissions = resolve_effective_permissions(
            request, current_user.email, current_user.groups or [], auth_manager,
        )
        results = manager.search(
            search_term, auth_manager, current_user, effective_permissions=effective_permissions,
        )
        return results
    except Exception as e:
        logger.exception(f"Error during search for query '{search_term}': {e}")
        raise HTTPException(status_code=500, detail="Search failed")

@router.post("/search/rebuild-index", status_code=202)
async def rebuild_search_index(
    request: Request,
    db: DBSessionDep,
    audit_manager: AuditManagerDep,
    current_user: AuditCurrentUserDep,
    manager: SearchManager = Depends(get_search_manager)
):
    """Triggers a rebuild of the search index."""
    try:
        # In a real app, this might be a background task
        manager.build_index()
        
        audit_manager.log_action(
            db=db,
            username=current_user.username if current_user else 'unknown',
            ip_address=request.client.host if request.client else None,
            feature='search',
            action='REBUILD_INDEX',
            success=True,
            details={}
        )
        
        return {"message": "Search index rebuild initiated."}
    except Exception as e:
        logger.exception(f"Error during index rebuild: {e}")
        raise HTTPException(status_code=500, detail="Index rebuild failed")

# --- Register Function ---
# Removed unused function argument `app` as it's not needed for `register_routes`
def register_routes(app):
    app.include_router(router)
    logger.info("Search routes registered")
