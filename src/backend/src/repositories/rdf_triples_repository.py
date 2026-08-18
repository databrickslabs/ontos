"""Repository for RDF triples storage operations.

Provides CRUD operations for RDF triples with support for bulk inserts
and context-based queries.
"""
import os
import time
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import and_, text
import uuid

from src.common.repository import CRUDBase
from src.db_models.rdf_triples import RdfTripleDb
from src.common.logging import get_logger

logger = get_logger(__name__)

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
    ) -> Optional[RdfTripleDb]:
        """Add a single triple with ON CONFLICT DO NOTHING.

        Returns the triple if inserted, None if it already existed.
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
        ).on_conflict_do_nothing(
            index_elements=['subject_uri', 'predicate_uri', 'object_value', 
                           'object_language', 'object_datatype', 'context_name']
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
                index_elements=['subject_uri', 'predicate_uri', 'object_value', 
                               'object_language', 'object_datatype', 'context_name']
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
        """Get all triples from the database."""
        return db.query(RdfTripleDb).all()

    def list_by_subject(self, db: Session, subject_uri: str) -> List[RdfTripleDb]:
        """Get all triples with a given subject."""
        return db.query(RdfTripleDb).filter(
            RdfTripleDb.subject_uri == subject_uri
        ).all()

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
    ) -> int:
        """Remove all triples matching subject and predicate.
        
        Useful for updating properties where you don't know the old value.
        Returns the number of triples deleted.
        """
        query = db.query(RdfTripleDb).filter(
            and_(
                RdfTripleDb.subject_uri == subject_uri,
                RdfTripleDb.predicate_uri == predicate_uri,
            )
        )
        if context_name:
            query = query.filter(RdfTripleDb.context_name == context_name)
        
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

