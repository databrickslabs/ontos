"""Actually grant concept perms to default roles (ac1 was a no-op)

ac1 applied but granted nothing: its guard used `NOT (fp ? feat_id)`, but the
seeder writes EVERY feature key (defaulting unset ones to the string 'None'), so
the key was already present and the grant was skipped. It also used lowercase
level strings; the stored FeatureAccessLevel values are 'Admin' / 'Read/Write' /
'Read-only' / 'None'.

This migration re-applies the grant correctly: set the level only where the role
currently has NO effective access (key absent OR value 'None'), using the real
enum string values. Idempotent — a real grant (Read/Write, Admin) is never
downgraded. Postgres-only (jsonb).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ac2_fix_concept_perms'
down_revision: Union[str, None] = 'ac1_grant_concept_perms'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


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
    # Reset the granted keys back to 'None' (don't remove — the seeder expects
    # every feature key present). Only touches the roles/features this granted.
    conn = op.get_bind()
    if not _table_exists(conn):
        return
    for role_name, grants in _GRANTS.items():
        for feat_id in grants:
            conn.execute(
                sa.text(f"""
                    UPDATE app_roles
                    SET feature_permissions = jsonb_set(
                        feature_permissions::jsonb,
                        '{{{feat_id}}}',
                        to_jsonb(cast('None' as text)),
                        true
                    )::text
                    WHERE name = :role_name
                """),
                {"role_name": role_name},
            )
