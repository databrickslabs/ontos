"""
Data Catalog / Data Dictionary Routes

Provides REST API endpoints for:
- Column dictionary browsing (paginated, multi-source)
- Column search (full-field, uncapped)
- Hierarchy filter values
- Table details
- Lineage visualization
- Impact analysis
"""

from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Request, Query

from databricks.sdk import WorkspaceClient
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.workspace_client import get_obo_workspace_client
from src.common.config import get_settings, Settings
from src.common.dependencies import DBSessionDep
from src.controller.data_catalog_manager import DataCatalogManager
from src.controller.data_contracts_manager import DataContractsManager
from src.models.data_catalog import (
    DataDictionaryResponse,
    ColumnSearchResponse,
    TableListResponse,
    TableInfo,
    HierarchyFilters,
    LineageGraph,
    ImpactAnalysis,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/data-catalog", tags=["Data Catalog"])

DATA_CATALOG_FEATURE_ID = "data-catalog"


def _get_manager(
    request: Request,
    db: DBSessionDep,
    obo_client: WorkspaceClient = Depends(get_obo_workspace_client),
) -> DataCatalogManager:
    """Helper to create manager with all dependencies."""
    settings = getattr(request.app.state, 'settings', None)
    contracts_manager = getattr(request.app.state, 'data_contracts_manager', None)

    return DataCatalogManager(
        obo_client=obo_client,
        db_session=db,
        contracts_manager=contracts_manager,
        settings=settings,
    )


# =============================================================================
# Column Dictionary Endpoints
# =============================================================================

@router.get(
    "/columns",
    response_model=DataDictionaryResponse,
    dependencies=[Depends(PermissionChecker(DATA_CATALOG_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
async def get_all_columns(
    request: Request,
    db: DBSessionDep,
    catalog: Optional[str] = Query(None, description="Filter to specific catalog"),
    schema: Optional[str] = Query(None, description="Filter to specific schema"),
    table: Optional[str] = Query(None, description="Filter to specific table (FQN or name)"),
    asset_type: Optional[str] = Query(None, description="Filter by asset type (Table, View, Dataset, CONTRACT)"),
    system: Optional[str] = Query(None, description="Filter by parent System name"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    obo_client: WorkspaceClient = Depends(get_obo_workspace_client),
) -> DataDictionaryResponse:
    """
    Get paginated columns from registered Data Contracts and Assets.

    Merges columns from both sources, deduplicates, and applies filters.
    """
    try:
        manager = _get_manager(request, db, obo_client)
        return manager.get_all_columns(
            catalog_filter=catalog,
            schema_filter=schema,
            table_filter=table,
            asset_type_filter=asset_type,
            system_filter=system,
            offset=offset,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Error getting columns: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch columns: {str(e)}")


@router.get(
    "/columns/search",
    response_model=ColumnSearchResponse,
    dependencies=[Depends(PermissionChecker(DATA_CATALOG_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
async def search_columns(
    request: Request,
    db: DBSessionDep,
    q: str = Query(..., min_length=1, description="Search query"),
    catalog: Optional[str] = Query(None, description="Filter to specific catalog"),
    schema: Optional[str] = Query(None, description="Filter to specific schema"),
    table: Optional[str] = Query(None, description="Filter to specific table (FQN or name)"),
    asset_type: Optional[str] = Query(None, description="Filter by asset type"),
    system: Optional[str] = Query(None, description="Filter by parent System name"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    limit: int = Query(50, ge=1, le=500, description="Page size"),
    obo_client: WorkspaceClient = Depends(get_obo_workspace_client),
) -> ColumnSearchResponse:
    """
    Search columns across all fields (name, description, business terms, parent table, etc.).

    Searches the full dataset with no hidden cap.
    """
    try:
        manager = _get_manager(request, db, obo_client)
        return manager.search_columns(
            query=q,
            catalog_filter=catalog,
            schema_filter=schema,
            table_filter=table,
            asset_type_filter=asset_type,
            system_filter=system,
            offset=offset,
            limit=limit,
        )
    except Exception as e:
        logger.error(f"Error searching columns: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to search columns: {str(e)}")


# =============================================================================
# Hierarchy / Filter Values
# =============================================================================

@router.get(
    "/hierarchy",
    response_model=HierarchyFilters,
    dependencies=[Depends(PermissionChecker(DATA_CATALOG_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
async def get_hierarchy_filters(
    request: Request,
    db: DBSessionDep,
    obo_client: WorkspaceClient = Depends(get_obo_workspace_client),
) -> HierarchyFilters:
    """
    Get available filter values for the faceted filter UI.

    Returns distinct asset types, systems, catalogs, and schemas.
    """
    try:
        manager = _get_manager(request, db, obo_client)
        return manager.get_hierarchy_filters()
    except Exception as e:
        logger.error(f"Error getting hierarchy filters: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get hierarchy filters: {str(e)}")


# =============================================================================
# Table Endpoints
# =============================================================================

@router.get(
    "/tables",
    response_model=TableListResponse,
    dependencies=[Depends(PermissionChecker(DATA_CATALOG_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
async def get_table_list(
    request: Request,
    db: DBSessionDep,
    catalog: Optional[str] = Query(None, description="Filter to specific catalog"),
    schema: Optional[str] = Query(None, description="Filter to specific schema"),
    obo_client: WorkspaceClient = Depends(get_obo_workspace_client),
) -> TableListResponse:
    """Get list of tables/schema objects for the filter dropdown."""
    try:
        manager = _get_manager(request, db, obo_client)
        return manager.get_table_list(catalog_filter=catalog, schema_filter=schema)
    except Exception as e:
        logger.error(f"Error getting table list: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get table list: {str(e)}")


@router.get(
    "/tables/{table_fqn:path}",
    response_model=TableInfo,
    dependencies=[Depends(PermissionChecker(DATA_CATALOG_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
async def get_table_details(
    request: Request,
    db: DBSessionDep,
    table_fqn: str,
    obo_client: WorkspaceClient = Depends(get_obo_workspace_client),
) -> TableInfo:
    """Get full table details including all columns."""
    try:
        manager = _get_manager(request, db, obo_client)
        result = manager.get_table_details(table_fqn)
        if not result:
            raise HTTPException(status_code=404, detail=f"Table not found: {table_fqn}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting table details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get table details: {str(e)}")


# =============================================================================
# Lineage Endpoints
# =============================================================================

@router.get(
    "/tables/{table_fqn:path}/lineage",
    response_model=LineageGraph,
    dependencies=[Depends(PermissionChecker(DATA_CATALOG_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
async def get_table_lineage(
    request: Request,
    db: DBSessionDep,
    table_fqn: str,
    direction: str = Query("both", regex="^(upstream|downstream|both)$"),
    obo_client: WorkspaceClient = Depends(get_obo_workspace_client),
) -> LineageGraph:
    """Get lineage graph for a table."""
    try:
        manager = _get_manager(request, db, obo_client)
        return manager.get_table_lineage(table_fqn, direction)
    except Exception as e:
        logger.error(f"Error getting lineage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get lineage: {str(e)}")


@router.get(
    "/tables/{table_fqn:path}/columns/{column_name}/lineage",
    response_model=LineageGraph,
    dependencies=[Depends(PermissionChecker(DATA_CATALOG_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
async def get_column_lineage(
    request: Request,
    db: DBSessionDep,
    table_fqn: str,
    column_name: str,
    direction: str = Query("both", regex="^(upstream|downstream|both)$"),
    obo_client: WorkspaceClient = Depends(get_obo_workspace_client),
) -> LineageGraph:
    """Get column-level lineage."""
    try:
        manager = _get_manager(request, db, obo_client)
        return manager.get_column_lineage(table_fqn, column_name, direction)
    except Exception as e:
        logger.error(f"Error getting column lineage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get column lineage: {str(e)}")


# =============================================================================
# Impact Analysis
# =============================================================================

@router.get(
    "/tables/{table_fqn:path}/impact",
    response_model=ImpactAnalysis,
    dependencies=[Depends(PermissionChecker(DATA_CATALOG_FEATURE_ID, FeatureAccessLevel.READ_ONLY))]
)
async def get_table_impact(
    request: Request,
    db: DBSessionDep,
    table_fqn: str,
    column: Optional[str] = Query(None, description="Optional column for column-level impact"),
    obo_client: WorkspaceClient = Depends(get_obo_workspace_client),
) -> ImpactAnalysis:
    """Get impact analysis for changing a table or column."""
    try:
        manager = _get_manager(request, db, obo_client)
        return manager.get_impact_analysis(table_fqn, column)
    except Exception as e:
        logger.error(f"Error getting impact analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get impact analysis: {str(e)}")


# =============================================================================
# Route Registration
# =============================================================================

def register_routes(app):
    """Register data catalog routes with the FastAPI app."""
    app.include_router(router)
    logger.info("Data Catalog routes registered")
