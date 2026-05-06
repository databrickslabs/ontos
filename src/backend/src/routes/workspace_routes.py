from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Any, Dict, List, Optional

from databricks.sdk.errors import PermissionDenied, DatabricksError

from src.common.dependencies import WorkspaceManagerDep
from src.controller.workspace_manager import WorkspaceManager
from src.models.workspace import WorkspaceAsset
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel

from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Workspace"])

@router.get("/workspace/assets/search", response_model=List[WorkspaceAsset])
async def search_workspace_assets(
    asset_type: str = Query(..., description="Type of asset to search (e.g., 'table', 'notebook', 'job')"),
    search_term: Optional[str] = Query(None, description="Search term to filter asset names/identifiers"),
    limit: int = Query(25, description="Maximum number of results to return", ge=1, le=100),
    manager: WorkspaceManager = Depends(WorkspaceManagerDep),
    _: bool = Depends(PermissionChecker('catalog-commander', FeatureAccessLevel.READ_ONLY))
):
    """
    Search for Databricks workspace assets based on type and search term.
    
    Supports searching for:
    - tables: Unity Catalog tables across available catalogs/schemas
    - notebooks: Notebooks in /Users, /Repos, and /Shared paths
    - jobs: Databricks jobs
    - views, functions, models: Placeholder (not yet implemented)
    """
    logger.info(f"Searching for workspace assets: type={asset_type}, term={search_term}, limit={limit}")

    try:
        # Delegate to manager
        results = manager.search_workspace_assets(
            asset_type=asset_type,
            search_term=search_term,
            limit=limit
        )
        return results
        
    except ValueError as e:
        # Invalid input (e.g., unsupported asset type, workspace not configured)
        logger.warning(f"Invalid request for workspace asset search: {e}")
        raise HTTPException(status_code=400, detail=str(e))
        
    except PermissionDenied as e:
        # Databricks permissions issue
        logger.error(f"Permission denied during workspace asset search: {e}")
        raise HTTPException(
            status_code=403,
            detail="Permission denied to access requested Databricks resources."
        )
        
    except DatabricksError as e:
        # Other Databricks SDK errors
        logger.error(f"Databricks error during workspace asset search: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail="Error communicating with Databricks workspace."
        )
        
    except Exception as e:
        # Unexpected errors
        logger.exception(f"Unexpected error searching workspace assets: {e}")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while searching workspace assets."
        )

@router.get("/workspace/groups")
async def list_workspace_groups(
    search: Optional[str] = Query(None, description="Optional substring filter on displayName (case-insensitive)"),
    limit: int = Query(200, description="Max groups to return", ge=1, le=1000),
    _: bool = Depends(PermissionChecker('data-products', FeatureAccessLevel.READ_ONLY)),
):
    """List Databricks workspace groups for use in pickers.

    Used by:
      * the data product publish form's ``consumer_principals`` multi-select
        (each selected group becomes a ``{type: "group", value: <name>}``
        principal)
      * the subscribe dialog's "for a group I'm part of" picker

    Returns ``[{id, display_name}, ...]``. Best-effort: SCIM directory may
    contain thousands of groups in large workspaces, so an optional
    ``search`` substring narrows the list; otherwise the first ``limit``
    groups are returned alphabetically.
    """
    try:
        from src.common.workspace_client import get_workspace_client
        ws = get_workspace_client()
    except Exception as e:
        logger.warning(f"Workspace client unavailable for /workspace/groups: {e}")
        return []

    try:
        # Build SCIM filter when a search term is provided. SCIM supports
        # `co` (contains) on displayName.
        kwargs: Dict[str, Any] = {"attributes": "displayName,id"}
        if search:
            # Escape any double-quotes in the search term to keep the filter valid.
            safe = search.replace('"', '\\"')
            kwargs["filter"] = f'displayName co "{safe}"'
        try:
            iterator = ws.groups.list(**kwargs)
        except TypeError:
            # Older SDK signatures may not accept all kwargs — degrade gracefully
            iterator = ws.groups.list()

        out: List[Dict[str, Any]] = []
        for grp in iterator:
            display_name = getattr(grp, 'display_name', None) or getattr(grp, 'displayName', None)
            grp_id = getattr(grp, 'id', None)
            if not display_name:
                continue
            out.append({"id": grp_id, "display_name": display_name})
            if len(out) >= limit:
                break
        # Stable order so the picker is predictable
        out.sort(key=lambda g: (g.get("display_name") or "").lower())
        return out
    except PermissionDenied as e:
        logger.error(f"Permission denied listing workspace groups: {e}")
        raise HTTPException(status_code=403, detail="Permission denied to list workspace groups.")
    except DatabricksError as e:
        logger.error(f"Databricks error listing workspace groups: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error listing workspace groups.")
    except Exception as e:
        logger.exception(f"Unexpected error listing workspace groups: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error listing workspace groups.")


def register_routes(app):
    """Register routes with the FastAPI app."""
    app.include_router(router)
    logger.info("Workspace routes registered")