from typing import List, Optional, Set
import json

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.models.comments import Comment, CommentCreate, CommentUpdate, CommentListResponse, CommentType, RatingAggregation
from src.repositories.comments_repository import comments_repo, CommentsRepository
from src.db_models.comments import CommentStatus, CommentType as DbCommentType

logger = get_logger(__name__)


class CommentsManager:
    def __init__(
        self,
        comments_repository: CommentsRepository = comments_repo,
        settings_manager=None,
        authorization_manager=None,
    ):
        self._comments_repo = comments_repository
        self._settings_manager = settings_manager
        self._authorization_manager = authorization_manager


    def _convert_audience_from_json(self, comment_db) -> Optional[List[str]]:
        """Convert JSON audience string back to list."""
        if comment_db.audience is None:
            return None
        try:
            return json.loads(comment_db.audience)
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Invalid JSON in comment audience: {comment_db.audience}")
            return None

    def _db_to_api_model(self, comment_db) -> Comment:
        """Convert database model to API model with proper audience handling."""
        # Convert DB enum to API enum for comment_type
        comment_type_value = CommentType.COMMENT
        if comment_db.comment_type == DbCommentType.RATING:
            comment_type_value = CommentType.RATING
        
        # Create the base comment data
        comment_data = {
            "id": comment_db.id,
            "entity_id": comment_db.entity_id,
            "entity_type": comment_db.entity_type,
            "title": comment_db.title,
            "comment": comment_db.comment,
            "audience": self._convert_audience_from_json(comment_db),
            "project_id": comment_db.project_id,
            "status": comment_db.status,
            "comment_type": comment_type_value,
            "rating": comment_db.rating,
            "created_by": comment_db.created_by,
            "updated_by": comment_db.updated_by,
            "created_at": comment_db.created_at,
            "updated_at": comment_db.updated_at,
        }
        return Comment(**comment_data)

    # ------------------------------------------------------------------
    # Role-audience helpers
    # ------------------------------------------------------------------

    def _resolve_viewer_role_ids(
        self,
        user_groups: Optional[List[str]],
        applied_role_override_id: Optional[str] = None,
    ) -> Set[str]:
        """Return the set of AppRole UUIDs the viewer holds.

        Delegates to ``AuthorizationManager.get_user_effective_role_ids`` when
        the authorization manager is available; falls back to an empty set so
        callers that don't inject the manager degrade gracefully (unfiltered
        audience is already handled upstream).
        """
        if self._authorization_manager is None:
            logger.debug("_resolve_viewer_role_ids: no authorization_manager; returning empty set")
            return set()
        try:
            return self._authorization_manager.get_user_effective_role_ids(
                user_groups, applied_role_override_id
            )
        except Exception:
            logger.exception("_resolve_viewer_role_ids: unexpected error; returning empty set")
            return set()

    def _resolve_legacy_role_name_to_id(self, role_name: str) -> Optional[str]:
        """Look up a role UUID by name for legacy ``role:<name>`` tokens."""
        if self._settings_manager is None:
            return None
        try:
            role = self._settings_manager.get_app_role_by_name(role_name)
            return str(role.id) if role else None
        except Exception:
            logger.exception("_resolve_legacy_role_name_to_id: error resolving name '%s'", role_name)
            return None

    def create_comment(
        self, 
        db: Session, 
        *, 
        data: CommentCreate, 
        user_email: str,
        user_teams: Optional[List[str]] = None,
        is_admin: bool = False
    ) -> Comment:
        """Create a new comment.
        
        Args:
            db: Database session
            data: Comment creation data
            user_email: Email of the user creating the comment
            user_teams: List of team IDs the user belongs to (for validation)
            is_admin: Whether the user is an admin
            
        Returns:
            Created comment
            
        Raises:
            ValueError: If project_id is None and user is not admin or member of owning team
        """
        logger.info(f"Creating comment for {data.entity_type}:{data.entity_id} by {user_email}, project_id={data.project_id}")
        
        # Validate global comment creation (project_id is None)
        if data.project_id is None and not is_admin:
            # For now, allow global comments only for admins
            # In the future, could check if user is member of entity's owning team
            logger.warning(f"User {user_email} attempted to create global comment without admin privileges")
            raise ValueError("Only administrators or entity owners can create global comments")
        
        db_obj = self._comments_repo.create_with_audience(
            db, obj_in=data, created_by=user_email
        )
        db.commit()
        db.refresh(db_obj)
        
        return self._db_to_api_model(db_obj)

    def list_comments(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        project_id: Optional[str] = None,
        user_groups: Optional[List[str]] = None,
        user_teams: Optional[List[str]] = None,
        user_app_role: Optional[str] = None,
        user_email: Optional[str] = None,
        applied_role_override_id: Optional[str] = None,
        include_deleted: bool = False
    ) -> CommentListResponse:
        """List comments for an entity, filtered by project and user's audience visibility.

        Args:
            db: Database session
            entity_type: Type of entity
            entity_id: ID of entity
            project_id: Filter by project context
            user_groups: User's group memberships
            user_teams: User's team memberships (IDs)
            user_app_role: User's app role name (legacy team-override path; kept for
                backward-compat but superseded by group-derived role resolution)
            user_email: User's email (for direct targeting)
            applied_role_override_id: UUID of the role the viewer has pinned via the
                role-switcher (from SettingsManager.get_applied_role_override_for_user).
                When set, this takes full precedence over group-derived roles.
            include_deleted: Include soft-deleted comments
        """
        logger.debug(f"Listing comments for {entity_type}:{entity_id}, project_id={project_id}")

        # Resolve the set of AppRole UUIDs this viewer holds, using the same
        # group-membership + override logic that AuthorizationManager uses for
        # feature-permission checks.
        viewer_role_ids: Set[str] = self._resolve_viewer_role_ids(
            user_groups, applied_role_override_id
        )

        # Get all comments (for total count) - without project filter for admin view
        all_comments = self._comments_repo.list_for_entity(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=None,  # Get all for count
            user_groups=None,
            user_teams=None,
            user_app_role=None,
            user_role_ids=None,
            include_deleted=include_deleted
        )
        total_count = len(all_comments)

        # Get visible comments filtered by project and audience.
        # Pass both the legacy user_app_role (team-override name) and the new
        # viewer_role_ids so the repository can match both token formats.
        visible_comments = self._comments_repo.list_for_entity(
            db,
            entity_type=entity_type,
            entity_id=entity_id,
            project_id=project_id,
            user_groups=user_groups,
            user_teams=user_teams,
            user_app_role=user_app_role,
            user_role_ids=viewer_role_ids if viewer_role_ids else None,
            include_deleted=include_deleted
        )

        # Additionally include comments targeted directly to the user's email via audience token,
        # and role-tagged comments matched via legacy role:<name> tokens resolved to IDs.
        if user_email or viewer_role_ids:
            try:
                already_visible_ids = {getattr(c, 'id', None) for c in visible_comments}
                for c in all_comments:
                    if getattr(c, 'id', None) in already_visible_ids:
                        continue
                    aud_raw = getattr(c, 'audience', None)
                    if not aud_raw:
                        continue
                    try:
                        aud_tokens: List[str] = json.loads(aud_raw)
                    except (json.JSONDecodeError, TypeError):
                        continue
                    matched = False

                    # Direct email targeting
                    if user_email and f"user:{user_email}" in aud_tokens:
                        matched = True

                    # Legacy role:<name> tokens — resolve name → UUID and compare
                    if not matched and viewer_role_ids:
                        for token in aud_tokens:
                            if token.startswith("role:"):
                                role_name = token[len("role:"):]
                                resolved_id = self._resolve_legacy_role_name_to_id(role_name)
                                if resolved_id and resolved_id in viewer_role_ids:
                                    matched = True
                                    break

                    if matched:
                        # Respect project_id scope
                        if project_id is None or c.project_id is None or c.project_id == project_id:
                            visible_comments.append(c)
            except Exception:
                logger.exception("list_comments: error during supplemental audience matching")

        visible_count = len(visible_comments)

        # Convert to API models
        api_comments = [self._db_to_api_model(comment) for comment in visible_comments]

        return CommentListResponse(
            comments=api_comments,
            total_count=total_count,
            visible_count=visible_count
        )

    def update_comment(
        self, 
        db: Session, 
        *, 
        comment_id: str, 
        data: CommentUpdate, 
        user_email: str,
        is_admin: bool = False
    ) -> Optional[Comment]:
        """Update a comment if user has permission."""
        logger.info(f"Updating comment {comment_id} by {user_email}")
        
        db_obj = self._comments_repo.get(db, comment_id)
        if not db_obj:
            logger.warning(f"Comment {comment_id} not found")
            return None
        
        # Check permissions
        if not self._comments_repo.can_user_modify(db_obj, user_email, is_admin):
            logger.warning(f"User {user_email} not authorized to modify comment {comment_id}")
            return None
        
        updated = self._comments_repo.update_with_audience(
            db, db_obj=db_obj, obj_in=data, updated_by=user_email
        )
        db.commit()
        db.refresh(updated)
        
        
        return self._db_to_api_model(updated)

    def delete_comment(
        self, 
        db: Session, 
        *, 
        comment_id: str, 
        user_email: str,
        is_admin: bool = False,
        hard_delete: bool = False
    ) -> bool:
        """Delete a comment if user has permission. Soft delete by default."""
        logger.info(f"Deleting comment {comment_id} by {user_email}, hard_delete={hard_delete}")
        
        db_obj = self._comments_repo.get(db, comment_id)
        if not db_obj:
            logger.warning(f"Comment {comment_id} not found")
            return False
        
        # Check permissions
        if not self._comments_repo.can_user_modify(db_obj, user_email, is_admin):
            logger.warning(f"User {user_email} not authorized to delete comment {comment_id}")
            return False
        
        entity_type, entity_id = db_obj.entity_type, db_obj.entity_id
        
        if hard_delete:
            # Permanently remove from database
            removed = self._comments_repo.remove(db, id=comment_id)
            if removed:
                db.commit()
                return True
        else:
            # Soft delete - mark as deleted
            soft_deleted = self._comments_repo.soft_delete(
                db, comment_id=comment_id, deleted_by=user_email
            )
            if soft_deleted:
                db.commit()
                return True
        
        return False

    def get_comment(self, db: Session, *, comment_id: str) -> Optional[Comment]:
        """Get a single comment by ID."""
        db_obj = self._comments_repo.get(db, comment_id)
        if not db_obj:
            return None
        return self._db_to_api_model(db_obj)

    def can_user_modify_comment(
        self, 
        db: Session, 
        *, 
        comment_id: str, 
        user_email: str, 
        is_admin: bool = False
    ) -> bool:
        """Check if user can modify a specific comment."""
        db_obj = self._comments_repo.get(db, comment_id)
        if not db_obj:
            return False
        return self._comments_repo.can_user_modify(db_obj, user_email, is_admin)

    # =========================================================================
    # Rating-specific methods
    # =========================================================================

    def create_rating(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        rating: int,
        comment: Optional[str] = None,
        project_id: Optional[str] = None,
        user_email: str
    ) -> Comment:
        """Create a new rating entry.
        
        Each user can rate an entity multiple times; the latest rating
        is considered their "current" rating for aggregation purposes.
        
        Args:
            db: Database session
            entity_type: Type of entity (data_product, dataset, etc.)
            entity_id: ID of the entity
            rating: Star rating 1-5
            comment: Optional review text
            project_id: Optional project scope
            user_email: Email of the rating user
            
        Returns:
            Created rating as Comment
        """
        logger.info(f"Creating rating for {entity_type}:{entity_id} by {user_email}, rating={rating}")
        
        # Create as CommentCreate with rating-specific fields
        data = CommentCreate(
            entity_type=entity_type,
            entity_id=entity_id,
            comment=comment or f"{rating} star rating",
            comment_type=CommentType.RATING,
            rating=rating,
            project_id=project_id
        )
        
        db_obj = self._comments_repo.create_with_audience(
            db, obj_in=data, created_by=user_email
        )
        db.commit()
        db.refresh(db_obj)
        
        return self._db_to_api_model(db_obj)

    def get_rating_aggregation(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        user_email: Optional[str] = None
    ) -> RatingAggregation:
        """Get aggregated rating statistics for an entity.
        
        Args:
            db: Database session
            entity_type: Type of entity
            entity_id: ID of the entity
            user_email: Optional user email to include their current rating
            
        Returns:
            RatingAggregation with average, total, distribution, and user's current rating
        """
        logger.debug(f"Getting rating aggregation for {entity_type}:{entity_id}")
        
        # Get all active ratings for this entity
        ratings = self._comments_repo.list_ratings_for_entity(
            db, entity_type=entity_type, entity_id=entity_id
        )
        
        # Calculate aggregations
        distribution = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
        user_ratings = []
        
        for r in ratings:
            if r.rating:
                distribution[r.rating] = distribution.get(r.rating, 0) + 1
                if user_email and r.created_by == user_email:
                    user_ratings.append(r)
        
        total = sum(distribution.values())
        avg = sum(k * v for k, v in distribution.items()) / total if total > 0 else 0.0
        
        # Get user's current (latest) rating
        user_current = None
        if user_ratings:
            # Already sorted by created_at desc from repository
            user_current = user_ratings[0].rating
        
        return RatingAggregation(
            entity_type=entity_type,
            entity_id=entity_id,
            average_rating=round(avg, 2),
            total_ratings=total,
            distribution=distribution,
            user_current_rating=user_current
        )

    def list_ratings(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        user_email: Optional[str] = None
    ) -> CommentListResponse:
        """List rating entries for an entity.
        
        Args:
            db: Database session
            entity_type: Type of entity
            entity_id: ID of the entity
            user_email: Optional filter to only show this user's ratings
            
        Returns:
            CommentListResponse containing rating entries
        """
        logger.debug(f"Listing ratings for {entity_type}:{entity_id}, user_filter={user_email}")
        
        ratings = self._comments_repo.list_ratings_for_entity(
            db, entity_type=entity_type, entity_id=entity_id, user_email=user_email
        )
        
        api_ratings = [self._db_to_api_model(r) for r in ratings]
        
        return CommentListResponse(
            comments=api_ratings,
            total_count=len(api_ratings),
            visible_count=len(api_ratings)
        )