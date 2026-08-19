"""Add partial unique index for unversioned rdf_triples (ON CONFLICT arbiter).

Imports/bulk inserts always write UNVERSIONED triples (concept_version_id IS
NULL). Dedup for those relied on the 7-col ``uq_rdf_triple`` constraint's
``NULLS NOT DISTINCT`` clause (migration m4). That works on Postgres, but the
bulk insert now targets a 6-col natural key with a ``concept_version_id IS NULL``
predicate so the same ON CONFLICT DO NOTHING dedups identically on SQLite (unit
tests), where NULLS NOT DISTINCT is a no-op and NULLs are always distinct.

This migration adds the matching partial unique index so Postgres has an
explicit arbiter for that ON CONFLICT target. It is functionally redundant with
the NULLS-NOT-DISTINCT behaviour of uq_rdf_triple for NULL-version rows (both
forbid duplicate unversioned triples), so it changes no observable production
behaviour — it only makes the conflict target inferrable. Versioned snapshot
rows (concept_version_id IS NOT NULL) are unaffected; they keep coexisting under
uq_rdf_triple.

Postgres-targeted (partial indexes are standard; the project deploys on
Postgres/Lakebase). The unit suite builds the equivalent index via create_all
(the model's Index carries postgresql_where + sqlite_where).

Revision ID: m5_rdf_triple_null_version_uq
Revises: ac2_fix_concept_perms
Create Date: 2026-08-19
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'm5_rdf_triple_null_version_uq'
down_revision: Union[str, None] = 'ac2_fix_concept_perms'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLS_6 = "subject_uri, predicate_uri, object_value, object_language, object_datatype, context_name"


def upgrade() -> None:
    # Partial unique index over the natural key for unversioned rows only.
    # z8_fix_rdf_triple_nulls already coalesced+deduped NULL-owned rows, so this
    # builds cleanly. IF NOT EXISTS keeps it idempotent across environments.
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS uq_rdf_triple_null_version "
        f"ON rdf_triples ({_COLS_6}) "
        f"WHERE concept_version_id IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_rdf_triple_null_version")
