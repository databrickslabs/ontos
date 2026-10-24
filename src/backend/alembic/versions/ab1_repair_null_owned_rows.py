"""Repair NULL-owned rdf_triples rows for versioned concepts (one-time heal).

Root cause (fixed in semantic_models_manager write paths): draft edits and
status walks re-added a concept's triples via ``add_triple`` WITHOUT a
``concept_version_id``, so the rewritten rows were born NULL-owned. The served
graph is built from ``rdf_triples_repo.list_current`` (rows where
``concept_version_id IS NULL`` OR the owning ``concept_version.is_current``), so a
versioned concept whose live payload rows became NULL-owned could still surface,
but a subsequent publish that only snapshot-copied the previous version's rows
would leave those NULL-owned edits dangling and, in the worst case, mint an EMPTY
new version — dropping the concept out of the served graph entirely.

The manager fixes stop NEW rows from orphaning. This migration heals rows that
already orphaned: for every ``rdf_triples`` row that is NULL-owned but whose
subject IS a versioned concept (i.e. matches the IRI of a CURRENT
``concept_version`` row), re-stamp it with that current version's id. Only the
concept's OWN payload rows (subject_uri == concept_version.iri) are re-owned;
genuinely-shared scheme/collection metadata (subject != any concept iri) is left
untouched.

Postgres-only: the SQLite test harness builds its schema via ``create_all`` and
does NOT run migrations, so this never executes in tests. The raw UPDATE below is
guarded to the Postgres dialect.

Revision ID: ab1_repair_null_owned_rows
Revises: p1_upload_preview
Create Date: 2026-08-14
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'ab1_repair_null_owned_rows'
# Chains onto the deploy branch's head (p1_upload_preview) rather than
# m4_rdf_triple_version_uq: on this branch p1 already sits on top of m4, so
# parenting to m4 would create a SECOND head. The heal is order-independent
# w.r.t. p1 (it touches rdf_triples ownership, not the upload_preview table), so
# running it after p1 is safe.
down_revision: Union[str, None] = 'p1_upload_preview'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Re-own orphaned payload rows to their concept's current version.

    Guarded to Postgres; the correlated UPDATE ... FROM syntax is Postgres-native
    and the SQLite test harness never runs migrations anyway.

    Two steps, because ``uq_rdf_triple`` is a 7-column unique constraint
    ``(subject, predicate, object, lang, datatype, context, concept_version_id)``:

      STEP 1 — DELETE the NULL-owned orphans that are pure DUPLICATES of a row the
      concept's current version ALREADY owns (same 6-tuple). These arise from the
      draft-edit + publish path (e.g. an orphan prefLabel/status/createdAt whose
      value the current version's snapshot already carries). Re-stamping them
      would violate uq_rdf_triple, so they are redundant and must be dropped.

      STEP 2 — RE-OWN the remaining NULL-owned rows (genuinely missing from the
      current version's set, e.g. an edited definition that never got folded in)
      by setting concept_version_id to the current version. After step 1 these no
      longer collide.
    """
    bind = op.get_bind()
    if bind.dialect.name != 'postgresql':
        return

    # STEP 1: drop NULL-owned duplicates the current version already owns.
    op.execute("""
        DELETE FROM rdf_triples t
         USING concept_version cv, rdf_triples existing
         WHERE t.concept_version_id IS NULL
           AND cv.is_current = true
           AND cv.iri = t.subject_uri
           AND existing.concept_version_id = cv.id
           AND existing.subject_uri    = t.subject_uri
           AND existing.predicate_uri  = t.predicate_uri
           AND existing.object_value   = t.object_value
           AND existing.object_language = t.object_language
           AND existing.object_datatype = t.object_datatype
           AND existing.context_name   = t.context_name
    """)

    # STEP 2: re-own the survivors (no longer collide with current-version rows).
    op.execute("""
        UPDATE rdf_triples t
           SET concept_version_id = cv.id
          FROM concept_version cv
         WHERE cv.is_current = true
           AND cv.iri = t.subject_uri
           AND t.concept_version_id IS NULL
    """)


def downgrade() -> None:
    # No-op: this is a one-time data heal and is NOT reversible. Re-owning the
    # rows is the correct end state; there is no meaningful "un-heal", and we do
    # not know which of the re-owned rows were originally NULL-owned. Leave the
    # data as-is on downgrade (do not raise).
    pass
