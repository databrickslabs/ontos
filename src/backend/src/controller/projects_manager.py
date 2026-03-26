import json
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import func

from src.repositories.projects_repository import project_repo
from src.repositories.teams_repository import team_repo
from src.controller.tags_manager import TagsManager
from src.models.projects import (
    ProjectCreate,
    ProjectUpdate,
    ProjectRead,
    ProjectSummary,
    UserProjectAccess,
    ProjectTeamAssignment,
    ProjectAccessRequest,
    ProjectAccessRequestResponse
)
from src.models.tags import AssignedTag, AssignedTagCreate
from src.db_models.projects import ProjectDb
from src.common.errors import ConflictError, NotFoundError
from src.models.notifications import NotificationType
from src.common.authorization import is_user_admin
from src.common.config import Settings

from src.common.logging import get_logger
logger = get_logger(__name__)


class ProjectsManager:
    def __init__(self, tags_manager: Optional[TagsManager] = None):
        self.project_repo = project_repo
        self.team_repo = team_repo
        self.tags_manager = tags_manager or TagsManager()
        logger.debug("ProjectsManager initialized.")

    def _serialize_list_fields(self, data: dict) -> dict:
        """Helper to serialize list fields to JSON strings for database storage."""
        # Tags are now handled through TagsManager, remove from data
        if 'tags' in data:
            del data['tags']
        if 'metadata' in data and isinstance(data['metadata'], dict):
            data['extra_metadata'] = json.dumps(data.pop('metadata'))
        elif 'metadata' in data:
            data.pop('metadata')
        return data

    def _convert_db_to_read_model(self, db_project: ProjectDb, db: Optional[Session] = None) -> ProjectRead:
        """Helper to convert DB model to Read model."""
        project_read = ProjectRead.model_validate(db_project)

        # Set owner_team_name from the owner_team relationship
        if db_project.owner_team:
            project_read.owner_team_name = db_project.owner_team.name

        # Load tags from TagsManager
        if db:
            try:
                assigned_tags = self.tags_manager.list_assigned_tags(
                    db, entity_id=db_project.id, entity_type="project"
                )
                project_read.tags = assigned_tags
            except Exception as e:
                logger.warning(f"Failed to load tags for project {db_project.id}: {e}")
                project_read.tags = []

        return project_read

    def _convert_db_to_summary_model(self, db_project: ProjectDb) -> ProjectSummary:
        """Helper to convert DB model to Summary model."""
        return ProjectSummary(
            id=db_project.id,
            name=db_project.name,
            title=db_project.title,
            team_count=len(db_project.teams) if db_project.teams else 0
        )

    # Project CRUD operations
    def create_project(self, db: Session, project_in: ProjectCreate, current_user_id: str) -> ProjectRead:
        """Creates a new project."""
        logger.debug(f"Attempting to create project: {project_in.name}")

        # Check if project name already exists
        existing_project = self.project_repo.get_by_name(db, name=project_in.name)
        if existing_project:
            raise ConflictError(f"Project with name '{project_in.name}' already exists.")

        # Prepare data for database
        db_obj_data = project_in.model_dump(exclude_unset=True, exclude={'team_ids'})
        db_obj_data['created_by'] = current_user_id
        db_obj_data['updated_by'] = current_user_id

        # Extract tags before serialization
        tags_data = db_obj_data.get('tags', [])
        self._serialize_list_fields(db_obj_data)

        db_project = ProjectDb(**db_obj_data)

        try:
            db.add(db_project)
            db.flush()
            db.refresh(db_project)

            # Handle tags if provided
            if tags_data:
                # Convert string tags to AssignedTagCreate objects
                tag_creates = []
                for tag in tags_data:
                    if isinstance(tag, str):
                        tag_creates.append(AssignedTagCreate(tag_fqn=tag))
                    elif isinstance(tag, dict):
                        tag_creates.append(AssignedTagCreate(**tag))

                if tag_creates:
                    self.tags_manager.set_tags_for_entity(
                        db, entity_id=db_project.id, entity_type="project",
                        tags=tag_creates, user_email=current_user_id
                    )

            # Assign initial teams if provided
            if project_in.team_ids:
                for team_id in project_in.team_ids:
                    self.assign_team_to_project(db, project_id=db_project.id, team_id=team_id, assigned_by=current_user_id)

            logger.info(f"Successfully created project '{db_project.name}' with id: {db_project.id}")

            # Reload with teams
            db_project = self.project_repo.get_with_teams(db, db_project.id)
            return self._convert_db_to_read_model(db_project, db)
        except IntegrityError as e:
            db.rollback()
            logger.warning(f"Integrity error creating project '{project_in.name}': {e}")
            if "unique constraint" in str(e).lower():
                raise ConflictError(f"Project with name '{project_in.name}' already exists.")
            raise
        except Exception as e:
            db.rollback()
            logger.exception(f"Error creating project '{project_in.name}': {e}")
            raise

    def get_project_by_id(self, db: Session, project_id: str) -> Optional[ProjectRead]:
        """Gets a project by its ID, including teams."""
        logger.debug(f"Fetching project with id: {project_id}")
        db_project = self.project_repo.get_with_teams(db, project_id)
        if not db_project:
            return None
        return self._convert_db_to_read_model(db_project)

    def get_all_projects(
        self, 
        db: Session, 
        skip: int = 0, 
        limit: int = 100,
        user_identifier: Optional[str] = None,
        user_groups: Optional[List[str]] = None,
        is_admin: bool = False
    ) -> List[ProjectRead]:
        """Gets a list of projects visible to the user.
        
        - Admins see all projects
        - Non-admins see projects based on domain relationships
        """
        logger.debug(f"Fetching projects with skip={skip}, limit={limit}, is_admin={is_admin}")
        
        if is_admin:
            # Admins see all projects
            db_projects = self.project_repo.get_multi_with_teams(db, skip=skip, limit=limit)
        elif user_identifier and user_groups is not None:
            # Non-admins see domain-related projects
            db_projects = self.project_repo.get_projects_by_domain_relationship(
                db, user_identifier, user_groups
            )
            # Apply pagination to domain-filtered results
            db_projects = db_projects[skip:skip+limit] if limit > 0 else db_projects[skip:]
        else:
            # No user context, return empty list
            db_projects = []
        
        return [self._convert_db_to_read_model(project) for project in db_projects]

    def get_projects_summary(self, db: Session) -> List[ProjectSummary]:
        """Gets a summary list of projects for dropdowns/selection."""
        logger.debug("Fetching projects summary")
        db_projects = self.project_repo.get_multi_with_teams(db, limit=1000)
        return [self._convert_db_to_summary_model(project) for project in db_projects]

    def get_user_projects(self, db: Session, user_identifier: str, user_groups: List[str]) -> UserProjectAccess:
        """Gets all projects that a user has access to through team membership."""
        logger.debug(f"Fetching accessible projects for user: {user_identifier}")

        try:
            # Check if user is admin
            is_admin = any("admin" in group.lower() for group in user_groups) if user_groups else False
            logger.debug(f"User {user_identifier} admin status: {is_admin}")

            if is_admin:
                # Admins see all projects
                logger.debug(f"User {user_identifier} is admin, showing all projects")
                db_projects = self.project_repo.get_multi(db)
            else:
                # Non-admins only see projects they have team access to
                db_projects = self.project_repo.get_projects_for_user(db, user_identifier, user_groups)

            project_summaries = [self._convert_db_to_summary_model(project) for project in db_projects]

            return UserProjectAccess(
                projects=project_summaries,
                current_project_id=None  # This would be set by session/context management
            )
        except Exception as e:
            logger.exception(f"Error fetching user projects: {e}")
            return UserProjectAccess(projects=[], current_project_id=None)

    def is_user_project_member(
        self, 
        db: Session, 
        user_identifier: str, 
        user_groups: List[str], 
        project_id: str,
        settings: Settings
    ) -> bool:
        """Check if user is a member of any team assigned to the project.
        
        Args:
            db: Database session
            user_identifier: User email/identifier
            user_groups: List of user's groups
            project_id: Project ID to check membership for
            settings: Application settings for admin group check
            
        Returns:
            True if user is a member or is admin, False otherwise
        """
        logger.debug(f"Checking if user {user_identifier} is member of project {project_id}")
        
        try:
            # Check if user is admin using configured admin groups
            if is_user_admin(user_groups, settings):
                logger.debug(f"User {user_identifier} is admin, granting access")
                return True
            
            # Get project
            project = self.project_repo.get_with_teams(db, project_id)
            if not project:
                logger.warning(f"Project {project_id} not found")
                return False
            
            # Check if user is member of any team in the project
            from src.db_models.teams import TeamMemberDb
            
            # Get project team IDs
            project_team_ids = [team.id for team in project.teams] if project.teams else []
            
            if not project_team_ids:
                logger.debug(f"Project {project_id} has no teams assigned")
                return False
            
            # Build member filters (case-insensitive)
            member_filters = [func.lower(TeamMemberDb.member_identifier) == user_identifier.lower()]
            for group in user_groups:
                member_filters.append(func.lower(TeamMemberDb.member_identifier) == group.lower())
            
            # Check if user is member of any project team
            from sqlalchemy import and_, or_
            membership_exists = db.query(TeamMemberDb).filter(
                and_(
                    TeamMemberDb.team_id.in_(project_team_ids),
                    or_(*member_filters)
                )
            ).first()
            
            is_member = membership_exists is not None
            logger.debug(f"User {user_identifier} project membership: {is_member}")
            return is_member
            
        except Exception as e:
            logger.exception(f"Error checking project membership: {e}")
            return False

    def update_project(self, db: Session, project_id: str, project_in: ProjectUpdate, current_user_id: str) -> Optional[ProjectRead]:
        """Updates an existing project."""
        logger.debug(f"Attempting to update project with id: {project_id}")

        db_project = self.project_repo.get(db, project_id)
        if not db_project:
            raise NotFoundError(f"Project with id '{project_id}' not found.")

        # Check for name conflicts if name is being updated
        if project_in.name and project_in.name != db_project.name:
            existing_project = self.project_repo.get_by_name(db, name=project_in.name)
            if existing_project:
                raise ConflictError(f"Project with name '{project_in.name}' already exists.")

        update_data = project_in.model_dump(exclude_unset=True)
        update_data['updated_by'] = current_user_id

        # Extract tags before serialization
        tags_data = update_data.get('tags')
        self._serialize_list_fields(update_data)

        try:
            updated_db_project = self.project_repo.update(db=db, db_obj=db_project, obj_in=update_data)
            db.flush()
            db.refresh(updated_db_project)

            # Handle tags if provided
            if tags_data is not None:  # Allow empty list to clear tags
                # Convert string tags to AssignedTagCreate objects
                tag_creates = []
                for tag in tags_data:
                    if isinstance(tag, str):
                        tag_creates.append(AssignedTagCreate(tag_fqn=tag))
                    elif isinstance(tag, dict):
                        tag_creates.append(AssignedTagCreate(**tag))

                self.tags_manager.set_tags_for_entity(
                    db, entity_id=updated_db_project.id, entity_type="project",
                    tags=tag_creates, user_email=current_user_id
                )

            logger.info(f"Successfully updated project '{updated_db_project.name}' (id: {project_id})")

            # Reload with teams
            updated_db_project = self.project_repo.get_with_teams(db, project_id)
            return self._convert_db_to_read_model(updated_db_project, db)
        except IntegrityError as e:
            db.rollback()
            logger.warning(f"Integrity error updating project {project_id}: {e}")
            if "unique constraint" in str(e).lower():
                raise ConflictError(f"Project name '{project_in.name}' is already in use.")
            raise
        except Exception as e:
            db.rollback()
            logger.exception(f"Error updating project {project_id}: {e}")
            raise

    def delete_project(self, db: Session, project_id: str) -> Optional[ProjectRead]:
        """Deletes a project by its ID."""
        logger.debug(f"Attempting to delete project with id: {project_id}")

        db_project = self.project_repo.get_with_teams(db, project_id)
        if not db_project:
            raise NotFoundError(f"Project with id '{project_id}' not found.")

        read_model = self._convert_db_to_read_model(db_project)

        try:
            self.project_repo.remove(db=db, id=project_id)
            logger.info(f"Successfully deleted project '{read_model.name}' (id: {project_id})")
            return read_model
        except Exception as e:
            db.rollback()
            logger.exception(f"Error deleting project {project_id}: {e}")
            raise

    # Team assignment operations
    def assign_team_to_project(self, db: Session, project_id: str, team_id: str, assigned_by: str) -> bool:
        """Assigns a team to a project."""
        logger.debug(f"Assigning team {team_id} to project {project_id}")

        # Verify project exists
        db_project = self.project_repo.get(db, project_id)
        if not db_project:
            raise NotFoundError(f"Project with id '{project_id}' not found.")

        # Verify team exists
        db_team = self.team_repo.get(db, team_id)
        if not db_team:
            raise NotFoundError(f"Team with id '{team_id}' not found.")

        try:
            success = self.project_repo.assign_team(db, project_id=project_id, team_id=team_id, assigned_by=assigned_by)
            if not success:
                raise ConflictError(f"Team '{db_team.name}' is already assigned to project '{db_project.name}'.")

            logger.info(f"Successfully assigned team '{db_team.name}' to project '{db_project.name}'")
            return True
        except ConflictError:
            raise
        except Exception as e:
            db.rollback()
            logger.exception(f"Error assigning team to project: {e}")
            raise

    def remove_team_from_project(self, db: Session, project_id: str, team_id: str) -> bool:
        """Removes a team from a project."""
        logger.debug(f"Removing team {team_id} from project {project_id}")

        try:
            success = self.project_repo.remove_team(db, project_id=project_id, team_id=team_id)
            if success:
                logger.info(f"Successfully removed team from project")
            else:
                logger.warning(f"Team {team_id} was not assigned to project {project_id}")
            return success
        except Exception as e:
            db.rollback()
            logger.exception(f"Error removing team from project: {e}")
            raise

    def get_project_teams(self, db: Session, project_id: str) -> List[dict]:
        """Gets all teams assigned to a project."""
        logger.debug(f"Fetching teams for project: {project_id}")

        # Verify project exists
        db_project = self.project_repo.get(db, project_id)
        if not db_project:
            raise NotFoundError(f"Project with id '{project_id}' not found.")

        db_teams = self.project_repo.get_team_assignments(db, project_id)
        return [{"id": team.id, "name": team.name, "title": team.title} for team in db_teams]

    def check_user_project_access(self, db: Session, user_identifier: str, user_groups: List[str], project_id: str) -> bool:
        """Checks if a user has access to a specific project."""
        logger.debug(f"Checking project access for user {user_identifier} to project {project_id}")

        user_projects = self.project_repo.get_projects_for_user(db, user_identifier, user_groups)
        return any(project.id == project_id for project in user_projects)

    async def request_project_access(self, db: Session, user_identifier: str, user_groups: List[str], request: ProjectAccessRequest, notifications_manager) -> ProjectAccessRequestResponse:
        """Request access to a project using workflow triggers."""
        logger.debug(f"Processing project access request from user {user_identifier} for project {request.project_id}")

        # Verify project exists
        db_project = self.project_repo.get(db, request.project_id)
        if not db_project:
            raise NotFoundError(f"Project with id '{request.project_id}' not found.")

        # Check if user already has access
        if self.check_user_project_access(db, user_identifier, user_groups, request.project_id):
            raise ConflictError(f"User already has access to project '{db_project.name}'.")

        # Get all teams assigned to the project
        project_teams = self.project_repo.get_team_assignments(db, request.project_id)

        if not project_teams:
            raise ConflictError(f"Project '{db_project.name}' has no assigned teams. Cannot request access.")

        # Collect team member emails for workflow notification
        team_members = []
        for team in project_teams:
            team_with_members = self.team_repo.get_with_members(db, team.id)
            if team_with_members and team_with_members.members:
                for member in team_with_members.members:
                    team_members.append(member.member_identifier)

        # --- Trigger workflow for project access request --- #
        try:
            from src.common.workflow_triggers import get_trigger_registry
            from src.models.process_workflows import EntityType
            
            trigger_registry = get_trigger_registry(db)
            entity_data = {
                "project_id": request.project_id,
                "project_name": db_project.name,
                "requester": user_identifier,
                "message": request.message,
                "team_ids": [team.id for team in project_teams],
                "team_members": team_members,
            }
            
            executions = trigger_registry.on_request_access(
                entity_type=EntityType.PROJECT,
                entity_id=request.project_id,
                entity_name=db_project.name,
                entity_data=entity_data,
                user_email=user_identifier,
                blocking=True,  # Wait for workflow to complete/pause
            )
            
            if executions:
                logger.info(f"Triggered {len(executions)} workflow(s) for project access request")
                return ProjectAccessRequestResponse(
                    message=f"Access request submitted. Workflow triggered for approval.",
                    project_name=db_project.name
                )
        except Exception as workflow_err:
            logger.error(f"Failed to trigger workflow for project access request: {workflow_err}", exc_info=True)

        # Fallback to direct notification if no workflow configured
        notifications_sent = 0
        logger.debug(f"No workflow configured; sending direct notifications to {len(team_members)} team members")
        
        for member_email in team_members:
            try:
                notification_title = "Project Access Request"
                notification_description = (
                    f"User {user_identifier} is requesting access to project '{db_project.name}'"
                    f"{' - ' + request.message if request.message else ''}. "
                    f"Please contact an administrator to grant access if appropriate."
                )

                notification = await notifications_manager.create_notification(
                    db=db,
                    user_id=member_email,
                    title=notification_title,
                    subtitle=f"From: {user_identifier}",
                    description=notification_description,
                    link=f"/projects/{request.project_id}",
                    type=NotificationType.INFO,
                    action_type="project_access_request",
                    action_payload={
                        "project_id": request.project_id,
                        "requester": user_identifier,
                    }
                )
                notifications_sent += 1
            except Exception as e:
                logger.error(f"Failed to send notification to {member_email}: {e}", exc_info=True)
                continue

        if notifications_sent == 0:
            raise ConflictError(f"Could not send notifications to any team members for project '{db_project.name}'.")

        logger.info(f"Sent {notifications_sent} project access request notifications for project '{db_project.name}'")

        return ProjectAccessRequestResponse(
            message=f"Access request sent successfully. {notifications_sent} team members have been notified.",
            project_name=db_project.name
        )



# Singleton instance
projects_manager = ProjectsManager()