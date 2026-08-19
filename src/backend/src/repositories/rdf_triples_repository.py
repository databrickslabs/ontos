"""Repository for RDF triples storage operations.

Provides CRUD operations for RDF triples with support for bulk inserts
and context-based queries.
"""
import os
import time
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session, aliased
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import and_, or_, text
import uuid

from src.common.repository import CRUDBase
from src.db_models.rdf_triples import RdfTripleDb
from src.db_models.concept_versions import ConceptVersionDb
from src.common.logging import get_logger

logger = get_logger(__name__)

# Sentinel so remove_by_subject_predicate can distinguish "not scoped by version"
# (delete across all versions) from "scoped to concept_version_id = None".
_UNSET = object()

# --- Bloat diagnostics ------------------------------------------------------
# The rdf_triples table has been observed growing to tens of thousands of rows
# on some instances while the UI only surfaces a few hundred concepts, and we
# have not been able to reproduce it locally. When the table crosses a
# threshold we emit a one-shot forensic snapshot (breakdown by source/context,
# blank-node share, constraint-bypass detection, and per-(subject,predicate)
# churn) so we can see WHERE the rows come from and WHAT their nature is on the
# affected instance. Tune/disable via env:
#   RDF_TRIPLES_DIAGNOSTIC_THRESHOLD  row count that arms diagnostics (0=off, default 30000)
#   RDF_TRIPLES_DIAGNOSTIC_INTERVAL_S minimum seconds between snapshots (default 300)
_DIAG_THRESHOLD = int(os.getenv("RDF_TRIPLES_DIAGNOSTIC_THRESHOLD", "30000"))
_DIAG_INTERVAL_S = int(os.getenv("RDF_TRIPLES_DIAGNOSTIC_INTERVAL_S", "300"))
_diag_last_run_monotonic: float = 0.0


class RdfTriplesRepository(CRUDBase[RdfTripleDb, dict, dict]):
    """Repository for RDF triple operations.
    
    Extends CRUDBase with specialized methods for:
    - Bulk triple inserts with ON CONFLICT DO NOTHING
    - Triple lookups by subject, predicate, object
    - Context-based operations for managing ontology sources
    """

    # Uniqueness key columns for ON CONFLICT DO NOTHING. Includes
    # concept_version_id (migration m4_rdf_triple_version_uq) so per-version
    # snapshot rows (same triple, different owning version) do not collide, while
    # NULL-owned duplicates are still deduped (UNIQUE NULLS NOT DISTINCT).
    _CONFLICT_COLS = [
        'subject_uri', 'predicate_uri', 'object_value',
        'object_language', 'object_datatype', 'context_name', 'concept_version_id',
    ]

    def add_triple(
        self,
        db: Session,
        subject_uri: str,
        predicate_uri: str,
        object_value: str,
        object_is_uri: bool = True,
        object_language: str = '',
        object_datatype: str = '',
        context_name: str = 'default',
        source_type: Optional[str] = None,
        source_identifier: Optional[str] = None,
        created_by: Optional[str] = None,
        concept_version_id=None,
    ) -> Optional[RdfTripleDb]:
        """Add a single triple with ON CONFLICT DO NOTHING.

        Returns the triple if inserted, None if it already existed.

        ``concept_version_id`` optionally stamps the owning concept-version at
        insert time (used by the publish snapshot-copy path so the new row is
        born owned by v2 rather than reassigned afterward).
        """
        # Coerce None to '' — the DB columns are NOT NULL with default ''
        if object_language is None:
            object_language = ''
        if object_datatype is None:
            object_datatype = ''
        stmt = insert(RdfTripleDb).values(
            id=uuid.uuid4(),
            subject_uri=subject_uri,
            predicate_uri=predicate_uri,
            object_value=object_value,
            object_is_uri=object_is_uri,
            object_language=object_language,
            object_datatype=object_datatype,
            context_name=context_name,
            source_type=source_type,
            source_identifier=source_identifier,
            created_by=created_by,
            concept_version_id=concept_version_id,
        ).on_conflict_do_nothing(
            index_elements=self._CONFLICT_COLS
        ).returning(RdfTripleDb.id)
        
        result = db.execute(stmt)
        row = result.fetchone()
        db.flush()
        
        if row:
            logger.debug(f"Inserted triple: {subject_uri} -> {predicate_uri}")
            return db.query(RdfTripleDb).filter(RdfTripleDb.id == row[0]).first()
        else:
            logger.debug(f"Triple already exists: {subject_uri} -> {predicate_uri}")
            return None

    def add_triples_bulk(
        self,
        db: Session,
        triples: List[Dict[str, Any]],
        batch_size: int = 1000,
    ) -> int:
        """Bulk insert triples with ON CONFLICT DO NOTHING.
        
        Args:
            db: Database session
            triples: List of dicts with keys: subject_uri, predicate_uri, object_value,
                     object_is_uri, object_language, object_datatype, context_name,
                     source_type, source_identifier, created_by
            batch_size: Number of triples per batch (default 1000)
        
        Returns:
            Number of triples actually inserted (excludes duplicates)
        """
        if not triples:
            return 0
        
        total_inserted = 0
        
        # Process in batches
        for i in range(0, len(triples), batch_size):
            batch = triples[i:i + batch_size]
            
            # Add UUIDs and coerce None -> '' for NOT NULL columns
            for triple in batch:
                if 'id' not in triple:
                    triple['id'] = uuid.uuid4()
                if triple.get('object_language') is None:
                    triple['object_language'] = ''
                if triple.get('object_datatype') is None:
                    triple['object_datatype'] = ''
            
            stmt = insert(RdfTripleDb).values(batch).on_conflict_do_nothing(
                index_elements=self._CONFLICT_COLS
            )
            
            result = db.execute(stmt)
            total_inserted += result.rowcount
            db.flush()
            
            logger.debug(f"Bulk insert batch {i // batch_size + 1}: "
                        f"inserted {result.rowcount}/{len(batch)} triples")
        
        logger.info(f"Bulk insert complete: {total_inserted}/{len(triples)} triples inserted")

        # Only worth checking when this call actually added rows (a re-import
        # that inserts 0 can't have grown the table).
        if total_inserted > 0:
            self.maybe_log_bloat_diagnostics(db, trigger="bulk_insert")

        return total_inserted

    def remove_triple(
        self,
        db: Session,
        subject_uri: str,
        predicate_uri: str,
        object_value: str,
        context_name: str = 'default',
        object_language: str = '',
        object_datatype: str = '',
    ) -> bool:
        """Remove a specific triple from the database.
        
        Returns True if a triple was deleted, False otherwise.
        """
        query = db.query(RdfTripleDb).filter(
            and_(
                RdfTripleDb.subject_uri == subject_uri,
                RdfTripleDb.predicate_uri == predicate_uri,
                RdfTripleDb.object_value == object_value,
                RdfTripleDb.context_name == context_name,
                RdfTripleDb.object_language == object_language,
                RdfTripleDb.object_datatype == object_datatype,
            )
        )
        
        deleted = query.delete(synchronize_session=False)
        db.flush()
        
        if deleted > 0:
            logger.debug(f"Removed triple: {subject_uri} -> {predicate_uri}")
            return True
        return False

    def remove_by_context(self, db: Session, context_name: str) -> int:
        """Remove all triples for a given context (e.g., when deleting an ontology).
        
        Returns the number of triples deleted.
        """
        deleted = db.query(RdfTripleDb).filter(
            RdfTripleDb.context_name == context_name
        ).delete(synchronize_session=False)
        db.flush()
        
        logger.info(f"Removed {deleted} triples from context '{context_name}'")
        return deleted

    def list_by_context(self, db: Session, context_name: str) -> List[RdfTripleDb]:
        """Get all triples for a given context."""
        return db.query(RdfTripleDb).filter(
            RdfTripleDb.context_name == context_name
        ).all()

    def list_all(self, db: Session) -> List[RdfTripleDb]:
        """Get all triples from the database (current + history).

        NOTE: for building the served in-memory graph use ``list_current`` — the
        hot graph must contain current-only triples (P0-2). This method returns
        every row including historical versions.
        """
        return db.query(RdfTripleDb).all()

    def list_current(self, db: Session) -> List[RdfTripleDb]:
        """Get the current-only triples for building the served hot graph (P0-2).

        A triple is current when EITHER:
          - it has no ``concept_version_id`` (scheme / collection / metadata and
            other P0-1-unowned triples — these MUST still load), OR
          - its owning concept-version has ``is_current = true``.

        History triples (owned by a non-current concept-version) are excluded so
        they never enter the materialized graph. The ``is_current`` filter runs
        HERE, once at build time; downstream reads carry no version predicate.

        Mirrors the ``rdf_triples_current`` DB view (migration
        ``m2_rdf_triples_current``) so the two stay in lockstep.
        """
        # Outer join to concept_version; keep rows that are unowned OR current.
        return (
            db.query(RdfTripleDb)
            .outerjoin(
                ConceptVersionDb,
                ConceptVersionDb.id == RdfTripleDb.concept_version_id,
            )
            .filter(
                or_(
                    RdfTripleDb.concept_version_id.is_(None),
                    ConceptVersionDb.is_current.is_(True),
                )
            )
            .all()
        )

    def list_by_subject(self, db: Session, subject_uri: str) -> List[RdfTripleDb]:
        """Get all triples with a given subject."""
        return db.query(RdfTripleDb).filter(
            RdfTripleDb.subject_uri == subject_uri
        ).all()

    def list_current_by_subject(self, db: Session, subject_uri: str) -> List[RdfTripleDb]:
        """Triples for a subject that belong in the SERVED (current) graph.

        A row is current when it has no owning version (unowned/metadata) OR its
        owning concept-version is current. Used to re-add a concept to the hot
        graph after publish WITHOUT leaking the prior version's frozen snapshot.
        Mirrors the rdf_triples_current view rule, scoped to one subject.
        """
        return (
            db.query(RdfTripleDb)
            .outerjoin(
                ConceptVersionDb,
                ConceptVersionDb.id == RdfTripleDb.concept_version_id,
            )
            .filter(
                RdfTripleDb.subject_uri == subject_uri,
                or_(
                    RdfTripleDb.concept_version_id.is_(None),
                    ConceptVersionDb.is_current.is_(True),
                ),
            )
            .all()
        )

    def list_by_concept_version(self, db: Session, concept_version_id) -> List[RdfTripleDb]:
        """All triples owned by a specific concept-version id (its frozen snapshot)."""
        return (
            db.query(RdfTripleDb)
            .filter(RdfTripleDb.concept_version_id == concept_version_id)
            .all()
        )

    def copy_triples_to_version(
        self,
        db: Session,
        subject_uri: str,
        source_concept_version_id,
        target_concept_version_id,
        context_name: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> int:
        """Duplicate a concept's triples into a NEW set owned by the target version.

        The prior (source) version's rows are LEFT UNTOUCHED — they are its frozen
        snapshot. Each source row is re-inserted with concept_version_id =
        target. Uniqueness now includes concept_version_id (migration m4), so the
        copy does not collide with the source rows. Returns rows copied.

        Source selection: rows owned by ``source_concept_version_id`` (the demoted
        version). If that is None (edge case: publishing an unversioned concept),
        falls back to the subject's currently-unowned rows so v2 still gets a set.
        """
        q = db.query(RdfTripleDb).filter(RdfTripleDb.subject_uri == subject_uri)
        if context_name:
            q = q.filter(RdfTripleDb.context_name == context_name)
        if source_concept_version_id is not None:
            q = q.filter(RdfTripleDb.concept_version_id == source_concept_version_id)
        else:
            q = q.filter(RdfTripleDb.concept_version_id.is_(None))
        source_rows = q.all()

        copied = 0
        for r in source_rows:
            db.add(RdfTripleDb(
                subject_uri=r.subject_uri,
                predicate_uri=r.predicate_uri,
                object_value=r.object_value,
                object_is_uri=r.object_is_uri,
                object_language=r.object_language,
                object_datatype=r.object_datatype,
                context_name=r.context_name,
                source_type=r.source_type,
                source_identifier=r.source_identifier,
                created_by=created_by or r.created_by,
                concept_version_id=target_concept_version_id,
            ))
            copied += 1
        db.flush()
        logger.debug(
            f"Copied {copied} triples of '{subject_uri}' from version "
            f"{source_concept_version_id} to {target_concept_version_id}"
        )
        return copied

    def reassign_subject_to_concept_version(
        self,
        db: Session,
        subject_uri: str,
        concept_version_id,
        context_name: Optional[str] = None,
        only_null_owned: bool = False,
    ) -> int:
        """Point triples owned by ``subject_uri`` at a concept-version (P0-3).

        Triple ownership is determined by the SUBJECT IRI (the P0-1 ownership
        rule). On an atomic publish, the affected concept's triples are moved to
        the newly-minted current version by setting their ``concept_version_id``.
        Optionally scoped to a single ``context_name``.

        ``only_null_owned``: when True, re-stamp ONLY rows that are currently
        NULL-owned (``concept_version_id IS NULL``). This is the safe variant for
        the write paths (update_concept / update_concept_status) that add new
        rows NULL-owned and need to adopt them into the CURRENT version WITHOUT
        touching a PRIOR version's frozen snapshot rows — moving those onto the
        current version would both destroy the snapshot AND collide with the
        current version's identical copies (unique key includes
        concept_version_id), raising an IntegrityError.

        Returns the number of triples reassigned. Flushes but does not commit —
        the caller owns the transaction so the swap is one Postgres commit.
        """
        if only_null_owned:
            # A NULL-owned row can be a DUPLICATE of a row the target version
            # already owns (same s,p,o,lang,datatype,context) — e.g. an
            # ontos:sourceFile provenance triple written both NULL-owned and
            # version-owned. Re-stamping it to concept_version_id would then
            # violate uq_rdf_triple (7-col unique incl. concept_version_id) and
            # 500 the whole transition (observed live on publish). DELETE those
            # colliding NULL-owned duplicates first; the surviving NULL-owned
            # rows are then safe to re-stamp. Deleting the NULL copy loses
            # nothing — the identical version-owned row remains.
            dup = aliased(RdfTripleDb)
            collide_q = (
                db.query(RdfTripleDb.id)
                .join(
                    dup,
                    and_(
                        dup.subject_uri == RdfTripleDb.subject_uri,
                        dup.predicate_uri == RdfTripleDb.predicate_uri,
                        dup.object_value == RdfTripleDb.object_value,
                        dup.object_language == RdfTripleDb.object_language,
                        dup.object_datatype == RdfTripleDb.object_datatype,
                        dup.context_name == RdfTripleDb.context_name,
                        dup.concept_version_id == concept_version_id,
                    ),
                )
                .filter(
                    RdfTripleDb.subject_uri == subject_uri,
                    RdfTripleDb.concept_version_id.is_(None),
                )
            )
            if context_name:
                collide_q = collide_q.filter(RdfTripleDb.context_name == context_name)
            collide_ids = [row[0] for row in collide_q.all()]
            if collide_ids:
                db.query(RdfTripleDb).filter(RdfTripleDb.id.in_(collide_ids)).delete(
                    synchronize_session=False
                )
                db.flush()

        query = db.query(RdfTripleDb).filter(RdfTripleDb.subject_uri == subject_uri)
        if context_name:
            query = query.filter(RdfTripleDb.context_name == context_name)
        if only_null_owned:
            query = query.filter(RdfTripleDb.concept_version_id.is_(None))
        updated = query.update(
            {RdfTripleDb.concept_version_id: concept_version_id},
            synchronize_session=False,
        )
        db.flush()
        logger.debug(
            f"Reassigned {updated} triples of '{subject_uri}' to concept_version "
            f"{concept_version_id} (only_null_owned={only_null_owned})"
        )
        return updated

    def remove_by_subject(
        self, db: Session, subject_uri: str, context_name: Optional[str] = None
    ) -> int:
        """Remove all triples with a given subject, optionally filtered by context.
        
        Returns the number of triples deleted.
        """
        query = db.query(RdfTripleDb).filter(
            RdfTripleDb.subject_uri == subject_uri
        )
        if context_name:
            query = query.filter(RdfTripleDb.context_name == context_name)
        
        deleted = query.delete(synchronize_session=False)
        db.flush()
        
        logger.debug(f"Removed {deleted} triples with subject '{subject_uri}'")
        return deleted

    def remove_by_subject_predicate(
        self,
        db: Session,
        subject_uri: str,
        predicate_uri: str,
        context_name: Optional[str] = None,
        concept_version_id: object = _UNSET,
    ) -> int:
        """Remove all triples matching subject and predicate.

        Useful for updating properties where you don't know the old value.
        Returns the number of triples deleted.

        ``concept_version_id``: when provided (including None), scopes the delete
        to rows owned by exactly that version — so a publish can overwrite v2's
        copied set WITHOUT touching the prior version's frozen snapshot. Left at
        the sentinel default = not scoped (delete across all versions, legacy
        behaviour for the plain update path).
        """
        query = db.query(RdfTripleDb).filter(
            and_(
                RdfTripleDb.subject_uri == subject_uri,
                RdfTripleDb.predicate_uri == predicate_uri,
            )
        )
        if context_name:
            query = query.filter(RdfTripleDb.context_name == context_name)
        if concept_version_id is not _UNSET:
            if concept_version_id is None:
                query = query.filter(RdfTripleDb.concept_version_id.is_(None))
            else:
                query = query.filter(RdfTripleDb.concept_version_id == concept_version_id)

        deleted = query.delete(synchronize_session=False)
        db.flush()

        logger.debug(f"Removed {deleted} triples for {subject_uri} -> {predicate_uri}")
        return deleted

    def count_by_context(self, db: Session, context_name: str) -> int:
        """Count triples in a given context."""
        return db.query(RdfTripleDb).filter(
            RdfTripleDb.context_name == context_name
        ).count()

    def list_contexts(self, db: Session) -> List[str]:
        """Get all distinct context names."""
        results = db.query(RdfTripleDb.context_name).distinct().all()
        return [r[0] for r in results]

    def context_exists(self, db: Session, context_name: str) -> bool:
        """Check if any triples exist for a given context."""
        return db.query(RdfTripleDb).filter(
            RdfTripleDb.context_name == context_name
        ).first() is not None

    def maybe_log_bloat_diagnostics(self, db: Session, *, trigger: str) -> None:
        """Emit a forensic snapshot of rdf_triples when the table looks bloated.

        No-op unless the table exceeds RDF_TRIPLES_DIAGNOSTIC_THRESHOLD rows,
        and then at most once per RDF_TRIPLES_DIAGNOSTIC_INTERVAL_S. The count
        check is a cheap indexed COUNT(*); the heavier breakdown queries only
        run once the threshold is crossed, so healthy instances pay ~nothing.

        Captures the signals we need to explain the "64k triples / few hundred
        concepts" reports without a local repro:
          - total rows and how many are blank-node (skolemised) triples
          - breakdown by source_type and by top contexts
          - constraint-bypass check: rows minus distinct 6-tuples (if > 0 the
            uq_rdf_triple unique index is not deduplicating — the classic
            NULL-in-unique-index / missing-constraint cause)
          - top churning (subject, predicate) groups — a single subject with
            hundreds of rows points at a re-write path that appends instead of
            replacing (e.g. per-save timestamps).

        `trigger` labels what invoked the check (e.g. "bulk_insert", "rebuild").
        """
        if _DIAG_THRESHOLD <= 0:
            return

        global _diag_last_run_monotonic
        now = time.monotonic()
        # Throttle first so a hot insert loop past the threshold logs once, not
        # on every batch. (First call: _diag_last_run_monotonic == 0.)
        if _diag_last_run_monotonic and (now - _diag_last_run_monotonic) < _DIAG_INTERVAL_S:
            return

        try:
            total = db.query(RdfTripleDb).count()
        except Exception as e:
            logger.debug(f"rdf_triples bloat check: count failed: {e}")
            return

        if total < _DIAG_THRESHOLD:
            return

        # Threshold crossed — mark the run now (even if a sub-query fails, we
        # don't want to hammer these heavier queries) and collect the snapshot.
        _diag_last_run_monotonic = now
        logger.warning(
            "rdf_triples BLOAT DIAGNOSTIC (trigger=%s): total=%d rows exceeds "
            "threshold=%d — collecting forensic snapshot",
            trigger, total, _DIAG_THRESHOLD,
        )

        def _run(label: str, sql: str, params: Optional[dict] = None):
            try:
                rows = db.execute(text(sql), params or {}).fetchall()
                logger.warning("  [rdf_triples/%s] %s", label, [tuple(r) for r in rows])
            except Exception as e:
                logger.warning("  [rdf_triples/%s] query failed: %s", label, e)

        # Blank-node share (skolemised subjects or object references).
        _run(
            "blank_nodes",
            "SELECT count(*) FROM rdf_triples "
            "WHERE subject_uri LIKE 'urn:ontos:bnode:%' "
            "OR (object_is_uri AND object_value LIKE 'urn:ontos:bnode:%')",
        )
        # Rows vs distinct logical triples — a positive gap means the unique
        # constraint is NOT collapsing exact duplicates (NULL cols / no index).
        # Count distinct groups via a subquery (GROUP BY) rather than
        # count(DISTINCT (row-value)), which Postgres supports but SQLite (used
        # in tests) rejects with "row value misused".
        _run(
            "constraint_bypass",
            "SELECT (SELECT count(*) FROM rdf_triples) - (SELECT count(*) FROM ("
            "SELECT 1 FROM rdf_triples GROUP BY subject_uri, predicate_uri, object_value, "
            "object_language, object_datatype, context_name) g) AS non_dedup_rows",
        )
        # Where the rows live.
        _run(
            "by_source_type",
            "SELECT source_type, count(*) FROM rdf_triples GROUP BY source_type ORDER BY 2 DESC",
        )
        _run(
            "top_contexts",
            "SELECT context_name, count(*) FROM rdf_triples GROUP BY context_name ORDER BY 2 DESC LIMIT 15",
        )
        # Churn: subjects+predicates re-written far more than a healthy graph
        # would (a well-behaved predicate is usually 1 row per subject).
        _run(
            "top_churn_subject_predicate",
            "SELECT subject_uri, predicate_uri, count(*) AS n FROM rdf_triples "
            "GROUP BY subject_uri, predicate_uri HAVING count(*) > 5 ORDER BY n DESC LIMIT 15",
        )
        # Most-repeated predicates overall (cheap orientation on nature of bloat).
        _run(
            "by_predicate",
            "SELECT predicate_uri, count(*) FROM rdf_triples GROUP BY predicate_uri ORDER BY 2 DESC LIMIT 10",
        )


# Singleton instance
rdf_triples_repo = RdfTriplesRepository(RdfTripleDb)

