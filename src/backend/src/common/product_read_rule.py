"""The data product read rule, shared by the product routes and the assistant tools.

Published products (active/deprecated) are readable by everyone. Any other
status is readable by data-products admins and by the product's owners: its
draft owner, a member of its owning team, or a member of its project.
"""

from types import SimpleNamespace
from typing import Any, Iterable, List, Optional, Set

from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger

logger = get_logger(__name__)

DATA_PRODUCTS_FEATURE_ID = "data-products"


def _status_of(product: Any) -> str:
    raw = getattr(product, "status", None)
    return raw.value if hasattr(raw, "value") else str(raw or "")


def is_published_product(product: Any) -> bool:
    """Whether every caller may read ``product`` (published lifecycle status)."""
    from src.common.version_visibility import is_visible_consumer

    return is_visible_consumer(SimpleNamespace(status=_status_of(product)))


def is_product_read_admin(request: Any, user: Any) -> bool:
    """Whether ``user`` reads every product: data-products Admin from its groups.

    An applied role override wins over the groups (no team role override), as
    in the product page's gate.
    """
    if not user:
        return False
    auth_manager = getattr(request.app.state, "authorization_manager", None)
    if not auth_manager:
        return False
    settings_manager = getattr(request.app.state, "settings_manager", None)
    applied_role_id = (
        settings_manager.get_applied_role_override_for_user(user.email)
        if settings_manager else None
    )
    if applied_role_id and settings_manager:
        eff = settings_manager.get_feature_permissions_for_role_id(applied_role_id)
    else:
        eff = auth_manager.get_user_effective_permissions(user.groups or [], None)
    return auth_manager.has_permission(eff, DATA_PRODUCTS_FEATURE_ID, FeatureAccessLevel.ADMIN)


def lookup_team_ids(db: Any, caller_email: Optional[str], caller_groups: Iterable[str]) -> Set[str]:
    """The ids of the teams the caller is a member of (one lookup)."""
    if not caller_email:
        return set()
    from src.controller.teams_manager import teams_manager

    teams = teams_manager.get_teams_for_user(db, caller_email, list(caller_groups or []))
    return {str(t.id) for t in teams if getattr(t, "id", None)}


# ``caller_project_ids`` not given: check the product's project with one query.
LOOKUP = object()
# ``caller_project_ids`` value for a caller who is a member of every project
# (configured admin groups, as in ``is_user_project_member``).
ALL_PROJECTS = None


def lookup_member_project_ids(
    db: Any, caller_email: Optional[str], caller_groups: Iterable[str]
) -> Optional[Set[str]]:
    """The projects the caller is a member of, in one query (``ALL_PROJECTS`` for admins).

    The same rule as ``projects_manager.is_user_project_member``: a member of
    any team assigned to the project, by email or group, case-insensitive.
    """
    from sqlalchemy import func

    from src.common.authorization import is_user_admin
    from src.common.config import get_settings
    from src.db_models.projects import project_team_association
    from src.db_models.teams import TeamMemberDb

    groups = list(caller_groups or [])
    if is_user_admin(groups, get_settings()):
        return ALL_PROJECTS
    identifiers = {str(i).lower() for i in [caller_email, *groups] if i}
    if not identifiers:
        return set()
    rows = (
        db.query(project_team_association.c.project_id)
        .join(TeamMemberDb, TeamMemberDb.team_id == project_team_association.c.team_id)
        .filter(func.lower(TeamMemberDb.member_identifier).in_(identifiers))
        .distinct()
        .all()
    )
    return {str(r[0]) for r in rows}


def caller_owns_product(
    db: Any,
    product: Any,
    *,
    caller_email: Optional[str],
    caller_groups: Iterable[str],
    caller_team_ids: Optional[Set[str]] = None,
    caller_project_ids: Any = LOOKUP,
) -> bool:
    """Whether the caller owns *this* product: draft owner, owning team or project member.

    Membership is resolved against the product only, never through a broad
    listing scope (ONT-NEG-011). ``caller_team_ids`` is looked up when not given;
    ``caller_project_ids`` (from ``lookup_member_project_ids``) saves the
    per-product project query when many products are checked.
    """
    if not caller_email:
        return False
    groups: List[str] = list(caller_groups or [])

    owner_email = getattr(product, "draft_owner_id", None)
    if owner_email and str(owner_email).lower() == str(caller_email).lower():
        return True

    product_team_id = getattr(product, "owner_team_id", None)
    if product_team_id:
        try:
            team_ids = (
                caller_team_ids if caller_team_ids is not None
                else lookup_team_ids(db, caller_email, groups)
            )
            if str(product_team_id) in team_ids:
                return True
        except Exception:
            logger.exception(
                "Team-membership resolution failed for %s in product read gate", caller_email
            )

    product_project_id = getattr(product, "project_id", None)
    if product_project_id and caller_project_ids is not LOOKUP:
        return caller_project_ids is ALL_PROJECTS or str(product_project_id) in caller_project_ids
    if product_project_id:
        try:
            from src.common.config import get_settings
            from src.controller.projects_manager import projects_manager

            # ``is_user_project_member`` uses the configured admin groups, not a
            # substring match, and checks real team membership of the project.
            if projects_manager.is_user_project_member(
                db=db,
                user_identifier=caller_email,
                user_groups=groups,
                project_id=str(product_project_id),
                settings=get_settings(),
            ):
                return True
        except Exception:
            logger.exception(
                "Project-membership resolution failed for %s in product read gate", caller_email
            )
    return False


def can_read_product(
    db: Any,
    product: Any,
    *,
    is_admin: bool,
    caller_email: Optional[str],
    caller_groups: Iterable[str],
    caller_team_ids: Optional[Set[str]] = None,
    caller_project_ids: Any = LOOKUP,
) -> bool:
    """The read rule for one product, with the caller's facts resolved by the caller."""
    if is_published_product(product) or is_admin:
        return True
    return caller_owns_product(
        db, product,
        caller_email=caller_email, caller_groups=caller_groups, caller_team_ids=caller_team_ids,
        caller_project_ids=caller_project_ids,
    )
