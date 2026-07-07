from src.common.repository import CRUDBase
from src.db_models.teams import TeamDb, TeamMemberDb
from src.models.teams import TeamCreate, TeamUpdate, TeamMemberCreate, TeamMemberUpdate
from src.common.logging import get_logger
from src.repositories.entity_domain_association_repository import entity_domain_repo
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import func
from typing import List, Optional

logger = get_logger(__name__)

TEAM_ENTITY_TYPE = "team"


class TeamRepository(CRUDBase[TeamDb, TeamCreate, TeamUpdate]):
    def __init__(self):
        super().__init__(TeamDb)
        logger.info("TeamRepository initialized.")

    def _resolve_domain_filter(
        self, db: Session, domain_id: Optional[str], domain_ids: Optional[List[str]]
    ) -> Optional[List[str]]:
        """Resolve a domain filter to the set of team IDs (any-of via the junction table).

        Returns None when no domain filter is supplied (caller should not filter), or a
        (possibly empty) list of team IDs when a filter is present.
        """
        ids: List[str] = []
        if domain_ids:
            ids.extend(domain_ids)
        if domain_id:
            ids.append(domain_id)
        if not ids:
            return None
        return entity_domain_repo.find_entity_ids_by_domains(
            db, domain_ids=ids, entity_type=TEAM_ENTITY_TYPE
        )

    def get_with_members(self, db: Session, id: str) -> Optional[TeamDb]:
        """Gets a single team by ID, eager loading members."""
        logger.debug(f"Fetching {self.model.__name__} with members for id: {id}")
        try:
            return (
                db.query(self.model)
                .options(selectinload(self.model.members))
                .filter(self.model.id == id)
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching {self.model.__name__} with members by id {id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_multi_with_members(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        domain_id: Optional[str] = None,
        domain_ids: Optional[List[str]] = None,
    ) -> List[TeamDb]:
        """Gets multiple teams, eager loading members. Optionally filter by domain(s) (any-of)."""
        logger.debug(f"Fetching multiple {self.model.__name__} with members, skip={skip}, limit={limit}, domain_id={domain_id}, domain_ids={domain_ids}")
        try:
            query = (
                db.query(self.model)
                .options(selectinload(self.model.members))
                .order_by(self.model.name)
            )

            filter_ids = self._resolve_domain_filter(db, domain_id, domain_ids)
            if filter_ids is not None:
                query = query.filter(self.model.id.in_(filter_ids))

            return query.offset(skip).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching multiple {self.model.__name__} with members: {e}", exc_info=True)
            db.rollback()
            raise

    def get_by_name(self, db: Session, *, name: str) -> Optional[TeamDb]:
        """Gets a team by name."""
        logger.debug(f"Fetching {self.model.__name__} with name: {name}")
        try:
            return db.query(self.model).filter(self.model.name == name).first()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching {self.model.__name__} by name {name}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_teams_by_domain(self, db: Session, domain_id: str) -> List[TeamDb]:
        """Gets all teams that include this domain (primary OR additional; any-of)."""
        logger.debug(f"Fetching teams for domain: {domain_id}")
        try:
            team_ids = entity_domain_repo.find_entity_ids_by_domain(
                db, domain_id=domain_id, entity_type=TEAM_ENTITY_TYPE
            )
            if not team_ids:
                return []
            return (
                db.query(self.model)
                .options(selectinload(self.model.members))
                .filter(self.model.id.in_(team_ids))
                .order_by(self.model.name)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching teams by domain {domain_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_standalone_teams(self, db: Session) -> List[TeamDb]:
        """Gets all standalone teams (zero domain assignments)."""
        logger.debug("Fetching standalone teams")
        try:
            assigned_ids = entity_domain_repo.find_entity_ids_with_any_domain(
                db, entity_type=TEAM_ENTITY_TYPE
            )
            query = (
                db.query(self.model)
                .options(selectinload(self.model.members))
                .order_by(self.model.name)
            )
            if assigned_ids:
                query = query.filter(self.model.id.notin_(assigned_ids))
            return query.all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching standalone teams: {e}", exc_info=True)
            db.rollback()
            raise

    def get_teams_for_user(
        self, db: Session, user_identifier: str, user_groups: Optional[List[str]] = None
    ) -> List[TeamDb]:
        """Gets all teams where a user is a member (either directly or via group)."""
        logger.debug(f"Fetching teams for user: {user_identifier}, groups: {user_groups}")
        try:
            from sqlalchemy import or_
            
            # Build filters for user identifier and groups (case-insensitive)
            member_filters = [func.lower(TeamMemberDb.member_identifier) == user_identifier.lower()]
            if user_groups:
                for group in user_groups:
                    member_filters.append(func.lower(TeamMemberDb.member_identifier) == group.lower())
            
            return (
                db.query(self.model)
                .options(selectinload(self.model.members))
                .join(TeamMemberDb)
                .filter(or_(*member_filters))
                .distinct()
                .order_by(self.model.name)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching teams for user {user_identifier}: {e}", exc_info=True)
            db.rollback()
            raise


class TeamMemberRepository(CRUDBase[TeamMemberDb, TeamMemberCreate, TeamMemberUpdate]):
    def __init__(self):
        super().__init__(TeamMemberDb)
        logger.info("TeamMemberRepository initialized.")

    def get_by_team_and_member(
        self, db: Session, *, team_id: str, member_identifier: str
    ) -> Optional[TeamMemberDb]:
        """Gets a team member by team ID and member identifier."""
        logger.debug(f"Fetching team member for team {team_id} and member {member_identifier}")
        try:
            return (
                db.query(self.model)
                .filter(
                    self.model.team_id == team_id,
                    self.model.member_identifier == member_identifier
                )
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching team member: {e}", exc_info=True)
            db.rollback()
            raise

    def get_members_by_team(self, db: Session, team_id: str) -> List[TeamMemberDb]:
        """Gets all members for a specific team."""
        logger.debug(f"Fetching members for team: {team_id}")
        try:
            return (
                db.query(self.model)
                .filter(self.model.team_id == team_id)
                .order_by(self.model.member_identifier)
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching members for team {team_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def remove_by_team_and_member(
        self, db: Session, *, team_id: str, member_identifier: str
    ) -> Optional[TeamMemberDb]:
        """Removes a team member by team ID and member identifier."""
        logger.debug(f"Removing team member for team {team_id} and member {member_identifier}")
        try:
            member = self.get_by_team_and_member(db, team_id=team_id, member_identifier=member_identifier)
            if member:
                db.delete(member)
                db.flush()
                logger.info(f"Successfully removed team member {member_identifier} from team {team_id}")
                return member
            else:
                logger.warning(f"Attempted to remove non-existent team member {member_identifier} from team {team_id}")
                return None
        except SQLAlchemyError as e:
            logger.error(f"Database error removing team member: {e}", exc_info=True)
            db.rollback()
            raise


# Singleton instances
team_repo = TeamRepository()
team_member_repo = TeamMemberRepository()