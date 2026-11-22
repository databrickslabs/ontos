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
set by hand is never lowered. ``feature_permissions`` is TEXT holding JSON, so
it is cast to jsonb and back. The downgrade removes only the keys whose value
is still the level this migration set.
"""
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
    return bool(conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'app_roles')"
    )).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    for role_name, level in _GRANTS.items():
        # Only where the role has no effective access yet (absent or 'None').
        conn.execute(
            sa.text("""
                UPDATE app_roles
                SET feature_permissions = jsonb_set(
                    feature_permissions::jsonb,
                    '{authority-resolution}',
                    to_jsonb(cast(:level as text)),
                    true
                )::text
                WHERE name = :role_name
                  AND COALESCE(feature_permissions::jsonb ->> 'authority-resolution', 'None') = 'None'
            """),
            {"level": level, "role_name": role_name},
        )


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    for role_name, level in _GRANTS.items():
        conn.execute(
            sa.text("""
                UPDATE app_roles
                SET feature_permissions = (feature_permissions::jsonb - 'authority-resolution')::text
                WHERE name = :role_name
                  AND feature_permissions::jsonb ->> 'authority-resolution' = cast(:level as text)
            """),
            {"role_name": role_name, "level": level},
        )
