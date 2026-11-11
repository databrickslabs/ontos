"""Team role override resolution, shared by request authorization and the teams self-lockout guard."""
from typing import Iterable, List, Optional


def team_role_overrides(teams: Iterable, user_identifier: str, user_groups: List[str]) -> List[str]:
    """Every app role override from team entries that apply to the user, in team order, once each.

    An entry applies when its identifier is the user's (case-insensitive) or one of the
    user's groups, in any of the given teams. The roles are combined with the user's
    other roles by highest level per feature, so their order doesn't change the result.
    """
    identifier = (user_identifier or "").strip().lower()
    groups = {g.strip().lower() for g in user_groups or [] if g}
    roles: List[str] = []
    for team in teams:
        for member in team.members:
            role = (member.app_role_override or "").strip()
            if not role:
                continue
            member_identifier = (member.member_identifier or "").strip().lower()
            if (identifier and member_identifier == identifier) or member_identifier in groups:
                if role not in roles:
                    roles.append(role)
    return roles


def pick_team_role_override(teams: Iterable, user_identifier: str, user_groups: List[str]) -> Optional[str]:
    """The first applying team role override, for callers that need a single role name.

    Permission checks use every override (``team_role_overrides``); this is kept for
    role-name matching such as comment audiences (``role:<name>``).
    """
    roles = team_role_overrides(teams, user_identifier, user_groups)
    return roles[0] if roles else None
