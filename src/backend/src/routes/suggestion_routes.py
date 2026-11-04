"""API routes for link candidate suggestions (fuzzy name/tag matching)."""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.common.authorization import PermissionChecker
from src.common.features import FeatureAccessLevel
from src.common.dependencies import DBSessionDep
from src.common.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/api/suggestions", tags=["Suggestions"])
FEATURE_ID = "assets"


class LinkCandidate(BaseModel):
    """A candidate entity for linking."""
    id: str
    name: str
    entity_type: str
    description: Optional[str] = None
    status: Optional[str] = None
    score: float = Field(0.0, description="Relevance score (higher = better match)")


class LinkCandidatesResponse(BaseModel):
    candidates: List[LinkCandidate] = Field(default_factory=list)
    total: int = 0


@router.get(
    "/link-candidates",
    response_model=LinkCandidatesResponse,
    dependencies=[Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY))],
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

    Supports fuzzy matching against assets and dedicated entity types.
    """
    from src.db_models.assets import AssetDb, AssetTypeDb
    from sqlalchemy import func, or_

    candidates: List[LinkCandidate] = []
    search_term = query or source_name or ""

    try:
        # Asset-backed types
        asset_type = db.query(AssetTypeDb).filter(AssetTypeDb.name == target_type).first()
        if not asset_type:
            label_map = {
                "Table": "Table",
                "View": "View",
                "MetricView": "Metric View",
                "Column": "Column",
                "Schema": "Schema",
                "BusinessTerm": "Business Term",
                "LogicalEntity": "Logical Entity",
                "LogicalAttribute": "Logical Attribute",
                "DeliveryChannel": "Delivery Channel",
                "APIEndpoint": "API Endpoint",
                "MLModel": "ML Model",
            }
            label = label_map.get(target_type, target_type)
            asset_type = db.query(AssetTypeDb).filter(AssetTypeDb.name == label).first()

        if asset_type:
            q = db.query(AssetDb).filter(
                AssetDb.asset_type_id == asset_type.id,
                AssetDb.status != 'retired',
            )

            if search_term:
                term_lower = search_term.lower()
                parts = term_lower.replace('.', ' ').split()
                conditions = []
                for part in parts:
                    conditions.append(func.lower(AssetDb.name).contains(part))
                    conditions.append(func.lower(AssetDb.description).contains(part))
                if conditions:
                    q = q.filter(or_(*conditions))

            results = q.order_by(AssetDb.name).limit(limit).all()

            for asset in results:
                score = _compute_score(asset.name, asset.description, asset.tags, search_term)
                candidates.append(LinkCandidate(
                    id=str(asset.id),
                    name=asset.name,
                    entity_type=target_type,
                    description=asset.description,
                    status=asset.status,
                    score=score,
                ))
        else:
            # Dedicated types
            dedicated_candidates = _search_dedicated_type(db, target_type, search_term, limit)
            candidates.extend(dedicated_candidates)

    except Exception as e:
        logger.error(f"Error fetching link candidates: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

    candidates.sort(key=lambda c: c.score, reverse=True)
    return LinkCandidatesResponse(candidates=candidates[:limit], total=len(candidates))


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
) -> List[LinkCandidate]:
    """Search dedicated entity types (DataProduct, DataDomain, etc.)."""
    candidates = []
    term_lower = (search_term or "").lower()

    try:
        if target_type == "DataProduct":
            from src.db_models.data_products import DataProductDb
            q = db.query(DataProductDb)
            if term_lower:
                q = q.filter(DataProductDb.name.ilike(f"%{term_lower}%"))
            for obj in q.limit(limit).all():
                candidates.append(LinkCandidate(
                    id=str(obj.id),
                    name=obj.name or str(obj.id),
                    entity_type="DataProduct",
                    status=obj.status,
                    score=_compute_score(obj.name or "", None, None, search_term),
                ))
        elif target_type == "DataDomain":
            from src.db_models.data_domains import DataDomain
            q = db.query(DataDomain)
            if term_lower:
                q = q.filter(DataDomain.name.ilike(f"%{term_lower}%"))
            for obj in q.limit(limit).all():
                candidates.append(LinkCandidate(
                    id=str(obj.id),
                    name=obj.name,
                    entity_type="DataDomain",
                    description=obj.description,
                    score=_compute_score(obj.name, obj.description, None, search_term),
                ))
        elif target_type == "DataContract":
            from src.db_models.data_contracts import DataContractDb
            q = db.query(DataContractDb)
            if term_lower:
                q = q.filter(DataContractDb.name.ilike(f"%{term_lower}%"))
            for obj in q.limit(limit).all():
                candidates.append(LinkCandidate(
                    id=str(obj.id),
                    name=obj.name or str(obj.id),
                    entity_type="DataContract",
                    status=obj.status,
                    score=_compute_score(obj.name or "", None, None, search_term),
                ))
    except Exception as e:
        logger.warning(f"Error searching dedicated type {target_type}: {e}")

    return candidates


def register_routes(app):
    app.include_router(router)
    logger.info("Suggestion routes registered with prefix /api/suggestions")
