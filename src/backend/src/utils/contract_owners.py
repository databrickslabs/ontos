"""A contract's business owners in ODCS, as the custom property ``ontosOwners``.

The ODCS export merges the active business owners (the "Owners" card) into the
team, as members with a mapped role, for ODCS readers. That alone made a
re-import create team contacts, not owners. The export also writes them as
``[{"email", "name", "role"}]`` (``role`` is the business role's name); the
import restores each entry whose business role exists, and keeps the others as
a custom property.
"""
import uuid
from typing import Any, Dict, List, Optional, Tuple

from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb

ONTOS_OWNERS_PROPERTY = 'ontosOwners'


def owners_value(db, object_type: str, object_id: str) -> Optional[List[Dict[str, str]]]:
    """The property's value: the object's active owners, or None."""
    if db is None:
        return None
    rows = (
        db.query(BusinessOwnerDb)
        .filter(BusinessOwnerDb.object_type == object_type,
                BusinessOwnerDb.object_id == object_id,
                BusinessOwnerDb.is_active.is_(True))
        .order_by(BusinessOwnerDb.assigned_at, BusinessOwnerDb.user_email)
        .all()
    )
    out = []
    for row in rows:
        entry = {'email': row.user_email}
        if row.user_name:
            entry['name'] = row.user_name
        entry['role'] = row.role.name if row.role else None
        out.append(entry)
    return out or None


def take_owners(db, document: Dict[str, Any]) -> List[Tuple[Dict[str, Any], BusinessRoleDb]]:
    """The document's ``ontosOwners`` entries whose business role exists, with
    the role. They are removed from the document's custom properties; entries
    that can't be restored stay there."""
    props = document.get('customProperties')
    if not isinstance(props, list):
        return []
    entry = next((p for p in props if isinstance(p, dict)
                  and p.get('property') == ONTOS_OWNERS_PROPERTY), None)
    if entry is None or not isinstance(entry.get('value'), list):
        return []
    restored, kept = [], []
    for owner in entry['value']:
        role = None
        if isinstance(owner, dict) and owner.get('email') and owner.get('role'):
            role = db.query(BusinessRoleDb).filter(BusinessRoleDb.name == owner['role']).first()
        if role is None:
            kept.append(owner)
        else:
            restored.append((owner, role))
    if kept:
        entry['value'] = kept
    else:
        props.remove(entry)
    return restored


def restore_owners(db, object_type: str, object_id: str, owners, created_by: Optional[str]):
    """Assign the owners ``take_owners`` returned to the new object."""
    for owner, role in owners:
        db.add(BusinessOwnerDb(
            id=uuid.uuid4(), object_type=object_type, object_id=object_id,
            user_email=owner['email'], user_name=owner.get('name'), role_id=role.id,
            is_active=True, created_by=created_by,
        ))
