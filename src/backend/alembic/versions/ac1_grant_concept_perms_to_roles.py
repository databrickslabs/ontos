"""Grant concept (semantic-models + term-mapping) permissions to default roles

Revision ID: ac1_grant_concept_perms
Revises: ab1_repair_null_owned_rows
Create Date: 2026-08-18

No non-admin role could work with Concepts: the default roles were seeded with
`business-glossary` but never `semantic-models` (the "Concept Browser" feature)
or `term-mapping` (Enrich). `ensure_default_roles_exist` skips existing DBs, so
updating DEFAULT_ROLE_PERMISSIONS only helps fresh installs — existing customers
(and cbv2b) need this backfill.

Additive + idempotent: only sets a key when the role LACKS it, so it never
downgrades an admin's explicit grant or a hand-edited role. Levels mirror the
in-code defaults:
  - Data Governance Officer : admin      (concept approver/certifier)
  - Data Steward            : read_write (concept author/curator)
  - Data Consumer / Producer: read_only  (browse)
feature_permissions is TEXT holding JSON, so we cast to jsonb and back.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ac1_grant_concept_perms'
down_revision: Union[str, None] = 'ab1_repair_null_owned_rows'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# role name -> {feature_id: level}. Levels are the FeatureAccessLevel STRING
# values ("Admin" / "Read/Write" / "Read-only" / "None"), matching how they are
# stored in app_roles.feature_permissions. Applied only where the role currently
# has NO effective access (key absent OR value 'None'), so a real grant is never
# downgraded.
_GRANTS = {
    'Data Governance Officer': {'semantic-models': 'Admin', 'term-mapping': 'Admin'},
    'Data Steward':            {'semantic-models': 'Read/Write', 'term-mapping': 'Read/Write'},
    'Data Consumer':           {'semantic-models': 'Read-only'},
    'Data Producer':           {'semantic-models': 'Read-only'},
}


def _table_exists(conn) -> bool:
    return bool(conn.execute(sa.text(
        "SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'app_roles')"
    )).scalar())


def upgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    for role_name, grants in _GRANTS.items():
        for feat_id, level in grants.items():
            # Grant only when the role currently has NO effective access to the
            # feature: the key is absent, OR present but 'None' (the seeder
            # writes every feature, defaulting unset ones to 'None'). Never
            # overwrite a real grant (Read/Write, Admin, ...).
            conn.execute(
                sa.text(f"""
                    UPDATE app_roles
                    SET feature_permissions = jsonb_set(
                        feature_permissions::jsonb,
                        '{{{feat_id}}}',
                        to_jsonb(cast(:level as text)),
                        true
                    )::text
                    WHERE name = :role_name
                      AND COALESCE(feature_permissions::jsonb ->> cast(:feat_id as text), 'None') = 'None'
                """),
                {"level": level, "role_name": role_name, "feat_id": feat_id},
            )


def downgrade() -> None:
    # Remove only the keys this migration may have added. Safe: if an admin later
    # re-granted them, this still just strips the key (they can re-add).
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    for role_name, grants in _GRANTS.items():
        for feat_id in grants:
            conn.execute(
                sa.text("""
                    UPDATE app_roles
                    SET feature_permissions = (feature_permissions::jsonb - cast(:feat_id as text))::text
                    WHERE name = :role_name
                """),
                {"role_name": role_name, "feat_id": feat_id},
            )
