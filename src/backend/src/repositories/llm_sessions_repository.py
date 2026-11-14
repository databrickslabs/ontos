"""
LLM Sessions Repository

Database operations for LLM conversation sessions and messages.
"""

from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
import json
from datetime import timedelta

from src.common.timestamps import utc_now
from src.db_models.llm_sessions import LLMSessionDb, LLMMessageDb
from src.common.logging import get_logger

logger = get_logger(__name__)


class LLMSessionsRepository:
    """Repository for LLM session CRUD operations."""

    def get_session(self, db: Session, session_id: str) -> Optional[LLMSessionDb]:
        """Get a session by ID with all messages."""
        return db.query(LLMSessionDb).filter(LLMSessionDb.id == session_id).first()

    def get_session_for_user(self, db: Session, session_id: str, user_id: str) -> Optional[LLMSessionDb]:
        """Get a session by ID if owned by user."""
        return db.query(LLMSessionDb).filter(
            LLMSessionDb.id == session_id,
            LLMSessionDb.user_id == user_id
        ).first()

    def list_sessions_for_user(
        self,
        db: Session,
        user_id: str,
        limit: int = 50,
        skip: int = 0
    ) -> List[LLMSessionDb]:
        """List sessions for a user, ordered by most recently updated."""
        return db.query(LLMSessionDb).filter(
            LLMSessionDb.user_id == user_id
        ).order_by(desc(LLMSessionDb.updated_at)).offset(skip).limit(limit).all()

    def count_sessions_for_user(self, db: Session, user_id: str) -> int:
        """Count sessions for a user."""
        return db.query(LLMSessionDb).filter(LLMSessionDb.user_id == user_id).count()

    def create_session(self, db: Session, user_id: str, title: Optional[str] = None) -> LLMSessionDb:
        """Create a new session."""
        session = LLMSessionDb(user_id=user_id, title=title)
        db.add(session)
        db.flush()
        db.refresh(session)
        logger.info(f"Created LLM session {session.id} for user {user_id}")
        return session

    def update_session_title(self, db: Session, session: LLMSessionDb, title: str) -> LLMSessionDb:
        """Update session title."""
        session.title = title
        session.updated_at = utc_now()
        db.flush()
        db.refresh(session)
        return session

    def delete_session(self, db: Session, session_id: str) -> bool:
        """Delete a session and all its messages."""
        session = db.query(LLMSessionDb).filter(LLMSessionDb.id == session_id).first()
        if session:
            db.delete(session)
            db.flush()
            logger.info(f"Deleted LLM session {session_id}")
            return True
        return False

    def delete_session_for_user(self, db: Session, session_id: str, user_id: str) -> bool:
        """Delete a session only if owned by user."""
        session = self.get_session_for_user(db, session_id, user_id)
        if session:
            db.delete(session)
            db.flush()
            logger.info(f"Deleted LLM session {session_id} for user {user_id}")
            return True
        return False

    def add_message(
        self,
        db: Session,
        session: LLMSessionDb,
        role: str,
        content: Optional[str] = None,
        tool_calls: Optional[List[dict]] = None,
        tool_call_id: Optional[str] = None
    ) -> LLMMessageDb:
        """Add a message to a session."""
        # Get next sequence number
        max_seq = db.query(LLMMessageDb.sequence).filter(
            LLMMessageDb.session_id == session.id
        ).order_by(desc(LLMMessageDb.sequence)).first()
        
        sequence = (max_seq[0] + 1) if max_seq else 0

        message = LLMMessageDb(
            session_id=session.id,
            role=role,
            content=content,
            tool_calls=json.dumps(tool_calls) if tool_calls else None,
            tool_call_id=tool_call_id,
            sequence=sequence
        )
        db.add(message)
        
        # Update session timestamp
        session.updated_at = utc_now()
        
        # Auto-generate title from first user message if not set
        if not session.title and role == 'user' and content:
            session.title = content[:100] + ('...' if len(content) > 100 else '')
        
        db.flush()
        db.refresh(message)
        return message

    def get_messages_for_session(self, db: Session, session_id: str) -> List[LLMMessageDb]:
        """Get all messages for a session in order."""
        return db.query(LLMMessageDb).filter(
            LLMMessageDb.session_id == session_id
        ).order_by(LLMMessageDb.sequence).all()

    def cleanup_old_sessions(
        self,
        db: Session,
        max_age_hours: int = 24 * 30,  # 30 days default
        max_sessions_per_user: int = 50
    ) -> int:
        """Clean up old sessions. Returns number deleted."""
        deleted_count = 0
        cutoff = utc_now() - timedelta(hours=max_age_hours)

        # Delete expired sessions
        expired = db.query(LLMSessionDb).filter(LLMSessionDb.updated_at < cutoff).all()
        for session in expired:
            db.delete(session)
            deleted_count += 1

        # Get users with too many sessions and delete oldest
        from sqlalchemy import func as sqlfunc
        user_counts = db.query(
            LLMSessionDb.user_id,
            sqlfunc.count(LLMSessionDb.id).label('count')
        ).group_by(LLMSessionDb.user_id).having(
            sqlfunc.count(LLMSessionDb.id) > max_sessions_per_user
        ).all()

        for user_id, count in user_counts:
            excess = count - max_sessions_per_user
            oldest = db.query(LLMSessionDb).filter(
                LLMSessionDb.user_id == user_id
            ).order_by(LLMSessionDb.updated_at).limit(excess).all()
            for session in oldest:
                db.delete(session)
                deleted_count += 1

        if deleted_count > 0:
            db.flush()
            logger.info(f"Cleaned up {deleted_count} old LLM sessions")

        return deleted_count


# Singleton instance
llm_sessions_repository = LLMSessionsRepository()

