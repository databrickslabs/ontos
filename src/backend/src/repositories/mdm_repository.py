"""
Master Data Management (MDM) Repository

Database operations for MDM entities.
"""

from typing import List, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import desc

from src.db_models.mdm import (
    MdmConfigDb,
    MdmSourceLinkDb,
    MdmMatchRunDb,
    MdmMatchCandidateDb,
)
from src.common.logging import get_logger

logger = get_logger(__name__)


class MdmConfigRepository:
    """Repository for MDM Configuration operations"""

    def create(self, db: Session, config: MdmConfigDb) -> MdmConfigDb:
        """Create a new MDM configuration"""
        db.add(config)
        db.commit()
        db.refresh(config)
        return config

    def get(self, db: Session, config_id: str) -> Optional[MdmConfigDb]:
        """Get an MDM configuration by ID"""
        return db.query(MdmConfigDb).filter(MdmConfigDb.id == config_id).first()

    def get_by_master_contract(self, db: Session, master_contract_id: str) -> Optional[MdmConfigDb]:
        """Get MDM configuration by master contract ID"""
        return db.query(MdmConfigDb).filter(
            MdmConfigDb.master_contract_id == master_contract_id
        ).first()

    def list(
        self,
        db: Session,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: Optional[int] = None
    ) -> List[MdmConfigDb]:
        """List MDM configurations with optional filters"""
        query = db.query(MdmConfigDb)
        
        if project_id:
            query = query.filter(MdmConfigDb.project_id == project_id)
        if status:
            query = query.filter(MdmConfigDb.status == status)
        
        return query.order_by(desc(MdmConfigDb.created_at)).offset(skip).limit(limit).all()

    def update(self, db: Session, config: MdmConfigDb, update_data: dict) -> MdmConfigDb:
        """Update an MDM configuration"""
        for key, value in update_data.items():
            if value is not None and hasattr(config, key):
                setattr(config, key, value)
        db.commit()
        db.refresh(config)
        return config

    def delete(self, db: Session, config_id: str) -> bool:
        """Delete an MDM configuration"""
        config = self.get(db, config_id)
        if config:
            db.delete(config)
            db.commit()
            return True
        return False


class MdmSourceLinkRepository:
    """Repository for MDM Source Link operations"""

    def create(self, db: Session, link: MdmSourceLinkDb) -> MdmSourceLinkDb:
        """Create a new source link"""
        db.add(link)
        db.commit()
        db.refresh(link)
        return link

    def get(self, db: Session, link_id: str) -> Optional[MdmSourceLinkDb]:
        """Get a source link by ID"""
        return db.query(MdmSourceLinkDb).filter(MdmSourceLinkDb.id == link_id).first()

    def get_by_config(self, db: Session, config_id: str, status: Optional[str] = None) -> List[MdmSourceLinkDb]:
        """Get all source links for a configuration"""
        query = db.query(MdmSourceLinkDb).filter(MdmSourceLinkDb.config_id == config_id)
        if status:
            query = query.filter(MdmSourceLinkDb.status == status)
        return query.order_by(desc(MdmSourceLinkDb.priority)).all()

    def get_by_source_contract(self, db: Session, source_contract_id: str) -> List[MdmSourceLinkDb]:
        """Get all source links for a source contract"""
        return db.query(MdmSourceLinkDb).filter(
            MdmSourceLinkDb.source_contract_id == source_contract_id
        ).all()

    def update(self, db: Session, link: MdmSourceLinkDb, update_data: dict) -> MdmSourceLinkDb:
        """Update a source link"""
        for key, value in update_data.items():
            if value is not None and hasattr(link, key):
                setattr(link, key, value)
        db.commit()
        db.refresh(link)
        return link

    def delete(self, db: Session, link_id: str) -> bool:
        """Delete a source link"""
        link = self.get(db, link_id)
        if link:
            db.delete(link)
            db.commit()
            return True
        return False


class MdmMatchRunRepository:
    """Repository for MDM Match Run operations"""

    def create(self, db: Session, run: MdmMatchRunDb) -> MdmMatchRunDb:
        """Create a new match run"""
        db.add(run)
        db.commit()
        db.refresh(run)
        return run

    def get(self, db: Session, run_id: str) -> Optional[MdmMatchRunDb]:
        """Get a match run by ID"""
        return db.query(MdmMatchRunDb).filter(MdmMatchRunDb.id == run_id).first()

    def get_by_config(
        self,
        db: Session,
        config_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: int = 50
    ) -> List[MdmMatchRunDb]:
        """Get match runs for a configuration"""
        query = db.query(MdmMatchRunDb).filter(MdmMatchRunDb.config_id == config_id)
        if status:
            query = query.filter(MdmMatchRunDb.status == status)
        return query.order_by(desc(MdmMatchRunDb.started_at)).offset(skip).limit(limit).all()

    def get_latest_by_config(self, db: Session, config_id: str) -> Optional[MdmMatchRunDb]:
        """Get the latest match run for a configuration"""
        return db.query(MdmMatchRunDb).filter(
            MdmMatchRunDb.config_id == config_id
        ).order_by(desc(MdmMatchRunDb.started_at)).first()

    def update(self, db: Session, run: MdmMatchRunDb, update_data: dict) -> MdmMatchRunDb:
        """Update a match run"""
        for key, value in update_data.items():
            if value is not None and hasattr(run, key):
                setattr(run, key, value)
        db.commit()
        db.refresh(run)
        return run

    def update_status(
        self,
        db: Session,
        run_id: str,
        status: str,
        error_message: Optional[str] = None
    ) -> Optional[MdmMatchRunDb]:
        """Update run status"""
        run = self.get(db, run_id)
        if run:
            run.status = status
            if status == 'completed' or status == 'failed':
                run.completed_at = datetime.utcnow()
            if error_message:
                run.error_message = error_message
            db.commit()
            db.refresh(run)
        return run


class MdmMatchCandidateRepository:
    """Repository for MDM Match Candidate operations"""

    def create(self, db: Session, candidate: MdmMatchCandidateDb) -> MdmMatchCandidateDb:
        """Create a new match candidate"""
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
        return candidate

    def bulk_create(self, db: Session, candidates: List[MdmMatchCandidateDb]) -> List[MdmMatchCandidateDb]:
        """Bulk create match candidates"""
        db.add_all(candidates)
        db.commit()
        for c in candidates:
            db.refresh(c)
        return candidates

    def get(self, db: Session, candidate_id: str) -> Optional[MdmMatchCandidateDb]:
        """Get a match candidate by ID"""
        return db.query(MdmMatchCandidateDb).filter(MdmMatchCandidateDb.id == candidate_id).first()

    def get_by_run(
        self,
        db: Session,
        run_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: Optional[int] = None
    ) -> List[MdmMatchCandidateDb]:
        """Get match candidates for a run"""
        query = db.query(MdmMatchCandidateDb).filter(MdmMatchCandidateDb.run_id == run_id)
        if status:
            query = query.filter(MdmMatchCandidateDb.status == status)
        return query.order_by(desc(MdmMatchCandidateDb.confidence_score)).offset(skip).limit(limit).all()

    def get_pending_by_run(self, db: Session, run_id: str) -> List[MdmMatchCandidateDb]:
        """Get all pending candidates for a run"""
        return db.query(MdmMatchCandidateDb).filter(
            MdmMatchCandidateDb.run_id == run_id,
            MdmMatchCandidateDb.status == 'pending'
        ).order_by(desc(MdmMatchCandidateDb.confidence_score)).all()

    def get_approved_by_run(self, db: Session, run_id: str) -> List[MdmMatchCandidateDb]:
        """Get all approved candidates for a run"""
        return db.query(MdmMatchCandidateDb).filter(
            MdmMatchCandidateDb.run_id == run_id,
            MdmMatchCandidateDb.status == 'approved'
        ).all()

    def count_by_run_and_status(self, db: Session, run_id: str, status: str) -> int:
        """Count candidates by run and status"""
        return db.query(MdmMatchCandidateDb).filter(
            MdmMatchCandidateDb.run_id == run_id,
            MdmMatchCandidateDb.status == status
        ).count()

    def update(self, db: Session, candidate: MdmMatchCandidateDb, update_data: dict) -> MdmMatchCandidateDb:
        """Update a match candidate"""
        for key, value in update_data.items():
            if value is not None and hasattr(candidate, key):
                setattr(candidate, key, value)
        db.commit()
        db.refresh(candidate)
        return candidate

    def update_status(
        self,
        db: Session,
        candidate_id: str,
        status: str,
        merged_record_data: Optional[dict] = None,
        reviewed_by: Optional[str] = None
    ) -> Optional[MdmMatchCandidateDb]:
        """Update candidate status"""
        candidate = self.get(db, candidate_id)
        if candidate:
            candidate.status = status
            if status in ('approved', 'rejected'):
                candidate.reviewed_at = datetime.utcnow()
                if reviewed_by:
                    candidate.reviewed_by = reviewed_by
            if status == 'merged':
                candidate.merged_at = datetime.utcnow()
            if merged_record_data:
                candidate.merged_record_data = merged_record_data
            db.commit()
            db.refresh(candidate)
        return candidate

    def link_to_review(
        self,
        db: Session,
        candidate_id: str,
        review_request_id: str,
        reviewed_asset_id: str
    ) -> Optional[MdmMatchCandidateDb]:
        """Link candidate to an asset review"""
        candidate = self.get(db, candidate_id)
        if candidate:
            candidate.review_request_id = review_request_id
            candidate.reviewed_asset_id = reviewed_asset_id
            db.commit()
            db.refresh(candidate)
        return candidate


# Singleton instances
mdm_config_repo = MdmConfigRepository()
mdm_source_link_repo = MdmSourceLinkRepository()
mdm_match_run_repo = MdmMatchRunRepository()
mdm_match_candidate_repo = MdmMatchCandidateRepository()

