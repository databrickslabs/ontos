"""The Enrich coverage matrix's per-scheme "suggested" count must reflect
PENDING term-mapping suggestions (it was hardcoded to 0, so the Review button
was permanently greyed for every scheme).

This covers the repo grouping (count_pending_by_target_concept): only pending
suggestions count, grouped by target_concept_iri, so the manager can sum per
scheme.
"""
import uuid

import pytest
from sqlalchemy.orm import Session

from src.db_models.term_mappings import (
    MappingApplyRunDb,
    MappingSuggestionDb,
    SUG_STATUS_PENDING,
    SUG_STATUS_ACCEPTED,
    SUG_STATUS_REJECTED,
)
from src.repositories.term_mapping_repository import mapping_suggestion_repo


def _mk_run(db: Session) -> MappingApplyRunDb:
    run = MappingApplyRunDb(id=uuid.uuid4())
    db.add(run)
    db.flush()
    return run


def _mk_sug(db, run, iri, status):
    db.add(MappingSuggestionDb(
        id=uuid.uuid4(),
        run_id=run.id,
        source_entity_type="uc_table",
        source_entity_id=f"cat.sch.{uuid.uuid4().hex[:6]}",
        suggestion_kind="entity_assignment",
        target_concept_iri=iri,
        status=status,
    ))


def test_count_pending_by_target_concept_groups_and_filters(db_session: Session):
    run = _mk_run(db_session)
    a = "urn:glossary:scheme#Customer"
    b = "urn:glossary:scheme#Revenue"

    # a: 2 pending + 1 accepted (accepted must NOT count)
    _mk_sug(db_session, run, a, SUG_STATUS_PENDING)
    _mk_sug(db_session, run, a, SUG_STATUS_PENDING)
    _mk_sug(db_session, run, a, SUG_STATUS_ACCEPTED)
    # b: 1 pending + 1 rejected
    _mk_sug(db_session, run, b, SUG_STATUS_PENDING)
    _mk_sug(db_session, run, b, SUG_STATUS_REJECTED)
    db_session.flush()

    counts = mapping_suggestion_repo.count_pending_by_target_concept(db_session)
    assert counts.get(a) == 2, counts
    assert counts.get(b) == 1, counts


def test_count_pending_by_target_concept_empty(db_session: Session):
    # No suggestions at all -> empty map (scheme suggested falls back to 0).
    counts = mapping_suggestion_repo.count_pending_by_target_concept(db_session)
    assert isinstance(counts, dict)
    # Any pre-existing rows are unrelated; just assert it does not raise and is a dict.
