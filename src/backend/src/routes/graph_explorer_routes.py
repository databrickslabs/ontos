"""
FastAPI routes for Graph Explorer.

All operations go through Databricks Statement Execution API.
The table name is passed as a query parameter or in the request body.
"""

from typing import Optional
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query, Request

from src.common.config import Settings, get_settings
from src.common.logging import get_logger
from src.common.workspace_client import get_workspace_client
from src.controller.graph_explorer_manager import GraphExplorerManager, DEFAULT_TABLE_NAME
from src.models.graph_explorer import (
    DeleteEdgeRequest,
    DeleteNodeRequest,
    EnsureTableResponse,
    GraphDataResponse,
    GraphQueryRequest,
    GraphQueryResponse,
    LlmConfigResponse,
    SaveGraphRequest,
    SaveGraphResponse,
    UpdateNodeRequest,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/graph-explorer", tags=["graph-explorer"])


def get_graph_explorer_manager(request: Request) -> GraphExplorerManager:
    """Get the GraphExplorerManager from app state."""
    return request.app.state.graph_explorer_manager


def _get_ws_and_warehouse(settings: Settings):
    """Get workspace client and warehouse_id."""
    ws_client = get_workspace_client()
    warehouse_id = settings.DATABRICKS_WAREHOUSE_ID
    if not warehouse_id:
        raise HTTPException(status_code=500, detail="DATABRICKS_WAREHOUSE_ID not configured")
    return ws_client, warehouse_id


@router.get("", response_model=GraphDataResponse)
async def get_graph_data(
    table_name: str = Query(default=DEFAULT_TABLE_NAME, alias="tableName"),
    manager: GraphExplorerManager = Depends(get_graph_explorer_manager),
    settings: Settings = Depends(get_settings),
):
    """Read graph data from a Databricks table."""
    try:
        ws_client, warehouse_id = _get_ws_and_warehouse(settings)
        # Ensure the table exists first
        manager.ensure_table_exists(ws_client, table_name, warehouse_id)
        data = manager.get_graph_data(ws_client, table_name, warehouse_id)
        return data
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error reading graph data: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading graph data: {str(e)}")


@router.post("/save", response_model=SaveGraphResponse)
async def save_graph_data(
    request: SaveGraphRequest,
    manager: GraphExplorerManager = Depends(get_graph_explorer_manager),
    settings: Settings = Depends(get_settings),
):
    """Write new nodes and edges to a Databricks table."""
    try:
        ws_client, warehouse_id = _get_ws_and_warehouse(settings)
        manager.ensure_table_exists(ws_client, request.tableName, warehouse_id)

        nodes_dicts = [n.model_dump() for n in request.nodes]
        edges_dicts = [e.model_dump() for e in request.edges]

        result = manager.write_nodes_and_edges(
            ws_client, request.tableName, warehouse_id, nodes_dicts, edges_dicts,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error saving graph data: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving graph data: {str(e)}")


@router.post("/ensure-table", response_model=EnsureTableResponse)
async def ensure_table(
    table_name: str = Query(default=DEFAULT_TABLE_NAME, alias="tableName"),
    manager: GraphExplorerManager = Depends(get_graph_explorer_manager),
    settings: Settings = Depends(get_settings),
):
    """Ensure the graph table exists, creating it if necessary."""
    try:
        ws_client, warehouse_id = _get_ws_and_warehouse(settings)
        manager.ensure_table_exists(ws_client, table_name, warehouse_id)
        return {"tableName": table_name, "status": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error ensuring table: {e}")
        raise HTTPException(status_code=500, detail=f"Error ensuring table: {str(e)}")


@router.delete("/node")
async def delete_node(
    request: DeleteNodeRequest,
    manager: GraphExplorerManager = Depends(get_graph_explorer_manager),
    settings: Settings = Depends(get_settings),
):
    """Delete a node and its connected edges from the Databricks table."""
    try:
        ws_client, warehouse_id = _get_ws_and_warehouse(settings)
        manager.delete_node(ws_client, request.tableName, warehouse_id, request.nodeId)
        return {"status": "deleted", "nodeId": request.nodeId}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting node: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting node: {str(e)}")


@router.delete("/edge")
async def delete_edge(
    request: DeleteEdgeRequest,
    manager: GraphExplorerManager = Depends(get_graph_explorer_manager),
    settings: Settings = Depends(get_settings),
):
    """Delete an edge from the Databricks table."""
    try:
        ws_client, warehouse_id = _get_ws_and_warehouse(settings)
        manager.delete_edge(
            ws_client, request.tableName, warehouse_id,
            request.sourceId, request.targetId, request.relationshipType,
        )
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting edge: {e}")
        raise HTTPException(status_code=500, detail=f"Error deleting edge: {str(e)}")


@router.put("/node")
async def update_node(
    request: UpdateNodeRequest,
    manager: GraphExplorerManager = Depends(get_graph_explorer_manager),
    settings: Settings = Depends(get_settings),
):
    """Update a node in the Databricks table."""
    try:
        ws_client, warehouse_id = _get_ws_and_warehouse(settings)
        manager.update_node(
            ws_client, request.tableName, warehouse_id,
            request.nodeId, request.label, request.type, request.properties,
        )
        return {"status": "updated", "nodeId": request.nodeId}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating node: {e}")
        raise HTTPException(status_code=500, detail=f"Error updating node: {str(e)}")


@router.get("/llm-config", response_model=LlmConfigResponse)
async def get_llm_config(
    manager: GraphExplorerManager = Depends(get_graph_explorer_manager),
):
    """Return the current LLM configuration status for the query panel."""
    return manager.get_llm_config()


@router.post("/query", response_model=GraphQueryResponse)
async def execute_graph_query(
    request: GraphQueryRequest,
    manager: GraphExplorerManager = Depends(get_graph_explorer_manager),
    settings: Settings = Depends(get_settings),
):
    """Translate a Cypher/Gremlin query to SQL via LLM and execute it."""
    try:
        ws_client, warehouse_id = _get_ws_and_warehouse(settings)
        table_name = request.tableName or DEFAULT_TABLE_NAME
        result = manager.execute_graph_query(
            ws_client=ws_client,
            warehouse_id=warehouse_id,
            query=request.query,
            language=request.language,
            table_name=table_name,
            override_sql=request.sql,
        )
        return result
    except RuntimeError as e:
        # LLM or SQL execution error — return as a structured error, not 500
        return GraphQueryResponse(
            success=False,
            sql="",
            language=request.language,
            originalQuery=request.query,
            message=str(e),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error executing graph query: {e}")
        raise HTTPException(status_code=500, detail=f"Error executing graph query: {str(e)}")


def register_routes(app: FastAPI):
    """Register graph explorer routes with the FastAPI app."""
    app.include_router(router)
