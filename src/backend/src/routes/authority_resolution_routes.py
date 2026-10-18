"""API routes for the Authority Resolution feature (ARF)."""
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body, Query, Request

from src.common.dependencies import DBSessionDep, AuditCurrentUserDep, DataAssetReviewManagerDep
from src.common.features import FeatureAccessLevel
from src.common.authorization import PermissionChecker
from src.controller.authority_resolution_manager import AuthorityResolutionManager
from src.models.authority_resolution import (
    AuthorityRelationCreate,
    AuthorityRelationUpdate,
    NewVersionRequest,
    StatusChangeRequest,
    AffirmRequest,
    ResolveRequest,
    FindAuthorityForConceptRequest,
)

from src.common.logging import get_logger
logger = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["Authority Resolution"])
manager = AuthorityResolutionManager()

FEATURE_ID = "authority-resolution"


def _resolve_req_dict(req: ResolveRequest) -> dict:
    base = {
        "actor_identity": req.actor_identity,
        "action": req.action,
        "object_id": req.object_id,
        "value": req.value,
        "cosign_present": req.cosign_present,
        "escalated": req.escalated,
    }
    base.update(req.params or {})
    return base


def _ws_factories(request: Request):
    """Lazy (obo, app_sp) WorkspaceClient factories for mcp_tool refs.

    The OBO factory is ``None`` when the caller carried no forwarded token, so
    an ``obo`` AR fails closed instead of silently running as the app SP.
    """
    from src.common.workspace_client import get_obo_workspace_client, get_workspace_client

    obo = None
    if request.headers.get("x-forwarded-access-token"):
        obo = lambda: get_obo_workspace_client(request)  # noqa: E731
    return obo, (lambda: get_workspace_client())


def _semantic_models_manager(request: Request):
    """Fish the SemanticModelsManager out of app.state when present.

    Resolve calls can enrich ``ontos_entity`` refs with a semantic-graph
    label when the manager has booted; absence is non-fatal — the resolver
    falls back to the raw IRI.
    """
    return getattr(request.app.state, "semantic_models_manager", None)


@router.get("/authority/relations")
async def list_relations(
    db: DBSessionDep,
    domain_ids: Optional[str] = Query(None, description="CSV of domain ids (any-of filter)"),
    include_history: bool = Query(False, description="Return every version instead of one row per family"),
    project_id: Optional[str] = Query(None, description="Only ARs in this project"),
    owner_team_id: Optional[str] = Query(None, description="Only ARs owned by this team"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    ids = [d for d in domain_ids.split(",") if d] if domain_ids else None
    relations = manager.list_relations(
        db, domain_ids=ids, include_history=include_history,
        project_id=project_id, owner_team_id=owner_team_id,
    )
    return [manager.to_read_dict(db, r) for r in relations]


@router.post("/authority/relations")
async def create_relation(
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: AuthorityRelationCreate = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    username = current_user.username if current_user else None
    try:
        relation = manager.create_relation(db, payload, current_user=username)
    except ValueError as e:
        # Author-visible validation errors from the manager (prerequisite
        # cycles, missing-slug + prereqs set, etc.) — surface as 400 so the
        # dialog can toast the specific message.
        raise HTTPException(status_code=400, detail=str(e))
    return manager.to_read_dict(db, relation)


@router.get("/authority/relations/{relation_id}")
async def get_relation(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    # UUID pins the exact version (version navigation uses ids); a slug resolves
    # to the family's active version (the stable agent-facing @id).
    relation = manager.resolve_relation_ref(db, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.to_read_dict(db, relation)


@router.put("/authority/relations/{relation_id}")
async def update_relation(
    relation_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: AuthorityRelationUpdate = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    username = current_user.username if current_user else None
    try:
        relation = manager.update_relation(db, relation_id, payload, current_user=username)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not relation:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.to_read_dict(db, relation)


@router.delete("/authority/relations/{relation_id}")
async def delete_relation(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        deleted = manager.delete_relation(db, relation_id)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    if not deleted:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return {"deleted": True, "id": relation_id}


@router.get("/authority/relations/{relation_id}/versions")
async def get_relation_versions(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Every version of an AR's family, newest first — the tight row shape the
    shared VersionSelector / VersionNavigator consumes (mirrors Data Products)."""
    try:
        rows = manager.get_relation_versions(db, relation_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return [
        {
            "id": r.id,
            "name": r.name,
            "version": r.version,
            "status": r.status,
            "versionFamilyId": r.version_family_id,
            "parentRelationId": getattr(r, "parent_relation_id", None),
            "baseName": getattr(r, "base_name", None),
            "changeSummary": getattr(r, "change_summary", None),
            "draftOwnerId": getattr(r, "draft_owner_id", None),
            "createdAt": r.created_at.isoformat() if r.created_at else None,
            "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.post("/authority/relations/{relation_id}/versions", status_code=201)
async def create_relation_version(
    relation_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: NewVersionRequest = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Snapshot an AR into a new immutable version (deep-clones the definition)."""
    username = current_user.username if current_user else None
    relation = manager.create_new_version(
        db, relation_id, payload.new_version,
        change_summary=payload.change_summary, current_user=username,
    )
    if relation is None:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.to_read_dict(db, relation)


@router.post("/authority/relations/{relation_id}/compute-dnaco")
async def compute_dnaco(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    try:
        run = manager.compute_dnaco(db, relation_id)
    except Exception as e:
        # Persist the failed run row before the error rolls the request back.
        db.commit()
        raise HTTPException(status_code=502, detail=f"DNA-Coefficient computation failed: {e}")
    if not run:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return {
        "run_id": run.id, "status": run.status, "sampled_count": run.sampled_count,
        "divergent_count": run.divergent_count, "magnitude": run.magnitude, "direction": run.direction,
    }


@router.post("/authority/relations/{relation_id}/status")
async def change_status(
    relation_id: str,
    db: DBSessionDep,
    payload: StatusChangeRequest = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    relation, error = manager.set_status(db, relation_id, payload.status)
    if relation is None:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    if error:
        raise HTTPException(status_code=409, detail=error)
    return manager.to_read_dict(db, relation)


@router.post("/authority/affirmations/{affirmation_id}/affirm")
async def affirm(
    affirmation_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: AffirmRequest = Body(default=AffirmRequest()),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    username = current_user.username if current_user else "unknown"
    try:
        aff = manager.affirm(db, affirmation_id, affirmed_by=username, notes=payload.notes, user=current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not aff:
        raise HTTPException(status_code=404, detail="Affirmation not found")
    return {"id": aff.id, "affirmed": aff.affirmed, "affirmed_by": aff.affirmed_by, "affirmed_at": aff.affirmed_at}


@router.post("/authority/relations/resolve-by-concept")
def resolve_by_concept(
    db: DBSessionDep,
    request: Request,
    payload: FindAuthorityForConceptRequest = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Find the AR governing a Business Concept in a given context. Returns ranked
    candidates and ``resolved`` (a family slug) only when exactly one survives."""
    obo, app_sp = _ws_factories(request)
    return manager.find_authority_for_concept(
        db, payload.concept_iri, payload.context, payload.domains, payload.request,
        semantic_models_manager=_semantic_models_manager(request),
        obo_ws_factory=obo, app_ws_factory=app_sp,
    )


@router.post("/authority/relations/{relation_id}/resolve")
def resolve(
    relation_id: str,
    db: DBSessionDep,
    request: Request,
    payload: ResolveRequest = Body(default=ResolveRequest()),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    obo, app_sp = _ws_factories(request)
    return manager.resolve(
        db, relation_id, _resolve_req_dict(payload),
        semantic_models_manager=_semantic_models_manager(request),
        obo_ws_factory=obo, app_ws_factory=app_sp,
    )


@router.post("/authority/relations/{relation_id}/test")
def test_resolve(
    relation_id: str,
    db: DBSessionDep,
    request: Request,
    payload: ResolveRequest = Body(default=ResolveRequest()),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Dry-run the resolution gate against this AR regardless of status, without
    recording the decision or touching the usage counters. Used by the detail-view
    Test dialog so authors can preview verdicts before activating.
    """
    obo, app_sp = _ws_factories(request)
    return manager.resolve(
        db, relation_id, _resolve_req_dict(payload),
        record=False, require_active=False,
        semantic_models_manager=_semantic_models_manager(request),
        obo_ws_factory=obo, app_ws_factory=app_sp,
    )


@router.get("/authority/relations/{relation_id}/decisions")
async def list_decisions(
    relation_id: str,
    db: DBSessionDep,
    source: Optional[str] = Query(None),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    from src.repositories.authority_resolution_repository import authority_decision_repo
    rows = authority_decision_repo.list_for_relation(db, relation_id=relation_id, source=source)
    return [
        {
            "id": d.id, "source": d.source, "verdict": d.verdict, "reason": d.reason,
            "actor_identity": d.actor_identity, "action": d.action, "object_id": d.object_id,
            "relation_version": d.relation_version, "divergence_magnitude": d.divergence_magnitude,
            "created_at": d.created_at,
        }
        for d in rows
    ]


@router.get("/authority/relations/{relation_id}/dna-runs")
async def list_dna_runs(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    from src.repositories.authority_resolution_repository import authority_dna_run_repo
    runs = authority_dna_run_repo.list_for_relation(db, relation_id=relation_id)
    return [
        {
            "id": r.id, "status": r.status, "started_at": r.started_at, "finished_at": r.finished_at,
            "sampled_count": r.sampled_count, "divergent_count": r.divergent_count,
            "magnitude": r.magnitude, "direction": r.direction, "error_message": r.error_message,
        }
        for r in runs
    ]


@router.post("/authority/relations/{relation_id}/start-review")
async def start_review(
    relation_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    reviews_manager: DataAssetReviewManagerDep,
    payload: dict = Body(default={}),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    owner = current_user.username if current_user else None
    message = payload.get("message") if isinstance(payload, dict) else None
    result = manager.start_review(db, relation_id, owner=owner, reviews_manager=reviews_manager, message=message)
    if result is None:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return result


@router.get("/authority/relation-slugs")
async def list_relation_slugs(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Family-level slugs the Requires picker consumes.

    One row per version family that carries a slug (slugs are per-row and
    unique, so each slug belongs to exactly one family). Shape stays tight:
    the picker only needs ``family_slug`` + a label.
    """
    return manager.list_family_slugs(db)


@router.get("/authority/relations/{relation_id}/prerequisites")
async def list_prerequisites(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """The AR's declared prerequisite edges (each resolved to the active
    family version for display)."""
    relation = manager.resolve_relation_ref(db, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.list_prerequisites(db, relation)


@router.get("/authority/relations/{relation_id}/resource-refs")
async def list_resource_refs(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """The AR's declared typed resource refs with each row's last cached label.

    Does *not* re-materialise (so detail views stay cheap); the live
    walk happens inside ``POST /resolve`` and ``POST /test``.
    """
    relation = manager.resolve_relation_ref(db, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.list_resource_refs(db, relation)


def _authoring_ws(request: Request):
    """(client, identity) for MCP discovery: the author's own token when forwarded,
    else the app SP (local dev) — reported so the picker can warn that obo ARs
    authored from this list may not be reachable for callers."""
    from src.common.workspace_client import get_obo_workspace_client, get_workspace_client

    if request.headers.get("x-forwarded-access-token"):
        return get_obo_workspace_client(request), "caller"
    return get_workspace_client(), "app_sp"


_SCHEMA_PARENT_RE = re.compile(r"^[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+$")


@router.get("/authority/mcp-services")
def list_mcp_services(
    request: Request,
    schemas: Optional[str] = Query(None, description="CSV of catalog.schema to search besides system.ai"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """UC MCP services visible to the caller (built-ins under ``system.ai`` plus
    any listed ``catalog.schema``) for the author's MCP-ref picker."""
    from src.common import mcp_resolver

    ws, identity = _authoring_ws(request)
    parents = [mcp_resolver.BUILTIN_PARENT]
    for sch in (schemas or "").split(","):
        sch = sch.strip()
        if not sch:
            continue
        if not _SCHEMA_PARENT_RE.match(sch):
            raise HTTPException(status_code=400, detail=f"Invalid schema '{sch}' — expected catalog.schema")
        parents.append(f"schemas/{sch}")
    return {"identity": identity, "services": mcp_resolver.list_mcp_services(ws, parents)}


@router.get("/authority/mcp-services/tools")
def list_mcp_service_tools(
    request: Request,
    service_name: str = Query(..., description="Full service name, mcp-services/<catalog>.<schema>.<name>"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Tools (name, description, input/output schema) exposed by one MCP service."""
    from src.common import mcp_resolver

    if not service_name.startswith(mcp_resolver.SERVICE_PREFIX):
        raise HTTPException(status_code=400, detail="service_name must start with 'mcp-services/'")
    ws, identity = _authoring_ws(request)
    try:
        client = mcp_resolver.McpHttpClient(ws, service_name, timeout=10.0)
        return {"identity": identity, "tools": client.list_tools()}
    except mcp_resolver.McpResolverError as e:
        status = 403 if e.kind == "permission" else 504 if e.kind == "timeout" else 502
        raise HTTPException(status_code=status, detail=str(e))


@router.get("/authority/entity-ref-candidates")
async def entity_ref_candidates(
    request: Request,
    db: DBSessionDep,
    entity_type: str = Query(..., description="Ontos entity type to search in"),
    q: Optional[str] = Query(None, description="Case-insensitive label filter"),
    limit: int = Query(50, ge=1, le=200),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Picker feed for the ``ontos_entity`` ref type in the author dialog.

    One flat shape — ``{entity_type, entity_id, label, iri?}`` — regardless
    of the backing store, so the frontend can render a single list widget.
    Supported types:

    * ``business_concept`` — hits the semantic-models search endpoint
      (``entity_id`` *is* the concept IRI).
    * ``data_product`` — ``name``-prefix match over data products.
    * ``data_domain`` — ``name``-prefix match over data domains.
    """
    needle = (q or "").strip().lower()
    out: List[dict] = []
    if entity_type == "business_concept":
        sm = _semantic_models_manager(request)
        if sm is None:
            return []
        try:
            # ``search_concepts`` already returns ``{value, label}`` pairs
            # (value = IRI); an empty needle is a plain limit-N listing.
            hits = sm.search_concepts(needle, limit=limit)
        except Exception as e:
            logger.warning(f"Concept search failed: {e}")
            return []
        for h in hits or []:
            iri = h.get("value") if isinstance(h, dict) else getattr(h, "value", None)
            label = h.get("label") if isinstance(h, dict) else getattr(h, "label", None)
            if not iri:
                continue
            out.append({
                "entity_type": "business_concept",
                "entity_id": iri,
                "label": label or iri,
                "iri": iri,
            })
    elif entity_type in ("data_product", "data_domain"):
        if entity_type == "data_product":
            from src.db_models.data_products import DataProductDb as model
        else:
            from src.db_models.data_domains import DataDomain as model
        query = db.query(model.id, model.name)
        if needle:
            escaped = needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.filter(model.name.ilike(f"%{escaped}%", escape="\\"))
        for row_id, row_name in query.order_by(model.name).limit(limit).all():
            out.append({
                "entity_type": entity_type,
                "entity_id": str(row_id),
                "label": row_name or str(row_id),
            })
    else:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported entity_type '{entity_type}' — expected "
                   "business_concept, data_product, or data_domain.",
        )
    out.sort(key=lambda x: (x.get("label") or "").lower())
    return out


@router.get("/authority/relations/{relation_id}/criteria")
async def list_criteria(
    relation_id: str,
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """The AR's author-configured decision criteria (Compliance Checks + facets)."""
    relation = manager.get_relation(db, relation_id)
    if not relation:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return manager.to_read_dict(db, relation).get("criteria", [])


@router.get("/authority/criteria/policies")
async def list_reusable_checks(
    db: DBSessionDep,
    category: Optional[str] = Query(None, description="Filter by compliance policy category"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Reusable Compliance Checks for the criteria picker (authority-scoped so the
    builder isn't gated on the separate compliance permission)."""
    from src.db_models.compliance import CompliancePolicyDb
    q = db.query(CompliancePolicyDb).filter(CompliancePolicyDb.is_active == True)  # noqa: E712
    if category:
        q = q.filter(CompliancePolicyDb.category == category)
    return [
        {
            "id": p.id, "name": p.name, "rule": p.rule, "category": p.category,
            "failure_message": p.failure_message, "severity": p.severity,
        }
        for p in q.order_by(CompliancePolicyDb.name.asc()).all()
    ]


@router.post("/authority/criteria/validate")
async def validate_criterion(
    db: DBSessionDep,
    payload: dict = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    """Live-validate a single criterion's DSL rule against a sample request object.

    Body: ``{rule, object}``. The ``ASSERT`` keyword is prepended if omitted.
    Returns ``{passed, message}``.
    """
    from src.common.compliance_dsl import evaluate_rule_on_object as eval_dsl
    rule = (payload.get("rule") or "").strip()
    if rule and not rule.upper().startswith("ASSERT"):
        rule = "ASSERT " + rule
    obj = payload.get("object") or {}
    try:
        passed, msg = eval_dsl(rule, obj)
        return {"passed": passed, "message": msg}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Rule validation failed: {e}")


@router.post("/authority/recompute-scheduled")
async def recompute_scheduled(
    db: DBSessionDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    """Manually trigger a DNAco recompute for every AR with a schedule set.

    The same routine the scheduled ``authority_dna_recompute`` job runs.
    """
    return manager.recompute_scheduled(db)


@router.get("/authority/relations/{relation_id}/review-tracking")
async def review_tracking(
    relation_id: str,
    db: DBSessionDep,
    reviews_manager: DataAssetReviewManagerDep,
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    result = manager.get_review_tracking(db, relation_id, reviews_manager=reviews_manager)
    if result is None:
        raise HTTPException(status_code=404, detail="Authority Relation not found")
    return result


@router.get("/authority/relations/{relation_id}/review-context")
async def review_context(
    relation_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    reviewer: str = Query(..., description="Reviewer principal (email/group)"),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_ONLY)),
):
    try:
        ctx = manager.get_review_context(db, relation_id, reviewer, user=current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if ctx is None:
        raise HTTPException(status_code=404, detail="No review found for this reviewer on this Authority Relation")
    return ctx


@router.post("/authority/participants/{participant_id}/submit-review")
async def submit_review(
    participant_id: str,
    db: DBSessionDep,
    current_user: AuditCurrentUserDep,
    payload: dict = Body(...),
    _: bool = Depends(PermissionChecker(FEATURE_ID, FeatureAccessLevel.READ_WRITE)),
):
    reviewer = current_user.username if current_user else None
    answers = payload.get("answers", payload) if isinstance(payload, dict) else {}
    try:
        participant = manager.submit_review(db, participant_id, answers=answers, reviewer=reviewer, user=current_user)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not participant:
        raise HTTPException(status_code=404, detail="Review participant not found")
    return {"id": participant.id, "review_status": participant.review_status}


def register_routes(app):
    """Register the Authority Resolution routes with the FastAPI app."""
    app.include_router(router)
