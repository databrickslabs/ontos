"""Update the shipped review-flow default workflows on existing installs (#859 review S7, B10, S8)

Revision ID: ak9_default_workflow_review_flow
Revises: ak8_authority_prerequisites_by_version
Create Date: 2026-11-22

``_seed_default_workflows`` creates a default only when it is missing, so an upgraded
install keeps the steps it was seeded with. This migration brings two shipped defaults
up to date, only where the stored definition is not user-customised (``is_customized``):

* Authority Relation Review Request: one notification to each named reviewer (was: a
  notification to the owner, which resolved to nobody, and a fail-flow notification), and
  its description.
  Its DataSteward approval never existed here; the AR's gate is the affirmations.
* Data Asset Review Request: the reviewer notification goes to the request's reviewer
  (was: the owner), and the three notifications are best-effort
  (``fail_flow_on_failure: false``), so a send failure no longer fails the review.

The step rows are the same as the YAML in ``data/default_workflows.yaml``; a test keeps
them equal. A config that can't be parsed is left as it is (logged). Data migration only: the downgrade leaves the workflows as they are.
"""
import json
import logging
import uuid
from typing import Any, Dict, Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

logger = logging.getLogger('alembic.runtime.migration')

revision: str = 'ak9_default_workflow_review_flow'
down_revision: Union[str, None] = 'ak8_authority_prerequisites_by_version'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


AR_WORKFLOW_NAME = 'Authority Relation Review Request'
AR_WORKFLOW_DESCRIPTION = (
    'Handles Authority Relation (ARF) review requests, once per review started. Notifies each named '
    'reviewer to complete their Asset Review; there is no approval step.'
)
DATA_ASSET_WORKFLOW_NAME = 'Data Asset Review Request'

# Replacement steps of the AR review workflow, in YAML form (step_id, name, type, config, on_pass)
AR_STEPS = (
    ('notify-reviewer', 'Notify Reviewer', 'notification', {
        'recipients': 'reviewers',
        'template': 'request_submitted',
        'custom_message': (
            "You have been asked to review Authority Relation '${entity_name}'. "
            "Complete your Asset Review to confirm it reflects reality."
        ),
        'fail_flow_on_failure': False,
    }, 'success'),
    ('success', 'Review Started', 'pass', {}, None),
)

BEST_EFFORT_NOTIFY_STEPS = ('notify-reviewer', 'notify-approved', 'notify-rejected')


def _workflow_id(conn, name: str):
    """Id of the default workflow with ``name`` whose definition the user has not customised."""
    row = conn.execute(sa.text(
        "SELECT id FROM process_workflows WHERE name = :name AND is_default = :is_default "
        "AND is_customized = :customized"
    ), {'name': name, 'is_default': True, 'customized': False}).first()
    return row[0] if row else None


def _load_config(raw: Any) -> Optional[Dict[str, Any]]:
    """The step's config as a dict, or None when it can't be read (the row is then left alone)."""
    if isinstance(raw, dict):
        return dict(raw)
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _replace_ar_steps(conn, workflow_id: str) -> None:
    conn.execute(sa.text("DELETE FROM workflow_steps WHERE workflow_id = :wf"), {'wf': workflow_id})
    for order, (step_id, name, step_type, config, on_pass) in enumerate(AR_STEPS):
        conn.execute(sa.text(
            "INSERT INTO workflow_steps (id, workflow_id, step_id, name, step_type, config, "
            "on_pass, on_fail, \"order\", position, created_at, updated_at) "
            "VALUES (:id, :wf, :step_id, :name, :step_type, :config, :on_pass, NULL, :ord, NULL, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ), {
            'id': str(uuid.uuid4()), 'wf': workflow_id, 'step_id': step_id,
            'name': name, 'step_type': step_type,
            'config': json.dumps(config), 'on_pass': on_pass, 'ord': order,
        })


def _update_data_asset_steps(conn, workflow_id: str) -> int:
    """Point the reviewer notification at the reviewer and make the notifications best-effort."""
    changed = 0
    rows = conn.execute(sa.text(
        "SELECT id, step_id, config FROM workflow_steps WHERE workflow_id = :wf AND step_type = 'notification'"
    ), {'wf': workflow_id}).all()
    for step_row_id, step_id, raw in rows:
        if step_id not in BEST_EFFORT_NOTIFY_STEPS:
            continue
        config = _load_config(raw)
        if config is None:
            # Never rewrite a config we can't read: the admin can fix that row by hand
            logger.warning("ak9: step %s of a review workflow has an unreadable config; left unchanged", step_row_id)
            continue
        before = dict(config)
        if step_id == 'notify-reviewer' and config.get('recipients') == 'owner':
            config['recipients'] = 'reviewer'
        config['fail_flow_on_failure'] = False
        if config != before:
            conn.execute(sa.text("UPDATE workflow_steps SET config = :config WHERE id = :id"),
                         {'config': json.dumps(config), 'id': step_row_id})
            changed += 1
    return changed


def apply_review_flow_defaults(conn) -> Dict[str, int]:
    """Bring the shipped AR and data-asset review defaults up to date. Returns counts of changes."""
    counts = {'ar_workflow_steps_replaced': 0, 'data_asset_steps_updated': 0}
    ar_id = _workflow_id(conn, AR_WORKFLOW_NAME)
    if ar_id:
        _replace_ar_steps(conn, ar_id)
        conn.execute(sa.text("UPDATE process_workflows SET description = :d WHERE id = :id"),
                     {'d': AR_WORKFLOW_DESCRIPTION, 'id': ar_id})
        counts['ar_workflow_steps_replaced'] = 1
    da_id = _workflow_id(conn, DATA_ASSET_WORKFLOW_NAME)
    if da_id:
        counts['data_asset_steps_updated'] = _update_data_asset_steps(conn, da_id)
    return counts


def upgrade() -> None:
    apply_review_flow_defaults(op.get_bind())


def downgrade() -> None:
    # Data migration: the earlier definitions are not restored.
    pass
