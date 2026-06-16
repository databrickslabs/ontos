from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from typing import List, Optional, Any, Dict, Union

from src.common.repository import CRUDBase
from src.models.data_asset_reviews import (DataAssetReviewRequest as DataAssetReviewRequestApi,
                                           DataAssetReviewRequestCreate,
                                           ReviewedAsset as ReviewedAssetApi,
                                           AssetType, ReviewedAssetStatus)
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb
from src.common.logging import get_logger

logger = get_logger(__name__)

# Define specific create/update types (can reuse API models if simple)
DataAssetReviewRequestDBCreate = DataAssetReviewRequestApi # Using full model for now
DataAssetReviewRequestDBUpdate = DataAssetReviewRequestApi # Using full model for now

class DataAssetReviewRepository(CRUDBase[DataAssetReviewRequestDb, DataAssetReviewRequestDBCreate, DataAssetReviewRequestDBUpdate]):
    """Repository for Data Asset Review Request CRUD operations."""

    def create_with_assets(self, db: Session, *, obj_in: DataAssetReviewRequestDBCreate) -> DataAssetReviewRequestDb:
        """Creates a review request along with its associated assets."""
        logger.debug(f"Creating DataAssetReviewRequest (DB layer) for reviewer: {obj_in.reviewer_email}")

        # 1. Prepare core Review Request data (excluding assets initially)
        db_obj_data = {
            "id": obj_in.id,
            "requester_email": obj_in.requester_email,
            "reviewer_email": obj_in.reviewer_email,
            "title": obj_in.title,
            "status": obj_in.status.value,
            "notes": obj_in.notes,
            # created_at/updated_at handled by DB defaults
        }
        db_obj = self.model(**db_obj_data)

        # 2. Create ReviewedAssetDb objects
        for asset_in in obj_in.assets:
            asset_data = {
                "id": asset_in.id,
                "review_request_id": db_obj.id, # Link back to the parent request
                "asset_fqn": asset_in.asset_fqn,
                "asset_type": asset_in.asset_type.value,
                "status": asset_in.status.value,
                "comments": asset_in.comments
                # updated_at handled by DB default/onupdate
            }
            asset_db = ReviewedAssetDb(**asset_data)
            db_obj.assets.append(asset_db) # Append relationship

        try:
            db.add(db_obj)
            db.flush() # Flush to ensure relationships are handled before commit
            db.refresh(db_obj)
            logger.info(f"Successfully created DataAssetReviewRequest (DB) with id: {db_obj.id}")
            return db_obj
        except Exception as e:
            logger.error(f"Database error creating DataAssetReviewRequest: {e}", exc_info=True)
            db.rollback()
            raise

    # Override get/get_multi to eagerly load assets
    def get(self, db: Session, id: Any) -> Optional[DataAssetReviewRequestDb]:
        logger.debug(f"Fetching DataAssetReviewRequest (DB) with id: {id}")
        try:
            return db.query(self.model).options(
                selectinload(self.model.assets)
            ).filter(self.model.id == id).first()
        except Exception as e:
            logger.error(f"Database error fetching DataAssetReviewRequest by id {id}: {e}", exc_info=True)
            db.rollback()
            raise

    def get_multi(
        self, db: Session, *, skip: int = 0, limit: int = 100
    ) -> List[DataAssetReviewRequestDb]:
        logger.debug(f"Fetching multiple DataAssetReviews (DB) with skip: {skip}, limit: {limit}")
        try:
            return db.query(self.model).options(
                 selectinload(self.model.assets)
            ).order_by(self.model.created_at.desc()).offset(skip).limit(limit).all()
        except Exception as e:
            logger.error(f"Database error fetching multiple DataAssetReviews: {e}", exc_info=True)
            db.rollback()
            raise

    def update_request_status(self, db: Session, *, db_obj: DataAssetReviewRequestDb, status: str, notes: Optional[str] = None) -> DataAssetReviewRequestDb:
        """Updates the status and optionally notes of a review request."""
        logger.debug(f"Updating status for DataAssetReviewRequest (DB) id: {db_obj.id} to {status}")
        db_obj.status = status
        if notes is not None:
            db_obj.notes = notes
        # updated_at is handled by onupdate trigger
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    def update_request_fields(
        self,
        db: Session,
        *,
        db_obj: DataAssetReviewRequestDb,
        title: Optional[str] = None,
        notes: Optional[str] = None,
        title_set: bool = False,
        notes_set: bool = False,
    ) -> DataAssetReviewRequestDb:
        """Updates editable scalar fields on a review request (title / notes).

        `*_set` flags distinguish "field not in payload" from "field explicitly cleared
        to null", since `None` alone cannot represent both.
        """
        logger.debug(f"Updating fields for DataAssetReviewRequest (DB) id: {db_obj.id}")
        if title_set:
            db_obj.title = title
        if notes_set:
            db_obj.notes = notes
        db.add(db_obj)
        db.flush()
        db.refresh(db_obj)
        return db_obj

    def get_asset(self, db: Session, *, request_id: str, asset_id: str) -> Optional[ReviewedAssetDb]:
        """Gets a specific asset within a review request."""
        logger.debug(f"Fetching ReviewedAsset (DB) id: {asset_id} for request id: {request_id}")
        try:
            return db.query(ReviewedAssetDb).filter(
                ReviewedAssetDb.id == asset_id,
                ReviewedAssetDb.review_request_id == request_id
            ).first()
        except Exception as e:
            logger.error(f"Database error fetching ReviewedAsset id {asset_id}: {e}", exc_info=True)
            db.rollback()
            raise

    def update_asset_status(self, db: Session, *, db_asset_obj: ReviewedAssetDb, status: str, comments: Optional[str] = None) -> ReviewedAssetDb:
        """Updates the status and optionally comments of a reviewed asset."""
        logger.debug(f"Updating status for ReviewedAsset (DB) id: {db_asset_obj.id} to {status}")
        db_asset_obj.status = status
        if comments is not None:
            db_asset_obj.comments = comments
        # updated_at is handled by onupdate trigger
        db.add(db_asset_obj)
        db.flush()
        db.refresh(db_asset_obj)
        return db_asset_obj

    def update_asset_status_by_id(self, db: Session, asset_id: str, status: ReviewedAssetStatus) -> bool:
        """Update the status of a reviewed asset by ID.
        
        Args:
            db: Database session
            asset_id: The reviewed asset ID
            status: The new status
            
        Returns:
            True if asset was found and updated, False otherwise
        """
        logger.debug(f"Updating status for ReviewedAsset (DB) id: {asset_id} to {status.value}")
        try:
            asset = db.query(ReviewedAssetDb).filter(ReviewedAssetDb.id == asset_id).first()
            if asset:
                asset.status = status.value
                # updated_at is handled by onupdate trigger
                db.flush()
                return True
            logger.warning(f"ReviewedAsset with id {asset_id} not found")
            return False
        except Exception as e:
            logger.error(f"Database error updating ReviewedAsset id {asset_id}: {e}", exc_info=True)
            db.rollback()
            raise


# Create a single instance of the repository
data_asset_review_repo = DataAssetReviewRepository(DataAssetReviewRequestDb) 