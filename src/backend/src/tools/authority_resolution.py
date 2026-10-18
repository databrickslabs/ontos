"""MCP tools for Authority Resolution.

``ResolveAuthorityTool`` is the differentiated agentic gate: an agent passes an
explicit Authority Relation id (or slug) plus the decision parameters and gets a
deterministic ``approved`` / ``denied`` / ``no_authority`` verdict with a
machine-readable reason — evaluated against the AR's compiled decision logic. It
never (re)computes the DNA-Coefficient; the DNAco gates *activation*, not the
per-decision verdict.

``ComputeDnaCoefficientTool`` is the explicit, write-scoped escape hatch an app
can call when it has reason to believe the cached DNA-Coefficient is stale (new
evidence landed, the authored criteria changed, or a drift signal fired) — the
same code path the ``POST /api/authority/relations/{id}/compute-dnaco`` endpoint
and the scheduled ``authority_dna_recompute`` job run through.
"""
from typing import Any

from starlette.concurrency import run_in_threadpool

from src.tools.base import BaseTool, ToolContext, ToolResult
from src.controller.authority_resolution_manager import AuthorityResolutionManager

_manager = AuthorityResolutionManager()


class ResolveAuthorityTool(BaseTool):
    name = "resolve_authority"
    description = (
        "Resolve whether a decision is authorized against a specific Authority "
        "Relation (ARF). Provide the Authority Relation id (or slug) and the "
        "decision parameters (who is signing off, the action, the value, whether "
        "a co-sign is present, whether it was escalated). Returns a deterministic "
        "verdict: 'approved', 'denied' (with a reason), or 'no_authority' when no "
        "active Authority Relation matches — in which case defer to a human. "
        "The response lists the prerequisite ARs walked (prerequisite_chain) and "
        "where each AR field value came from (resolved_refs)."
    )
    parameters = {
        "ar_id": {"type": "string", "description": "Authority Relation id or slug to resolve against."},
        "actor_identity": {"type": "string", "description": "The principal signing off / making the decision."},
        "action": {"type": "string", "description": "The governed action (e.g. approve)."},
        "object_id": {"type": "string", "description": "Identifier of the object the decision acts on."},
        "value": {"type": "number", "description": "The decision's numeric value (e.g. discount fraction) for threshold checks."},
        "cosign_present": {"type": "boolean", "description": "Whether a required co-sign is present."},
        "escalated": {"type": "boolean", "description": "Whether an over-threshold value was escalated."},
    }
    required_params = ["ar_id"]
    required_scope = "authority:read"
    category = "authority"

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        ar_id = kwargs.get("ar_id")
        if not ar_id:
            return ToolResult(success=False, error="ar_id is required")
        req = {
            "actor_identity": kwargs.get("actor_identity"),
            "action": kwargs.get("action"),
            "object_id": kwargs.get("object_id"),
            "value": kwargs.get("value"),
            "cosign_present": kwargs.get("cosign_present"),
            "escalated": kwargs.get("escalated"),
        }
        app_ws = ctx.workspace_client
        # Resolves may make blocking MCP/HTTP calls; keep them off the event loop.
        result = await run_in_threadpool(
            _manager.resolve,
            ctx.db, ar_id, req,
            semantic_models_manager=ctx.semantic_models_manager,
            obo_ws_factory=ctx.obo_workspace_client_factory,
            app_ws_factory=(lambda: app_ws) if app_ws is not None else None,
        )
        return ToolResult(success=True, data=result)


class FindAuthorityForConceptTool(BaseTool):
    name = "find_authority_for_concept"
    description = (
        "Find which Authority Relation (ARF) governs a decision about a Business "
        "Concept, without knowing the AR id. Provide the concept IRI and the "
        "decision context (e.g. brand, market, channel) and optionally the data "
        "domain. Returns ranked candidates with match scores, domain overlap and "
        "unmet prerequisites. 'resolved' is the AR slug to pass to "
        "resolve_authority — set only when exactly one AR applies; otherwise "
        "'reason' is 'ambiguous', 'prerequisites_unmet' or 'no_authority' and "
        "you should pick from the candidates or defer to a human."
    )
    parameters = {
        "concept_iri": {"type": "string", "description": "IRI of the Business Concept the decision is about."},
        "context": {"type": "object", "description": "Decision context, e.g. {\"brand\": \"Alpha Cola\", \"market\": \"DE\"}."},
        "domains": {"type": "array", "items": {"type": "string"}, "description": "Data domain ids or names the decision belongs to."},
        "request": {"type": "object", "description": "Decision parameters used to dry-run each candidate's prerequisite chain."},
    }
    required_params = ["concept_iri"]
    required_scope = "authority:read"
    category = "authority"

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        concept_iri = kwargs.get("concept_iri")
        if not concept_iri:
            return ToolResult(success=False, error="concept_iri is required")
        app_ws = ctx.workspace_client
        result = await run_in_threadpool(
            _manager.find_authority_for_concept,
            ctx.db, concept_iri,
            context=kwargs.get("context") or {},
            domains=kwargs.get("domains") or [],
            request=kwargs.get("request") or {},
            semantic_models_manager=ctx.semantic_models_manager,
            obo_ws_factory=ctx.obo_workspace_client_factory,
            app_ws_factory=(lambda: app_ws) if app_ws is not None else None,
        )
        return ToolResult(success=True, data=result)


class GetAuthorityRelationTool(BaseTool):
    name = "get_authority_relation"
    description = (
        "Fetch a single Authority Relation (ARF) by id or slug, including its "
        "current DNA-Coefficient, status, maturity level, and affirmations."
    )
    parameters = {
        "ar_id": {"type": "string", "description": "Authority Relation id or slug."},
    }
    required_params = ["ar_id"]
    required_scope = "authority:read"
    category = "authority"

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        ar_id = kwargs.get("ar_id")
        # By slug this returns the family's active version (the stable @id);
        # by UUID it returns that exact version.
        relation = _manager.resolve_relation_ref(ctx.db, ar_id)
        if not relation:
            return ToolResult(success=False, error=f"Authority Relation not found: {ar_id}")
        return ToolResult(success=True, data=_manager.to_read_dict(ctx.db, relation))


class ComputeDnaCoefficientTool(BaseTool):
    name = "compute_dna_coefficient"
    description = (
        "Recompute the DNA-Coefficient for an Authority Relation (ARF) by re-"
        "evaluating its authored criteria against the bound evidence sources. "
        "The DNA-Coefficient is a divergence measure (0.0 = documented authority "
        "matches lived practice, higher = worse) that gates the AR's activation. "
        "Use when new evidence has landed or the criteria have changed and the "
        "cached value is suspected stale. The AR row's dna_magnitude / "
        "dna_direction / dna_dimensions / dna_measured_at are updated in place "
        "and a new AuthorityDnaRun record is persisted."
    )
    parameters = {
        "ar_id": {"type": "string", "description": "Authority Relation id or slug to recompute. By slug the family's active version is used; by UUID that exact version is recomputed."},
    }
    required_params = ["ar_id"]
    required_scope = "authority:write"
    category = "authority"

    async def execute(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        ar_id = kwargs.get("ar_id")
        if not ar_id:
            return ToolResult(success=False, error="ar_id is required")
        relation = _manager.resolve_relation_ref(ctx.db, ar_id)
        if not relation:
            return ToolResult(success=False, error=f"Authority Relation not found: {ar_id}")
        try:
            run = _manager.compute_dnaco(ctx.db, relation.id)
        except Exception as e:
            return ToolResult(success=False, error=f"DNA-Coefficient computation failed: {e}")
        if not run:
            return ToolResult(success=False, error=f"Authority Relation not found: {ar_id}")
        return ToolResult(success=True, data={
            "run_id": run.id,
            "relation_id": relation.id,
            "status": run.status,
            "sampled_count": run.sampled_count,
            "divergent_count": run.divergent_count,
            "magnitude": run.magnitude,
            "direction": run.direction,
            "per_dimension_scores": run.per_dimension_scores,
            "error_message": run.error_message,
        })
