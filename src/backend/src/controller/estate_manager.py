from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.db_models.estates import EstateDb, SharingPolicyDb
from src.models.estate import (
    Estate, SharingPolicy, SharingPolicyDirection, SharingRule, SyncStatus,
)
from src.repositories.estates_repository import EstatesRepository, estates_repo

logger = get_logger(__name__)


class EstateNameConflictError(CodedValueError):
    code = 'estate_name_conflict'


class EstateManager:
    """Estates stored in the database (PRD #143, #146).

    One instance lives on ``app.state.estate_manager``; every method takes the
    request's session, like the other DB-backed managers.
    """

    def __init__(self, repository: Optional[EstatesRepository] = None):
        self._repo = repository or estates_repo

    # --- conversion ---------------------------------------------------------------

    @staticmethod
    def _policy_to_api(row: SharingPolicyDb) -> SharingPolicy:
        return SharingPolicy(
            id=row.id,
            name=row.name,
            description=row.description,
            resource_type=row.resource_type,
            rules=[
                SharingRule(filter_type=r.filter_type, operator=r.operator, filter_value=r.filter_value)
                for r in row.rules
            ],
            is_enabled=row.is_enabled,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _to_api(self, row: EstateDb) -> Estate:
        policies = list(row.policies or [])
        return Estate(
            id=row.id,
            name=row.name,
            description=row.description or '',
            workspace_url=row.workspace_url,
            cloud_type=row.cloud_type,
            metastore_name=row.metastore_name,
            connection_type=row.connection_type,
            export_policies=[
                self._policy_to_api(p) for p in policies if p.direction == SharingPolicyDirection.EXPORT.value
            ],
            import_policies=[
                self._policy_to_api(p) for p in policies if p.direction == SharingPolicyDirection.IMPORT.value
            ],
            is_enabled=row.is_enabled,
            sync_schedule=row.sync_schedule,
            last_sync_time=row.last_sync_time,
            last_sync_status=row.last_sync_status,
            last_sync_error=row.last_sync_error,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _check_name_free(self, db: Session, name: str, estate_id: Optional[str] = None) -> None:
        other = self._repo.get_by_name(db, name)
        if other is not None and other.id != estate_id:
            raise EstateNameConflictError(f"An estate named '{name}' already exists.", name=name)

    @staticmethod
    def _is_name_conflict(error: IntegrityError) -> bool:
        """Whether ``error`` is the unique constraint on ``estates.name``."""
        message = str(getattr(error, 'orig', error)).lower()
        # Postgres names the constraint estates_name_key; SQLite reports the column.
        return 'estates_name_key' in message or 'estates.name' in message

    def _commit(self, db: Session, name: str, commit: bool = True) -> None:
        """Flush and optionally commit, turning a lost race on the unique name into the coded 409.

        The pre-check can't see an estate another request creates in the
        meantime; the database constraint then fails the commit. Other
        integrity errors are re-raised unchanged.

        Args:
            db: Database session
            name: Estate name for error reporting
            commit: If True, commit after flush. If False, only flush (for batch operations).
        """
        try:
            db.flush()
        except IntegrityError as e:
            db.rollback()
            if self._is_name_conflict(e):
                raise EstateNameConflictError(
                    f"An estate named '{name}' already exists.", name=name
                ) from e
            raise
        if commit:
            db.commit()

    # --- CRUD -----------------------------------------------------------------------

    def list_estates(self, db: Session) -> List[Estate]:
        return [self._to_api(row) for row in self._repo.list_all(db)]

    def get_estate(self, db: Session, estate_id: str) -> Optional[Estate]:
        row = self._repo.get(db, estate_id)
        return self._to_api(row) if row else None

    def create_estate(self, db: Session, estate: Estate, user: Optional[str] = None) -> Estate:
        self._check_name_free(db, estate.name)
        row = self._repo.apply(db, EstateDb(), estate)
        row.created_by = user
        row.updated_by = user
        db.add(row)
        self._commit(db, estate.name)
        db.refresh(row)
        logger.info("Created estate %s (%s)", row.name, row.id)
        return self._to_api(row)

    def create_estate_batch(self, db: Session, estate: Estate, user: Optional[str] = None) -> EstateDb:
        """Create an estate without committing (for batch operations like YAML import).

        This is an internal method used by bulk import operations that need to
        commit multiple estates atomically. It flushes to the session but does
        not commit, allowing the caller to batch multiple creates and commit once.

        Returns the database row (not the API model), which must be refreshed
        by the caller after commit.
        """
        self._check_name_free(db, estate.name)
        row = self._repo.apply(db, EstateDb(), estate)
        row.created_by = user
        row.updated_by = user
        db.add(row)
        self._commit(db, estate.name, commit=False)
        logger.info("Staged estate for batch import: %s", row.name)
        return row

    def update_estate(
        self, db: Session, estate_id: str, estate: Estate, user: Optional[str] = None
    ) -> Optional[Estate]:
        row = self._repo.get(db, estate_id)
        if row is None:
            return None
        self._check_name_free(db, estate.name, estate_id)
        self._repo.apply(db, row, estate)
        row.updated_by = user
        row.updated_at = datetime.now(timezone.utc)
        self._commit(db, estate.name)
        db.refresh(row)
        return self._to_api(row)

    def delete_estate(self, db: Session, estate_id: str) -> bool:
        row = self._repo.get(db, estate_id)
        if row is None:
            return False
        db.delete(row)
        db.commit()
        return True

    def sync_estate(self, db: Session, estate_id: str) -> bool:
        """Record a sync of the estate.

        The transport (Git, Delta Sharing) isn't implemented yet (PRD #143), so the
        sync only records its time and status, as it did before estates were stored.
        """
        row = self._repo.get(db, estate_id)
        if row is None or not row.is_enabled:
            logger.warning("Sync attempt for disabled or non-existent estate: %s", estate_id)
            return False
        logger.info("Recording sync for estate %s (%s), connection %s", row.name, estate_id, row.connection_type)
        row.last_sync_time = datetime.now(timezone.utc)
        row.last_sync_status = SyncStatus.SUCCESS.value
        row.last_sync_error = None
        db.commit()
        return True
