"""Authority Resolution — scoped domain context + ODRL-shaped rule

Revision ID: al1_authority_scoped_context
Revises: ak9_default_workflow_review_flow
Create Date: 2026-11-12

Adds nullable ``authority_relations.rule`` (JSON, the ODRL-shaped rule:
permission constraints and duties, prohibitions). Rewraps each legacy flat
``domain_context`` blob as ``{"scope": [], "params": <blob>}``: the old keys
never gated a resolve, so they become parameters (``ctx.<key>`` in rules) and
no existing AR starts refusing requests; authors move keys into the scope
deliberately. A downgrade unwraps the params again (the scope is dropped).

Re-pointed (batch 2 merge) from ak4 to ak8: it touches only authority_relations.rule
and domain_context, none of which ak5-ak8 dropped or renamed.
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'al1_authority_scoped_context'
down_revision: Union[str, None] = 'ak9_default_workflow_review_flow'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _load(value):
    if value is None or isinstance(value, dict):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return None


def _rewrite(convert) -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, domain_context FROM authority_relations WHERE domain_context IS NOT NULL"
    )).fetchall()
    for row_id, raw in rows:
        value = _load(raw)
        if not isinstance(value, dict):
            continue
        new = convert(value)
        if new is not value:
            conn.execute(
                sa.text("UPDATE authority_relations SET domain_context = :dc WHERE id = :id"),
                {"dc": json.dumps(new), "id": row_id},
            )


def _structured(dc: dict) -> bool:
    # The new shape has only scope (list / mapping) and params (mapping); a legacy
    # blob with a "scope" key next to others (e.g. "scope": "feature") is a blob.
    # Mirrors src.common.authority_rule.is_structured (migrations don't import app code).
    if not dc or not set(dc) <= {'scope', 'params'}:
        return False
    return (dc.get('scope') is None or isinstance(dc['scope'], (list, dict))) and \
        (dc.get('params') is None or isinstance(dc['params'], dict))


def wrap_legacy(dc: dict) -> dict:
    """A legacy flat blob as ``{scope: [], params: blob}``; the new shape as is."""
    return dc if _structured(dc) else {'scope': [], 'params': dc}


def unwrap(dc: dict) -> dict:
    """The params of the new shape as a flat blob; a flat blob as is."""
    return dict(dc.get('params') or {}) if _structured(dc) else dc


def upgrade() -> None:
    op.add_column('authority_relations', sa.Column('rule', sa.JSON(), nullable=True))
    _rewrite(wrap_legacy)


def downgrade() -> None:
    _rewrite(unwrap)
    op.drop_column('authority_relations', 'rule')
