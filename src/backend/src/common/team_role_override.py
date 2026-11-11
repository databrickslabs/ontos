"""Team role override resolution, shared by request authorization and the teams self-lockout guard."""
from typing import Iterable, List


def team_role_overrides(teams: Iterable, user_identifier: str, user_groups: List[str]) -> List[str]:
    """Every app role override from team entries that apply to the user, in team order, once each.

    An entry applies when its identifier is the user's (case-insensitive) or one of the
    user's groups, in any of the given teams. The user's own entries come first. For
    permissions the roles are combined by highest level per feature, so the order
    doesn't change the result.
    """
    identifier = (user_identifier or "").strip().lower()
    groups = {g.strip().lower() for g in user_groups or [] if g}
    direct: List[str] = []
    via_group: List[str] = []
    for team in teams:
        for member in team.members:
            role = (member.app_role_override or "").strip()
            if not role:
                continue
            member_identifier = (member.member_identifier or "").strip().lower()
            if identifier and member_identifier == identifier:
                direct.append(role)
            elif member_identifier in groups:
                via_group.append(role)
    # The user's own entries first, as before #1245: callers that need one role name
    # (comment audiences) keep getting the user's own override.
    roles: List[str] = []
    for role in direct + via_group:
        if role not in roles:
            roles.append(role)
    return roles
