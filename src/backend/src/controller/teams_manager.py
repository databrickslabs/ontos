import json
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from src.repositories.teams_repository import team_repo, team_member_repo
from src.repositories.data_domain_repository import data_domain_repo
from src.repositories.entity_domain_association_repository import entity_domain_repo
from src.controller.tags_manager import TagsManager
from src.models.teams import (
    TeamCreate,
    TeamUpdate,
    TeamRead,
    TeamSummary,
    TeamMemberCreate,
    TeamMemberUpdate,
    TeamMemberRead
)
from src.models.tags import AssignedTag, AssignedTagCreate
from src.db_models.teams import TeamDb, TeamMemberDb
from src.common.errors import ConflictError, NotFoundError

from src.common.logging import get_logger
logger = get_logger(__name__)


class TeamsManager:
    def __init__(self, tags_manager: Optional[TagsManager] = None):
        self.team_repo = team_repo
        self.team_member_repo = team_member_repo
        self.domain_repo = data_domain_repo
        self.tags_manager = tags_manager or TagsManager()
        logger.debug("TeamsManager initialized.")

    def _serialize_list_fields(self, data: dict) -> dict:
        """Helper to serialize list fields to JSON strings for database storage."""
        # Tags are now handled through TagsManager, remove from data
        if 'tags' in data:
            del data['tags']
        # Domain assignment is handled through the junction table, not a column.
        data.pop('domain_ids', None)
        data.pop('primary_domain_id', None)
        if 'metadata' in data and isinstance(data['metadata'], dict):
            data['extra_metadata'] = json.dumps(data.pop('metadata'))
        elif 'metadata' in data:
            data.pop('metadata')
        return data

    def _apply_domains(self, team_read: TeamRead, assigned_domains) -> TeamRead:
        """Populate the read model's domain fields from a list of AssignedDomain."""
        team_read.domains = assigned_domains or []
        team_read.domain_ids = [d.domain_id for d in team_read.domains]
        primary = next((d.domain_id for d in team_read.domains if d.is_primary), None)
        team_read.primary_domain_id = primary
        return team_read

    def _convert_db_to_read_model(
        self, db_team: TeamDb, db: Optional[Session] = None, assigned_domains=None
    ) -> TeamRead:
        """Helper to convert DB model to Read model."""
        team_read = TeamRead.model_validate(db_team)

        # Populate domain assignments (from batch map if provided, else fetch).
        if assigned_domains is None and db:
            try:
                assigned_domains = entity_domain_repo.get_domains_for_entity(
                    db, entity_type="team", entity_id=db_team.id
                )
            except Exception as e:
                logger.warning(f"Failed to load domains for team {db_team.id}: {e}")
                assigned_domains = []
        self._apply_domains(team_read, assigned_domains or [])

        # Load tags from TagsManager
        if db:
            try:
                assigned_tags = self.tags_manager.list_assigned_tags(
                    db, entity_id=db_team.id, entity_type="team"
                )
                team_read.tags = assigned_tags
            except Exception as e:
                logger.warning(f"Failed to load tags for team {db_team.id}: {e}")
                team_read.tags = []

        return team_read

    def _convert_many_to_read_models(self, db: Session, db_teams: List[TeamDb]) -> List[TeamRead]:
        """Convert many teams to read models, batch-loading domain assignments (no N+1)."""
        if not db_teams:
            return []
        domains_map = entity_domain_repo.get_domains_for_entities(
            db, entity_type="team", entity_ids=[t.id for t in db_teams]
        )
        return [
            self._convert_db_to_read_model(t, db, assigned_domains=domains_map.get(t.id, []))
            for t in db_teams
        ]

    def _convert_db_to_summary_model(self, db_team: TeamDb, assigned_domains=None) -> TeamSummary:
        """Helper to convert DB model to Summary model."""
        assigned_domains = assigned_domains or []
        return TeamSummary(
            id=db_team.id,
            name=db_team.name,
            title=db_team.title,
            domain_ids=[d.domain_id for d in assigned_domains],
            primary_domain_id=next((d.domain_id for d in assigned_domains if d.is_primary), None),
            member_count=len(db_team.members) if db_team.members else 0
        )

    def _resolve_domain_name_to_id(self, db: Session, domain_name: str) -> Optional[str]:
        """Helper to resolve domain name to domain ID."""
        if not domain_name:
            return None
        try:
            # Get all domains and find by name
            domains = self.domain_repo.get_multi(db, limit=1000)
            for domain in domains:
                if domain.name == domain_name:
                    return domain.id
            logger.warning(f"Domain '{domain_name}' not found")
            return None
        except Exception as e:
            logger.error(f"Error resolving domain name '{domain_name}': {e}")
            return None

    @staticmethod
    def _normalize_primary_domain(domain_ids: List[str], primary_domain_id: Optional[str]) -> Optional[str]:
        """Clamp the primary to the assigned set: keep it when present, else fall back to
        the first id (or None when unassigned). Mirrors the contract/product resolvers so a
        primary_domain_id outside domain_ids can't reach set_domains_for_entity and turn its
        ValueError into an HTTP 500."""
        if not domain_ids:
            return None
        if primary_domain_id and primary_domain_id in domain_ids:
            return primary_domain_id
        return domain_ids[0]

    # Team CRUD operations
    def create_team(self, db: Session, team_in: TeamCreate, current_user_id: str) -> TeamRead:
        """Creates a new team."""
        logger.debug(f"Attempting to create team: {team_in.name}")

        # Check if team name already exists
        existing_team = self.team_repo.get_by_name(db, name=team_in.name)
        if existing_team:
            raise ConflictError(f"Team with name '{team_in.name}' already exists.")

        # Prepare data for database
        db_obj_data = team_in.model_dump(exclude_unset=True)
        db_obj_data['created_by'] = current_user_id
        db_obj_data['updated_by'] = current_user_id

        # Extract tags + domains before serialization
        tags_data = db_obj_data.get('tags', [])
        domain_ids = team_in.domain_ids or []
        primary_domain_id = self._normalize_primary_domain(domain_ids, team_in.primary_domain_id)
        self._serialize_list_fields(db_obj_data)

        db_team = TeamDb(**db_obj_data)

        try:
            db.add(db_team)
            db.flush()
            db.refresh(db_team)

            # Assign domains via the junction table
            if domain_ids:
                entity_domain_repo.set_domains_for_entity(
                    db, entity_type="team", entity_id=db_team.id,
                    domain_ids=domain_ids, primary_domain_id=primary_domain_id,
                    assigned_by=current_user_id,
                )

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
                        db, entity_id=db_team.id, entity_type="team",
                        tags=tag_creates, user_email=current_user_id
                    )

            logger.info(f"Successfully created team '{db_team.name}' with id: {db_team.id}")
            return self._convert_db_to_read_model(db_team, db)
        except IntegrityError as e:
            db.rollback()
            logger.warning(f"Integrity error creating team '{team_in.name}': {e}")
            if "unique constraint" in str(e).lower():
                raise ConflictError(f"Team with name '{team_in.name}' already exists.")
            raise
        except Exception as e:
            db.rollback()
            logger.exception(f"Error creating team '{team_in.name}': {e}")
            raise

    def get_team_by_id(self, db: Session, team_id: str) -> Optional[TeamRead]:
        """Gets a team by its ID, including members."""
        logger.debug(f"Fetching team with id: {team_id}")
        db_team = self.team_repo.get_with_members(db, team_id)
        if not db_team:
            return None
        return self._convert_db_to_read_model(db_team, db)

    def get_all_teams(
        self,
        db: Session,
        skip: int = 0,
        limit: int = 100,
        domain_id: Optional[str] = None,
        domain_ids: Optional[List[str]] = None,
    ) -> List[TeamRead]:
        """Gets a list of all teams, optionally filtered by domain(s) (any-of)."""
        logger.debug(f"Fetching teams with skip={skip}, limit={limit}, domain_id={domain_id}, domain_ids={domain_ids}")
        db_teams = self.team_repo.get_multi_with_members(
            db, skip=skip, limit=limit, domain_id=domain_id, domain_ids=domain_ids
        )
        return self._convert_many_to_read_models(db, db_teams)

    def get_teams_summary(
        self, db: Session, domain_id: Optional[str] = None, domain_ids: Optional[List[str]] = None
    ) -> List[TeamSummary]:
        """Gets a summary list of teams for dropdowns/selection."""
        logger.debug(f"Fetching teams summary for domain_id={domain_id}, domain_ids={domain_ids}")
        db_teams = self.team_repo.get_multi_with_members(
            db, limit=1000, domain_id=domain_id, domain_ids=domain_ids
        )
        domains_map = entity_domain_repo.get_domains_for_entities(
            db, entity_type="team", entity_ids=[t.id for t in db_teams]
        )
        return [self._convert_db_to_summary_model(t, domains_map.get(t.id, [])) for t in db_teams]

    def get_teams_by_domain(self, db: Session, domain_id: str) -> List[TeamRead]:
        """Gets all teams that include this domain (primary or additional)."""
        db_teams = self.team_repo.get_teams_by_domain(db, domain_id)
        return self._convert_many_to_read_models(db, db_teams)

    def get_standalone_teams(self, db: Session) -> List[TeamRead]:
        """Gets all standalone teams (zero domain assignments)."""
        db_teams = self.team_repo.get_standalone_teams(db)
        return self._convert_many_to_read_models(db, db_teams)

    def get_teams_for_user(
        self, db: Session, user_identifier: str, user_groups: Optional[List[str]] = None
    ) -> List[TeamRead]:
        """Gets all teams where a user is a member (either directly or via group)."""
        db_teams = self.team_repo.get_teams_for_user(db, user_identifier, user_groups)
        return self._convert_many_to_read_models(db, db_teams)

    def update_team(self, db: Session, team_id: str, team_in: TeamUpdate, current_user_id: str) -> Optional[TeamRead]:
        """Updates an existing team."""
        logger.debug(f"Attempting to update team with id: {team_id}")

        db_team = self.team_repo.get(db, team_id)
        if not db_team:
            raise NotFoundError(f"Team with id '{team_id}' not found.")

        # Check for name conflicts if name is being updated
        if team_in.name and team_in.name != db_team.name:
            existing_team = self.team_repo.get_by_name(db, name=team_in.name)
            if existing_team:
                raise ConflictError(f"Team with name '{team_in.name}' already exists.")

        update_data = team_in.model_dump(exclude_unset=True)
        update_data['updated_by'] = current_user_id

        # Extract tags + domains before serialization
        tags_data = update_data.get('tags')
        domains_provided = 'domain_ids' in update_data
        domain_ids = update_data.get('domain_ids') or []
        primary_domain_id = self._normalize_primary_domain(domain_ids, update_data.get('primary_domain_id'))
        self._serialize_list_fields(update_data)

        try:
            updated_db_team = self.team_repo.update(db=db, db_obj=db_team, obj_in=update_data)
            db.flush()
            db.refresh(updated_db_team)

            # Replace domain assignments if the caller supplied domain_ids (empty clears them)
            if domains_provided:
                entity_domain_repo.set_domains_for_entity(
                    db, entity_type="team", entity_id=updated_db_team.id,
                    domain_ids=domain_ids, primary_domain_id=primary_domain_id,
                    assigned_by=current_user_id,
                )

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
                    db, entity_id=updated_db_team.id, entity_type="team",
                    tags=tag_creates, user_email=current_user_id
                )

            logger.info(f"Successfully updated team '{updated_db_team.name}' (id: {team_id})")
            return self._convert_db_to_read_model(updated_db_team, db)
        except IntegrityError as e:
            db.rollback()
            logger.warning(f"Integrity error updating team {team_id}: {e}")
            if "unique constraint" in str(e).lower():
                raise ConflictError(f"Team name '{team_in.name}' is already in use.")
            raise
        except Exception as e:
            db.rollback()
            logger.exception(f"Error updating team {team_id}: {e}")
            raise

    def delete_team(self, db: Session, team_id: str) -> Optional[TeamRead]:
        """Deletes a team by its ID."""
        logger.debug(f"Attempting to delete team with id: {team_id}")

        db_team = self.team_repo.get_with_members(db, team_id)
        if not db_team:
            raise NotFoundError(f"Team with id '{team_id}' not found.")

        read_model = self._convert_db_to_read_model(db_team, db)

        try:
            entity_domain_repo.remove_all_for_entity(db, entity_type="team", entity_id=team_id)
            self.team_repo.remove(db=db, id=team_id)
            logger.info(f"Successfully deleted team '{read_model.name}' (id: {team_id})")
            return read_model
        except Exception as e:
            db.rollback()
            logger.exception(f"Error deleting team {team_id}: {e}")
            raise

    # Team Member operations
    def add_team_member(self, db: Session, team_id: str, member_in: TeamMemberCreate, current_user_id: str) -> TeamMemberRead:
        """Adds a member to a team."""
        logger.debug(f"Adding member {member_in.member_identifier} to team {team_id}")

        # Check if team exists
        db_team = self.team_repo.get(db, team_id)
        if not db_team:
            raise NotFoundError(f"Team with id '{team_id}' not found.")

        # Check if member already exists
        existing_member = self.team_member_repo.get_by_team_and_member(
            db, team_id=team_id, member_identifier=member_in.member_identifier
        )
        if existing_member:
            raise ConflictError(f"Member '{member_in.member_identifier}' is already in team '{db_team.name}'.")

        db_obj_data = member_in.model_dump()
        db_obj_data['team_id'] = team_id
        db_obj_data['added_by'] = current_user_id

        db_member = TeamMemberDb(**db_obj_data)

        try:
            db.add(db_member)
            db.flush()
            db.refresh(db_member)
            logger.info(f"Successfully added member '{member_in.member_identifier}' to team '{db_team.name}'")
            return TeamMemberRead.model_validate(db_member)
        except Exception as e:
            db.rollback()
            logger.exception(f"Error adding member to team: {e}")
            raise

    def update_team_member(self, db: Session, team_id: str, member_id: str, member_in: TeamMemberUpdate, current_user_id: str) -> Optional[TeamMemberRead]:
        """Updates a team member."""
        logger.debug(f"Updating team member {member_id} in team {team_id}")

        db_member = self.team_member_repo.get(db, member_id)
        if not db_member or db_member.team_id != team_id:
            raise NotFoundError(f"Team member with id '{member_id}' not found in team '{team_id}'.")

        update_data = member_in.model_dump(exclude_unset=True)

        try:
            updated_db_member = self.team_member_repo.update(db=db, db_obj=db_member, obj_in=update_data)
            db.flush()
            db.refresh(updated_db_member)
            logger.info(f"Successfully updated team member '{updated_db_member.member_identifier}'")
            return TeamMemberRead.model_validate(updated_db_member)
        except Exception as e:
            db.rollback()
            logger.exception(f"Error updating team member: {e}")
            raise

    def remove_team_member(self, db: Session, team_id: str, member_identifier: str) -> bool:
        """Removes a member from a team."""
        logger.debug(f"Removing member {member_identifier} from team {team_id}")

        try:
            removed_member = self.team_member_repo.remove_by_team_and_member(
                db, team_id=team_id, member_identifier=member_identifier
            )
            if removed_member:
                logger.info(f"Successfully removed member '{member_identifier}' from team")
                return True
            else:
                logger.warning(f"Member '{member_identifier}' not found in team '{team_id}'")
                return False
        except Exception as e:
            db.rollback()
            logger.exception(f"Error removing team member: {e}")
            raise

    def get_team_members(self, db: Session, team_id: str) -> List[TeamMemberRead]:
        """Gets all members of a team."""
        db_members = self.team_member_repo.get_members_by_team(db, team_id)
        return [TeamMemberRead.model_validate(member) for member in db_members]



# Singleton instance
teams_manager = TeamsManager()