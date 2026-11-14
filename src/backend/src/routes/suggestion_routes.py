"""API routes for link candidate suggestions (fuzzy name/tag matching)."""

from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.common.authorization import enforce_feature_permission, get_user_details_from_sdk
from src.common.features import FeatureAccessLevel
from src.common.dependencies import DBSessionDep
from src.common.logging import get_logger
from src.repositories.tags_repository import entity_tag_repo
from src.common.manager_dependencies import get_data_contracts_manager
from src.common.ontology_type_names import ONTOS_NS, canonical_type_name
from src.models.users import UserInfo

logger = get_logger(__name__)

router = APIRouter(prefix="/api/suggestions", tags=["Suggestions"])
FEATURE_ID = "assets"

# Non-asset target types and the feature whose read access lists them. Every other
# target type is matched against the asset types and needs asset read access.
DEDICATED_TARGET_FEATURES = {
    "DataDomain": "data-domains",
    "DataProduct": "data-products",
    "DataContract": "data-contracts",
    "Team": "teams",
    "Project": "projects",
    "OntologyConcept": "semantic-models",
}
# Ontology superclass of every asset type: a relationship to "Asset" accepts any asset.
GENERIC_ASSET_TYPE = "Asset"
# Concept types a "Has Concepts" link can point to (properties are not concepts).
LINKABLE_CONCEPT_TYPES = ["concept", "class", "term", "individual"]
MAX_CONCEPT_MATCHES = 10000


class LinkCandidate(BaseModel):
    """A candidate entity for linking."""
    id: str
    name: str
    entity_type: str
    description: Optional[str] = None
    status: Optional[str] = None
    context: Optional[str] = Field(None, description="Where the entity lives, e.g. a concept's collection")
    score: float = Field(0.0, description="Relevance score (higher = better match)")


class LinkCandidatesResponse(BaseModel):
    candidates: List[LinkCandidate] = Field(default_factory=list)
    total: int = 0


async def _require_target_read_access(
    request: Request,
    target_type: str = Query(..., description="Target entity type to search for candidates"),
    user_details: UserInfo = Depends(get_user_details_from_sdk),
) -> None:
    """Read access to the feature that owns ``target_type`` (assets for asset types)."""
    feature_id = DEDICATED_TARGET_FEATURES.get(canonical_type_name(target_type), FEATURE_ID)
    await enforce_feature_permission(feature_id, FeatureAccessLevel.READ_ONLY, user_details, request)


async def _contract_scope(
    request: Request,
    db: DBSessionDep,
    target_type: str = Query(..., description="Target entity type to search for candidates"),
    user_details: UserInfo = Depends(get_user_details_from_sdk),
) -> Dict[str, Any]:
    """The contract list's read scope (``contract_read_scope``), for contract targets only.

    The other read scopes need no async role check and are resolved in the
    (threadpool) handler.
    """
    if canonical_type_name(target_type) != "DataContract":
        return {}
    from src.routes.data_contracts_routes import contract_read_scope
    return await contract_read_scope(request, db, user_details)


# A plain ``def``: the queries are synchronous, so FastAPI runs it in its threadpool.
@router.get(
    "/link-candidates",
    response_model=LinkCandidatesResponse,
    dependencies=[Depends(_require_target_read_access)],
)
def get_link_candidates(
    db: DBSessionDep,
    request: Request,
    source_type: Optional[str] = Query(None, description="Source entity type for context"),
    source_name: Optional[str] = Query(None, description="Source entity name for fuzzy matching"),
    target_type: str = Query(..., description="Target entity type to search for candidates"),
    query: Optional[str] = Query(None, description="Additional search query"),
    limit: int = Query(20, ge=1, le=100),
    contract_scope: Dict[str, Any] = Depends(_contract_scope),
    user_details: UserInfo = Depends(get_user_details_from_sdk),
):
    """Find candidate entities for linking, ranked by name/tag similarity.

    ``target_type`` is an ontology type: an asset type (local name ``LogicalEntity``
    or label ``Logical Entity``), ``Asset`` for any asset, or one of the dedicated
    types in ``DEDICATED_TARGET_FEATURES``. Without ``query`` (and ``source_name``)
    the first ``limit`` entities by name are returned, for browsing. Each target
    type needs read access to the feature that owns it, and only entities the
    caller could open are returned (see ``_search_dedicated_type``).
    Types that have no list here (e.g. ``Ownership``) return no candidates.
    """
    target_type = canonical_type_name(target_type)  # 'Data Domain', IRIs -> 'DataDomain'
    search_term = query or source_name or ""
    # Outside the try: a missing manager answers its own 503, not a generic 500.
    contracts_manager = get_data_contracts_manager(request) if target_type == "DataContract" else None
    try:
        if target_type == "OntologyConcept":
            candidates, total = _search_concepts(request, search_term, limit)
        elif target_type in DEDICATED_TARGET_FEATURES:
            candidates, total = _search_dedicated_type(
                db, request, target_type, search_term, limit,
                user=user_details, contract_scope=contract_scope, contracts_manager=contracts_manager,
            )
        else:
            candidates, total = _search_assets(db, target_type, search_term, limit)
    except Exception:
        logger.error("Error fetching link candidates for %s", target_type, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to fetch link candidates")

    candidates.sort(key=lambda c: (-c.score, c.name.lower()))
    return LinkCandidatesResponse(candidates=candidates[:limit], total=total)


def _asset_types(db: Session, target_type: str) -> Dict:
    """``{asset_type_id: ontology local name}`` for a target type; empty if it isn't one.

    Matches the type name as stored ('Logical Entity') and its ontology local name
    ('LogicalEntity'). ``Asset`` matches every asset type.
    """
    from src.db_models.assets import AssetTypeDb

    types = db.query(AssetTypeDb.id, AssetTypeDb.name).all()
    return {
        t.id: canonical_type_name(t.name)
        for t in types
        if target_type == GENERIC_ASSET_TYPE or canonical_type_name(t.name) == target_type
    }


def _search_assets(
    db: Session, target_type: str, search_term: str, limit: int,
) -> Tuple[List[LinkCandidate], int]:
    from src.db_models.assets import AssetDb

    type_names = _asset_types(db, target_type)
    if not type_names:
        return [], 0

    q = db.query(AssetDb).filter(AssetDb.asset_type_id.in_(list(type_names)), AssetDb.status != 'retired')
    if search_term:
        conditions = []
        for part in search_term.lower().replace('.', ' ').split():
            conditions.append(func.lower(AssetDb.name).contains(part))
            conditions.append(func.lower(AssetDb.description).contains(part))
        if conditions:
            q = q.filter(or_(*conditions))

    total = q.count()
    rows = q.order_by(AssetDb.name).limit(limit).all()
    # Tags live on the shared store (#1422): one batch lookup for the page
    tags_map = entity_tag_repo.get_assigned_tags_for_entities(
        db, entity_ids=[str(a.id) for a in rows], entity_type="asset",
    ) if rows else {}
    candidates = [
        LinkCandidate(
            id=str(asset.id),
            name=asset.name,
            entity_type=type_names.get(asset.asset_type_id, target_type),
            description=asset.description,
            status=asset.status,
            context=asset.location,
            score=_compute_score(
                asset.name, asset.description,
                [t.tag_name for t in tags_map.get(str(asset.id), [])], search_term,
            ),
        )
        for asset in rows
    ]
    return candidates, total


def _search_concepts(request: Request, search_term: str, limit: int) -> Tuple[List[LinkCandidate], int]:
    """Concepts of every collection, except the app's own metamodel classes."""
    manager = getattr(request.app.state, "semantic_models_manager", None)
    if manager is None:
        raise RuntimeError("Semantic models manager not configured")

    # The search reads the cached concept list: take every match, so the total is
    # right after the metamodel classes are dropped.
    rows = manager.search_concepts_by_type(search_term, LINKABLE_CONCEPT_TYPES, limit=MAX_CONCEPT_MATCHES)
    # Neither the app's metamodel classes nor the graph nodes of app entities
    # (urn:ontos:<type>:<id>, e.g. a draft product) are concepts to link to.
    from src.tools.read_access import graph_entity
    rows = [
        r for r in rows
        if not str(r.get("value", "")).startswith(ONTOS_NS) and graph_entity(r.get("value")) is None
    ]
    collection_labels: Dict[str, str] = manager._scheme_labels_by_source_key()

    candidates = [
        LinkCandidate(
            id=row["value"],
            name=row.get("label") or row["value"],
            entity_type="OntologyConcept",
            context=collection_labels.get(row.get("source_context") or "", row.get("source_context")),
            score=_compute_score(row.get("label") or "", None, None, search_term),
        )
        for row in rows
    ]
    # Best matches first before the page is cut, as the route sorts the page.
    candidates.sort(key=lambda c: (-c.score, c.name.lower()))
    return candidates[:limit], len(candidates)


def _compute_score(name: str, description: Optional[str], tags: Optional[list], search_term: str) -> float:
    """Simple relevance scoring based on name/description/tag overlap."""
    if not search_term:
        return 0.5

    score = 0.0
    term_lower = search_term.lower()
    name_lower = name.lower()

    if name_lower == term_lower:
        score += 10.0
    elif term_lower in name_lower:
        score += 5.0
    elif name_lower in term_lower:
        score += 3.0

    parts = term_lower.replace('.', ' ').split()
    for part in parts:
        if part in name_lower:
            score += 2.0
        if description and part in description.lower():
            score += 1.0
        if tags:
            for tag in tags:
                if part in str(tag).lower():
                    score += 0.5

    return score


def _ilike_pattern(term: str) -> str:
    """``%term%`` with LIKE wildcards in the term taken literally (escape character ``\\``)."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _candidate(obj: Any, target_type: str, search_term: str, *, with_description: bool = True) -> LinkCandidate:
    description = getattr(obj, "description", None) if with_description else None
    status = getattr(obj, "status", None)
    return LinkCandidate(
        id=str(obj.id),
        name=getattr(obj, "name", None) or str(obj.id),
        entity_type=target_type,
        description=description if isinstance(description, str) else None,
        status=getattr(status, "value", status),
        score=_compute_score(getattr(obj, "name", None) or "", None, None, search_term),
    )


def _page(rows: List[Any], target_type: str, search_term: str, limit: int,
          **kwargs: Any) -> Tuple[List[LinkCandidate], int]:
    """The first ``limit`` rows by name as candidates, and the number of rows."""
    rows = sorted(rows, key=lambda r: (getattr(r, "name", None) or "").lower())
    return [_candidate(r, target_type, search_term, **kwargs) for r in rows[:limit]], len(rows)


def _product_candidates(
    db: Session, request: Request, user: Optional[UserInfo], search_term: str, limit: int,
) -> Tuple[List[LinkCandidate], int]:
    """Products the caller can open, by the product read rule (``common.product_read_rule``).

    Published products for everyone; others for data-products admins and the
    product's draft owner, owning team and project members. The caller's teams
    and projects are looked up once, in a savepoint; a failed lookup leaves the
    published products and the caller's own drafts (fail closed). SQL keeps a
    superset of the readable rows (name, published status or an ownership
    match) and the rule decides each of them.
    """
    from sqlalchemy.orm import load_only

    from src.common import product_read_rule as rule
    from src.common.version_visibility import CONSUMER_VISIBLE_STATUSES
    from src.db_models.data_products import DataProductDb

    email = user.email if user else None
    groups = list(user.groups or []) if user else []
    is_admin = rule.is_product_read_admin(request, user)
    team_ids: set = set()
    project_ids: Any = set()
    if not is_admin:
        try:
            with db.begin_nested():
                team_ids = rule.lookup_team_ids(db, email, groups)
                project_ids = rule.lookup_member_project_ids(db, email, groups)
        except Exception:
            logger.exception("Ownership lookup failed for %s; offering published products only", email)
            team_ids, project_ids = set(), set()

    model = DataProductDb
    q = db.query(model).options(load_only(
        model.id, model.name, model.status, model.draft_owner_id, model.owner_team_id, model.project_id,
    ))
    if search_term:
        q = q.filter(model.name.ilike(_ilike_pattern(search_term), escape="\\"))
    if not is_admin:
        clauses = [func.lower(model.status).in_(sorted(CONSUMER_VISIBLE_STATUSES))]
        if email:
            clauses.append(func.lower(model.draft_owner_id) == email.lower())
        if team_ids:
            clauses.append(model.owner_team_id.in_(sorted(team_ids)))
        if project_ids is rule.ALL_PROJECTS:
            clauses.append(model.project_id.isnot(None))
        elif project_ids:
            clauses.append(model.project_id.in_(sorted(project_ids)))
        q = q.filter(or_(*clauses))
    rows = [
        p for p in q.all()
        if rule.can_read_product(
            db, p, is_admin=is_admin, caller_email=email, caller_groups=groups,
            caller_team_ids=team_ids, caller_project_ids=project_ids,
        )
    ]
    return _page(rows, "DataProduct", search_term, limit, with_description=False)


def _search_dedicated_type(
    db: Session,
    request: Request,
    target_type: str,
    search_term: str,
    limit: int,
    *,
    user: Optional[UserInfo],
    contract_scope: Dict[str, Any],
    contracts_manager: Any = None,
) -> Tuple[List[LinkCandidate], int]:
    """Search dedicated entity types (DataProduct, DataDomain, ...) by name.

    Only entities the caller could open are offered:
    - products: the product read rule (``_product_candidates``);
    - contracts: ``readable_contracts``, the rule for opening a contract by id
      (published, or a family the caller or their team owns, never another
      user's personal draft), with the contract list's scope;
    - projects: the projects list's rule (admins all, others the projects
      related to their domains);
    - domains and teams: all of them, as in their lists.
    """
    if target_type == "DataProduct":
        return _product_candidates(db, request, user, search_term, limit)

    from src.db_models.data_contracts import DataContractDb
    from src.db_models.data_domains import DataDomain
    from src.db_models.projects import ProjectDb
    from src.db_models.teams import TeamDb

    models = {"DataContract": DataContractDb, "Project": ProjectDb, "DataDomain": DataDomain, "Team": TeamDb}
    model = models.get(target_type)
    if model is None:
        return [], 0
    q = db.query(model)
    if search_term:
        q = q.filter(model.name.ilike(_ilike_pattern(search_term), escape="\\"))

    if target_type == "DataContract":
        return _page(contracts_manager.readable_contracts(db, q.all(), **contract_scope),
                     target_type, search_term, limit)
    if target_type == "Project":
        from src.common.authorization import is_user_admin
        from src.common.config import get_settings
        from src.repositories.projects_repository import project_repo

        groups = list(user.groups or []) if user else []
        if not is_user_admin(groups, get_settings()):
            visible = {p.id for p in project_repo.get_projects_by_domain_relationship(
                db, user.email if user else None, groups)}
            q = q.filter(model.id.in_(sorted(visible))) if visible else q.filter(False)
        return _page(q.all(), target_type, search_term, limit)

    total = q.count()
    rows = q.order_by(model.name).limit(limit).all()
    return [_candidate(r, target_type, search_term) for r in rows], total


def register_routes(app):
    app.include_router(router)
    logger.info("Suggestion routes registered with prefix /api/suggestions")
