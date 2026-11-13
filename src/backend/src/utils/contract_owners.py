"""A contract's business owners in ODCS, as the custom property ``ontosOwners``.

The ODCS export merges the active business owners (the "Owners" card) into the
team, as members with a mapped role, for ODCS readers; each such member carries
the marker custom property ``ontosBusinessOwner`` (ODCS v3.1.0+ team members
have custom properties). The export also writes the owners as
``[{"email", "name", "role"}]`` (``role`` is the business role's name). The
import restores an entry as an owner when the importer may assign owners
(``business-owners`` write, as ``POST /api/business-owners`` requires) and its
business role exists, and then leaves out the marked team member the export
added for it. Everything else stays: entries in the custom property, members in
the team.
"""
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb

ONTOS_OWNERS_PROPERTY = 'ontosOwners'
# On a team member the export added for a business owner
OWNER_MEMBER_MARKER = 'ontosBusinessOwner'
_EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


@dataclass
class OwnerRestorer:
    """Whether the importer may assign owners, and the audit of each one
    assigned (``audit(details)``, as the business owners route logs it)."""
    allowed: bool = False
    audit: Optional[Callable[[Dict[str, Any]], None]] = None
    restored: List[Dict[str, Any]] = field(default_factory=list)


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


def unrestored_owners(custom_properties: Any, owners: List[Dict[str, str]]) -> List[Any]:
    """The stored ``ontosOwners`` entries (kept by an import that couldn't
    restore them) that aren't among ``owners``."""
    stored = next((cp.get('value') for cp in custom_properties or []
                   if isinstance(cp, dict) and cp.get('property') == ONTOS_OWNERS_PROPERTY), None)
    if not isinstance(stored, list):
        return []
    current = {(o['email'].lower(), o.get('role')) for o in owners}
    out = []
    for entry in stored:
        key = None
        if (isinstance(entry, dict) and isinstance(entry.get('email'), str)
                and isinstance(entry.get('role'), str)):
            key = (entry['email'].strip().lower(), entry['role'].strip())
        if key not in current:
            out.append(entry)
    return out


def is_owner_member(member: Any) -> bool:
    """A team member the export added for a business owner (it has the marker)."""
    if not isinstance(member, dict) or not isinstance(member.get('customProperties'), list):
        return False
    return any(isinstance(cp, dict) and cp.get('property') == OWNER_MEMBER_MARKER
               for cp in member['customProperties'])


def _clean(owner: Any) -> Optional[Dict[str, str]]:
    """The entry with stripped strings, or None when it isn't a valid owner."""
    if not isinstance(owner, dict):
        return None
    email, role, name = owner.get('email'), owner.get('role'), owner.get('name')
    if not isinstance(email, str) or not isinstance(role, str):
        return None
    if name is not None and not isinstance(name, str):
        return None
    email, role = email.strip(), role.strip()
    if not _EMAIL.match(email) or not role:
        return None
    out = {'email': email, 'role': role}
    if name and name.strip():
        out['name'] = name.strip()
    return out


def take_owners(db, document: Dict[str, Any], restorer: Optional[OwnerRestorer]
                ) -> List[Tuple[Dict[str, str], BusinessRoleDb]]:
    """The document's ``ontosOwners`` entries that can be restored, with their
    role, once each (by email and role). They are removed from the document's
    custom properties; the others (not allowed, unknown role, invalid,
    duplicate) stay there."""
    if restorer is None or not restorer.allowed:
        return []
    props = document.get('customProperties')
    if not isinstance(props, list):
        return []
    entry = next((p for p in props if isinstance(p, dict)
                  and p.get('property') == ONTOS_OWNERS_PROPERTY), None)
    if entry is None or not isinstance(entry.get('value'), list):
        return []
    restored, kept, seen = [], [], set()
    for raw in entry['value']:
        owner = _clean(raw)
        role = None
        if owner is not None:
            role = db.query(BusinessRoleDb).filter(BusinessRoleDb.name == owner['role']).first()
        key = (owner['email'].lower(), role.id) if role is not None else None
        if role is None or key in seen:
            kept.append(raw)
            continue
        seen.add(key)
        restored.append((owner, role))
    if kept:
        entry['value'] = kept
    else:
        props.remove(entry)
    return restored


def restore_owners(db, object_type: str, object_id: str, owners,
                   restorer: Optional[OwnerRestorer], created_by: Optional[str]) -> None:
    """Assign the owners ``take_owners`` returned to the new object (an owner
    already active with that role is skipped)."""
    for owner, role in owners:
        active = db.query(BusinessOwnerDb).filter(
            BusinessOwnerDb.object_type == object_type, BusinessOwnerDb.object_id == object_id,
            BusinessOwnerDb.role_id == role.id, BusinessOwnerDb.is_active.is_(True),
        ).all()
        if any(row.user_email.lower() == owner['email'].lower() for row in active):
            continue
        row_id = uuid.uuid4()
        db.add(BusinessOwnerDb(
            id=row_id, object_type=object_type, object_id=object_id,
            user_email=owner['email'], user_name=owner.get('name'), role_id=role.id,
            is_active=True, created_by=created_by,
        ))
        db.flush()
        if restorer is not None:
            restorer.restored.append({
                "params": {"object": f"{object_type}:{object_id}", "user": owner['email'],
                           "role_id": str(role.id)},
                "created_resource_id": str(row_id),
            })


def audit_restored(restorer: Optional[OwnerRestorer]) -> None:
    """Log each owner assigned (after the import committed), as the route does."""
    if restorer is None or restorer.audit is None:
        return
    for details in restorer.restored:
        restorer.audit(details)
    restorer.restored.clear()
