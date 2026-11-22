"""The caller and the audit entries of the assistant write tools.

A tool that changes an entity writes the audit entry of the REST route doing
the same change (same feature and action), with the caller as username and
the tool name and auth path in the details, for Ask Ontos and MCP alike.
"""

from contextlib import contextmanager
from typing import Any, Dict, Optional

from src.tools.base import ToolContext


def caller_email(ctx: ToolContext) -> Optional[str]:
    """The caller's email: the user the REST routes pass to the managers and workflows."""
    return ctx.caller.email if ctx.caller else None


def audit_change(
    ctx: ToolContext, feature: str, tool_name: str, action: str, success: bool,
    details: Dict[str, Any],
) -> None:
    """Write the ``feature`` audit entry of the REST route doing the same change."""
    # The module, not the function, so tests can replace log_system_action.
    from src.controller import audit_manager

    caller = ctx.caller
    audit_manager.log_system_action(
        username=(caller.email or caller.auth_path) if caller else "unknown",
        feature=feature,
        action=action,
        success=success,
        details={
            **details,
            "tool_name": tool_name,
            "auth_path": caller.auth_path if caller else None,
        },
    )


@contextmanager
def audited(
    ctx: ToolContext, feature: str, tool_name: str, action: str, details: Dict[str, Any]
):
    """Audit the change in the block once it ends: failed unless it sets ``success``."""
    outcome = {"success": False}
    try:
        yield outcome
    finally:
        audit_change(ctx, feature, tool_name, action, outcome["success"], details)
