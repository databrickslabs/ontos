"""
Access Policies tools for LLM / MCP.

Deterministic access checks against the active W3C ODRL Access Policies, plus
read access to policies, audiences and the Ontos ODRL profile.
"""

from typing import Any, Dict, List, Optional

from src.common import odrl
from src.common.logging import get_logger
from src.tools.base import BaseTool, ToolContext, ToolResult, tool_failure

logger = get_logger(__name__)


def _manager():
    from src.controller.access_policies_manager import AccessPoliciesManager
    return AccessPoliciesManager()


class CheckAccessTool(BaseTool):
    """Can a principal perform an action on an asset under the active Access Policies?"""

    name = "check_access"
    category = "governance"
    description = (
        "Decide deterministically whether a principal may perform an action on a data asset, "
        "evaluated against the ACTIVE W3C ODRL Access Policies. Returns a verdict "
        "(allow | deny | conditional | not_applicable), an explanation, matching rules and any "
        "pending duties (e.g. ontos:acknowledgeTerms) that must be fulfilled first. "
        "Assets are UC refs like 'uc:catalog.schema.table' (a catalog/schema covers its children)."
    )
    parameters = {
        "principal": {"type": "string", "description": "User email or service principal id."},
        "action": {"type": "string", "description": "Profile action, e.g. read, modify, ontos:create, ontos:manage."},
        "asset": {"type": "string", "description": "Asset ref, e.g. uc:main.sales.orders."},
        "principal_groups": {"type": "array", "items": {"type": "string"},
                             "description": "Identity-provider groups of the principal."},
        "asset_attributes": {"type": "object",
                             "description": "Asset attributes keyed by leftOperand (ontos:domain, ontos:tag, ontos:classification)."},
        "context": {"type": "object", "description": "Request context keyed by leftOperand (purpose, spatial, dateTime)."},
        "fulfilled_duties": {"type": "array", "items": {"type": "string"},
                             "description": "Duty actions already fulfilled (e.g. ontos:acknowledgeTerms)."},
    }
    required_params = ["principal", "action", "asset"]
    required_scope = "access-policies:read"

    async def execute(self, ctx: ToolContext, principal: str = "", action: str = "", asset: str = "",
                      principal_groups: Optional[List[str]] = None, asset_attributes: Optional[Dict[str, Any]] = None,
                      context: Optional[Dict[str, Any]] = None, fulfilled_duties: Optional[List[str]] = None,
                      **_: Any) -> ToolResult:
        from src.models.access_policies import CheckAccessRequest
        try:
            req = CheckAccessRequest(
                principal=principal, action=action, asset=asset,
                principal_groups=principal_groups or [], asset_attributes=asset_attributes or {},
                context=context or {}, fulfilled_duties=fulfilled_duties or [],
            )
            return ToolResult(success=True, data=_manager().check_access(ctx.db, req))
        except Exception as e:
            return ToolResult(success=False, **tool_failure("check_access", e))


class ListAccessPoliciesTool(BaseTool):
    """List Access Policies (one row per version family)."""

    name = "list_access_policies"
    category = "governance"
    description = (
        "List W3C ODRL Access Policies (latest relevant version per family) with status, version, "
        "policy type and rule counts. Optionally filter by status (e.g. 'active')."
    )
    parameters = {
        "status": {"type": "string", "description": "Optional status filter: draft, under_review, approved, active, deprecated, retired."},
    }
    required_params: List[str] = []
    required_scope = "access-policies:read"

    async def execute(self, ctx: ToolContext, status: Optional[str] = None, **_: Any) -> ToolResult:
        from src.controller.access_policies_manager import KIND_POLICY
        mgr = _manager()
        rows = mgr.list(ctx.db, KIND_POLICY, status=status)
        items = []
        for r in rows:
            d = mgr.to_read_dict(ctx.db, KIND_POLICY, r)
            items.append({k: d[k] for k in ("id", "uid", "name", "description", "status", "version",
                                            "policy_type", "conflict", "rule_counts")})
        return ToolResult(success=True, data={"policies": items, "total_count": len(items)})


class GetAccessPolicyTool(BaseTool):
    """Get one Access Policy as ODRL JSON-LD."""

    name = "get_access_policy"
    category = "governance"
    description = (
        "Get an Access Policy by id as a W3C ODRL JSON-LD document (rules, assignees, targets, "
        "constraints, duties), plus its lifecycle status and validation issues."
    )
    parameters = {"policy_id": {"type": "string", "description": "Access Policy id (UUID)."}}
    required_params = ["policy_id"]
    required_scope = "access-policies:read"

    async def execute(self, ctx: ToolContext, policy_id: str = "", **_: Any) -> ToolResult:
        from src.controller.access_policies_manager import KIND_POLICY
        mgr = _manager()
        row = mgr.get(ctx.db, KIND_POLICY, policy_id)
        if not row:
            return ToolResult(success=False, error=f"Access Policy {policy_id} not found")
        issues = mgr.validate_body(ctx.db, row.policy_type, row.conflict, row.inherit_from or [], row.body or {})
        return ToolResult(success=True, data={
            "id": row.id, "status": row.status, "version": row.version,
            "document": mgr.to_jsonld(ctx.db, row), "issues": issues,
        })


class GetOdrlProfileTool(BaseTool):
    """The Ontos ODRL profile vocabulary."""

    name = "get_odrl_profile"
    category = "governance"
    description = (
        "Return the Ontos ODRL profile: allowed actions (with includedIn hierarchy), constraint "
        "left operands (with enforcement class: platform | workflow | advisory) and operators."
    )
    parameters: Dict[str, Any] = {}
    required_params: List[str] = []
    required_scope = "access-policies:read"

    async def execute(self, ctx: ToolContext, **_: Any) -> ToolResult:
        return ToolResult(success=True, data=odrl.profile_vocabulary())
