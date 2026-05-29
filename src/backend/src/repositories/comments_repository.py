from typing import List, Optional, Set
import json

from sqlalchemy.orm import Session
from sqlalchemy import and_, or_

from src.common.repository import CRUDBase
from src.db_models.comments import CommentDb, CommentStatus, CommentType as DbCommentType
from src.models.comments import CommentCreate, CommentUpdate, CommentType as ApiCommentType


class CommentsRepository(CRUDBase[CommentDb, CommentCreate, CommentUpdate]):
    def list_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        project_id: Optional[str] = None,
        user_groups: Optional[List[str]] = None,
        user_teams: Optional[List[str]] = None,
        user_app_role: Optional[str] = None,
        user_role_ids: Optional[Set[str]] = None,
        include_deleted: bool = False
    ) -> List[CommentDb]:
        """Get comments for a specific entity, filtered by project and audience visibility.

        Args:
            db: Database session
            entity_type: Type of entity (data_domain, data_product, etc.)
            entity_id: ID of the entity
            project_id: Filter by project ID. If provided, matches comments with this
                project_id or null (global)
            user_groups: List of user's group memberships
            user_teams: List of team IDs the user belongs to
            user_app_role: The user's app role *name* (legacy team-override path;
                matches ``role:<name>`` tokens in stored audience JSON)
            user_role_ids: Set of AppRole UUIDs the viewer holds (group-derived + any
                applied override). Matches ``role_id:<uuid>`` tokens in stored audience
                JSON. This is the authoritative path introduced in issue #326.
            include_deleted: Whether to include soft-deleted comments
        """
        query = db.query(CommentDb).filter(
            CommentDb.entity_type == entity_type,
            CommentDb.entity_id == entity_id
        )

        # Filter by project_id: match specific project or global (null) comments
        if project_id is not None:
            query = query.filter(
                or_(
                    CommentDb.project_id == project_id,
                    CommentDb.project_id.is_(None)
                )
            )

        # Filter by status unless explicitly including deleted
        if not include_deleted:
            query = query.filter(CommentDb.status == CommentStatus.ACTIVE)

        # Filter by audience if user info provided
        has_audience_filter = (
            user_groups is not None
            or user_teams is not None
            or user_app_role is not None
            or user_role_ids is not None
        )
        if has_audience_filter:
            # Comments are visible to the user if:
            # 1. audience is null (visible to all)
            # 2. audience contains at least one of user's groups (plain string)
            # 3. audience contains team:<team_id> matching user's teams
            # 4. audience contains role:<role_name> matching user's app role (legacy)
            # 5. audience contains role_id:<uuid> matching one of the user's effective
            #    AppRole UUIDs (group-derived or override — introduced in issue #326)
            audience_conditions = [CommentDb.audience.is_(None)]

            # Check plain group memberships
            if user_groups:
                for group in user_groups:
                    audience_conditions.append(
                        CommentDb.audience.contains(f'"{group}"')
                    )

            # Check team: prefixed tokens
            if user_teams:
                for team_id in user_teams:
                    audience_conditions.append(
                        CommentDb.audience.contains(f'"team:{team_id}"')
                    )

            # Check legacy role:<name> token (team-override path)
            if user_app_role:
                audience_conditions.append(
                    CommentDb.audience.contains(f'"role:{user_app_role}"')
                )

            # Check role_id:<uuid> tokens — the authoritative path for new comments
            if user_role_ids:
                for role_id in user_role_ids:
                    audience_conditions.append(
                        CommentDb.audience.contains(f'"role_id:{role_id}"')
                    )

            query = query.filter(or_(*audience_conditions))

        return query.order_by(CommentDb.created_at.desc()).all()
    
    def create_with_audience(
        self, 
        db: Session, 
        *, 
        obj_in: CommentCreate, 
        created_by: str
    ) -> CommentDb:
        """Create a comment with proper audience JSON handling."""
        # Convert audience list to JSON string if provided
        audience_json = json.dumps(obj_in.audience) if obj_in.audience else None
        
        # Create the comment dict without the audience and comment_type fields
        # (we need to convert comment_type from Pydantic enum to DB enum)
        comment_data = obj_in.model_dump(exclude={"audience", "comment_type"})
        comment_data["created_by"] = created_by
        comment_data["audience"] = audience_json
        
        # Convert Pydantic CommentType enum to DB CommentType enum
        if obj_in.comment_type == ApiCommentType.RATING:
            comment_data["comment_type"] = DbCommentType.RATING
        else:
            comment_data["comment_type"] = DbCommentType.COMMENT
        
        db_obj = CommentDb(**comment_data)
        
        try:
            db.add(db_obj)
            db.flush()
            db.refresh(db_obj)
            return db_obj
        except Exception as e:
            db.rollback()
            raise
    
    def update_with_audience(
        self, 
        db: Session, 
        *, 
        db_obj: CommentDb, 
        obj_in: CommentUpdate, 
        updated_by: str
    ) -> CommentDb:
        """Update a comment with proper audience JSON handling."""
        update_data = obj_in.model_dump(exclude_unset=True, exclude={"audience"})
        update_data["updated_by"] = updated_by
        
        # Handle audience update if provided
        if obj_in.audience is not None:
            update_data["audience"] = json.dumps(obj_in.audience) if obj_in.audience else None
        
        for field, value in update_data.items():
            if hasattr(db_obj, field):
                setattr(db_obj, field, value)
        
        try:
            db.add(db_obj)
            db.flush()
            db.refresh(db_obj)
            return db_obj
        except Exception as e:
            db.rollback()
            raise
    
    def soft_delete(self, db: Session, *, comment_id: str, deleted_by: str) -> Optional[CommentDb]:
        """Soft delete a comment by setting status to DELETED."""
        comment = self.get(db, comment_id)
        if comment:
            comment.status = CommentStatus.DELETED
            comment.updated_by = deleted_by
            try:
                db.add(comment)
                db.flush()
                db.refresh(comment)
                return comment
            except Exception as e:
                db.rollback()
                raise
        return None
    
    def can_user_modify(self, comment: CommentDb, user_email: str, is_admin: bool = False) -> bool:
        """Check if a user can modify (edit/delete) a comment."""
        return is_admin or comment.created_by == user_email

    def list_ratings_for_entity(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        user_email: Optional[str] = None
    ) -> List[CommentDb]:
        """Get all rating-type comments for an entity.
        
        Args:
            db: Database session
            entity_type: Type of entity (data_product, dataset, etc.)
            entity_id: ID of the entity
            user_email: Optional filter by specific user's ratings
            
        Returns:
            List of rating entries ordered by created_at desc
        """
        query = db.query(CommentDb).filter(
            CommentDb.entity_type == entity_type,
            CommentDb.entity_id == entity_id,
            CommentDb.comment_type == DbCommentType.RATING,
            CommentDb.status == CommentStatus.ACTIVE
        )
        
        if user_email:
            query = query.filter(CommentDb.created_by == user_email)
        
        return query.order_by(CommentDb.created_at.desc()).all()


# Instantiate repository
comments_repo = CommentsRepository(CommentDb)