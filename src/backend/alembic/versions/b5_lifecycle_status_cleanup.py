"""move product and contract statuses that aren't lifecycle statuses to the lifecycle ones

a9 and b2_add_cert_pub_to_contracts turned 'certified' into status 'active'
plus the top certification level. Create, import and the contract dialogs kept
accepting any status after that ('certified', the dialogs' 'archived', or a
capitalized 'Proposed'), and an update could change it. Now a new entity starts
in a lifecycle status and an update can't change it, so a product left in one
of those would be stuck (a product's transitions start from a lifecycle
status). This converts all known aliases and legacy values to their canonical
lifecycle statuses, and moves any other historical value (or NULL/empty) to 'draft'
so entities can transition normally post-upgrade. For each converted row, a
change_log entry with action 'status_migrated' and details {from, to} is written.

Conversion rules (applied in order, case-insensitive + trimmed):
- 'certified' -> 'active' plus the top certification level, as a9/b2 did;
- 'archived' -> 'retired';
- 'production', 'prod', 'live', 'published' -> 'active';
- 'development', 'dev', 'test', 'testing' -> 'sandbox';
- 'pending', 'in_review' (and hyphenated/spaced variants), 'review' -> 'under_review';
- 'inactive', 'obsolete' -> 'deprecated';
- 'deleted' -> 'retired';
- a lifecycle status in another case -> lowercase;
- NULL, empty, or any other value -> 'draft'.

Revision ID: b5_lifecycle_status_cleanup
Revises: b4_compliance_run_error_code
Create Date: 2026-10-19 12:00:00.000000

"""
import json
import logging
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b5_lifecycle_status_cleanup'
down_revision: Union[str, None] = 'b4_compliance_run_error_code'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

LIFECYCLE_STATUSES = (
    'draft', 'sandbox', 'proposed', 'under_review', 'approved', 'active', 'deprecated', 'retired',
)

# Mapping of known aliases/legacy values (normalized: lower + trim) to canonical statuses
STATUS_ALIASES = {
    'production': 'active',
    'prod': 'active',
    'live': 'active',
    'published': 'active',
    'development': 'sandbox',
    'dev': 'sandbox',
    'test': 'sandbox',
    'testing': 'sandbox',
    'pending': 'under_review',
    'in_review': 'under_review',
    'in review': 'under_review',
    'under_review': 'under_review',
    'under review': 'under_review',
    'in-review': 'under_review',
    'under-review': 'under_review',
    'review': 'under_review',
    'inactive': 'deprecated',
    'obsolete': 'deprecated',
    'deleted': 'retired',
    'archived': 'retired',
    'certified': 'active',  # Special case: also sets certification_level
}


def upgrade() -> None:
    conn = op.get_bind()

    for table in ('data_products', 'data_contracts'):
        # 1. Handle 'certified' special case: set to 'active' + top cert level.
        # Fetch rows that are certified first to create change log entries.
        certified_rows = conn.execute(sa.text(f"""
            SELECT id FROM {table}
            WHERE lower(trim(status)) = 'certified'
        """)).fetchall()

        for row in certified_rows:
            entity_id = row[0]
            _log_status_change(conn, table, entity_id, 'certified', 'active')

        op.execute(f"""
            UPDATE {table}
            SET status = 'active',
                certification_level = COALESCE(
                    certification_level, (SELECT MAX(level_order) FROM certification_levels)
                ),
                certified_at = COALESCE(certified_at, updated_at)
            WHERE lower(trim(status)) = 'certified'
        """)

        # 2. Process aliases and legacy values.
        # Build a CASE statement for all aliases (excluding 'certified' and 'archived' which were handled above).
        all_rows = conn.execute(sa.text(f"""
            SELECT id, status FROM {table}
        """)).fetchall()

        for row in all_rows:
            entity_id, current_status = row[0], row[1]
            normalized = current_status.lower().strip() if current_status else ''

            # Skip rows already 'certified' (just handled above).
            if normalized == 'certified':
                continue

            # Determine the new status.
            new_status = None

            # Check if it matches an alias.
            if normalized in STATUS_ALIASES:
                new_status = STATUS_ALIASES[normalized]
                # Skip if already in canonical form.
                if new_status == current_status:
                    continue
            elif normalized and normalized in LIFECYCLE_STATUSES:
                # It's a lifecycle status but in wrong case; normalize to lowercase.
                new_status = normalized
                if new_status == current_status:
                    continue
            else:
                # Unknown value or empty/NULL: convert to 'draft'.
                new_status = 'draft'
                # Skip if already 'draft'.
                if current_status == 'draft':
                    continue

            # Log the change and update.
            _log_status_change(conn, table, entity_id, current_status, new_status)
            conn.execute(sa.text(f"""
                UPDATE {table}
                SET status = :new_status
                WHERE id = :entity_id
            """), {"new_status": new_status, "entity_id": entity_id})


def _log_status_change(conn, table: str, entity_id: str, from_status, to_status) -> None:
    """Create a change_log entry for a status migration."""
    try:
        # Map table name to entity_type.
        if table == 'data_products':
            entity_type = 'data_product'
        elif table == 'data_contracts':
            entity_type = 'data_contract'
        else:
            return

        # Generate a UUID for the change log entry using Python (portable across DB engines).
        change_log_id = str(uuid.uuid4())

        details = json.dumps({"from": from_status, "to": to_status})

        conn.execute(sa.text("""
            INSERT INTO entity_change_log (id, entity_type, entity_id, action, username, details_json)
            VALUES (:id, :entity_type, :entity_id, :action, :username, :details_json)
        """), {
            "id": change_log_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": "status_migrated",
            "username": 'system@migration',
            "details_json": details,
        })

        logger.warning(
            "Migration: %s %s status %r -> %r",
            entity_type, entity_id, from_status, to_status,
        )
    except Exception as e:
        logger.error(
            "Failed to log status change for %s %s: %s",
            table, entity_id, str(e),
        )


def downgrade() -> None:
    # Data only: the converted rows keep their new status.
    pass
