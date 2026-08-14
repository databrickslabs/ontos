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

    def delete_by_iri(self, db: Session, iri: str) -> int:
        """Delete ALL concept_version rows for an exact iri; returns row count.

        Used to self-heal orphaned version rows (rows whose concept was removed
        from the graph by a collection delete but whose concept_version rows were
        left behind, colliding with the unique constraints on a same-named
        recreate). Flushes so subsequent inserts in the same transaction see the
        deletion.
        """
        count = (
            db.query(ConceptVersionDb)
            .filter(ConceptVersionDb.iri == iri)
            .delete(synchronize_session=False)
        )
        db.flush()
        return count

    def delete_for_collection(self, db: Session, collection_iri: str) -> int:
        """Delete every concept_version row for concepts in a collection.

        Concept IRIs are always ``<collection_iri>/<slug>``, so a prefix match on
        ``collection_iri + '/'`` selects exactly this collection's concepts (and
        never the collection IRI itself). Must run in the SAME transaction as the
        rdf_triples deletion in ``delete_collection`` so recreating a same-named
        scheme+concept does not collide with leftover version rows. Flushes.

        The prefix is LIKE-escaped: collection IRIs routinely contain ``_`` (a
        LIKE single-char wildcard), e.g. ``urn:glossary:new_test_author_mk`` — an
        unescaped pattern would over-match a different collection and delete its
        version rows. ``\\`` is the escape char (both Postgres and SQLite honour
        ``ESCAPE``).
        """
        escaped = collection_iri.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        count = (
            db.query(ConceptVersionDb)
            .filter(ConceptVersionDb.iri.like(f"{escaped}/%", escape="\\"))
            .delete(synchronize_session=False)
        )
        db.flush()
        return count

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
        """Insert a new concept_version row and flush it (so its id is available).

        RAW insert with NO orphan/collision protection. New-concept v1 minting
        MUST go through ``SemanticModelsManager._mint_new_concept_version``, which
        self-heals orphaned leftover version rows and picks the next free version
        so a same-named recreate never hits the unique constraints
        (uq_concept_version_iri_version / uq_concept_version_current_per_iri).
        Calling this directly for a fresh v1 is a bug. The ONLY sanctioned direct
        caller is ``publish_concept_version``, which depends on the rawness: it
        demotes the current row first, then inserts version=max+1.
        """
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
