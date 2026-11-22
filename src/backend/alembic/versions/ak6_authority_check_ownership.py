"""Own each Authority Relation's decision checks on the version row (#859 review B7, S12)

Revision ID: ak6_authority_check_ownership
Revises: ak5_authority_definition_tracking
Create Date: 2026-11-22

Until now an AR's ``authority_criteria`` row linked a shared ``compliance_policies``
row (ON DELETE CASCADE). Inline checks created an "Authority Decision" policy per
save, so every save duplicated them, and a Compliance edit or delete changed
active ARs silently.

This revision moves the check onto the AR version:

* ``authority_criteria`` gains ``name``, ``rule``, ``failure_message`` and
  ``copied_from`` (JSON provenance, no live link).
* Each row's name, rule and failure message are copied from its linked policy,
  with ``copied_from = {"kind": "migrated", "label": <policy name>, "id": <policy id>}``.
* The ``compliance_policy_id`` column, its index and its foreign key are dropped.
* The ARF-created policies that nothing references are deleted. "ARF-created" means
  category ``Authority Decision`` AND slug ``ar-criterion-…``. A policy that a
  maturity gate or a compliance run still references is kept, and so is any
  Compliance check a user wrote in that category (no ARF slug).

Downgrade is supported: it recreates one ``ar-criterion-…`` policy per check from
its stored name, rule and failure message, then links the check back to it. The
policies are recreated, so a downgrade and upgrade pair is lossless for the rule
text; the ``copied_from`` provenance is lost on downgrade.
"""
import uuid
from datetime import datetime
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'ak6_authority_check_ownership'
down_revision: Union[str, None] = 'ak5_authority_definition_tracking'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ARF_CATEGORY = 'Authority Decision'
ARF_SLUG_PREFIX = 'ar-criterion-'

_criteria = sa.table(
    'authority_criteria',
    sa.column('id', sa.String()),
    sa.column('relation_id', sa.String()),
    sa.column('compliance_policy_id', sa.String()),
    sa.column('name', sa.String()),
    sa.column('rule', sa.Text()),
    sa.column('failure_message', sa.Text()),
    sa.column('copied_from', sa.JSON()),
    sa.column('display_order', sa.Integer()),
)
_policies = sa.table(
    'compliance_policies',
    sa.column('id', sa.String()),
    sa.column('slug', sa.String()),
    sa.column('name', sa.String()),
    sa.column('description', sa.Text()),
    sa.column('failure_message', sa.Text()),
    sa.column('rule', sa.Text()),
    sa.column('category', sa.String()),
    sa.column('severity', sa.String()),
    sa.column('is_active', sa.Boolean()),
    sa.column('created_at', sa.DateTime(timezone=True)),
    sa.column('updated_at', sa.DateTime(timezone=True)),
)


def copy_rules_from_policies(conn) -> int:
    """Copy each check's name, rule and failure message from its linked policy.

    Returns the number of checks copied. Runs before the link column is dropped.
    """
    linked = conn.execute(
        sa.select(
            _criteria.c.id, _criteria.c.compliance_policy_id,
            _policies.c.name, _policies.c.rule, _policies.c.failure_message,
        ).select_from(
            _criteria.join(_policies, _policies.c.id == _criteria.c.compliance_policy_id)
        )
    ).fetchall()
    for crit_id, policy_id, name, rule, failure_message in linked:
        conn.execute(
            _criteria.update()
            .where(_criteria.c.id == crit_id)
            .values(
                name=name or 'Authority check',
                rule=rule,
                failure_message=failure_message,
                copied_from={'kind': 'migrated', 'label': name, 'id': policy_id},
            )
        )
    return len(linked)


def _referenced_policy_ids(conn) -> set:
    """Policies a maturity gate or a compliance run still points at."""
    inspector = sa.inspect(conn)
    referenced: set = set()
    if inspector.has_table('maturity_gates'):
        gates = sa.table('maturity_gates', sa.column('compliance_policy_id', sa.String()))
        referenced |= {row[0] for row in conn.execute(sa.select(gates.c.compliance_policy_id)).fetchall()}
    if inspector.has_table('compliance_runs'):
        runs = sa.table('compliance_runs', sa.column('policy_id', sa.String()))
        referenced |= {row[0] for row in conn.execute(sa.select(runs.c.policy_id)).fetchall()}
    return referenced


def _linked_policy_ids(conn) -> set:
    """Policies an AR check still links to. Empty once the link column is gone."""
    columns = {c['name'] for c in sa.inspect(conn).get_columns('authority_criteria')}
    if 'compliance_policy_id' not in columns:
        return set()
    rows = conn.execute(
        sa.select(_criteria.c.compliance_policy_id).where(_criteria.c.compliance_policy_id.isnot(None))
    ).fetchall()
    return {row[0] for row in rows}


def drop_orphan_check_policies(conn) -> int:
    """Delete the ARF-created Authority Decision policies nothing else references.

    Conservative: a policy with a maturity gate, a compliance run or a link from
    an AR check is kept, and so is any policy that is not ARF-created.
    Returns the number of policies deleted.
    """
    candidates = conn.execute(
        sa.select(_policies.c.id).where(
            _policies.c.category == ARF_CATEGORY,
            _policies.c.slug.like(ARF_SLUG_PREFIX + '%'),
        )
    ).fetchall()
    referenced = _referenced_policy_ids(conn) | _linked_policy_ids(conn)
    deleted = 0
    for (policy_id,) in candidates:
        if policy_id in referenced:
            continue
        conn.execute(_policies.delete().where(_policies.c.id == policy_id))
        deleted += 1
    return deleted


def restore_policies_for_criteria(conn) -> int:
    """Downgrade: one ``ar-criterion-…`` policy per check, linked back by id."""
    rows = conn.execute(sa.select(
        _criteria.c.id, _criteria.c.relation_id, _criteria.c.name,
        _criteria.c.rule, _criteria.c.failure_message,
    )).fetchall()
    now = datetime.utcnow()
    for crit_id, relation_id, name, rule, failure_message in rows:
        policy_id = str(uuid.uuid4())
        conn.execute(_policies.insert().values(
            id=policy_id,
            slug=f"{ARF_SLUG_PREFIX}{crit_id[:12]}",
            name=name,
            description=f"Authority decision criterion for Authority Relation {relation_id}",
            failure_message=failure_message,
            rule=rule,
            category=ARF_CATEGORY,
            severity='high',
            is_active=True,
            created_at=now,
            updated_at=now,
        ))
        conn.execute(
            _criteria.update().where(_criteria.c.id == crit_id).values(compliance_policy_id=policy_id)
        )
    return len(rows)


def upgrade() -> None:
    op.add_column('authority_criteria', sa.Column('name', sa.String(), nullable=True))
    op.add_column('authority_criteria', sa.Column('rule', sa.Text(), nullable=True))
    op.add_column('authority_criteria', sa.Column('failure_message', sa.Text(), nullable=True))
    op.add_column('authority_criteria', sa.Column('copied_from', sa.JSON(), nullable=True))

    conn = op.get_bind()
    copy_rules_from_policies(conn)

    op.drop_index('ix_authority_criteria_compliance_policy_id', table_name='authority_criteria')
    with op.batch_alter_table('authority_criteria') as batch:
        batch.drop_column('compliance_policy_id')
        batch.alter_column('name', existing_type=sa.String(), nullable=False)
        batch.alter_column('rule', existing_type=sa.Text(), nullable=False)

    drop_orphan_check_policies(conn)


def downgrade() -> None:
    op.add_column('authority_criteria', sa.Column('compliance_policy_id', sa.String(), nullable=True))
    conn = op.get_bind()
    restore_policies_for_criteria(conn)

    with op.batch_alter_table('authority_criteria') as batch:
        batch.alter_column('compliance_policy_id', existing_type=sa.String(), nullable=False)
        batch.create_foreign_key(
            'fk_authority_criteria_compliance_policy_id', 'compliance_policies',
            ['compliance_policy_id'], ['id'], ondelete='CASCADE',
        )
    op.create_index('ix_authority_criteria_compliance_policy_id', 'authority_criteria',
                    ['compliance_policy_id'])

    with op.batch_alter_table('authority_criteria') as batch:
        batch.drop_column('copied_from')
        batch.drop_column('failure_message')
        batch.drop_column('rule')
        batch.drop_column('name')
