"""Resolve the caller the assistant tools act for (Ask Ontos and MCP).

The tools check the caller's feature levels and read rules themselves
(``check_tool_permission`` in ``src.tools.base``, ``src.tools.read_access``),
so everything they need is resolved here once per request, the same way as
the REST routes: the levels like ``PermissionChecker``, the admin flags like
the product and contract read rules, and the caller's teams in one lookup.
"""

from typing import Any, Dict

from fastapi import Request

from src.common.authorization import is_user_feature_admin, resolve_effective_permissions
from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.product_read_rule import (
    is_product_read_admin,
    lookup_member_project_ids,
    lookup_team_ids,
)
from src.models.users import UserInfo
from src.tools.base import ToolCaller

logger = get_logger(__name__)

ASK_ONTOS_AUTH_PATH = "ask_ontos"
MCP_API_KEY_AUTH_PATH = "mcp_api_key"
MCP_FORWARDED_TOKEN_AUTH_PATH = "mcp_forwarded_token"


async def resolve_tool_caller(
    user: UserInfo, request: Request, auth_path: str, db: Any = None
) -> ToolCaller:
    """Build the ``ToolCaller`` of a resolved user.

    Each part that can't be resolved falls back to the least: no levels (tools
    that need one are refused), not admin, no teams (only published products
    and contracts, plus the caller's own drafts). The failure is logged; the
    request itself goes on.
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

    try:
        products_admin = bool(is_product_read_admin(request, user))
    except Exception:
        logger.error("Could not resolve the product read admin flag of %s", user.email,
                     exc_info=True)
        products_admin = False
    contracts_admin = await is_user_feature_admin(
        user_email=user.email, user_groups=groups, feature_id="data-contracts", request=request
    )

    team_ids: set = set()
    if db is not None and not (products_admin and contracts_admin):
        try:
            team_ids = lookup_team_ids(db, user.email, groups)
        except Exception:
            logger.error("Could not resolve the teams of %s (auth path %s)", user.email,
                         auth_path, exc_info=True)
    project_ids: Any = set()
    if db is not None:
        try:
            project_ids = lookup_member_project_ids(db, user.email, groups)
        except Exception:
            logger.error("Could not resolve the projects of %s (auth path %s)", user.email,
                         auth_path, exc_info=True)
    return ToolCaller(
        email=user.email,
        auth_path=auth_path,
        groups=groups,
        permissions=permissions,
        products_admin=products_admin,
        contracts_admin=contracts_admin,
        team_ids=team_ids,
        project_ids=project_ids,
    )


# MCP token scope prefix -> the feature it reads (the tools' ``required_scope``).
SCOPE_FEATURES = {
    "data-products": "data-products",
    "contracts": "data-contracts",
    "domains": "data-domains",
    "teams": "teams",
    "projects": "projects",
    "semantic": "semantic-models",
    "tags": "tags",
}


def scope_read_levels(scopes: Any) -> Dict[str, FeatureAccessLevel]:
    """Read-only on each feature a token scope names (``<prefix>:read``,
    ``<prefix>:write`` or ``<prefix>:*``); ``*`` names them all."""
    levels: Dict[str, FeatureAccessLevel] = {}
    for scope in scopes or []:
        scope = str(scope)
        if scope == "*":
            return {f: FeatureAccessLevel.READ_ONLY for f in SCOPE_FEATURES.values()}
        feature = SCOPE_FEATURES.get(scope.split(":", 1)[0])
        if feature:
            levels[feature] = FeatureAccessLevel.READ_ONLY
    return levels


def mcp_api_key_caller(token_info: Any) -> ToolCaller:
    """The caller of an MCP request that has an API key and no forwarded user token.

    # Open decision (the policy for API-key clients without a user, decided as
    # consumer-only on 2026-10-30, read levels from the scopes on 2026-10-31):
    # the caller has no identity and no teams, and Read-only on the features
    # its token's scopes name (``scope_read_levels``). So it reads only
    # published products and contracts, only with ``data-products:*`` /
    # ``contracts:*`` (or ``*``) scopes, and every tool that changes data is
    # refused; the scopes still limit which tools it may call. The previous
    # behaviour (act as the token's creator, with no checks) is
    # ``ToolCaller(..., full_access=True)``. Change it here, nowhere else.
    """
    return ToolCaller(
        email=None,
        auth_path=MCP_API_KEY_AUTH_PATH,
        permissions=scope_read_levels(getattr(token_info, "scopes", None)),
    )
