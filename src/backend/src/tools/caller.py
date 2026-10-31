"""Resolve the caller the assistant tools act for (Ask Ontos and MCP).

The tools check the caller's feature levels themselves (``check_tool_permission``
in ``src.tools.base``), so the levels are resolved here once per request, the
same way as the REST routes' ``PermissionChecker``.
"""

from typing import Any, Optional

from fastapi import Request

from src.common.authorization import resolve_effective_permissions
from src.common.logging import get_logger
from src.models.users import UserInfo
from src.tools.base import ToolCaller

logger = get_logger(__name__)

ASK_ONTOS_AUTH_PATH = "ask_ontos"
MCP_API_KEY_AUTH_PATH = "mcp_api_key"


async def resolve_tool_caller(user: UserInfo, request: Request, auth_path: str) -> ToolCaller:
    """Build the ``ToolCaller`` of a resolved user.

    When the levels can't be resolved the caller gets none (tools that need a
    level are refused) and the failure is logged; the request itself goes on.
    """
    groups = list(user.groups or [])
    try:
        permissions = dict(await resolve_effective_permissions(user.email, groups, request))
    except Exception:
        logger.error(
            "Could not resolve the feature levels of %s (auth path %s); "
            "tools that need one will be refused.",
            user.email,
            auth_path,
            exc_info=True,
        )
        permissions = {}
    return ToolCaller(
        email=user.email, auth_path=auth_path, groups=groups, permissions=permissions
    )


def mcp_api_key_caller(token_info: Any) -> ToolCaller:
    """The caller of an MCP request that has an API key and no forwarded user.

    # Open decision: what an API-key client with no forwarded user may do.
    # Today it acts as the token's creator (only Ontos admins mint tokens) with
    # no feature checks, limited by the token's scopes only; that is kept here.
    # The alternative under discussion is to resolve the creator's levels or to
    # give such clients consumer visibility only. Change it here, nowhere else.
    """
    created_by: Optional[str] = getattr(token_info, "created_by", None)
    return ToolCaller(email=created_by, auth_path=MCP_API_KEY_AUTH_PATH, full_access=True)
