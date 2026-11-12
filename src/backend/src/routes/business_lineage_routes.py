"""API routes for business lineage graph traversal and impact analysis."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from src.models.entity_relationships import LineageGraph
from src.controller.entity_relationships_manager import EntityRelationshipsManager
from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import CurrentUserDep, DBSessionDep
from src.common.logging import get_logger
from src.controller.model_lineage import LineageAccess

logger = get_logger(__name__)

router = APIRouter(prefix="/api/business-lineage", tags=["Business Lineage"])
FEATURE_ID = "entity_relationships"


def get_entity_relationships_manager(request: Request) -> EntityRelationshipsManager:
    mgr = getattr(request.app.state, "entity_relationships_manager", None)
    if not mgr:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Entity Relationships manager not configured.",
        )
    return mgr


async def contracts_feature_admin(request: Request, current_user: CurrentUserDep) -> bool:
    """Role-aware data-contracts admin check (same as the contract list route).

    ``is_user_admin`` only sees workspace groups; admins whose rights come from
    an Ontos role must bypass contract visibility too. Fails closed.
    """
    from src.common.authorization import is_user_feature_admin
    try:
        return await is_user_feature_admin(
            user_email=getattr(current_user, "email", None),
            user_groups=list(getattr(current_user, "groups", None) or []),
            feature_id="data-contracts",
            request=request,
        )
    except Exception:
        logger.exception("Feature-admin resolution failed for lineage access; treating as non-admin")
        return False


def build_lineage_access(request: Request, db, current_user, contracts_admin: bool) -> LineageAccess:
    """Read checks the lineage walk applies to every product and contract it adds.

    Products use the same gate as ``GET /data-products/{id}`` (published, or
    admin/owner/team/project member). Contracts mirror the PRD #442 list
    visibility (``DataContractsManager._query_contracts``): admins see all;
    nobody else sees another user's personal draft; otherwise a contract is
    visible when published (active/deprecated) or when the caller is elevated
    for its version family (draft owner or owning-team member of any version).
    Both fail closed.
    """
    from src.common.version_visibility import is_admin_only_status, is_visible_consumer
    from src.db_models.data_contracts import DataContractDb
    from src.routes.data_product_routes import _caller_can_read_product

    groups = list(getattr(current_user, "groups", None) or [])
    email = getattr(current_user, "email", None)
    identities = {
        str(v).lower()
        for v in (getattr(current_user, "username", None), email)
        if v
    }
    team_ids: list = []  # resolved lazily, once per request

    def caller_team_ids() -> set:
        if not team_ids:
            ids: set = set()
            try:
                from src.controller.teams_manager import teams_manager
                ids = {str(t.id) for t in teams_manager.get_teams_for_user(db, email, groups) if getattr(t, "id", None)}
            except Exception:
                logger.exception("Team resolution failed for lineage access; no team elevation")
            team_ids.append(ids)
        return team_ids[0]

    def can_read_product(row) -> bool:
        return _caller_can_read_product(request, db, current_user, None, row)

    def can_read_contract(row) -> bool:
        if contracts_admin:
            return True
        owner = getattr(row, "draft_owner_id", None)
        if owner and str(owner).lower() not in identities:
            return False  # someone else's personal draft
        if not is_admin_only_status(row) and is_visible_consumer(row):
            return True
        family_id = row.version_family_id or row.id
        family = db.query(DataContractDb).filter(
            (DataContractDb.version_family_id == family_id) | (DataContractDb.id == family_id)
        ).all()
        teams = caller_team_ids()
        return any(
            (c.draft_owner_id and str(c.draft_owner_id).lower() in identities)
            or (c.owner_team_id and str(c.owner_team_id) in teams)
            for c in family
        )

    return LineageAccess(can_read_product=can_read_product, can_read_contract=can_read_contract)


@router.get(
    "/{entity_type}/{entity_id}",
    response_model=LineageGraph,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_business_lineage(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    contracts_admin: bool = Depends(contracts_feature_admin),
    max_depth: int = Query(3, ge=1, le=10),
    direction: Optional[str] = Query(None, pattern="^(upstream|downstream)$"),
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Get lineage graph centered on an entity.

    Returns nodes and edges for rendering a lineage graph.
    Optionally filter by direction: 'upstream' or 'downstream'.
    """
    return manager.get_business_lineage(
        db=db,
        entity_type=entity_type,
        entity_id=entity_id,
        max_depth=max_depth,
        direction=direction,
        access=build_lineage_access(request, db, current_user, contracts_admin),
    )


@router.get(
    "/{entity_type}/{entity_id}/impact",
    response_model=LineageGraph,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
)
def get_impact_analysis(
    entity_type: str,
    entity_id: str,
    request: Request,
    db: DBSessionDep,
    current_user: CurrentUserDep,
    contracts_admin: bool = Depends(contracts_feature_admin),
    max_depth: int = Query(4, ge=1, le=10),
    manager: EntityRelationshipsManager = Depends(get_entity_relationships_manager),
):
    """Get downstream impact graph from an entity (e.g. Policy or BusinessTerm).

    Traverses only downstream/outgoing relationships to find affected entities.
    """
    return manager.get_business_lineage(
        db=db,
        entity_type=entity_type,
        entity_id=entity_id,
        max_depth=max_depth,
        direction="downstream",
        access=build_lineage_access(request, db, current_user, contracts_admin),
    )


def register_routes(app):
    app.include_router(router)
    logger.info("Business lineage routes registered with prefix /api/business-lineage")
