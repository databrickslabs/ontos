"""Grant the Authority Resolution feature to the default roles (ARF 1.2.0, R7)

Revision ID: ak4_authority_resolution_grants
Revises: ak3_merge_ak2_s2
Create Date: 2026-11-22

Existing installs were seeded before ``authority-resolution`` had any grant
outside Admin, and ``ensure_default_roles_exist`` skips existing databases, so
the new defaults reach fresh installs only. This backfills the same levels:

  - Admin, Data Governance Officer : Admin       (activate, retire, ceiling, delete)
  - Data Steward                   : Read/Write  (author drafts, review, affirm, test)
  - Security Officer, Data Producer, Data Consumer : Read-only (view, resolve)

Additive and idempotent: a role gets the feature only where it has NO effective
access (the key is absent, or present with 'None'), so a real grant an admin
set by hand is never lowered. ``feature_permissions`` is a TEXT column holding
a JSON object. The migration reads each role's JSON, computes the change with
``grants_to_add`` (the function the tests cover, and the one upgrade() runs),
and writes the JSON back. That keeps the logic in one place and works on any
dialect. The downgrade removes only the keys whose value is still the level this
migration set.
"""
import json
from typing import Dict, Mapping, Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ak4_authority_resolution_grants'
down_revision: Union[str, None] = 'ak3_merge_ak2_s2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FEATURE_ID = 'authority-resolution'

# role name -> level. Strings are the FeatureAccessLevel values as stored in
# app_roles.feature_permissions ("Admin" / "Read/Write" / "Read-only" / "None").
_GRANTS: Dict[str, str] = {
    'Admin': 'Admin',
    'Data Governance Officer': 'Admin',
    'Data Steward': 'Read/Write',
    'Security Officer': 'Read-only',
    'Data Producer': 'Read-only',
    'Data Consumer': 'Read-only',
}


def grants_to_add(role_name: str, feature_permissions: Optional[Mapping[str, str]]) -> Dict[str, str]:
    """The ``{feature_id: level}`` this migration adds to a role, given its current grants.

    Empty when the role has no default for the feature, or already has a level
    for it other than 'None' (an admin's grant, or a level set by hand, stays).
    """
    level = _GRANTS.get(role_name)
    if level is None:
        return {}
    current = (feature_permissions or {}).get(FEATURE_ID)
    if current not in (None, 'None'):
        return {}
    return {FEATURE_ID: level}


def _table_exists(conn) -> bool:
    return sa.inspect(conn).has_table('app_roles')


def _read_permissions(raw: Optional[str]) -> Dict[str, str]:
    """A role's feature_permissions as a dict; anything that isn't a JSON object is empty."""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    rows = conn.execute(sa.text("SELECT name, feature_permissions FROM app_roles")).fetchall()
    for name, raw in rows:
        permissions = _read_permissions(raw)
        added = grants_to_add(name, permissions)
        if not added:
            continue
        permissions.update(added)
        conn.execute(
            sa.text("UPDATE app_roles SET feature_permissions = :permissions WHERE name = :name"),
            {"permissions": json.dumps(permissions), "name": name},
        )


def downgrade() -> None:
    """Remove the key only where it still holds the level this migration set."""
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    rows = conn.execute(sa.text("SELECT name, feature_permissions FROM app_roles")).fetchall()
    for name, raw in rows:
        permissions = _read_permissions(raw)
        if name not in _GRANTS or permissions.get(FEATURE_ID) != _GRANTS[name]:
            continue
        del permissions[FEATURE_ID]
        conn.execute(
            sa.text("UPDATE app_roles SET feature_permissions = :permissions WHERE name = :name"),
            {"permissions": json.dumps(permissions), "name": name},
        )
