"""
Master Data Management (MDM) Manager

Business logic for MDM operations including:
- Configuration management
- Source contract linking
- Match detection orchestration
- Review integration
- Merge processing
"""

from typing import List, Optional, Dict, Any
from uuid import uuid4
from datetime import datetime
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.db_models.mdm import (
    MdmConfigDb,
    MdmSourceLinkDb,
    MdmMatchRunDb,
    MdmMatchCandidateDb,
)
from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
from src.repositories.mdm_repository import (
    mdm_config_repo,
    mdm_source_link_repo,
    mdm_match_run_repo,
    mdm_match_candidate_repo,
)
from src.models.mdm import (
    MdmConfigCreate,
    MdmConfigUpdate,
    MdmConfigApi,
    MdmSourceLinkCreate,
    MdmSourceLinkUpdate,
    MdmSourceLinkApi,
    MdmMatchRunApi,
    MdmMatchCandidateApi,
    MdmMatchCandidateUpdate,
    MdmCreateReviewResponse,
    MdmMergeResponse,
    MdmConfigStatus,
    MdmSourceLinkStatus,
    MdmMatchRunStatus,
    MdmMatchCandidateStatus,
    MdmMatchType,
)
from src.models.data_asset_reviews import ReviewedAssetStatus
logger = get_logger(__name__)


class MdmManager:
    """Manager for Master Data Management operations"""

    def __init__(
        self,
        db: Session,
        reviews_manager=None,
        jobs_manager=None,
        notifications_manager=None,
        contracts_manager=None,
    ):
        self._db = db
        self._reviews_manager = reviews_manager
        self._jobs_manager = jobs_manager
        self._notifications_manager = notifications_manager
        self._contracts_manager = contracts_manager

    # ==================== Configuration Management ====================

    def list_configs(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        skip: int = 0,
        limit: Optional[int] = None
    ) -> List[MdmConfigApi]:
        """List all MDM configurations"""
        configs = mdm_config_repo.list(
            db=self._db,
            project_id=project_id,
            status=status,
            skip=skip,
            limit=limit
        )
        return [self._config_to_api(config) for config in configs]

    def get_config(self, config_id: str) -> Optional[MdmConfigApi]:
        """Get an MDM configuration by ID"""
        config = mdm_config_repo.get(db=self._db, config_id=config_id)
        if config:
            return self._config_to_api(config)
        return None

    def create_config(self, data: MdmConfigCreate, created_by: Optional[str] = None) -> MdmConfigApi:
        """Create a new MDM configuration"""
        # Verify master contract exists
        master = self._db.query(DataContractDb).filter_by(id=data.master_contract_id).first()
        if not master:
            raise ValueError(f"Master contract {data.master_contract_id} not found")

        # Check if config already exists for this master contract
        existing = mdm_config_repo.get_by_master_contract(db=self._db, master_contract_id=data.master_contract_id)
        if existing:
            raise ValueError(f"MDM configuration already exists for contract {data.master_contract_id}")

        config = MdmConfigDb(
            id=str(uuid4()),
            master_contract_id=data.master_contract_id,
            name=data.name,
            description=data.description,
            entity_type=data.entity_type.value,
            status=MdmConfigStatus.ACTIVE.value,
            matching_rules=[r.model_dump() for r in data.matching_rules] if data.matching_rules else [],
            survivorship_rules=[r.model_dump() for r in data.survivorship_rules] if data.survivorship_rules else [],
            project_id=data.project_id,
            created_by=created_by,
        )

        created = mdm_config_repo.create(db=self._db, config=config)
        logger.info(f"Created MDM config {created.id} for master contract {data.master_contract_id}")
        return self._config_to_api(created)

    def update_config(self, config_id: str, data: MdmConfigUpdate, updated_by: Optional[str] = None) -> Optional[MdmConfigApi]:
        """Update an MDM configuration"""
        config = mdm_config_repo.get(db=self._db, config_id=config_id)
        if not config:
            return None

        update_data = data.model_dump(exclude_unset=True)
        if 'status' in update_data and update_data['status']:
            update_data['status'] = update_data['status'].value
        if 'matching_rules' in update_data and update_data['matching_rules']:
            update_data['matching_rules'] = [r.model_dump() if hasattr(r, 'model_dump') else r for r in update_data['matching_rules']]
        if 'survivorship_rules' in update_data and update_data['survivorship_rules']:
            update_data['survivorship_rules'] = [r.model_dump() if hasattr(r, 'model_dump') else r for r in update_data['survivorship_rules']]
        
        update_data['updated_by'] = updated_by

        updated = mdm_config_repo.update(db=self._db, config=config, update_data=update_data)
        return self._config_to_api(updated)

    def delete_config(self, config_id: str) -> bool:
        """Delete an MDM configuration"""
        return mdm_config_repo.delete(db=self._db, config_id=config_id)

    # ==================== Source Link Management ====================

    def list_source_links(self, config_id: str) -> List[MdmSourceLinkApi]:
        """List source links for a configuration"""
        links = mdm_source_link_repo.get_by_config(db=self._db, config_id=config_id)
        return [self._source_link_to_api(link) for link in links]

    def get_source_link(self, link_id: str) -> Optional[MdmSourceLinkApi]:
        """Get a source link by ID"""
        link = mdm_source_link_repo.get(db=self._db, link_id=link_id)
        if link:
            return self._source_link_to_api(link)
        return None

    def create_source_link(self, config_id: str, data: MdmSourceLinkCreate) -> MdmSourceLinkApi:
        """Link a source contract to an MDM configuration"""
        # Verify config exists
        config = mdm_config_repo.get(db=self._db, config_id=config_id)
        if not config:
            raise ValueError(f"MDM config {config_id} not found")

        # Verify source contract exists
        source = self._db.query(DataContractDb).filter_by(id=data.source_contract_id).first()
        if not source:
            raise ValueError(f"Source contract {data.source_contract_id} not found")

        # Check if link already exists
        existing = mdm_source_link_repo.get_by_config(db=self._db, config_id=config_id)
        if any(l.source_contract_id == data.source_contract_id for l in existing):
            raise ValueError(f"Source contract {data.source_contract_id} is already linked to this config")

        link = MdmSourceLinkDb(
            id=str(uuid4()),
            config_id=config_id,
            source_contract_id=data.source_contract_id,
            key_column=data.key_column,
            column_mapping=data.column_mapping or {},
            priority=data.priority,
            status=MdmSourceLinkStatus.ACTIVE.value,
        )

        created = mdm_source_link_repo.create(db=self._db, link=link)
        logger.info(f"Linked source contract {data.source_contract_id} to MDM config {config_id}")
        return self._source_link_to_api(created)

    def update_source_link(self, link_id: str, data: MdmSourceLinkUpdate) -> Optional[MdmSourceLinkApi]:
        """Update a source link"""
        link = mdm_source_link_repo.get(db=self._db, link_id=link_id)
        if not link:
            return None

        update_data = data.model_dump(exclude_unset=True)
        if 'status' in update_data and update_data['status']:
            update_data['status'] = update_data['status'].value

        updated = mdm_source_link_repo.update(db=self._db, link=link, update_data=update_data)
        return self._source_link_to_api(updated)

    def delete_source_link(self, link_id: str) -> bool:
        """Delete a source link"""
        return mdm_source_link_repo.delete(db=self._db, link_id=link_id)

    # ==================== Match Run Management ====================

    def list_match_runs(self, config_id: str, skip: int = 0, limit: int = 50) -> List[MdmMatchRunApi]:
        """List match runs for a configuration"""
        runs = mdm_match_run_repo.get_by_config(db=self._db, config_id=config_id, skip=skip, limit=limit)
        return [self._match_run_to_api(run) for run in runs]

    def get_match_run(self, run_id: str) -> Optional[MdmMatchRunApi]:
        """Get a match run by ID"""
        run = mdm_match_run_repo.get(db=self._db, run_id=run_id)
        if run:
            return self._match_run_to_api(run)
        return None

    def start_match_run(
        self,
        config_id: str,
        source_link_id: Optional[str] = None,
        triggered_by: str = "manual"
    ) -> MdmMatchRunApi:
        """Start an MDM matching job"""
        config = mdm_config_repo.get(db=self._db, config_id=config_id)
        if not config:
            raise ValueError(f"MDM config {config_id} not found")

        if config.status != MdmConfigStatus.ACTIVE.value:
            raise ValueError(f"MDM config {config_id} is not active")

        # Check if jobs manager is available
        if not self._jobs_manager:
            raise ValueError(
                "MDM Match Detection workflow is not available. "
                "An administrator needs to configure the Jobs Manager in Settings."
            )

        # Check if the MDM workflow is installed
        from src.repositories.workflow_installations_repository import workflow_installation_repo
        installation = workflow_installation_repo.get_by_workflow_id(
            db=self._db,
            workflow_id="mdm_match_detect"
        )

        if not installation:
            raise ValueError(
                "MDM Match Detection workflow is not installed. "
                "An administrator needs to deploy the 'mdm_match_detect' workflow in Settings → Workflows."
            )

        # Create match run record
        run = MdmMatchRunDb(
            id=str(uuid4()),
            config_id=config_id,
            source_link_id=source_link_id,
            status=MdmMatchRunStatus.PENDING.value,
            started_at=datetime.utcnow(),
            triggered_by=triggered_by,
        )
        created_run = mdm_match_run_repo.create(db=self._db, run=run)

        try:
            job_params = {
                "run_id": created_run.id,
                "config_id": config_id,
                "source_link_id": source_link_id or "",
            }

            databricks_run_id = self._jobs_manager.run_job(
                job_id=int(installation.job_id),
                job_name="mdm_match_detect",
                workflow_id="mdm_match_detect",
                job_parameters=job_params
            )

            created_run.databricks_run_id = str(databricks_run_id)
            created_run.status = MdmMatchRunStatus.RUNNING.value
            self._db.commit()
            self._db.refresh(created_run)

            logger.info(f"Started MDM match run {created_run.id} with Databricks run {databricks_run_id}")

        except Exception as e:
            # Mark run as failed
            created_run.status = MdmMatchRunStatus.FAILED.value
            created_run.error_message = str(e)
            self._db.commit()
            logger.error(f"Failed to start MDM match run: {e}")
            raise ValueError(
                f"Failed to start Databricks job: {str(e)}. "
                "Please check that the workflow is properly deployed and the Databricks connection is configured."
            )

        return self._match_run_to_api(created_run)

    # ==================== Match Candidate Management ====================

    def list_match_candidates(
        self,
        run_id: str,
        status: Optional[str] = None,
        skip: int = 0,
        limit: Optional[int] = None
    ) -> List[MdmMatchCandidateApi]:
        """List match candidates for a run"""
        candidates = mdm_match_candidate_repo.get_by_run(
            db=self._db,
            run_id=run_id,
            status=status,
            skip=skip,
            limit=limit
        )
        return [self._match_candidate_to_api(c) for c in candidates]

    def get_match_candidate(self, candidate_id: str) -> Optional[MdmMatchCandidateApi]:
        """Get a match candidate by ID"""
        candidate = mdm_match_candidate_repo.get(db=self._db, candidate_id=candidate_id)
        if candidate:
            return self._match_candidate_to_api(candidate)
        return None

    def update_match_candidate(
        self,
        candidate_id: str,
        data: MdmMatchCandidateUpdate,
        reviewed_by: Optional[str] = None
    ) -> Optional[MdmMatchCandidateApi]:
        """Update a match candidate (approve/reject)"""
        candidate = mdm_match_candidate_repo.get(db=self._db, candidate_id=candidate_id)
        if not candidate:
            return None

        updated = mdm_match_candidate_repo.update_status(
            db=self._db,
            candidate_id=candidate_id,
            status=data.status.value,
            merged_record_data=data.merged_record_data,
            reviewed_by=reviewed_by
        )

        if updated:
            # Sync linked ReviewedAsset status if linked to a review
            if updated.reviewed_asset_id and self._reviews_manager:
                new_asset_status = None
                if data.status.value == 'approved':
                    new_asset_status = ReviewedAssetStatus.APPROVED
                elif data.status.value == 'rejected':
                    new_asset_status = ReviewedAssetStatus.REJECTED
                
                if new_asset_status:
                    try:
                        self._reviews_manager.update_asset_status_by_id(
                            updated.reviewed_asset_id,
                            new_asset_status,
                            db=self._db
                        )
                        logger.debug(f"Synced ReviewedAsset {updated.reviewed_asset_id} status to {new_asset_status.value}")
                    except Exception as e:
                        logger.warning(f"Failed to sync ReviewedAsset status for {updated.reviewed_asset_id}: {e}")
            
            return self._match_candidate_to_api(updated)
        return None

    # ==================== Review Integration ====================

    def create_review_for_matches(
        self,
        run_id: str,
        reviewer_email: str,
        requester_email: str,
        notes: Optional[str] = None
    ) -> MdmCreateReviewResponse:
        """Create an Asset Review request for match candidates"""
        run = mdm_match_run_repo.get(db=self._db, run_id=run_id)
        if not run:
            raise ValueError(f"Match run {run_id} not found")

        candidates = mdm_match_candidate_repo.get_pending_by_run(db=self._db, run_id=run_id)
        if not candidates:
            raise ValueError("No pending match candidates to review")

        if not self._reviews_manager:
            raise ValueError("Reviews manager not configured")

        # Build asset FQNs for review
        # Format: mdm://config_id/run_id/candidate_id
        asset_fqns = [
            f"mdm://{run.config_id}/{run_id}/{c.id}"
            for c in candidates
        ]

        # Create review request
        from src.models.data_asset_reviews import DataAssetReviewRequestCreate

        review_data = DataAssetReviewRequestCreate(
            requester_email=requester_email,
            reviewer_email=reviewer_email,
            asset_fqns=asset_fqns,
            notes=notes or f"MDM match review for run {run_id}. {len(candidates)} candidates to review."
        )

        # The reviews manager will detect MDM FQNs (mdm://) and set the correct asset type
        # Pass our db session to ensure the review is committed in the same transaction
        review = self._reviews_manager.create_review_request(
            request_data=review_data,
            db=self._db
        )

        # Link candidates to review assets
        for i, candidate in enumerate(candidates):
            if i < len(review.assets):
                mdm_match_candidate_repo.link_to_review(
                    db=self._db,
                    candidate_id=candidate.id,
                    review_request_id=review.id,
                    reviewed_asset_id=review.assets[i].id
                )

        logger.info(f"Created review request {review.id} for {len(candidates)} MDM candidates")

        return MdmCreateReviewResponse(
            review_id=review.id,
            candidate_count=len(candidates),
            message=f"Created review request with {len(candidates)} match candidates"
        )

    def sync_review_asset_statuses(self, run_id: str) -> Dict[str, int]:
        """Sync ReviewedAsset statuses with MDM candidate statuses for a run.
        
        This is useful to fix out-of-sync data from before the auto-sync was implemented.
        
        Returns:
            Dict with counts of synced approved, rejected, and skipped items
        """
        if not self._reviews_manager:
            raise ValueError("Reviews manager not available")
        
        run = mdm_match_run_repo.get(db=self._db, run_id=run_id)
        if not run:
            raise ValueError(f"Match run {run_id} not found")
        
        # Get all candidates with linked review assets
        all_candidates = mdm_match_candidate_repo.get_by_run(db=self._db, run_id=run_id)
        
        synced_approved = 0
        synced_rejected = 0
        skipped = 0
        
        for candidate in all_candidates:
            if not candidate.reviewed_asset_id:
                skipped += 1
                continue
            
            new_status = None
            if candidate.status == 'approved':
                new_status = ReviewedAssetStatus.APPROVED
            elif candidate.status == 'rejected':
                new_status = ReviewedAssetStatus.REJECTED
            else:
                skipped += 1
                continue
            
            try:
                success = self._reviews_manager.update_asset_status_by_id(
                    candidate.reviewed_asset_id,
                    new_status,
                    db=self._db
                )
                if success:
                    if candidate.status == 'approved':
                        synced_approved += 1
                    else:
                        synced_rejected += 1
                    logger.debug(f"Synced asset {candidate.reviewed_asset_id} to {new_status.value}")
                else:
                    skipped += 1
            except Exception as e:
                logger.warning(f"Failed to sync asset {candidate.reviewed_asset_id}: {e}")
                skipped += 1
        
        logger.info(f"Sync complete for run {run_id}: {synced_approved} approved, {synced_rejected} rejected, {skipped} skipped")
        return {
            "synced_approved": synced_approved,
            "synced_rejected": synced_rejected,
            "skipped": skipped
        }

    # ==================== Merge Operations ====================

    def process_approved_matches(self, run_id: str, dry_run: bool = False) -> MdmMergeResponse:
        """Process and merge all approved matches"""
        run = mdm_match_run_repo.get(db=self._db, run_id=run_id)
        if not run:
            raise ValueError(f"Match run {run_id} not found")

        config = mdm_config_repo.get(db=self._db, config_id=run.config_id)
        if not config:
            raise ValueError(f"MDM config {run.config_id} not found")

        approved = mdm_match_candidate_repo.get_approved_by_run(db=self._db, run_id=run_id)

        if not approved:
            return MdmMergeResponse(
                run_id=run_id,
                approved_count=0,
                merged_count=0,
                message="No approved matches to merge"
            )

        merged_count = 0
        failed_count = 0

        for candidate in approved:
            try:
                # Apply survivorship rules to create merged record
                if candidate.merged_record_data:
                    # User already provided merged data
                    merged_data = candidate.merged_record_data
                else:
                    # Apply survivorship rules
                    merged_data = self._apply_survivorship(
                        master_data=candidate.master_record_data,
                        source_data=candidate.source_record_data,
                        rules=config.survivorship_rules or []
                    )
                    candidate.merged_record_data = merged_data

                if not dry_run:
                    candidate.status = MdmMatchCandidateStatus.MERGED.value
                    candidate.merged_at = datetime.utcnow()
                    # TODO: Actually write to master table via Spark

                merged_count += 1
                logger.debug(f"Merged candidate {candidate.id}")

            except Exception as e:
                logger.error(f"Failed to merge candidate {candidate.id}: {e}")
                failed_count += 1

        if not dry_run:
            self._db.commit()

        message = f"Merged {merged_count} records"
        if dry_run:
            message = f"[DRY RUN] Would merge {merged_count} records"
        if failed_count > 0:
            message += f", {failed_count} failed"

        return MdmMergeResponse(
            run_id=run_id,
            approved_count=len(approved),
            merged_count=merged_count,
            failed_count=failed_count,
            message=message
        )

    def _apply_survivorship(
        self,
        master_data: Optional[Dict],
        source_data: Dict,
        rules: List[Dict]
    ) -> Dict:
        """Apply survivorship rules to determine final field values"""
        if not master_data:
            return source_data.copy() if source_data else {}

        merged = {}
        all_fields = set(master_data.keys()) | set(source_data.keys())

        for field in all_fields:
            master_val = master_data.get(field)
            source_val = source_data.get(field)

            # Find rule for this field
            rule = next((r for r in rules if r.get('field') == field), None)
            strategy = rule.get('strategy', 'source_wins') if rule else 'source_wins'

            if strategy == 'most_recent':
                merged[field] = source_val if source_val else master_val
            elif strategy == 'most_complete':
                # Prefer longer/non-null value
                if source_val and (not master_val or len(str(source_val)) > len(str(master_val))):
                    merged[field] = source_val
                else:
                    merged[field] = master_val
            elif strategy == 'master_wins':
                merged[field] = master_val if master_val else source_val
            else:  # source_wins (default)
                merged[field] = source_val if source_val else master_val

        return merged

    # ==================== Helper Methods ====================

    def _config_to_api(self, config: MdmConfigDb) -> MdmConfigApi:
        """Convert DB model to API model"""
        # Get master contract name
        master_name = None
        if config.master_contract:
            master_name = config.master_contract.name

        # Get source count
        source_count = len(config.source_links) if config.source_links else 0

        # Get last run info
        last_run = mdm_match_run_repo.get_latest_by_config(db=self._db, config_id=config.id)
        last_run_at = last_run.started_at if last_run else None
        last_run_status = last_run.status if last_run else None

        return MdmConfigApi(
            id=config.id,
            name=config.name,
            description=config.description,
            entity_type=config.entity_type,
            master_contract_id=config.master_contract_id,
            master_contract_name=master_name,
            status=MdmConfigStatus(config.status),
            project_id=config.project_id,
            matching_rules=config.matching_rules or [],
            survivorship_rules=config.survivorship_rules or [],
            source_count=source_count,
            last_run_at=last_run_at,
            last_run_status=last_run_status,
            created_at=config.created_at,
            updated_at=config.updated_at,
            created_by=config.created_by,
        )

    def _source_link_to_api(self, link: MdmSourceLinkDb) -> MdmSourceLinkApi:
        """Convert DB model to API model"""
        source_name = None
        source_table_fqn = None
        
        if link.source_contract:
            source_name = link.source_contract.name
            # Try to get table FQN from contract schema
            schema_obj = self._db.query(SchemaObjectDb).filter_by(
                contract_id=link.source_contract_id
            ).first()
            if schema_obj and schema_obj.physical_name:
                source_table_fqn = schema_obj.physical_name

        return MdmSourceLinkApi(
            id=link.id,
            config_id=link.config_id,
            source_contract_id=link.source_contract_id,
            source_contract_name=source_name,
            source_table_fqn=source_table_fqn,
            key_column=link.key_column,
            column_mapping=link.column_mapping or {},
            priority=link.priority,
            status=MdmSourceLinkStatus(link.status),
            last_sync_at=link.last_sync_at,
            created_at=link.created_at,
            updated_at=link.updated_at,
        )

    def _match_run_to_api(self, run: MdmMatchRunDb) -> MdmMatchRunApi:
        """Convert DB model to API model"""
        # Get pending review count
        pending_count = mdm_match_candidate_repo.count_by_run_and_status(
            db=self._db,
            run_id=run.id,
            status=MdmMatchCandidateStatus.PENDING.value
        )
        
        # Get approved count (approved but not yet merged)
        approved_count = mdm_match_candidate_repo.count_by_run_and_status(
            db=self._db,
            run_id=run.id,
            status=MdmMatchCandidateStatus.APPROVED.value
        )

        return MdmMatchRunApi(
            id=run.id,
            config_id=run.config_id,
            source_link_id=run.source_link_id,
            status=MdmMatchRunStatus(run.status),
            databricks_run_id=run.databricks_run_id,
            total_source_records=run.total_source_records,
            total_master_records=run.total_master_records,
            matches_found=run.matches_found,
            new_records=run.new_records,
            started_at=run.started_at,
            completed_at=run.completed_at,
            error_message=run.error_message,
            triggered_by=run.triggered_by,
            pending_review_count=pending_count,
            approved_count=approved_count,
        )

    def _match_candidate_to_api(self, candidate: MdmMatchCandidateDb) -> MdmMatchCandidateApi:
        """Convert DB model to API model"""
        return MdmMatchCandidateApi(
            id=candidate.id,
            run_id=candidate.run_id,
            master_record_id=candidate.master_record_id,
            source_record_id=candidate.source_record_id,
            source_contract_id=candidate.source_contract_id,
            confidence_score=candidate.confidence_score,
            match_type=MdmMatchType(candidate.match_type),
            matched_fields=candidate.matched_fields,
            status=MdmMatchCandidateStatus(candidate.status),
            master_record_data=candidate.master_record_data,
            source_record_data=candidate.source_record_data,
            merged_record_data=candidate.merged_record_data,
            review_request_id=candidate.review_request_id,
            reviewed_at=candidate.reviewed_at,
            reviewed_by=candidate.reviewed_by,
            merged_at=candidate.merged_at,
        )

