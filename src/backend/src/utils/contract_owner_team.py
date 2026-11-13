"""A contract's owner team in ODCS, as the custom property ``ontosOwnerTeam``.

ODCS has no field for the Ontos owner team (``data_contracts.owner_team_id``).
The export writes it as ``{"id": ..., "name": ...}``, in the ``ontos*`` style of
the other round-trip properties; the import resolves it to an existing team, by
id and then by name, and keeps it as a custom property when no team matches.
"""
from typing import Any, Dict, Optional

from src.db_models.teams import TeamDb

ONTOS_OWNER_TEAM_PROPERTY = 'ontosOwnerTeam'


def owner_team_value(db, team_id: Optional[str]) -> Optional[Dict[str, str]]:
    """The property's value for the owner team ``team_id``, or None."""
    if not team_id or db is None:
        return None
    team = db.get(TeamDb, team_id)
    return {'id': team.id, 'name': team.name} if team else {'id': team_id}


def _resolve(db, value: Any) -> Optional[str]:
    if isinstance(value, str):
        value = {'name': value}
    if not isinstance(value, dict):
        return None
    if value.get('id') and db.get(TeamDb, value['id']) is not None:
        return value['id']
    if value.get('name'):
        team = db.query(TeamDb).filter(TeamDb.name == value['name']).first()
        if team is not None:
            return team.id
    return None


def pop_owner_team(db, document: Dict[str, Any]) -> Optional[str]:
    """The id of the existing team the document's ``ontosOwnerTeam`` names,
    or None. A resolved entry is removed from the document's custom
    properties (the owner team column holds it); an unresolved one stays."""
    props = document.get('customProperties')
    if isinstance(props, dict):
        if ONTOS_OWNER_TEAM_PROPERTY not in props:
            return None
        team_id = _resolve(db, props[ONTOS_OWNER_TEAM_PROPERTY])
        if team_id:
            props.pop(ONTOS_OWNER_TEAM_PROPERTY)
        return team_id
    if not isinstance(props, list):
        return None
    for entry in props:
        if isinstance(entry, dict) and entry.get('property') == ONTOS_OWNER_TEAM_PROPERTY:
            team_id = _resolve(db, entry.get('value'))
            if team_id:
                props.remove(entry)
            return team_id
    return None
