"""Repository for concept-version rows (the versioned unit ``(iri, version)``).

Backs the atomic-publish swap (P0-3). The partial unique index
``uq_concept_version_current_per_iri`` (migration ``m1_concept_versioning``) is the
DB-level backstop that makes two ``is_current=true`` rows for one ``iri``
structurally impossible; the swap here demotes the old current BEFORE inserting the
new current so that invariant is never transiently violated.
"""
from typing import List, Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from src.common.repository import CRUDBase
from src.db_models.concept_versions import ConceptVersionDb
from src.common.logging import get_logger

logger = get_logger(__name__)


class ConceptVersionsRepository(CRUDBase[ConceptVersionDb, dict, dict]):
    """CRUD + version-swap helpers for ``concept_version``."""

    def get_current(self, db: Session, iri: str) -> Optional[ConceptVersionDb]:
        """The single current version for an iri (or None if not yet versioned)."""
        return (
            db.query(ConceptVersionDb)
            .filter(ConceptVersionDb.iri == iri, ConceptVersionDb.is_current.is_(True))
            .one_or_none()
        )

    def get_by_iri_version(
        self, db: Session, iri: str, version: int
    ) -> Optional[ConceptVersionDb]:
        """Fetch a specific historical (or current) version by key."""
        return (
            db.query(ConceptVersionDb)
            .filter(ConceptVersionDb.iri == iri, ConceptVersionDb.version == version)
            .one_or_none()
        )

    def list_versions(self, db: Session, iri: str) -> List[ConceptVersionDb]:
        """All versions for an iri, newest first."""
        return (
            db.query(ConceptVersionDb)
            .filter(ConceptVersionDb.iri == iri)
            .order_by(ConceptVersionDb.version.desc())
            .all()
        )

    def max_version(self, db: Session, iri: str) -> int:
        """Highest version number for an iri, or 0 if none exist."""
        result = (
            db.query(func.max(ConceptVersionDb.version))
            .filter(ConceptVersionDb.iri == iri)
            .scalar()
        )
        return int(result) if result is not None else 0

    def demote_current(self, db: Session, iri: str, status: str = "superseded") -> Optional[ConceptVersionDb]:
        """Flip the current version to history (``is_current=false``).

        MUST be flushed before inserting the new current row so the partial
        unique index never sees two current rows for the iri.
        """
        current = self.get_current(db, iri)
        if current is None:
            return None
        current.is_current = False
        current.status = status
        db.flush()
        return current

    def create_version(
        self,
        db: Session,
        iri: str,
        version: int,
        is_current: bool = True,
        status: str = "active",
        parent_version_id=None,
        replaces_iri: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> ConceptVersionDb:
        """Insert a new concept_version row and flush it (so its id is available)."""
        cv = ConceptVersionDb(
            iri=iri,
            version=version,
            is_current=is_current,
            status=status,
            parent_version_id=parent_version_id,
            replaces_iri=replaces_iri,
            created_by=created_by,
        )
        db.add(cv)
        db.flush()
        return cv


# Singleton instance (matches rdf_triples_repo / entity_semantic_links_repo pattern).
concept_versions_repo = ConceptVersionsRepository(ConceptVersionDb)
