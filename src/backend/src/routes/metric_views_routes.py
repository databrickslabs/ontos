"""KPI consistency views over metric view measures (#1263, phase 1). Read-only.

Unity Catalog decides which definitions a user sees: each metric view in a
response is checked with the user's (on-behalf-of) client, and only the
definitions of views the user can read are returned. Without the user's
token no definition is shown, and the response still lists the measures,
their assets, concepts and verdicts (Ontos-level metadata).
"""
from typing import Optional
from uuid import UUID

from databricks.sdk.errors import BadRequest, NotFound, PermissionDenied, Unauthenticated
from databricks.sdk.service.catalog import TableType
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.common.api_errors import CodedValueError
from src.common.authorization import PermissionChecker, get_user_details_from_sdk
from src.common.dependencies import CurrentUserDep, DBSessionDep
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.manager_dependencies import get_auth_manager
from src.controller.metric_view_consistency_manager import (
    MetricViewAssetNotFoundError, MetricViewConsistencyManager, Readable,
)
from src.controller.metric_views_manager import UserClientUnavailableError, UserTokenRequiredError
from src.models.metric_view_consistency import LinkCheck, MetricViewConsistency
from src.routes import assets_routes

logger = get_logger(__name__)

router = APIRouter(prefix="/api/metric-views", tags=["Metric Views"])

_SEMANTIC_READ = PermissionChecker('semantic-models', FeatureAccessLevel.READ_ONLY)


class ConsistencyQueryError(CodedValueError):
    """The consistency view needs exactly one of ``concept_iri`` and ``asset_id``."""

    code = 'consistency_query_invalid'


def _readable_as_user(request: Request) -> Readable:
    """Whether the requesting user can read a metric view in Unity Catalog.

    Without the user's token (or client) nothing is readable.
    """
    try:
        ws_client = assets_routes._user_workspace_client(request)
    except (UserTokenRequiredError, UserClientUnavailableError):
        return lambda fqn: False

    def readable(fqn: str) -> bool:
        try:
            table = ws_client.tables.get(full_name=fqn)
        except (NotFound, PermissionDenied, BadRequest, Unauthenticated):
            return False
        return getattr(table, 'table_type', None) == TableType.METRIC_VIEW

    return readable


@router.get("/consistency", response_model=MetricViewConsistency)
async def get_consistency(
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    concept_iri: Optional[str] = Query(None, min_length=1, description="Concept IRI"),
    asset_id: Optional[UUID] = Query(None, description="Metric View asset id"),
    user_details=Depends(get_user_details_from_sdk),
    auth_manager=Depends(get_auth_manager),
):
    """The measures linked to a concept grouped by fingerprint (``concept_iri``), or,
    per measure of a metric view asset, the measures with the same or a similar
    definition and the conflicting links (``asset_id``).

    By concept: needs ``semantic-models`` read access, as the concept page.
    By asset: the asset must be readable by the user, as ``GET /api/assets/{id}``.
    400 ``consistency_query_invalid`` unless exactly one of the two is given;
    404 ``metric_view_asset_not_found`` for an unknown asset.
    """
    if (concept_iri is None) == (asset_id is None):
        error = ConsistencyQueryError('Give either concept_iri or asset_id.')
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    manager = MetricViewConsistencyManager(db)
    if concept_iri is not None:
        await _SEMANTIC_READ(request, user_details, auth_manager)
        try:
            return manager.for_concept(concept_iri, _readable_as_user(request))
        except Exception:
            logger.exception("Failed to build the consistency view of concept %s", concept_iri)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to build the consistency view",
            )

    assets_routes._ensure_asset_readable(
        request, db, current_user, assets_routes.get_assets_manager(), asset_id,
    )
    try:
        return manager.for_asset(asset_id, _readable_as_user(request))
    except MetricViewAssetNotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except Exception:
        logger.exception("Failed to build the consistency view of asset %s", asset_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to build the consistency view",
        )


@router.get("/consistency/link-check", response_model=LinkCheck)
def check_link(
    db: DBSessionDep,
    entity_id: str = Query(..., min_length=1, description="catalog.schema.view.measure"),
    iri: str = Query(..., min_length=1, description="Concept IRI"),
    _: bool = Depends(_SEMANTIC_READ),
):
    """The non-blocking warnings linking a measure to a concept would raise.

    Coded (``concept_has_other_definitions``, ``definition_linked_to_other_concepts``)
    with Ontos-level params only (measure and concept names), translated by the UI.
    """
    try:
        return MetricViewConsistencyManager(db).check_link(entity_id, iri)
    except Exception:
        logger.exception("Failed to check the link of %s to %s", entity_id, iri)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to check the link",
        )


def register_routes(app):
    app.include_router(router)
