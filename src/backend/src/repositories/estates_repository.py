from typing import List, Optional

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.repository import CRUDBase
from src.db_models.estates import EstateDb, SharingPolicyDb, SharingRuleDb
from src.models.estate import Estate, SharingPolicy, SharingPolicyDirection

logger = get_logger(__name__)


class EstatesRepository(CRUDBase[EstateDb, Estate, Estate]):
    """Estates with their export/import sharing policies and rules."""

    def __init__(self):
        super().__init__(EstateDb)

    def list_all(self, db: Session) -> List[EstateDb]:
        try:
            return db.query(EstateDb).order_by(EstateDb.name).all()
        except SQLAlchemyError:
            db.rollback()
            raise

    def get_by_name(self, db: Session, name: str) -> Optional[EstateDb]:
        try:
            return db.query(EstateDb).filter(EstateDb.name == name).first()
        except SQLAlchemyError:
            db.rollback()
            raise

    @staticmethod
    def _policy_rows(
        policies: List[SharingPolicy], direction: SharingPolicyDirection, existing: dict
    ) -> List[SharingPolicyDb]:
        rows = []
        for position, policy in enumerate(policies):
            row = existing.pop(policy.id, None) if policy.id else None
            if row is None or row.direction != direction.value:
                # Unknown ids (or a policy moved to the other list) get a new row and id.
                row = SharingPolicyDb()
            row.direction = direction.value
            row.name = policy.name
            row.description = policy.description
            row.resource_type = policy.resource_type.value
            row.is_enabled = policy.is_enabled
            row.position = position
            row.rules = [
                SharingRuleDb(
                    filter_type=rule.filter_type,
                    operator=rule.operator.value,
                    filter_value=rule.filter_value,
                    position=rule_position,
                )
                for rule_position, rule in enumerate(policy.rules)
            ]
            rows.append(row)
        return rows

    def apply(self, db: Session, row: EstateDb, estate: Estate) -> EstateDb:
        """Copy the estate's fields and policies onto ``row`` (new or existing).

        Policies keep their id when the payload names one the estate already has, so an
        edit doesn't change ids; their rules are replaced as a whole.
        """
        row.name = estate.name
        row.description = estate.description
        row.workspace_url = estate.workspace_url
        row.cloud_type = estate.cloud_type.value
        row.metastore_name = estate.metastore_name
        row.connection_type = estate.connection_type.value
        row.is_enabled = estate.is_enabled
        row.sync_schedule = estate.sync_schedule
        existing = {p.id: p for p in (row.policies or [])}
        row.policies = (
            self._policy_rows(estate.export_policies, SharingPolicyDirection.EXPORT, existing)
            + self._policy_rows(estate.import_policies, SharingPolicyDirection.IMPORT, existing)
        )
        return row


estates_repo = EstatesRepository()
