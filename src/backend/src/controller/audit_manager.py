import asyncio
import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from src.common.config import Settings
from src.common.logging import get_logger
from src.models.audit_log import AuditLogCreate, AuditLogRead
from src.repositories.audit_log_repository import audit_log_repository
from src.db_models.audit_log import AuditLogDb # Import the DB model
from src.common.database import get_session_factory # Import session factory

# Use the main logger configuration but add a specific handler for audit logs
file_audit_logger = logging.getLogger("audit_file")
# Prevent propagation to avoid duplicate logging if root logger has handlers
file_audit_logger.propagate = False 


def log_system_action(
    *,
    username: str,
    feature: str,
    action: str,
    success: bool,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Audit an action the app takes outside a request, where no AuditManager is at hand.

    Writes the same entry as ``AuditManager.log_action`` (audit file and
    database, in its own session), without a client IP.
    """
    session_factory = get_session_factory()
    if not session_factory:
        get_logger(__name__).error("Cannot log audit action: DB session factory not available.")
        return
    log_entry_data = {
        "username": username,
        "ip_address": None,
        "feature": feature,
        "action": action,
        "success": success,
        "details": details or {},
    }
    # The entry is written as AuditManager writes it; the instance skips __init__,
    # which would reconfigure the audit file logger the app set up at startup.
    writer = AuditManager.__new__(AuditManager)
    writer.repository = audit_log_repository
    try:
        with session_factory() as independent_db:
            writer._log_action_internal(independent_db, log_entry_data)
    except Exception as e:
        get_logger(__name__).error(f"[SYNC] Failed to write audit log: {e}", exc_info=True)


class AuditManager:
    """Manages logging of user actions to file and database."""

    def __init__(self, settings: Settings, db_session: Session):
        self.settings = settings
        self.db = db_session # Store session for potential direct use if needed, though repo is preferred
        self.repository = audit_log_repository
        self._configure_file_logger()

    def _configure_file_logger(self):
        """Configures the file logger for audit trails."""
        log_dir_path = Path(self.settings.APP_AUDIT_LOG_DIR)
        try:
            log_dir_path.mkdir(parents=True, exist_ok=True)
            log_file = log_dir_path / "audit.log"

            # Use JSON formatter for structured logging
            formatter = logging.Formatter(
                '{"timestamp": "%(asctime)s", "level": "%(levelname)s", "message": "%(message)s"}',
                datefmt='%Y-%m-%dT%H:%M:%S%z' # ISO 8601 format
            )
            
            # Rotate logs hourly, keeping 24 * 7 = 168 hours (1 week)
            file_handler = TimedRotatingFileHandler(
                log_file, 
                when="H", 
                interval=1, 
                backupCount=168, # Keep 1 week of hourly logs
                encoding='utf-8'
            )
            file_handler.setFormatter(formatter)

            # Clear existing handlers to avoid duplication if re-initialized
            if file_audit_logger.hasHandlers():
                file_audit_logger.handlers.clear()

            file_audit_logger.addHandler(file_handler)
            file_audit_logger.setLevel(logging.INFO) # Log INFO level and above to file
            file_audit_logger.info(f"Audit file logger configured. Logging to: {log_file}")

        except Exception as e:
            # Fallback to standard logger if file logging fails
            main_logger = get_logger(__name__)
            main_logger.error(f"Failed to configure audit file logger at {log_dir_path}: {e}", exc_info=True)
            # Ensure logger is disabled if setup fails
            file_audit_logger.disabled = True 


    def _log_action_internal(
        self,
        db: Session,
        log_entry_data: Dict[str, Any]
    ):
        """Internal synchronous logic to log to file and DB using a given session."""
        # 1. Log to file (structured as JSON string)
        if not file_audit_logger.disabled:
            try:
                file_log_message = {
                    "user": log_entry_data["username"],
                    "ip": log_entry_data["ip_address"],
                    "feature": log_entry_data["feature"],
                    "action": log_entry_data["action"],
                    "success": log_entry_data["success"],
                    "details": log_entry_data["details"]
                }
                file_audit_logger.info(str(file_log_message).replace("'", '"'))
            except Exception as e:
                main_logger = get_logger(__name__)
                main_logger.error(f"Failed to write audit log to file: {e}", exc_info=True)

        # 2. Log to database
        try:
            log_entry = AuditLogCreate(**log_entry_data)
            self.repository.create(db=db, obj_in=log_entry)
            db.commit() # Commit this independent transaction
        except Exception as e:
            main_logger = get_logger(__name__)
            main_logger.error(f"Failed to write audit log to database: {e}", exc_info=True)
            db.rollback() # Rollback only the audit transaction on error
            # Do not re-raise here, as it's a background task

    # Original log_action (now uses independent session and commits)
    def log_action(
        self,
        db: Session, # Ignored - kept for backwards compatibility
        *,
        username: str,
        ip_address: Optional[str],
        feature: str,
        action: str,
        success: bool,
        details: Optional[Dict[str, Any]] = None
    ):
        """Logs an action synchronously using an INDEPENDENT DB session with auto-commit."""
        session_factory = get_session_factory()
        if not session_factory:
            main_logger = get_logger(__name__)
            main_logger.error("Cannot log audit action: DB session factory not available.")
            return

        log_entry_data = {
            "username": username,
            "ip_address": ip_address,
            "feature": feature,
            "action": action,
            "success": success,
            "details": details or {},
        }

        try:
            with session_factory() as independent_db:
                # Use the internal logging logic which commits
                self._log_action_internal(db=independent_db, log_entry_data=log_entry_data)
        except Exception as e:
            main_logger = get_logger(__name__)
            main_logger.error(f"[SYNC] Failed to write audit log: {e}", exc_info=True)

    # New method for background task
    async def log_action_background(
        self,
        *,
        username: str,
        ip_address: Optional[str],
        feature: str,
        action: str,
        success: bool,
        details: Optional[Dict[str, Any]] = None
    ):
        """Logs an action in the background using an independent DB session."""
        session_factory = get_session_factory()
        if not session_factory:
            main_logger = get_logger(__name__)
            main_logger.error("Cannot log audit action in background: DB session factory not available.")
            return

        log_entry_data = {
            "username": username,
            "ip_address": ip_address,
            "feature": feature,
            "action": action,
            "success": success,
            "details": details or {},
        }
        
        db_session = None
        try:
            with session_factory() as db_session:
                # Run the internal logging logic (which now handles file+DB and commits)
                self._log_action_internal(db=db_session, log_entry_data=log_entry_data)
        except Exception as e:
            # Catch potential errors during session creation or the internal log call itself
            main_logger = get_logger(__name__)
            main_logger.error(f"Error during background audit logging process: {e}", exc_info=True)
            if db_session:
                 db_session.rollback() # Ensure rollback if session existed but internal log failed before commit
        # Session is automatically closed by the context manager

    async def get_audit_logs(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        username: Optional[str] = None,
        feature: Optional[str] = None,
        action: Optional[str] = None,
        success: Optional[bool] = None,
    ) -> tuple[int, List[AuditLogRead]]:
        """Retrieves audit logs from the database with filtering and pagination."""
        try:
            total_count = self.repository.get_multi_count(
                db,
                start_time=start_time,
                end_time=end_time,
                username=username,
                feature=feature,
                action=action,
                success=success,
            )
            db_logs = self.repository.get_multi(
                db,
                skip=skip,
                limit=limit,
                start_time=start_time,
                end_time=end_time,
                username=username,
                feature=feature,
                action=action,
                success=success,
            )
            # Convert DB models to Pydantic models for response
            return total_count, [AuditLogRead.model_validate(log) for log in db_logs]
        except Exception as e:
            main_logger = get_logger(__name__)
            main_logger.error(f"Failed to retrieve audit logs from database: {e}", exc_info=True)
            # Return empty list or re-raise
            return 0, [] 