"""Authority Resolution — shared ADM schema evidence (ARF 1.2.0, #1294 slice 4)

Revision ID: ao1_authority_adm_schema
Revises: an1_authority_policy_references
Create Date: 2026-11-23

The per-AR arbitrary-table evidence path is removed. The shared ADM schema is the only
evidence source, so an Authority Relation declares the slice it reads instead of a table
and a column map.

The definition hash changes for every AR that had table-linked evidence. This is intended
(#1294 slice 4, B6): ARF has never shipped, and the table path is invalid by design, so the
DNA-Coefficient and affirmations of those ARs were measured against evidence that no longer
exists. Treat them as stale and measure again.

Upgrade
- Adds ``authority_relations.evidence_slice`` (JSON), ``adm_schema_override`` (the Admin-only
  per-AR schema) and ``dna_position``; adds ``authority_dna_runs.position`` and
  ``sample_basis``.
- Each AR that had a table-linked evidence binding gets a slice carrying its action code
  (``action_codes = [action]``, the domain scope on). An AR without an action code gets no
  slice, so its DNA-Coefficient can't be measured until one is set. The table reference
  itself can't be carried over; it names a table that is no longer read.
- Drops ``authority_relations.evidence_binding`` and ``evidence_sources``.

Downgrade
- Restores the two columns empty (the table references are not recoverable) and drops the
  new columns. The slices are lost on downgrade.
"""
import json
import re
from typing import Any, Mapping, Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'ao1_authority_adm_schema'
down_revision: Union[str, None] = 'an1_authority_policy_references'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# The slice an AR carries after the upgrade: its own action code, the domain scope applied.
DEFAULT_WINDOW_DAYS = 90
DEFAULT_SAMPLE_SIZE = 500

# The action-code grammar of ``src.common.adm.ACTION_CODE_PATTERN``. A migration must not import
# the app package, so the pattern is repeated here: change both together.
ACTION_CODE_RE = re.compile(r"^[a-z][a-z0-9_:.\-]{0,127}$")


def normalise_action_code(raw: Any) -> Optional[str]:
    """A legacy free-text action as an ADM action code, or None when nothing valid is left.

    Lowercased, whitespace runs become ``_``, characters outside the grammar are dropped, and
    the result must start with a letter. ``"Approve Budget!"`` becomes ``approve_budget``;
    ``"!!!"`` becomes nothing and the AR gets no slice.
    """
    text = re.sub(r"\s+", "_", str(raw or "").strip().lower())
    text = re.sub(r"[^a-z0-9_:.\-]", "", text).lstrip("0123456789_:.-")[:128]
    return text if ACTION_CODE_RE.match(text) else None


def _as_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def slice_for_row(row: Mapping[str, Any]) -> Optional[dict]:
    """The slice an AR keeps from its table-linked binding (see the module docstring)."""
    had_table = bool(_as_json(row.get("evidence_binding")) or _as_json(row.get("evidence_sources")))
    action = normalise_action_code(row.get("action"))
    if not had_table or not action:
        return None
    return {
        "action_codes": [action],
        "object_refs": [],
        "domain_scope": True,
        "window_days": DEFAULT_WINDOW_DAYS,
        "sample_size": DEFAULT_SAMPLE_SIZE,
    }


def upgrade() -> None:
    op.add_column('authority_relations', sa.Column('evidence_slice', sa.JSON(), nullable=True))
    op.add_column('authority_relations', sa.Column('adm_schema_override', sa.String(), nullable=True))
    op.add_column('authority_relations', sa.Column('dna_position', sa.Float(), nullable=True))
    op.add_column('authority_dna_runs', sa.Column('position', sa.Float(), nullable=True))
    op.add_column('authority_dna_runs', sa.Column('sample_basis', sa.JSON(), nullable=True))

    conn = op.get_bind()
    rels = sa.table(
        'authority_relations',
        sa.column('id', sa.String()), sa.column('action', sa.String()),
        sa.column('evidence_binding', sa.JSON()), sa.column('evidence_sources', sa.JSON()),
        sa.column('evidence_slice', sa.JSON()),
    )
    rows = conn.execute(sa.select(
        rels.c.id, rels.c.action, rels.c.evidence_binding, rels.c.evidence_sources,
    )).mappings().all()
    # Intentional: the definition hash of an AR with table-linked evidence changes here (see above).
    for row in rows:
        new_slice = slice_for_row(row)
        if new_slice is None:
            continue
        conn.execute(
            rels.update().where(rels.c.id == row['id']).values(evidence_slice=new_slice)
        )

    op.drop_column('authority_relations', 'evidence_sources')
    op.drop_column('authority_relations', 'evidence_binding')


def downgrade() -> None:
    op.add_column('authority_relations', sa.Column('evidence_binding', sa.JSON(), nullable=True))
    op.add_column('authority_relations', sa.Column('evidence_sources', sa.JSON(), nullable=True))
    op.drop_column('authority_dna_runs', 'sample_basis')
    op.drop_column('authority_dna_runs', 'position')
    op.drop_column('authority_relations', 'dna_position')
    op.drop_column('authority_relations', 'adm_schema_override')
    op.drop_column('authority_relations', 'evidence_slice')
