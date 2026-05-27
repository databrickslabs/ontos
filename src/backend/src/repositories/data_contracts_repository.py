from typing import Any, Dict, Optional, List, Union

from sqlalchemy import or_, and_
from sqlalchemy.orm import Session, selectinload

from src.common.repository import CRUDBase
from src.db_models.data_contracts import (
    DataContractDb,
    DataContractTagDb,
    DataContractServerDb,
    DataContractServerPropertyDb,
    DataContractRoleDb,
    DataContractRolePropertyDb,
    DataContractTeamDb,
    DataContractSupportDb,
    DataContractPricingDb,
    DataContractAuthoritativeDefinitionDb,
    DataContractCustomPropertyDb,
    DataContractSlaPropertyDb,
    SchemaObjectDb,
    SchemaObjectAuthoritativeDefinitionDb,
    SchemaPropertyDb,
    SchemaPropertyAuthoritativeDefinitionDb,
    DataQualityCheckDb,
    DataContractCommentDb,
)
from src.common.logging import get_logger

logger = get_logger(__name__)


class DataContractRepository(CRUDBase[DataContractDb, Dict[str, Any], Union[Dict[str, Any], DataContractDb]]):
    def __init__(self):
        super().__init__(DataContractDb)

    def get_by_name(self, db: Session, *, name: str) -> Optional[DataContractDb]:
        """Get data contract by name."""
        try:
            return db.query(self.model).filter(self.model.name == name).first()
        except Exception as e:
            logger.error(f"Error fetching DataContractDb by name {name}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_with_all(self, db: Session, *, id: str) -> Optional[DataContractDb]:
        try:
            return (
                db.query(self.model)
                .options(
                    selectinload(self.model.tags),
                    selectinload(self.model.servers).selectinload(DataContractServerDb.properties),
                    selectinload(self.model.roles).selectinload(DataContractRoleDb.custom_properties),
                    selectinload(self.model.team),
                    selectinload(self.model.support),
                    selectinload(self.model.pricing),
                    selectinload(self.model.authoritative_defs),
                    selectinload(self.model.custom_properties),
                    selectinload(self.model.sla_properties),
                    selectinload(self.model.schema_objects)
                        .selectinload(SchemaObjectDb.properties)
                        .selectinload(SchemaPropertyDb.authoritative_definitions),
                    selectinload(self.model.schema_objects)
                        .selectinload(SchemaObjectDb.quality_checks),
                    selectinload(self.model.schema_objects)
                        .selectinload(SchemaObjectDb.authoritative_definitions),
                    selectinload(self.model.schema_objects)
                        .selectinload(SchemaObjectDb.custom_properties),
                    selectinload(self.model.comments),
                )
                .filter(self.model.id == id)
                .first()
            )
        except Exception as e:
            logger.error(f"Error fetching DataContractDb with all relations for id {id}: {e}", exc_info=True)
            db.rollback()
            raise

    # Override create to accept either a dict payload or a pre-built SA model
    def create(self, db: Session, *, obj_in: Union[Dict[str, Any], DataContractDb]) -> DataContractDb:
        try:
            if isinstance(obj_in, DataContractDb):
                # Defaulting: every contract belongs to exactly one family.
                # If the caller didn't supply one (this is an initial create,
                # not a clone), make the row its own family root.
                if obj_in.id is None:
                    from uuid import uuid4
                    obj_in.id = str(uuid4())
                if obj_in.version_family_id is None:
                    obj_in.version_family_id = obj_in.id
                db.add(obj_in)
                db.flush()
                db.refresh(obj_in)
                return obj_in
            payload: Dict[str, Any] = dict(obj_in)
            if not payload.get('id'):
                from uuid import uuid4
                payload['id'] = str(uuid4())
            if not payload.get('version_family_id'):
                payload['version_family_id'] = payload['id']
            db_obj = self.model(**payload)
            db.add(db_obj)
            db.flush()
            db.refresh(db_obj)
            return db_obj
        except Exception as e:
            logger.error(f"Error creating DataContractDb: {e}", exc_info=True)
            db.rollback()
            raise

    # ---- Version-family lookups (PRD #442) ----

    def get_family_versions(
        self,
        db: Session,
        *,
        family_id: str,
        user_email: Optional[str] = None,
        is_admin: bool = False,
    ) -> List[DataContractDb]:
        """Return every version in a family that's visible to the caller, newest first.

        Visibility rules:
          - Personal drafts (draft_owner_id IS NOT NULL) are visible only to
            their owner, regardless of role.
          - Admins see everything; other users see all non-personal-draft rows.

        Args:
            db: Database session
            family_id: version_family_id to look up (every row in a family
                       carries this same UUID — see PRD #442).
            user_email: Caller's email/username (used for personal-draft
                        ownership check).
            is_admin: If True, bypasses the personal-draft filter entirely.

        Returns:
            List of DataContractDb rows ordered by created_at DESC.
        """
        try:
            query = db.query(self.model).filter(self.model.version_family_id == family_id)
            if not is_admin:
                # Hide other users' personal drafts.
                query = query.filter(
                    or_(
                        self.model.draft_owner_id.is_(None),
                        self.model.draft_owner_id == user_email,
                    )
                )
            return query.order_by(self.model.created_at.desc()).all()
        except Exception as e:
            logger.error(f"Error fetching family versions for {family_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def list_family_representatives(
        self,
        db: Session,
        *,
        user_email: Optional[str] = None,
        is_admin: bool = False,
        project_id: Optional[str] = None,
        include_history: bool = False,
        skip: int = 0,
        limit: int = 100,
    ) -> List[DataContractDb]:
        """List one row per family (latest visible representative), or all
        rows if include_history is True.

        Representative-pick rules:
          - For each family, choose the most recently created row that
            passes the visibility filter (personal drafts hidden from
            non-owners; project filter applied for non-admins).

        Args:
            db: Database session
            user_email: Caller's email for personal-draft visibility
            is_admin: If True, bypasses visibility filters
            project_id: Optional project scope (non-admins see only project +
                        unassigned rows)
            include_history: If True, returns all visible rows flat (no
                             family collapse). Use for "Show all versions".
            skip / limit: Pagination
        """
        from sqlalchemy import func

        try:
            base_filters = []
            if not is_admin:
                base_filters.append(
                    or_(
                        self.model.draft_owner_id.is_(None),
                        self.model.draft_owner_id == user_email,
                    )
                )
                if project_id:
                    base_filters.append(
                        or_(
                            self.model.project_id == project_id,
                            self.model.project_id.is_(None),
                        )
                    )

            if include_history:
                query = db.query(self.model)
                if base_filters:
                    query = query.filter(*base_filters)
                return (
                    query.order_by(
                        self.model.version_family_id,
                        self.model.created_at.desc(),
                    )
                    .offset(skip)
                    .limit(limit)
                    .all()
                )

            # Window function: rank rows within each family newest-first;
            # pick rank 1. Postgres supports ROW_NUMBER() OVER (...).
            rn = (
                func.row_number()
                .over(
                    partition_by=self.model.version_family_id,
                    order_by=self.model.created_at.desc(),
                )
                .label("_family_rn")
            )
            ranked = db.query(self.model.id.label("_id"), rn)
            if base_filters:
                ranked = ranked.filter(*base_filters)
            ranked_sq = ranked.subquery()
            query = (
                db.query(self.model)
                .join(ranked_sq, self.model.id == ranked_sq.c._id)
                .filter(ranked_sq.c._family_rn == 1)
            )
            return (
                query.order_by(self.model.created_at.desc())
                .offset(skip)
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.error(f"Error listing family representatives: {e}", exc_info=True)
            db.rollback()
            raise

    # Override get_multi to support project filtering
    def get_multi(
        self,
        db: Session,
        *,
        skip: int = 0,
        limit: int = 100,
        project_id: Optional[str] = None,
        is_admin: bool = False
    ) -> List[DataContractDb]:
        """Get multiple data contracts with optional project filtering.

        Args:
            db: Database session
            skip: Number of records to skip
            limit: Maximum number of records to return
            project_id: Optional project ID to filter by (ignored if is_admin=True)
            is_admin: If True, return all contracts regardless of project_id

        Returns:
            List of DataContractDb objects
        """
        logger.debug(f"Fetching DataContracts (skip: {skip}, limit: {limit}, project_id: {project_id}, is_admin: {is_admin})")
        try:
            query = db.query(self.model)

            # Apply project filtering only if not admin and project_id is provided
            if not is_admin and project_id:
                logger.debug(f"Filtering contracts by project_id: {project_id}")
                # Include contracts with matching project_id OR null project_id (legacy/unassigned)
                query = query.filter(
                    (self.model.project_id == project_id) |
                    (self.model.project_id.is_(None))
                )

            return query.offset(skip).limit(limit).all()
        except Exception as e:
            logger.error(f"Database error fetching DataContracts: {e}", exc_info=True)
            db.rollback()
            raise

    # --- Project Filtering Methods ---
    def get_by_project(self, db: Session, project_id: str, skip: int = 0, limit: int = 100) -> List[DataContractDb]:
        """Get data contracts filtered by project_id."""
        logger.debug(f"Fetching DataContracts for project {project_id} with skip: {skip}, limit: {limit}")
        try:
            return (
                db.query(self.model)
                .filter(self.model.project_id == project_id)
                .offset(skip)
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.error(f"Database error fetching DataContracts by project {project_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_without_project(self, db: Session, skip: int = 0, limit: int = 100) -> List[DataContractDb]:
        """Get data contracts that are not assigned to any project."""
        logger.debug(f"Fetching DataContracts without project assignment with skip: {skip}, limit: {limit}")
        try:
            return (
                db.query(self.model)
                .filter(self.model.project_id.is_(None))
                .offset(skip)
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.error(f"Database error fetching DataContracts without project: {e}", exc_info=True)
            db.rollback()
            raise

    def count_by_project(self, db: Session, project_id: str) -> int:
        """Count data contracts for a specific project."""
        logger.debug(f"Counting DataContracts for project {project_id}")
        try:
            return db.query(self.model).filter(self.model.project_id == project_id).count()
        except Exception as e:
            logger.error(f"Database error counting DataContracts by project {project_id}: {e}", exc_info=True)
            db.rollback()
            raise

    # --- Three-Tier Visibility Filtering ---
    def get_visible_contracts(
        self,
        db: Session,
        current_user: str,
        user_projects: List[str],
        skip: int = 0,
        limit: int = 100
    ) -> List[DataContractDb]:
        """Get contracts visible to user based on three-tier visibility model.
        
        Tier 1: Personal drafts (draft_owner_id set) - only visible to owner
        Tier 2: Team/project versions (draft_owner_id null, publication_scope none) - visible to project members
        Tier 3: Published versions (publication_scope not none) - visible to everyone
        
        Args:
            db: Database session
            current_user: Current user's username/ID
            user_projects: List of project IDs the user is a member of
            skip: Number of records to skip
            limit: Maximum number of records to return
            
        Returns:
            List of DataContractDb objects visible to the user
        """
        logger.debug(f"Fetching visible contracts for user {current_user}, projects: {user_projects}")
        try:
            query = db.query(self.model).filter(
                or_(
                    # Tier 3: Published to marketplace (everyone can see)
                    self.model.publication_scope != "none",
                    # Tier 2: Team/project versions (no personal owner, in user's projects)
                    and_(
                        self.model.draft_owner_id.is_(None),
                        self.model.project_id.in_(user_projects) if user_projects else False
                    ),
                    # Tier 2: Contracts without project assignment (legacy/shared)
                    and_(
                        self.model.draft_owner_id.is_(None),
                        self.model.project_id.is_(None)
                    ),
                    # Tier 1: User's own personal drafts
                    self.model.draft_owner_id == current_user,
                )
            )
            return query.offset(skip).limit(limit).all()
        except Exception as e:
            logger.error(f"Database error fetching visible contracts: {e}", exc_info=True)
            db.rollback()
            raise

    def get_user_personal_drafts(
        self,
        db: Session,
        current_user: str,
        skip: int = 0,
        limit: int = 100
    ) -> List[DataContractDb]:
        """Get all personal drafts owned by a specific user.
        
        Args:
            db: Database session
            current_user: Current user's username/ID
            skip: Number of records to skip
            limit: Maximum number of records to return
            
        Returns:
            List of DataContractDb objects that are personal drafts for this user
        """
        logger.debug(f"Fetching personal drafts for user {current_user}")
        try:
            return (
                db.query(self.model)
                .filter(self.model.draft_owner_id == current_user)
                .offset(skip)
                .limit(limit)
                .all()
            )
        except Exception as e:
            logger.error(f"Database error fetching personal drafts for user {current_user}: {e}", exc_info=True)
            db.rollback()
            raise

    def is_visible_to_user(
        self,
        db: Session,
        contract_id: str,
        current_user: str,
        user_projects: List[str]
    ) -> bool:
        """Check if a specific contract is visible to the user.
        
        Args:
            db: Database session
            contract_id: ID of the contract to check
            current_user: Current user's username/ID
            user_projects: List of project IDs the user is a member of
            
        Returns:
            True if the contract is visible to the user, False otherwise
        """
        try:
            contract = db.query(self.model).filter(self.model.id == contract_id).first()
            if not contract:
                return False
            
            # Tier 3: Published to marketplace
            if (contract.publication_scope or "none") != "none":
                return True
            
            # Tier 1: User's own personal draft
            if contract.draft_owner_id == current_user:
                return True
            
            # Tier 2: Team/project version (no personal owner, in user's projects)
            if contract.draft_owner_id is None:
                # Contract without project assignment is visible to all team members
                if contract.project_id is None:
                    return True
                # Contract in user's project
                if contract.project_id in user_projects:
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Database error checking visibility for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise


# Singleton-like access if desired
data_contract_repo = DataContractRepository()


# ===== Tag Repository Methods =====
class ContractTagRepository(CRUDBase[DataContractTagDb, Dict[str, Any], DataContractTagDb]):
    def __init__(self):
        super().__init__(DataContractTagDb)

    def get_by_contract(self, db: Session, *, contract_id: str) -> List[DataContractTagDb]:
        """Get all tags for a specific contract."""
        try:
            return db.query(self.model).filter(self.model.contract_id == contract_id).all()
        except Exception as e:
            logger.error(f"Error fetching tags for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_by_name(self, db: Session, *, contract_id: str, name: str) -> Optional[DataContractTagDb]:
        """Get a tag by contract_id and name (to prevent duplicates)."""
        try:
            return db.query(self.model).filter(
                self.model.contract_id == contract_id,
                self.model.name == name
            ).first()
        except Exception as e:
            logger.error(f"Error fetching tag {name} for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def create_tag(self, db: Session, *, contract_id: str, name: str) -> DataContractTagDb:
        """Create a new tag for a contract."""
        try:
            # Check for duplicate
            existing = self.get_by_name(db=db, contract_id=contract_id, name=name)
            if existing:
                raise ValueError(f"Tag '{name}' already exists for this contract")

            tag = DataContractTagDb(contract_id=contract_id, name=name)
            db.add(tag)
            db.flush()
            db.refresh(tag)
            return tag
        except Exception as e:
            logger.error(f"Error creating tag for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def update_tag(self, db: Session, *, tag_id: str, name: str) -> Optional[DataContractTagDb]:
        """Update a tag's name."""
        try:
            tag = db.query(self.model).filter(self.model.id == tag_id).first()
            if not tag:
                return None

            # Check for duplicate name in same contract
            existing = self.get_by_name(db=db, contract_id=tag.contract_id, name=name)
            if existing and existing.id != tag_id:
                raise ValueError(f"Tag '{name}' already exists for this contract")

            tag.name = name
            db.flush()
            db.refresh(tag)
            return tag
        except Exception as e:
            logger.error(f"Error updating tag {tag_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def delete_tag(self, db: Session, *, tag_id: str) -> bool:
        """Delete a tag."""
        try:
            tag = db.query(self.model).filter(self.model.id == tag_id).first()
            if not tag:
                return False
            db.delete(tag)
            db.flush()
            return True
        except Exception as e:
            logger.error(f"Error deleting tag {tag_id}: {e}", exc_info=True)
            db.rollback()
            raise


# Singleton instance
contract_tag_repo = ContractTagRepository()


# ===== Custom Properties Repository =====
class CustomPropertyRepository(CRUDBase[DataContractCustomPropertyDb, Dict[str, Any], DataContractCustomPropertyDb]):
    def __init__(self):
        super().__init__(DataContractCustomPropertyDb)

    def get_by_contract(self, db: Session, *, contract_id: str) -> List[DataContractCustomPropertyDb]:
        """Get all custom properties for a specific contract."""
        try:
            return db.query(self.model).filter(self.model.contract_id == contract_id).all()
        except Exception as e:
            logger.error(f"Error fetching custom properties for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def create_property(self, db: Session, *, contract_id: str, property: str, value: Optional[str] = None) -> DataContractCustomPropertyDb:
        """Create a new custom property for a contract."""
        try:
            prop = DataContractCustomPropertyDb(contract_id=contract_id, property=property, value=value)
            db.add(prop)
            db.flush()
            db.refresh(prop)
            return prop
        except Exception as e:
            logger.error(f"Error creating custom property for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def update_property(self, db: Session, *, property_id: str, property: Optional[str] = None, value: Optional[str] = None) -> Optional[DataContractCustomPropertyDb]:
        """Update a custom property."""
        try:
            prop = db.query(self.model).filter(self.model.id == property_id).first()
            if not prop:
                return None

            if property is not None:
                prop.property = property
            if value is not None:
                prop.value = value

            db.flush()
            db.refresh(prop)
            return prop
        except Exception as e:
            logger.error(f"Error updating custom property {property_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def delete_property(self, db: Session, *, property_id: str) -> bool:
        """Delete a custom property."""
        try:
            prop = db.query(self.model).filter(self.model.id == property_id).first()
            if not prop:
                return False
            db.delete(prop)
            db.flush()
            return True
        except Exception as e:
            logger.error(f"Error deleting custom property {property_id}: {e}", exc_info=True)
            db.rollback()
            raise


custom_property_repo = CustomPropertyRepository()


# ===== Support Channel Repository =====
class SupportChannelRepository(CRUDBase[DataContractSupportDb, Dict[str, Any], DataContractSupportDb]):
    def __init__(self):
        super().__init__(DataContractSupportDb)

    def get_by_contract(self, db: Session, *, contract_id: str) -> List[DataContractSupportDb]:
        """Get all support channels for a specific contract."""
        try:
            return db.query(self.model).filter(self.model.contract_id == contract_id).all()
        except Exception as e:
            logger.error(f"Error fetching support channels for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def create_channel(
        self,
        db: Session,
        *,
        contract_id: str,
        channel: str,
        url: str,
        description: Optional[str] = None,
        tool: Optional[str] = None,
        scope: Optional[str] = None,
        invitation_url: Optional[str] = None
    ) -> DataContractSupportDb:
        """Create a new support channel for a contract."""
        try:
            support = DataContractSupportDb(
                contract_id=contract_id,
                channel=channel,
                url=url,
                description=description,
                tool=tool,
                scope=scope,
                invitation_url=invitation_url
            )
            db.add(support)
            db.flush()
            db.refresh(support)
            return support
        except Exception as e:
            logger.error(f"Error creating support channel for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def update_channel(
        self,
        db: Session,
        *,
        channel_id: str,
        channel: Optional[str] = None,
        url: Optional[str] = None,
        description: Optional[str] = None,
        tool: Optional[str] = None,
        scope: Optional[str] = None,
        invitation_url: Optional[str] = None
    ) -> Optional[DataContractSupportDb]:
        """Update a support channel."""
        try:
            support = db.query(self.model).filter(self.model.id == channel_id).first()
            if not support:
                return None

            if channel is not None:
                support.channel = channel
            if url is not None:
                support.url = url
            if description is not None:
                support.description = description
            if tool is not None:
                support.tool = tool
            if scope is not None:
                support.scope = scope
            if invitation_url is not None:
                support.invitation_url = invitation_url

            db.flush()
            db.refresh(support)
            return support
        except Exception as e:
            logger.error(f"Error updating support channel {channel_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def delete_channel(self, db: Session, *, channel_id: str) -> bool:
        """Delete a support channel."""
        try:
            support = db.query(self.model).filter(self.model.id == channel_id).first()
            if not support:
                return False
            db.delete(support)
            db.flush()
            return True
        except Exception as e:
            logger.error(f"Error deleting support channel {channel_id}: {e}", exc_info=True)
            db.rollback()
            raise


support_channel_repo = SupportChannelRepository()


# ===== Pricing Repository (Singleton Pattern) =====
class PricingRepository(CRUDBase[DataContractPricingDb, Dict[str, Any], DataContractPricingDb]):
    def __init__(self):
        super().__init__(DataContractPricingDb)

    def get_pricing(self, db: Session, *, contract_id: str) -> Optional[DataContractPricingDb]:
        """Get pricing for a contract (returns None if not exists)."""
        try:
            return db.query(self.model).filter(self.model.contract_id == contract_id).first()
        except Exception as e:
            logger.error(f"Error fetching pricing for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_or_create_pricing(self, db: Session, *, contract_id: str) -> DataContractPricingDb:
        """Get pricing for a contract, create if not exists (singleton pattern)."""
        try:
            pricing = self.get_pricing(db=db, contract_id=contract_id)
            if pricing:
                return pricing

            # Create empty pricing record
            pricing = DataContractPricingDb(contract_id=contract_id)
            db.add(pricing)
            db.flush()
            db.refresh(pricing)
            return pricing
        except Exception as e:
            logger.error(f"Error getting or creating pricing for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def update_pricing(
        self,
        db: Session,
        *,
        contract_id: str,
        price_amount: Optional[str] = None,
        price_currency: Optional[str] = None,
        price_unit: Optional[str] = None
    ) -> DataContractPricingDb:
        """Update pricing for a contract (creates if not exists)."""
        try:
            pricing = self.get_or_create_pricing(db=db, contract_id=contract_id)

            # Update fields if provided
            if price_amount is not None:
                pricing.price_amount = price_amount
            if price_currency is not None:
                pricing.price_currency = price_currency
            if price_unit is not None:
                pricing.price_unit = price_unit

            db.flush()
            db.refresh(pricing)
            return pricing
        except Exception as e:
            logger.error(f"Error updating pricing for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise


pricing_repo = PricingRepository()


# ===== Role Repository (With Nested Properties) =====
class RoleRepository(CRUDBase[DataContractRoleDb, Dict[str, Any], DataContractRoleDb]):
    def __init__(self):
        super().__init__(DataContractRoleDb)

    def get_by_contract(self, db: Session, *, contract_id: str) -> List[DataContractRoleDb]:
        """Get all roles for a specific contract (with nested properties loaded)."""
        try:
            return (
                db.query(self.model)
                .options(selectinload(self.model.custom_properties))
                .filter(self.model.contract_id == contract_id)
                .all()
            )
        except Exception as e:
            logger.error(f"Error fetching roles for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def create_role(
        self,
        db: Session,
        *,
        contract_id: str,
        role: str,
        description: Optional[str] = None,
        access: Optional[str] = None,
        first_level_approvers: Optional[str] = None,
        second_level_approvers: Optional[str] = None,
        custom_properties: Optional[List[Dict[str, Any]]] = None
    ) -> DataContractRoleDb:
        """Create a new role for a contract with optional nested properties."""
        try:
            # Create main role
            role_db = DataContractRoleDb(
                contract_id=contract_id,
                role=role,
                description=description,
                access=access,
                first_level_approvers=first_level_approvers,
                second_level_approvers=second_level_approvers
            )
            db.add(role_db)
            db.flush()  # Flush to get role ID

            # Create nested properties if provided
            if custom_properties:
                for prop in custom_properties:
                    prop_db = DataContractRolePropertyDb(
                        role_id=role_db.id,
                        property=prop.get('property'),
                        value=prop.get('value')
                    )
                    db.add(prop_db)

            db.flush()
            db.refresh(role_db)
            return role_db
        except Exception as e:
            logger.error(f"Error creating role for contract {contract_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def update_role(
        self,
        db: Session,
        *,
        role_id: str,
        role: Optional[str] = None,
        description: Optional[str] = None,
        access: Optional[str] = None,
        first_level_approvers: Optional[str] = None,
        second_level_approvers: Optional[str] = None,
        custom_properties: Optional[List[Dict[str, Any]]] = None
    ) -> Optional[DataContractRoleDb]:
        """Update a role (replaces nested properties if provided)."""
        try:
            role_db = (
                db.query(self.model)
                .options(selectinload(self.model.custom_properties))
                .filter(self.model.id == role_id)
                .first()
            )
            if not role_db:
                return None

            # Update main fields
            if role is not None:
                role_db.role = role
            if description is not None:
                role_db.description = description
            if access is not None:
                role_db.access = access
            if first_level_approvers is not None:
                role_db.first_level_approvers = first_level_approvers
            if second_level_approvers is not None:
                role_db.second_level_approvers = second_level_approvers

            # Replace nested properties if provided
            if custom_properties is not None:
                # Delete existing properties
                for existing_prop in role_db.custom_properties:
                    db.delete(existing_prop)
                db.flush()

                # Create new properties
                for prop in custom_properties:
                    prop_db = DataContractRolePropertyDb(
                        role_id=role_db.id,
                        property=prop.get('property'),
                        value=prop.get('value')
                    )
                    db.add(prop_db)

            db.flush()
            db.refresh(role_db)
            return role_db
        except Exception as e:
            logger.error(f"Error updating role {role_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def delete_role(self, db: Session, *, role_id: str) -> bool:
        """Delete a role (cascade deletes nested properties)."""
        try:
            role_db = db.query(self.model).filter(self.model.id == role_id).first()
            if not role_db:
                return False
            db.delete(role_db)
            db.flush()
            return True
        except Exception as e:
            logger.error(f"Error deleting role {role_id}: {e}", exc_info=True)
            db.rollback()
            raise


role_repo = RoleRepository()


# ===== Contract Authoritative Definition Repository =====
class ContractAuthoritativeDefinitionRepository(CRUDBase[DataContractAuthoritativeDefinitionDb, Dict[str, Any], DataContractAuthoritativeDefinitionDb]):
    def __init__(self):
        super().__init__(DataContractAuthoritativeDefinitionDb)

    def get_by_contract(self, db: Session, *, contract_id: str) -> List[DataContractAuthoritativeDefinitionDb]:
        """Get all authoritative definitions for a contract."""
        try:
            return db.query(self.model).filter(self.model.contract_id == contract_id).all()
        except Exception as e:
            logger.error(f"Error fetching contract authoritative definitions: {e}", exc_info=True)
            db.rollback()
            raise

    def create_definition(self, db: Session, *, contract_id: str, url: str, type: str) -> DataContractAuthoritativeDefinitionDb:
        """Create an authoritative definition for a contract."""
        try:
            definition = DataContractAuthoritativeDefinitionDb(contract_id=contract_id, url=url, type=type)
            db.add(definition)
            db.flush()
            db.refresh(definition)
            return definition
        except Exception as e:
            logger.error(f"Error creating contract authoritative definition: {e}", exc_info=True)
            db.rollback()
            raise

    def update_definition(self, db: Session, *, definition_id: str, url: Optional[str] = None, type: Optional[str] = None) -> Optional[DataContractAuthoritativeDefinitionDb]:
        """Update an authoritative definition."""
        try:
            definition = db.query(self.model).filter(self.model.id == definition_id).first()
            if not definition:
                return None
            if url is not None:
                definition.url = url
            if type is not None:
                definition.type = type
            db.flush()
            db.refresh(definition)
            return definition
        except Exception as e:
            logger.error(f"Error updating contract authoritative definition: {e}", exc_info=True)
            db.rollback()
            raise

    def delete_definition(self, db: Session, *, definition_id: str) -> bool:
        """Delete an authoritative definition."""
        try:
            definition = db.query(self.model).filter(self.model.id == definition_id).first()
            if not definition:
                return False
            db.delete(definition)
            db.flush()
            return True
        except Exception as e:
            logger.error(f"Error deleting contract authoritative definition: {e}", exc_info=True)
            db.rollback()
            raise


contract_authoritative_definition_repo = ContractAuthoritativeDefinitionRepository()


# ===== Schema Authoritative Definition Repository =====
class SchemaAuthoritativeDefinitionRepository(CRUDBase[SchemaObjectAuthoritativeDefinitionDb, Dict[str, Any], SchemaObjectAuthoritativeDefinitionDb]):
    def __init__(self):
        super().__init__(SchemaObjectAuthoritativeDefinitionDb)

    def get_by_schema(self, db: Session, *, schema_id: str) -> List[SchemaObjectAuthoritativeDefinitionDb]:
        """Get all authoritative definitions for a schema object."""
        try:
            return db.query(self.model).filter(self.model.schema_object_id == schema_id).all()
        except Exception as e:
            logger.error(f"Error fetching schema authoritative definitions: {e}", exc_info=True)
            db.rollback()
            raise

    def create_definition(self, db: Session, *, schema_id: str, url: str, type: str) -> SchemaObjectAuthoritativeDefinitionDb:
        """Create an authoritative definition for a schema object."""
        try:
            definition = SchemaObjectAuthoritativeDefinitionDb(schema_object_id=schema_id, url=url, type=type)
            db.add(definition)
            db.flush()
            db.refresh(definition)
            return definition
        except Exception as e:
            logger.error(f"Error creating schema authoritative definition: {e}", exc_info=True)
            db.rollback()
            raise

    def update_definition(self, db: Session, *, definition_id: str, url: Optional[str] = None, type: Optional[str] = None) -> Optional[SchemaObjectAuthoritativeDefinitionDb]:
        """Update an authoritative definition."""
        try:
            definition = db.query(self.model).filter(self.model.id == definition_id).first()
            if not definition:
                return None
            if url is not None:
                definition.url = url
            if type is not None:
                definition.type = type
            db.flush()
            db.refresh(definition)
            return definition
        except Exception as e:
            logger.error(f"Error updating schema authoritative definition: {e}", exc_info=True)
            db.rollback()
            raise

    def delete_definition(self, db: Session, *, definition_id: str) -> bool:
        """Delete an authoritative definition."""
        try:
            definition = db.query(self.model).filter(self.model.id == definition_id).first()
            if not definition:
                return False
            db.delete(definition)
            db.flush()
            return True
        except Exception as e:
            logger.error(f"Error deleting schema authoritative definition: {e}", exc_info=True)
            db.rollback()
            raise


schema_authoritative_definition_repo = SchemaAuthoritativeDefinitionRepository()


# ===== Property Authoritative Definition Repository =====
class PropertyAuthoritativeDefinitionRepository(CRUDBase[SchemaPropertyAuthoritativeDefinitionDb, Dict[str, Any], SchemaPropertyAuthoritativeDefinitionDb]):
    def __init__(self):
        super().__init__(SchemaPropertyAuthoritativeDefinitionDb)

    def get_by_property(self, db: Session, *, property_id: str) -> List[SchemaPropertyAuthoritativeDefinitionDb]:
        """Get all authoritative definitions for a schema property."""
        try:
            return db.query(self.model).filter(self.model.property_id == property_id).all()
        except Exception as e:
            logger.error(f"Error fetching property authoritative definitions: {e}", exc_info=True)
            db.rollback()
            raise

    def create_definition(self, db: Session, *, property_id: str, url: str, type: str) -> SchemaPropertyAuthoritativeDefinitionDb:
        """Create an authoritative definition for a schema property."""
        try:
            definition = SchemaPropertyAuthoritativeDefinitionDb(property_id=property_id, url=url, type=type)
            db.add(definition)
            db.flush()
            db.refresh(definition)
            return definition
        except Exception as e:
            logger.error(f"Error creating property authoritative definition: {e}", exc_info=True)
            db.rollback()
            raise

    def update_definition(self, db: Session, *, definition_id: str, url: Optional[str] = None, type: Optional[str] = None) -> Optional[SchemaPropertyAuthoritativeDefinitionDb]:
        """Update an authoritative definition."""
        try:
            definition = db.query(self.model).filter(self.model.id == definition_id).first()
            if not definition:
                return None
            if url is not None:
                definition.url = url
            if type is not None:
                definition.type = type
            db.flush()
            db.refresh(definition)
            return definition
        except Exception as e:
            logger.error(f"Error updating property authoritative definition: {e}", exc_info=True)
            db.rollback()
            raise

    def delete_definition(self, db: Session, *, definition_id: str) -> bool:
        """Delete an authoritative definition."""
        try:
            definition = db.query(self.model).filter(self.model.id == definition_id).first()
            if not definition:
                return False
            db.delete(definition)
            db.flush()
            return True
        except Exception as e:
            logger.error(f"Error deleting property authoritative definition: {e}", exc_info=True)
            db.rollback()
            raise


property_authoritative_definition_repo = PropertyAuthoritativeDefinitionRepository()


