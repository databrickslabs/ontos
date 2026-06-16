from sqlalchemy import Column, String, DateTime, Text, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID # Use generic String for broader compatibility
import uuid
from datetime import datetime

from src.common.database import Base
# Import Enums from Pydantic models to ensure consistency
from src.models.data_asset_reviews import ReviewRequestStatus, ReviewedAssetStatus, AssetType

# --- Main Review Request Table ---
class DataAssetReviewRequestDb(Base):
    """Review request for data assets: requester, reviewer, status, optional project; used by Data Asset Review workflow."""
    __tablename__ = 'data_asset_review_requests'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    requester_email = Column(String, nullable=False, index=True)
    reviewer_email = Column(String, nullable=False, index=True)
    title = Column(String(200), nullable=True)
    status = Column(String, default=ReviewRequestStatus.QUEUED.value, nullable=False, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Project relationship (nullable for backward compatibility)
    project_id = Column(String, ForeignKey('projects.id'), nullable=True, index=True)

    # Relationship to Reviewed Assets (One-to-Many)
    assets = relationship("ReviewedAssetDb", back_populates="review_request", cascade="all, delete-orphan", lazy="selectin")

    def __repr__(self):
        return f"<DataAssetReviewRequestDb(id='{self.id}', status='{self.status}', reviewer='{self.reviewer_email}')>"

# --- Reviewed Asset Table ---
class ReviewedAssetDb(Base):
    """Single asset within a review request: asset FQN, type, status, optional comments; linked to DataAssetReviewRequestDb."""
    __tablename__ = 'reviewed_assets'

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    review_request_id = Column(String, ForeignKey('data_asset_review_requests.id'), nullable=False, index=True)
    asset_fqn = Column(String, nullable=False, index=True) # Fully qualified name
    asset_type = Column(String, nullable=False)
    status = Column(String, default=ReviewedAssetStatus.PENDING.value, nullable=False, index=True)
    comments = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationship back to the Review Request
    review_request = relationship("DataAssetReviewRequestDb", back_populates="assets")

    def __repr__(self):
        return f"<ReviewedAssetDb(id='{self.id}', asset_fqn='{self.asset_fqn}', status='{self.status}')>" 