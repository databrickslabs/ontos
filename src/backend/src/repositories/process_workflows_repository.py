"""
Repository for process workflows.

Provides CRUD operations for workflow definitions, steps, and executions.
"""

import json
from typing import Dict, List, Optional
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_

from src.db_models.process_workflows import (
    ProcessWorkflowDb,
    WorkflowStepDb,
    WorkflowExecutionDb,
    WorkflowStepExecutionDb,
)
from src.models.process_workflows import (
    ProcessWorkflowCreate,
    ProcessWorkflowUpdate,
    WorkflowStepCreate,
    WorkflowExecutionCreate,
    TriggerType,
    EntityType,
    WorkflowType,
)
from src.common.logging import get_logger

logger = get_logger(__name__)


class ProcessWorkflowRepository:
    """Repository for ProcessWorkflow operations."""

    def list_all(
        self,
        db: Session,
        *,
        is_active: Optional[bool] = None,
        workflow_type: Optional[WorkflowType] = None,
        include_steps: bool = True
    ) -> List[ProcessWorkflowDb]:
        """List all workflows, optionally filtered by active status and workflow_type."""
        query = db.query(ProcessWorkflowDb)
        
        if is_active is not None:
            query = query.filter(ProcessWorkflowDb.is_active == is_active)
        if workflow_type is not None:
            query = query.filter(ProcessWorkflowDb.workflow_type == workflow_type.value)
        
        if include_steps:
            query = query.options(joinedload(ProcessWorkflowDb.steps))
        
        return query.order_by(ProcessWorkflowDb.name).all()

    def get(self, db: Session, workflow_id: str) -> Optional[ProcessWorkflowDb]:
        """Get a workflow by ID with its steps."""
        return (
            db.query(ProcessWorkflowDb)
            .options(joinedload(ProcessWorkflowDb.steps))
            .filter(ProcessWorkflowDb.id == workflow_id)
            .first()
        )

    def get_by_name(self, db: Session, name: str) -> Optional[ProcessWorkflowDb]:
        """Get a workflow by name."""
        return (
            db.query(ProcessWorkflowDb)
            .options(joinedload(ProcessWorkflowDb.steps))
            .filter(ProcessWorkflowDb.name == name)
            .first()
        )

    def get_by_trigger_type(
        self,
        db: Session,
        trigger_type: str,
        *,
        entity_type: Optional[str] = None,
        active_only: bool = True,
    ) -> Optional[ProcessWorkflowDb]:
        """Get the first active workflow whose trigger.type matches.

        If *entity_type* is given, only workflows whose trigger.entity_types
        list includes the value (or is empty — meaning "all") are considered.
        Used for app-known UI actions (for_approval_response, for_subscribe,
        for_request_review, for_request_access, etc.).
        """
        query = (
            db.query(ProcessWorkflowDb)
            .options(joinedload(ProcessWorkflowDb.steps))
            .order_by(ProcessWorkflowDb.name)
        )
        if active_only:
            query = query.filter(ProcessWorkflowDb.is_active == True)
        workflows = query.all()
        for wf in workflows:
            try:
                trigger_config = json.loads(wf.trigger_config) if wf.trigger_config else {}
                if trigger_config.get('type') != trigger_type:
                    continue
                if entity_type:
                    et_list = trigger_config.get('entity_types', [])
                    if et_list and entity_type not in et_list:
                        continue
                return wf
            except (json.JSONDecodeError, TypeError):
                continue
        return None

    def get_for_trigger(
        self,
        db: Session,
        *,
        trigger_type: TriggerType,
        entity_type: EntityType,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> List[ProcessWorkflowDb]:
        """Get active workflows matching a trigger event."""
        workflows = (
            db.query(ProcessWorkflowDb)
            .options(joinedload(ProcessWorkflowDb.steps))
            .filter(ProcessWorkflowDb.is_active == True)
            .all()
        )
        
        matching = []
        for wf in workflows:
            try:
                trigger_config = json.loads(wf.trigger_config) if wf.trigger_config else {}
                
                # Check trigger type
                if trigger_config.get('type') != trigger_type.value:
                    continue
                
                # Check entity type
                entity_types = trigger_config.get('entity_types', [])
                if entity_types and entity_type.value not in entity_types:
                    continue
                
                # Check scope if provided
                if scope_type and scope_id:
                    scope_config = json.loads(wf.scope_config) if wf.scope_config else {}
                    wf_scope_type = scope_config.get('type', 'all')
                    
                    if wf_scope_type != 'all':
                        scope_ids = scope_config.get('ids', [])
                        if wf_scope_type != scope_type or scope_id not in scope_ids:
                            continue
                
                matching.append(wf)
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Invalid trigger config for workflow {wf.id}")
                continue
        
        return matching

    def create(
        self,
        db: Session,
        workflow: ProcessWorkflowCreate,
        *,
        is_default: bool = False,
        created_by: Optional[str] = None,
    ) -> ProcessWorkflowDb:
        """Create a new workflow with its steps."""
        # Create workflow
        db_workflow = ProcessWorkflowDb(
            name=workflow.name,
            description=workflow.description,
            trigger_config=workflow.trigger.model_dump_json(),
            scope_config=workflow.scope.model_dump_json() if workflow.scope else None,
            workflow_type=(getattr(workflow, 'workflow_type', WorkflowType.PROCESS) or WorkflowType.PROCESS).value,
            is_active=workflow.is_active,
            is_default=is_default,
            created_by=created_by,
            updated_by=created_by,
        )
        db.add(db_workflow)
        db.flush()  # Get the ID
        
        # Create steps
        for i, step in enumerate(workflow.steps):
            db_step = WorkflowStepDb(
                workflow_id=db_workflow.id,
                step_id=step.step_id,
                name=step.name,
                step_type=step.step_type.value,
                config=json.dumps(step.config) if step.config else None,
                on_pass=step.on_pass,
                on_fail=step.on_fail,
                order=step.order if step.order else i,
                position=step.position.model_dump_json() if step.position else None,
            )
            db.add(db_step)
        
        db.commit()
        db.refresh(db_workflow)
        return db_workflow

    def update(
        self,
        db: Session,
        workflow_id: str,
        workflow: ProcessWorkflowUpdate,
        *,
        updated_by: Optional[str] = None,
    ) -> Optional[ProcessWorkflowDb]:
        """Update an existing workflow."""
        db_workflow = self.get(db, workflow_id)
        if not db_workflow:
            return None
        
        # Update fields
        if workflow.name is not None:
            db_workflow.name = workflow.name
        if workflow.description is not None:
            db_workflow.description = workflow.description
        if workflow.trigger is not None:
            db_workflow.trigger_config = workflow.trigger.model_dump_json()
        if workflow.scope is not None:
            db_workflow.scope_config = workflow.scope.model_dump_json()
        if workflow.workflow_type is not None:
            db_workflow.workflow_type = workflow.workflow_type.value
        if workflow.is_active is not None:
            db_workflow.is_active = workflow.is_active
        
        db_workflow.updated_by = updated_by
        db_workflow.version += 1
        
        # Update steps if provided
        if workflow.steps is not None:
            self._replace_steps(db, db_workflow, workflow.steps)

        db.commit()
        db.refresh(db_workflow)
        return db_workflow

    def _replace_steps(
        self, db: Session, db_workflow: ProcessWorkflowDb, steps: List[WorkflowStepCreate],
    ) -> None:
        """Make the workflow's steps match ``steps``, keeping the rows of the steps that stay.

        Step results (``workflow_step_executions``) reference the step's row id
        and are deleted with it, so recreating every step on save erased the
        results of all past executions. A step whose ``step_id`` is still in
        the workflow keeps its row and is updated in place; only the steps that
        are no longer in it are deleted; their results stay, with the step's
        ``step_id`` and name (``step_key``, ``step_name``) and no row id.
        """
        existing: Dict[str, WorkflowStepDb] = {}
        for db_step in db_workflow.steps:
            if db_step.step_id in existing:
                db.delete(db_step)  # A duplicate step_id: keep one row
            else:
                existing[db_step.step_id] = db_step

        kept = set()
        for i, step in enumerate(steps):
            db_step = existing.get(step.step_id)
            if db_step is None or step.step_id in kept:
                db_step = WorkflowStepDb(workflow_id=db_workflow.id, step_id=step.step_id)
                db.add(db_step)
            kept.add(step.step_id)
            db_step.name = step.name
            db_step.step_type = step.step_type.value
            db_step.config = json.dumps(step.config) if step.config else None
            db_step.on_pass = step.on_pass
            db_step.on_fail = step.on_fail
            db_step.order = step.order if step.order else i
            db_step.position = step.position.model_dump_json() if step.position else None

        for step_id, db_step in existing.items():
            if step_id not in kept:
                db.delete(db_step)

    def delete(self, db: Session, workflow_id: str) -> bool:
        """Delete a workflow (cascades to steps and executions)."""
        db_workflow = db.get(ProcessWorkflowDb, workflow_id)
        if not db_workflow:
            return False
        
        # Don't allow deleting default workflows
        if db_workflow.is_default:
            logger.warning(f"Cannot delete default workflow {workflow_id}")
            return False
        
        db.delete(db_workflow)
        db.commit()
        return True

    def toggle_active(
        self,
        db: Session,
        workflow_id: str,
        is_active: bool,
        *,
        updated_by: Optional[str] = None,
    ) -> Optional[ProcessWorkflowDb]:
        """Toggle workflow active status."""
        db_workflow = db.get(ProcessWorkflowDb, workflow_id)
        if not db_workflow:
            return None
        
        db_workflow.is_active = is_active
        db_workflow.updated_by = updated_by
        db_workflow.version += 1
        
        db.commit()
        db.refresh(db_workflow)
        return db_workflow

    def exists_by_name(self, db: Session, name: str) -> bool:
        """Check if a workflow with the given name exists."""
        return db.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.name == name).count() > 0


class WorkflowExecutionRepository:
    """Repository for WorkflowExecution operations."""

    def list_for_workflow(
        self,
        db: Session,
        workflow_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WorkflowExecutionDb]:
        """List executions for a workflow."""
        return (
            db.query(WorkflowExecutionDb)
            .filter(WorkflowExecutionDb.workflow_id == workflow_id)
            .options(joinedload(WorkflowExecutionDb.step_executions))
            .order_by(WorkflowExecutionDb.started_at.desc())
            .offset(offset)
            .limit(limit)
            .all()
        )

    def list_all(
        self,
        db: Session,
        *,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[WorkflowExecutionDb]:
        """List all executions, optionally filtered by status."""
        query = db.query(WorkflowExecutionDb).options(
            joinedload(WorkflowExecutionDb.step_executions),
            joinedload(WorkflowExecutionDb.workflow),
        )
        
        if status:
            query = query.filter(WorkflowExecutionDb.status == status)
        
        return query.order_by(WorkflowExecutionDb.started_at.desc()).offset(offset).limit(limit).all()

    def get(self, db: Session, execution_id: str) -> Optional[WorkflowExecutionDb]:
        """Get an execution by ID."""
        return (
            db.query(WorkflowExecutionDb)
            .options(
                joinedload(WorkflowExecutionDb.step_executions),
                joinedload(WorkflowExecutionDb.workflow),
            )
            .filter(WorkflowExecutionDb.id == execution_id)
            .first()
        )

    def create(
        self,
        db: Session,
        execution: WorkflowExecutionCreate,
    ) -> WorkflowExecutionDb:
        """Create a new execution."""
        db_execution = WorkflowExecutionDb(
            workflow_id=execution.workflow_id,
            trigger_context=execution.trigger_context.model_dump_json() if execution.trigger_context else None,
            triggered_by=execution.triggered_by,
            status='running',
        )
        db.add(db_execution)
        db.commit()
        db.refresh(db_execution)
        return db_execution

    def update_status(
        self,
        db: Session,
        execution_id: str,
        *,
        status: str,
        current_step_id: Optional[str] = None,
        success_count: Optional[int] = None,
        failure_count: Optional[int] = None,
        error_message: Optional[str] = None,
        finished_at: Optional[str] = None,
    ) -> Optional[WorkflowExecutionDb]:
        """Update execution status."""
        db_execution = db.get(WorkflowExecutionDb, execution_id)
        if not db_execution:
            return None
        
        db_execution.status = status
        if current_step_id is not None:
            db_execution.current_step_id = current_step_id
        if success_count is not None:
            db_execution.success_count = success_count
        if failure_count is not None:
            db_execution.failure_count = failure_count
        if error_message is not None:
            db_execution.error_message = error_message
        if finished_at is not None:
            db_execution.finished_at = finished_at
        
        db.commit()
        db.refresh(db_execution)
        return db_execution

    def add_step_execution(
        self,
        db: Session,
        execution_id: str,
        step_id: str,
        *,
        status: str,
        passed: Optional[bool] = None,
        result_data: Optional[dict] = None,
        error_message: Optional[str] = None,
        duration_ms: Optional[float] = None,
        step_key: Optional[str] = None,
        step_name: Optional[str] = None,
    ) -> WorkflowStepExecutionDb:
        """Add a step execution result.

        ``step_id`` is the step's row id. The step's ``step_id`` and name are
        stored with the result (``step_key``, ``step_name``), read from the step
        when not given, so the result still names its step if the step is
        removed from the workflow later.
        """
        if step_key is None or step_name is None:
            db_step = db.get(WorkflowStepDb, step_id)
            if db_step is not None:
                step_key = step_key if step_key is not None else db_step.step_id
                step_name = step_name if step_name is not None else db_step.name
        db_step_exec = WorkflowStepExecutionDb(
            execution_id=execution_id,
            step_id=step_id,
            step_key=step_key,
            step_name=step_name,
            status=status,
            passed=passed,
            result_data=json.dumps(result_data) if result_data else None,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        db.add(db_step_exec)
        db.commit()
        db.refresh(db_step_exec)
        return db_step_exec

    def cancel(
        self,
        db: Session,
        execution_id: str,
        *,
        cancelled_by: Optional[str] = None,
    ) -> Optional[WorkflowExecutionDb]:
        """Cancel a running or paused execution."""
        from datetime import datetime
        
        db_execution = db.get(WorkflowExecutionDb, execution_id)
        if not db_execution:
            return None
        
        # Only cancel if running or paused
        if db_execution.status not in ('running', 'paused'):
            logger.warning(f"Cannot cancel execution {execution_id} with status {db_execution.status}")
            return None
        
        db_execution.status = 'cancelled'
        db_execution.error_message = f"Cancelled by {cancelled_by or 'admin'}"
        db_execution.finished_at = datetime.utcnow()
        
        db.commit()
        db.refresh(db_execution)
        return db_execution

    def delete(self, db: Session, execution_id: str) -> bool:
        """Delete an execution and its step executions."""
        db_execution = db.get(WorkflowExecutionDb, execution_id)
        if not db_execution:
            return False
        
        # Delete step executions first (cascade should handle this, but be explicit)
        db.query(WorkflowStepExecutionDb).filter(
            WorkflowStepExecutionDb.execution_id == execution_id
        ).delete()
        
        db.delete(db_execution)
        db.commit()
        return True

    def delete_bulk(
        self,
        db: Session,
        *,
        older_than_days: Optional[int] = None,
        status: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> int:
        """Delete multiple executions matching criteria. Returns count deleted."""
        from datetime import datetime, timedelta
        
        query = db.query(WorkflowExecutionDb)
        
        if older_than_days is not None:
            cutoff = datetime.utcnow() - timedelta(days=older_than_days)
            query = query.filter(WorkflowExecutionDb.started_at < cutoff)
        
        if status:
            query = query.filter(WorkflowExecutionDb.status == status)
        
        if workflow_id:
            query = query.filter(WorkflowExecutionDb.workflow_id == workflow_id)
        
        # Don't delete running or paused executions
        query = query.filter(WorkflowExecutionDb.status.notin_(['running', 'paused']))
        
        # Get IDs to delete step executions
        execution_ids = [e.id for e in query.all()]
        
        if execution_ids:
            # Delete step executions
            db.query(WorkflowStepExecutionDb).filter(
                WorkflowStepExecutionDb.execution_id.in_(execution_ids)
            ).delete(synchronize_session=False)
            
            # Delete executions
            count = query.delete(synchronize_session=False)
            db.commit()
            return count
        
        return 0

    def reset_for_retry(
        self,
        db: Session,
        execution_id: str,
    ) -> Optional[WorkflowExecutionDb]:
        """Reset a failed execution to allow retry from the beginning."""
        db_execution = db.get(WorkflowExecutionDb, execution_id)
        if not db_execution:
            return None
        
        # Allow retry for failed and cancelled executions
        if db_execution.status not in ('failed', 'cancelled'):
            logger.warning(f"Cannot retry execution {execution_id} with status {db_execution.status}")
            return None
        
        # Delete step executions
        db.query(WorkflowStepExecutionDb).filter(
            WorkflowStepExecutionDb.execution_id == execution_id
        ).delete()
        
        # Reset execution state
        db_execution.status = 'running'
        db_execution.current_step_id = None
        db_execution.success_count = 0
        db_execution.failure_count = 0
        db_execution.error_message = None
        db_execution.finished_at = None
        
        db.commit()
        db.refresh(db_execution)
        return db_execution


# Global repository instances
process_workflow_repo = ProcessWorkflowRepository()
workflow_execution_repo = WorkflowExecutionRepository()

