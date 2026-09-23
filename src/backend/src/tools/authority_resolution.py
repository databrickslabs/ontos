"""MCP tools for Authority Resolution.

``ResolveAuthorityTool`` is the differentiated agentic gate: an agent passes an
explicit Authority Relation id (or slug) plus the decision parameters and gets a
deterministic ``approved`` / ``denied`` / ``no_authority`` verdict with a
machine-readable reason — evaluated against the AR's compiled decision logic. It
never (re)computes the DNA-Coefficient; the DNAco gates *activation*, not the
per-decision verdict.
"""
from typing import Any

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
        "active Authority Relation matches — in which case defer to a human."
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
        result = _manager.resolve(ctx.db, ar_id, req)
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
        relation = _manager.get_relation(ctx.db, ar_id) or _manager.get_relation_by_slug(ctx.db, ar_id)
        if not relation:
            return ToolResult(success=False, error=f"Authority Relation not found: {ar_id}")
        return ToolResult(success=True, data=_manager.to_read_dict(ctx.db, relation))
