"""API routes for LLM-based ontology generation.

Both POST /generate and POST /generate-from-connection are async: they
return HTTP 202 with a run_id immediately, and the actual LLM work runs
in a background thread.  Clients poll GET /runs/{run_id} for progress.
"""

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from src.controller.ontology_generator_manager import OntologyGeneratorManager
from src.models.ontology_generator import (
    AgentStepResponse,
    GenerateFromConnectionRequest,
    GenerateOntologyRequest,
    GenerateOntologyResponse,
    GenerationRunDetail,
    GenerationRunStatus,
    GenerationRunSummary,
    OntologyClassResponse,
    OntologyInfoResponse,
    OntologyPropertyResponse,
    RunListResponse,
    RunParams,
    SaveToCollectionRequest,
    SaveToCollectionResponse,
    StartRunResponse,
)
from src.common.authorization import PermissionChecker, is_user_feature_admin
from src.common.features import FeatureAccessLevel
from src.common.dependencies import (
    DBSessionDep,
    AuditManagerDep,
    AuditCurrentUserDep,
    OntologyGeneratorManagerDep,
)
from src.common.manager_dependencies import (
    get_ontology_generator_manager,
    get_semantic_models_manager,
)
from src.common.workspace_client import get_obo_workspace_client
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/ontology", tags=["Ontology Generator"])
FEATURE_ID = "ontology"


def _get_user_token(request: Request) -> Optional[str]:
    """Extract the OBO token from request headers (None in local dev)."""
    return request.headers.get("x-forwarded-access-token")


# ------------------------------------------------------------------
# Helpers to convert DB rows to response models
# ------------------------------------------------------------------

def _run_to_params(run) -> RunParams:
    return RunParams(
        connection_id=run.connection_id,
        connection_name=run.connection_name,
        path_count=len(run.selected_paths) if run.selected_paths else 0,
        guidelines=(run.guidelines or "")[:200],
        base_uri=run.base_uri or "",
        options=run.options or {},
    )


def _run_to_summary(run) -> GenerationRunSummary:
    return GenerationRunSummary(
        run_id=run.id,
        status=GenerationRunStatus(run.status),
        progress_message=run.progress_message,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        params=_run_to_params(run),
        step_count=len(run.steps) if run.steps else 0,
    )


def _run_to_detail(run) -> GenerationRunDetail:
    steps = []
    if run.steps:
        for s in run.steps:
            steps.append(AgentStepResponse(
                step_type=s.get("step_type", ""),
                content=s.get("content", ""),
                tool_name=s.get("tool_name", ""),
                duration_ms=s.get("duration_ms", 0),
            ))

    result_model = None
    if run.result:
        try:
            result_model = GenerateOntologyResponse(**run.result)
        except Exception:
            logger.warning("Failed to parse stored result for run %s", run.id)

    return GenerationRunDetail(
        run_id=run.id,
        status=GenerationRunStatus(run.status),
        progress_message=run.progress_message,
        error=run.error,
        created_at=run.created_at,
        updated_at=run.updated_at,
        completed_at=run.completed_at,
        params=_run_to_params(run),
        steps=steps,
        result=result_model,
    )


# ------------------------------------------------------------------
# Async generation endpoints
# ------------------------------------------------------------------

@router.post(
    "/generate",
    response_model=StartRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start async OWL ontology generation from table metadata",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def generate_ontology(
    request: Request,
    body: GenerateOntologyRequest,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologyGeneratorManagerDep = None,
):
    """Kick off an async ontology generation run and return the run_id."""
    success = False
    details = {
        "table_count": len(body.metadata.tables),
        "guidelines_length": len(body.guidelines),
        "base_uri": body.base_uri,
    }

    try:
        metadata_dict = {"tables": [t.model_dump() for t in body.metadata.tables]}
        options = {
            "includeDataProperties": body.include_data_properties,
            "includeRelationships": body.include_relationships,
            "includeInheritance": body.include_inheritance,
        }

        run_id = manager.start_run(
            db=db,
            user_id=current_user.email or current_user.username or "unknown",
            metadata=metadata_dict,
            guidelines=body.guidelines,
            options=options,
            base_uri=body.base_uri,
            user_token=_get_user_token(request),
        )

        success = True
        details["run_id"] = run_id
        return StartRunResponse(run_id=run_id, status=GenerationRunStatus.PENDING)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except Exception as e:
        logger.exception("Failed to start ontology generation run")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start generation: {e}",
        )
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="START_ONTOLOGY_GENERATION",
            success=success,
            details=details,
        )


@router.post(
    "/generate-from-connection",
    response_model=StartRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start async OWL ontology generation from a connection",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def generate_from_connection(
    request: Request,
    body: GenerateFromConnectionRequest,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologyGeneratorManagerDep = None,
):
    """Resolve table metadata from a connection, then start an async generation run."""
    success = False
    details = {
        "connection_id": body.connection_id,
        "selected_count": len(body.selected_paths),
        "guidelines_length": len(body.guidelines),
    }

    try:
        from src.controller.connections_manager import ConnectionsManager

        ws = get_obo_workspace_client(request)
        conn_mgr = ConnectionsManager(db=db, workspace_client=ws)

        connector = conn_mgr.get_connector_for_connection(UUID(body.connection_id))
        if connector is None:
            raise HTTPException(status_code=404, detail="Connection not found")

        tables_metadata = OntologyGeneratorManager.resolve_tables_from_connector(
            connector, body.selected_paths,
        )

        if not tables_metadata:
            raise HTTPException(
                status_code=400,
                detail="No tables with schema found in the selected paths",
            )

        details["resolved_tables"] = len(tables_metadata)

        options = {
            "includeDataProperties": body.include_data_properties,
            "includeRelationships": body.include_relationships,
            "includeInheritance": body.include_inheritance,
        }

        connection = conn_mgr.get_connection(UUID(body.connection_id))
        conn_name = connection.name if connection else body.connection_id

        run_id = manager.start_run(
            db=db,
            user_id=current_user.email or current_user.username or "unknown",
            metadata={"tables": tables_metadata},
            guidelines=body.guidelines,
            options=options,
            base_uri=body.base_uri,
            user_token=_get_user_token(request),
            connection_id=body.connection_id,
            connection_name=conn_name,
            selected_paths=body.selected_paths,
        )

        success = True
        details["run_id"] = run_id
        return StartRunResponse(run_id=run_id, status=GenerationRunStatus.PENDING)

    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to start ontology generation from connection")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to start generation: {e}",
        )
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="START_ONTOLOGY_GENERATION_FROM_CONNECTION",
            success=success,
            details=details,
        )


# ------------------------------------------------------------------
# Run management endpoints
# ------------------------------------------------------------------

@router.get(
    "/runs",
    response_model=RunListResponse,
    summary="List recent ontology generation runs",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
async def list_runs(
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologyGeneratorManagerDep = None,
    limit: int = 50,
):
    user_id = current_user.email or current_user.username or "unknown"
    is_admin = await is_user_feature_admin(
        current_user.email, current_user.groups, FEATURE_ID, request,
    )

    if is_admin:
        rows = manager.list_all_runs(db, limit=limit)
    else:
        rows = manager.list_runs(db, user_id, limit=limit)

    return RunListResponse(runs=[_run_to_summary(r) for r in rows])


@router.get(
    "/runs/{run_id}",
    response_model=GenerationRunDetail,
    summary="Get full details of a generation run",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
async def get_run(
    run_id: str,
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologyGeneratorManagerDep = None,
):
    user_id = current_user.email or current_user.username or "unknown"
    is_admin = await is_user_feature_admin(
        current_user.email, current_user.groups, FEATURE_ID, request,
    )

    if is_admin:
        run = manager.get_run(db, run_id)
    else:
        run = manager.get_run_for_user(db, run_id, user_id)

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # Refresh to pick up latest background-thread updates
    db.refresh(run)
    return _run_to_detail(run)


@router.delete(
    "/runs/{run_id}",
    summary="Cancel a running generation or delete a finished run",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
async def delete_run(
    run_id: str,
    request: Request,
    db: DBSessionDep = None,
    current_user: AuditCurrentUserDep = None,
    manager: OntologyGeneratorManagerDep = None,
):
    user_id = current_user.email or current_user.username or "unknown"
    is_admin = await is_user_feature_admin(
        current_user.email, current_user.groups, FEATURE_ID, request,
    )

    if is_admin:
        run = manager.get_run(db, run_id)
    else:
        run = manager.get_run_for_user(db, run_id, user_id)

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    if run.status in ('pending', 'running'):
        manager.cancel_run(run_id)
        from src.repositories.ontology_generation_runs_repository import ontology_generation_runs_repo
        from datetime import datetime, timezone as tz
        ontology_generation_runs_repo.update_status(
            db, run_id, 'cancelled',
            progress_message='Cancelled',
            error='Cancelled by user',
            completed_at=datetime.now(tz.utc),
        )
        db.commit()
        return {"detail": "Run cancelled", "run_id": run_id}

    manager.delete_run(db, run_id)
    db.commit()
    return {"detail": "Run deleted", "run_id": run_id}


# ------------------------------------------------------------------
# Save to collection (unchanged — synchronous)
# ------------------------------------------------------------------

@router.post(
    "/save-to-collection",
    response_model=SaveToCollectionResponse,
    summary="Save generated OWL Turtle as a new Concept Collection",
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE))],
)
def save_to_collection(
    request: Request,
    body: SaveToCollectionRequest,
    db: DBSessionDep = None,
    audit_manager: AuditManagerDep = None,
    current_user: AuditCurrentUserDep = None,
):
    """Create a new Concept Collection of type 'ontology' and load
    the generated Turtle triples into it.
    """
    success = False
    details = {
        "collection_name": body.collection_name,
        "content_length": len(body.owl_content),
    }

    try:
        sm_manager = get_semantic_models_manager(request)

        collection = sm_manager.create_collection(
            label=body.collection_name,
            collection_type="ontology",
            scope_level="enterprise",
            description=body.collection_description or f"Generated ontology: {body.collection_name}",
            is_editable=True,
            created_by=current_user.email,
        )

        collection_iri = collection["iri"]
        details["collection_iri"] = collection_iri

        count = sm_manager.import_rdf_to_collection(
            collection_iri=collection_iri,
            content=body.owl_content,
            format="turtle",
            imported_by=current_user.email,
        )

        success = True
        details["triples_imported"] = count

        return SaveToCollectionResponse(
            success=True,
            collection_iri=collection_iri,
            triples_imported=count,
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Failed to save ontology to collection")
        details["exception"] = {"type": type(e).__name__, "message": str(e)}
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to save to collection: {e}",
        )
    finally:
        audit_manager.log_action(
            db=db,
            username=current_user.username,
            ip_address=request.client.host if request.client else None,
            feature=FEATURE_ID,
            action="SAVE_ONTOLOGY_TO_COLLECTION",
            success=success,
            details=details,
        )


def register_routes(app):
    app.include_router(router)
    logger.info("Ontology generator routes registered with prefix /api/ontology")
