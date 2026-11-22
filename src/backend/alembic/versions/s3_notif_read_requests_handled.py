"""Mark the read request notifications handled

Revision ID: s3_notif_read_requests_handled
Revises: s2_document_markdown_import
Create Date: 2026-11-21

My actions lists an actionable notification until its decision writes the
``handled`` marker into ``action_payload`` (a delivery: ``completed``), because
the bell sets ``read`` when a notification is opened (#1526). Older builds
recorded a decided request (every action type but ``workflow_approval``, whose
decisions have always written the marker) only as ``read``. At the upgrade,
this migration adds ``"handled": true`` to the payload of every read
``action_required`` row with an action type other than ``workflow_approval``
that has neither marker yet, so the requests an older build decided stay
decided, whenever the installation upgrades. Approvals and unread rows are
untouched. A payload that is not a JSON object (not written by the app) is
kept under ``legacy_action_payload`` next to the marker.

Downgrade is a no-op: the added marker cannot be told apart from one a
decision wrote, and the older builds decide these rows by ``read`` anyway.
"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 's3_notif_read_requests_handled'
down_revision: Union[str, None] = 's2_document_markdown_import'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

APPROVAL_ACTION_TYPE = 'workflow_approval'
_MARKERS = ('"handled":true', '"completed":true')
_BATCH = 500


def _marked(payload: str) -> bool:
    """What the classifier matches: either marker, whatever the JSON spacing."""
    compact = payload
    for char in (' ', '\t', '\n', '\r'):
        compact = compact.replace(char, '')
    return any(marker in compact for marker in _MARKERS)


def _handled(payload):
    """The payload with the ``handled`` marker, or None when it already has a marker."""
    if payload and _marked(payload):
        return None
    if not payload:
        return json.dumps({'handled': True})
    try:
        value = json.loads(payload)
    except ValueError:
        value = None
    if isinstance(value, dict):
        return json.dumps({**value, 'handled': True})
    return json.dumps({'legacy_action_payload': payload, 'handled': True})


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, action_payload FROM notifications "
            "WHERE read = :read AND type = 'action_required' "
            "AND action_type IS NOT NULL AND action_type <> '' "
            "AND action_type <> :approval"
        ),
        {'read': True, 'approval': APPROVAL_ACTION_TYPE},
    ).all()
    updates = []
    for row_id, payload in rows:
        new_payload = _handled(payload)
        if new_payload is not None:
            updates.append({'id': row_id, 'payload': new_payload})
    statement = sa.text("UPDATE notifications SET action_payload = :payload WHERE id = :id")
    for start in range(0, len(updates), _BATCH):
        conn.execute(statement, updates[start:start + _BATCH])


def downgrade() -> None:
    # No-op: see the module docstring
    pass
