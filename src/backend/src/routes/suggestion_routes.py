"""API routes for link candidate suggestions (fuzzy name/tag matching)."""

from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from src.common.authorization import enforce_feature_permission, get_user_details_from_sdk
from src.common.features import FeatureAccessLevel
from src.common.dependencies import DBSessionDep
from src.common.logging import get_logger
from src.models.users import UserInfo

logger = get_logger(__name__)

router = APIRouter(prefix="/api/suggestions", tags=["Suggestions"])
FEATURE_ID = "assets"

ONTOS_NS = "http://ontos.app/ontology#"

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
    feature_id = DEDICATED_TARGET_FEATURES.get(target_type, FEATURE_ID)
    await enforce_feature_permission(feature_id, FeatureAccessLevel.READ_ONLY, user_details, request)


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
):
    """Find candidate entities for linking, ranked by name/tag similarity.

    ``target_type`` is an ontology type: an asset type (local name ``LogicalEntity``
    or label ``Logical Entity``), ``Asset`` for any asset, or one of the dedicated
    types in ``DEDICATED_TARGET_FEATURES``. Without ``query`` (and ``source_name``)
    the first ``limit`` entities by name are returned, for browsing. Each target
    type needs read access to the feature that owns it. Types that have no list
    here (e.g. ``Ownership``) return no candidates.
    """
    search_term = query or source_name or ""
    try:
        if target_type == "OntologyConcept":
            candidates, total = _search_concepts(request, search_term, limit)
        elif target_type in DEDICATED_TARGET_FEATURES:
            candidates, total = _search_dedicated_type(db, target_type, search_term, limit)
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
    wanted = target_type.replace(" ", "")
    return {
        t.id: t.name.replace(" ", "")
        for t in types
        if target_type == GENERIC_ASSET_TYPE or t.name.replace(" ", "") == wanted
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
    candidates = [
        LinkCandidate(
            id=str(asset.id),
            name=asset.name,
            entity_type=type_names.get(asset.asset_type_id, target_type),
            description=asset.description,
            status=asset.status,
            context=asset.location,
            score=_compute_score(asset.name, asset.description, asset.tags, search_term),
        )
        for asset in q.order_by(AssetDb.name).limit(limit).all()
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
    rows = [r for r in rows if not str(r.get("value", "")).startswith(ONTOS_NS)]
    collection_labels: Dict[str, str] = {}
    for collection in manager.get_collections() or []:
        if collection.get("source_key"):
            collection_labels[collection["source_key"]] = collection.get("label") or collection["source_key"]

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


def _search_dedicated_type(
    db: Session,
    target_type: str,
    search_term: str,
    limit: int,
) -> Tuple[List[LinkCandidate], int]:
    """Search dedicated entity types (DataProduct, DataDomain, ...) by name."""
    from src.db_models.data_contracts import DataContractDb
    from src.db_models.data_domains import DataDomain
    from src.db_models.data_products import DataProductDb
    from src.db_models.projects import ProjectDb
    from src.db_models.teams import TeamDb

    models = {
        "DataProduct": DataProductDb,
        "DataDomain": DataDomain,
        "DataContract": DataContractDb,
        "Team": TeamDb,
        "Project": ProjectDb,
    }
    model = models.get(target_type)
    if model is None:
        return [], 0

    q = db.query(model)
    if search_term:
        q = q.filter(model.name.ilike(f"%{search_term}%"))
    total = q.count()
    candidates = []
    for obj in q.order_by(model.name).limit(limit).all():
        description = getattr(obj, "description", None)
        candidates.append(LinkCandidate(
            id=str(obj.id),
            name=obj.name or str(obj.id),
            entity_type=target_type,
            description=description if isinstance(description, str) else None,
            status=getattr(obj, "status", None),
            score=_compute_score(obj.name or "", None, None, search_term),
        ))
    return candidates, total


def register_routes(app):
    app.include_router(router)
    logger.info("Suggestion routes registered with prefix /api/suggestions")
