from typing import List, Optional
import json

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.repositories.change_log_repository import change_log_repo, ChangeLogRepository
from src.db_models.change_log import ChangeLogDb

logger = get_logger(__name__)


class ChangeLogManager:
    def __init__(self, change_log_repository: ChangeLogRepository = change_log_repo):
        self._change_log_repo = change_log_repository

    def log_change(
        self, 
        db: Session, 
        *, 
        entity_type: str, 
        entity_id: str, 
        action: str, 
        username: Optional[str], 
        details_json: Optional[str] = None
    ) -> ChangeLogDb:
        """Log a change to the change log."""
        logger.info(f"Logging change: {entity_type}:{entity_id} - {action} by {username}")
        
        entry = ChangeLogDb(
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            username=username,
            details_json=details_json,
        )
        db.add(entry)
        db.commit()
        db.refresh(entry)
        return entry

    def log_change_with_details(
        self, 
        db: Session, 
        *, 
        entity_type: str, 
        entity_id: str, 
        action: str, 
        username: Optional[str], 
        details: Optional[dict] = None
    ) -> ChangeLogDb:
        """Log a change with structured details."""
        details_json = None
        if details:
            try:
                details_json = json.dumps(details)
            except (TypeError, ValueError) as e:
                logger.warning(f"Failed to serialize details to JSON: {e}")
                
        return self.log_change(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            username=username,
            details_json=details_json
        )

    def get_changes_for_entity(
        self, db: Session, entity_type: str, entity_id: str, limit: int = 100
    ) -> List[ChangeLogDb]:
        """Change log entries for an entity, newest first (``entry.details`` is parsed).

        Used by the request / approval flows to find who made a request.
        """
        return self.list_changes_for_entity(
            db, entity_type=entity_type, entity_id=entity_id, limit=limit
        )

    def list_changes_for_entity(
        self, 
        db: Session, 
        *, 
        entity_type: str, 
        entity_id: str, 
        limit: int = 100
    ) -> List[ChangeLogDb]:
        """List change log entries for a specific entity."""
        return self._change_log_repo.list_by_entity(
            db, 
            entity_type=entity_type, 
            entity_id=entity_id, 
            limit=limit
        )

    def list_filtered_changes(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        username: Optional[str] = None,
        action: Optional[str] = None,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> List[ChangeLogDb]:
        """List filtered change log entries."""
        return self._change_log_repo.list_filtered(
            db,
            skip=skip,
            limit=limit,
            entity_type=entity_type,
            entity_id=entity_id,
            username=username,
            action=action,
            start_time=start_time,
            end_time=end_time,
        )


change_log_manager = ChangeLogManager()