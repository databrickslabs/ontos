"""Team role override resolution, shared by request authorization and the teams self-lockout guard."""
from typing import Iterable, List, Optional


def pick_team_role_override(teams: Iterable, user_identifier: str, user_groups: List[str]) -> Optional[str]:
    """Pick the team role override for a user from the teams they are a direct member of.

    Direct entries win over the user's group entries in those same teams; within each kind the
    first match in team order wins (there is no role hierarchy yet).
    """
    user_groups_lower = {g.lower() for g in user_groups or []}
    teams = list(teams)
    direct = [
        member.app_role_override
        for team in teams for member in team.members
        if member.app_role_override and member.member_identifier == user_identifier
    ]
    via_group = [
        member.app_role_override
        for team in teams for member in team.members
        if member.app_role_override and member.member_identifier.lower() in user_groups_lower
    ]
    overrides = direct + via_group
    return overrides[0] if overrides else None
