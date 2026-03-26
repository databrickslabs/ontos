"""Repository for RDF triples storage operations.

Provides CRUD operations for RDF triples with support for bulk inserts
and context-based queries.
"""
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy import and_
import uuid

from src.common.repository import CRUDBase
from src.db_models.rdf_triples import RdfTripleDb
from src.common.logging import get_logger

logger = get_logger(__name__)


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


# Singleton instance
rdf_triples_repo = RdfTriplesRepository(RdfTripleDb)

