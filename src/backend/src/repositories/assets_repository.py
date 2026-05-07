from typing import List, Optional
from uuid import UUID

from sqlalchemy.orm import Session, selectinload
from sqlalchemy.exc import SQLAlchemyError

from src.common.repository import CRUDBase
from src.db_models.assets import AssetTypeDb, AssetDb, AssetRelationshipDb
from src.models.assets import (
    AssetTypeCreate, AssetTypeUpdate,
    AssetCreate, AssetUpdate,
    AssetRelationshipCreate,
)
from src.common.logging import get_logger

logger = get_logger(__name__)


class AssetTypeRepository(CRUDBase[AssetTypeDb, AssetTypeCreate, AssetTypeUpdate]):
    def __init__(self):
        super().__init__(AssetTypeDb)
        logger.info("AssetTypeRepository initialized.")

    def get_by_name(self, db: Session, *, name: str) -> Optional[AssetTypeDb]:
        """Gets an asset type by name."""
        try:
            return db.query(self.model).filter(self.model.name == name).first()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching asset type by name {name}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_multi_filtered(
        self, db: Session, *, skip: int = 0, limit: int = 100,
        category: Optional[str] = None, status: Optional[str] = None
    ) -> List[AssetTypeDb]:
        """Gets multiple asset types with optional filters."""
        try:
            query = db.query(self.model).order_by(self.model.name)
            if category:
                query = query.filter(self.model.category == category)
            if status:
                query = query.filter(self.model.status == status)
            return query.offset(skip).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching asset types: {e}", exc_info=True)
            db.rollback()
            raise

    def get_asset_count(self, db: Session, asset_type_id: UUID) -> int:
        """Gets the count of assets for a given asset type."""
        try:
            return db.query(AssetDb).filter(AssetDb.asset_type_id == asset_type_id).count()
        except SQLAlchemyError as e:
            logger.error(f"Database error counting assets for type {asset_type_id}: {e}", exc_info=True)
            db.rollback()
            raise


class AssetRepository(CRUDBase[AssetDb, AssetCreate, AssetUpdate]):
    def __init__(self):
        super().__init__(AssetDb)
        logger.info("AssetRepository initialized.")

    def get_with_relationships(self, db: Session, id: UUID) -> Optional[AssetDb]:
        """Gets a single asset by ID, eager loading relationships and asset type."""
        try:
            return (
                db.query(self.model)
                .options(
                    selectinload(self.model.asset_type),
                    selectinload(self.model.source_relationships),
                    selectinload(self.model.target_relationships),
                )
                .filter(self.model.id == id)
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching asset with relationships by id {id}: {e}", exc_info=True)
            db.rollback()
            raise

    def _apply_filters(self, query, *, asset_type_id=None, asset_type_names=None,
                        platform=None, domain_id=None, status=None, name=None,
                        restrict_to_ids=None):
        """Apply common filter predicates to a query.

        ``restrict_to_ids`` is an optional iterable of asset UUIDs to scope
        results to (used for role-based DP-link scoping). An empty iterable
        intentionally yields zero results — pass None for "no restriction".
        """
        if asset_type_id:
            query = query.filter(self.model.asset_type_id == asset_type_id)
        if asset_type_names:
            query = query.join(AssetTypeDb, self.model.asset_type_id == AssetTypeDb.id).filter(
                AssetTypeDb.name.in_(asset_type_names)
            )
        if platform:
            query = query.filter(self.model.platform == platform)
        if domain_id:
            query = query.filter(self.model.domain_id == domain_id)
        if status:
            query = query.filter(self.model.status == status)
        if name:
            query = query.filter(self.model.name.ilike(f"%{name}%"))
        if restrict_to_ids is not None:
            # Empty set must yield zero rows, not be ignored.
            ids = list(restrict_to_ids)
            if not ids:
                # Force empty result.
                query = query.filter(self.model.id.is_(None))
            else:
                query = query.filter(self.model.id.in_(ids))
        return query

    def get_multi_filtered(
        self, db: Session, *, skip: int = 0, limit: int = 100,
        asset_type_id: Optional[UUID] = None, asset_type_names: Optional[list] = None,
        platform: Optional[str] = None, domain_id: Optional[str] = None,
        status: Optional[str] = None, name: Optional[str] = None,
        restrict_to_ids: Optional[list] = None,
    ) -> List[AssetDb]:
        """Gets multiple assets with optional filters."""
        try:
            query = (
                db.query(self.model)
                .options(
                    selectinload(self.model.asset_type),
                    selectinload(self.model.target_relationships)
                    .selectinload(AssetRelationshipDb.source_asset),
                )
                .order_by(self.model.name)
            )
            query = self._apply_filters(
                query, asset_type_id=asset_type_id, asset_type_names=asset_type_names,
                platform=platform, domain_id=domain_id, status=status, name=name,
                restrict_to_ids=restrict_to_ids,
            )
            return query.offset(skip).limit(limit).all()
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching assets: {e}", exc_info=True)
            db.rollback()
            raise

    def count_filtered(
        self, db: Session, *,
        asset_type_id: Optional[UUID] = None, asset_type_names: Optional[list] = None,
        platform: Optional[str] = None, domain_id: Optional[str] = None,
        status: Optional[str] = None, name: Optional[str] = None,
        restrict_to_ids: Optional[list] = None,
    ) -> int:
        """Returns the total count of assets matching the given filters."""
        try:
            from sqlalchemy import func
            query = db.query(func.count(self.model.id))
            query = self._apply_filters(
                query, asset_type_id=asset_type_id, asset_type_names=asset_type_names,
                platform=platform, domain_id=domain_id, status=status, name=name,
                restrict_to_ids=restrict_to_ids,
            )
            return query.scalar() or 0
        except SQLAlchemyError as e:
            logger.error(f"Database error counting assets: {e}", exc_info=True)
            db.rollback()
            raise

    def get_by_name_and_type(self, db: Session, *, name: str, asset_type_id: UUID) -> Optional[AssetDb]:
        """Gets an asset by name and type."""
        try:
            return (
                db.query(self.model)
                .filter(self.model.name == name, self.model.asset_type_id == asset_type_id)
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching asset by name/type: {e}", exc_info=True)
            db.rollback()
            raise

    def get_by_identity(
        self, db: Session, *, name: str, asset_type_id: UUID, platform: str, location: str,
    ) -> Optional[AssetDb]:
        """Gets an asset by its full identity (matches the uq_asset_identity constraint)."""
        try:
            return (
                db.query(self.model)
                .filter(
                    self.model.name == name,
                    self.model.asset_type_id == asset_type_id,
                    self.model.platform == platform,
                    self.model.location == location,
                )
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching asset by identity: {e}", exc_info=True)
            db.rollback()
            raise


class AssetRelationshipRepository(CRUDBase[AssetRelationshipDb, AssetRelationshipCreate, AssetRelationshipCreate]):
    def __init__(self):
        super().__init__(AssetRelationshipDb)
        logger.info("AssetRelationshipRepository initialized.")

    def get_for_asset(self, db: Session, *, asset_id: UUID) -> List[AssetRelationshipDb]:
        """Gets all relationships where the asset is source or target."""
        try:
            from sqlalchemy import or_
            return (
                db.query(self.model)
                .filter(
                    or_(
                        self.model.source_asset_id == asset_id,
                        self.model.target_asset_id == asset_id,
                    )
                )
                .all()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error fetching relationships for asset {asset_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def find_existing(
        self, db: Session, *, source_asset_id: UUID, target_asset_id: UUID, relationship_type: str
    ) -> Optional[AssetRelationshipDb]:
        """Checks if a relationship already exists."""
        try:
            return (
                db.query(self.model)
                .filter(
                    self.model.source_asset_id == source_asset_id,
                    self.model.target_asset_id == target_asset_id,
                    self.model.relationship_type == relationship_type,
                )
                .first()
            )
        except SQLAlchemyError as e:
            logger.error(f"Database error checking existing relationship: {e}", exc_info=True)
            db.rollback()
            raise


# Singleton instances
asset_type_repo = AssetTypeRepository()
asset_repo = AssetRepository()
asset_relationship_repo = AssetRelationshipRepository()
