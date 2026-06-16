"""
Workflow Trigger Registry.

Provides a centralized system for registering trigger points throughout the app
and executing matching workflows when events occur.
"""

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple
from sqlalchemy.orm import Session

from src.models.process_workflows import (
    TriggerType,
    EntityType,
    TriggerContext,
    ProcessWorkflow,
    WorkflowExecution,
    ExecutionStatus,
)
from src.common.logging import get_logger

logger = get_logger(__name__)


@dataclass
class TriggerEvent:
    """Represents a trigger event."""
    trigger_type: TriggerType
    entity_type: EntityType
    entity_id: str
    entity_name: Optional[str] = None
    entity_data: Optional[Dict[str, Any]] = None
    user_email: Optional[str] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    scope_type: Optional[str] = None  # 'project', 'catalog', 'domain'
    scope_id: Optional[str] = None


class TriggerRegistry:
    """Registry for workflow triggers.
    
    Provides methods to fire trigger events and execute matching workflows.
    """

    def __init__(self, db: Session):
        self._db = db
        self._workflows_manager = None
        self._workflow_executor = None

    def _get_workflows_manager(self):
        """Lazy load workflows manager to avoid circular imports."""
        if self._workflows_manager is None:
            from src.controller.workflows_manager import WorkflowsManager
            self._workflows_manager = WorkflowsManager(self._db)
        return self._workflows_manager

    def _get_workflow_executor(self):
        """Lazy load workflow executor to avoid circular imports."""
        if self._workflow_executor is None:
            from src.common.workflow_executor import WorkflowExecutor
            self._workflow_executor = WorkflowExecutor(self._db)
        return self._workflow_executor

    def fire_trigger(
        self,
        event: TriggerEvent,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire a trigger event and execute matching workflows.
        
        Args:
            event: The trigger event
            blocking: If True, execute workflows synchronously
            
        Returns:
            List of workflow executions
        """
        logger.info(
            f"Trigger fired: {event.trigger_type.value} for {event.entity_type.value} "
            f"'{event.entity_id}'"
        )
        
        # Get matching workflows
        workflows_manager = self._get_workflows_manager()
        matching_workflows = workflows_manager.get_workflows_for_trigger(
            trigger_type=event.trigger_type,
            entity_type=event.entity_type,
            scope_type=event.scope_type,
            scope_id=event.scope_id,
            from_status=event.from_status,
            to_status=event.to_status,
        )
        
        if not matching_workflows:
            logger.debug(f"No workflows match trigger: {event.trigger_type.value}")
            return []
        
        logger.info(f"Found {len(matching_workflows)} matching workflow(s)")
        
        # Build trigger context
        trigger_context = TriggerContext(
            entity_type=event.entity_type.value,
            entity_id=event.entity_id,
            entity_name=event.entity_name,
            trigger_type=event.trigger_type,
            user_email=event.user_email,
            entity_data=event.entity_data,
            from_status=event.from_status,
            to_status=event.to_status,
        )
        
        # Execute workflows
        executor = self._get_workflow_executor()
        executions = []
        
        for workflow in matching_workflows:
            try:
                execution = executor.execute_workflow(
                    workflow=workflow,
                    entity=event.entity_data or {},
                    entity_type=event.entity_type.value,
                    entity_id=event.entity_id,
                    entity_name=event.entity_name,
                    user_email=event.user_email,
                    trigger_context=trigger_context,
                    blocking=blocking,
                )
                executions.append(execution)
                
                logger.info(
                    f"Workflow '{workflow.name}' executed with status: {execution.status.value}"
                )
            except Exception as e:
                logger.exception(f"Failed to execute workflow '{workflow.name}': {e}")
        
        return executions

    def on_create(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire an on_create trigger.
        
        Args:
            entity_type: Type of entity being created
            entity_id: ID of the entity
            entity_name: Name of the entity
            entity_data: Entity data dictionary
            user_email: User performing the action
            scope_type: Scope type (project, catalog, domain)
            scope_id: Scope ID
            blocking: Execute synchronously
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_CREATE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        return self.fire_trigger(event, blocking=blocking)

    def on_update(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire an on_update trigger."""
        event = TriggerEvent(
            trigger_type=TriggerType.ON_UPDATE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        return self.fire_trigger(event, blocking=blocking)

    def on_delete(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire an on_delete trigger."""
        event = TriggerEvent(
            trigger_type=TriggerType.ON_DELETE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        return self.fire_trigger(event, blocking=blocking)

    def on_status_change(
        self,
        entity_type: EntityType,
        entity_id: str,
        from_status: str,
        to_status: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire an on_status_change trigger."""
        event = TriggerEvent(
            trigger_type=TriggerType.ON_STATUS_CHANGE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            from_status=from_status,
            to_status=to_status,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        return self.fire_trigger(event, blocking=blocking)

    def before_create(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> Tuple[bool, List[WorkflowExecution]]:
        """Fire a before_create trigger for pre-creation validation.
        
        This is an inline/blocking trigger that runs BEFORE the entity is created.
        Use for compliance checks, naming convention validation, etc.
        
        Args:
            entity_type: Type of entity being created
            entity_id: Proposed ID of the entity (may not exist yet)
            entity_name: Name of the entity
            entity_data: Entity data dictionary to validate
            user_email: User performing the action
            scope_type: Scope type (project, catalog, domain)
            scope_id: Scope ID
            
        Returns:
            Tuple of (all_passed, executions) where:
            - all_passed: True if all workflows succeeded, False if any failed
            - executions: List of workflow executions with detailed results
        """
        event = TriggerEvent(
            trigger_type=TriggerType.BEFORE_CREATE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        logger.info(f"before_create called for {entity_type.value} '{entity_name}' with data: {entity_data}")
        executions = self.fire_trigger(event, blocking=True)
        logger.info(f"before_create returned {len(executions)} executions")
        
        # Check if all workflows passed
        all_passed = all(
            exe.status == ExecutionStatus.SUCCEEDED 
            for exe in executions
        ) if executions else True  # No workflows = pass
        
        return all_passed, executions

    def before_update(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> Tuple[bool, List[WorkflowExecution]]:
        """Fire a before_update trigger for pre-update validation.
        
        This is an inline/blocking trigger that runs BEFORE the entity is updated.
        
        Args:
            entity_type: Type of entity being updated
            entity_id: ID of the entity
            entity_name: Name of the entity
            entity_data: Updated entity data dictionary to validate
            user_email: User performing the action
            scope_type: Scope type (project, catalog, domain)
            scope_id: Scope ID
            
        Returns:
            Tuple of (all_passed, executions)
        """
        event = TriggerEvent(
            trigger_type=TriggerType.BEFORE_UPDATE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        executions = self.fire_trigger(event, blocking=True)
        
        all_passed = all(
            exe.status == ExecutionStatus.SUCCEEDED 
            for exe in executions
        ) if executions else True
        
        return all_passed, executions

    def before_status_change(
        self,
        entity_type: EntityType,
        entity_id: str,
        from_status: str,
        to_status: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
    ) -> Tuple[bool, List[WorkflowExecution]]:
        """Fire a before_status_change trigger for pre-transition validation.

        Runs BEFORE the status is persisted. Returns (all_passed, executions)
        so the caller can block the transition when any workflow fails.
        """
        event = TriggerEvent(
            trigger_type=TriggerType.BEFORE_STATUS_CHANGE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            from_status=from_status,
            to_status=to_status,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        logger.info(
            f"before_status_change called for {entity_type.value} '{entity_name}': "
            f"'{from_status}' -> '{to_status}'"
        )
        executions = self.fire_trigger(event, blocking=True)

        all_passed = all(
            exe.status == ExecutionStatus.SUCCEEDED
            for exe in executions
        ) if executions else True

        return all_passed, executions

    # =========================================================================
    # Publication Triggers
    # =========================================================================

    def on_publish(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire when an entity is published to the marketplace."""
        event = TriggerEvent(
            trigger_type=TriggerType.ON_PUBLISH,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_publish fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    def on_unpublish(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire when an entity is unpublished from the marketplace."""
        event = TriggerEvent(
            trigger_type=TriggerType.ON_UNPUBLISH,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_unpublish fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    # =========================================================================
    # Certification Triggers
    # =========================================================================

    def on_request_certify(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire when certification is requested for an entity."""
        event = TriggerEvent(
            trigger_type=TriggerType.ON_REQUEST_CERTIFY,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        logger.info(f"on_request_certify fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    def on_certify(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire after certification is granted."""
        event = TriggerEvent(
            trigger_type=TriggerType.ON_CERTIFY,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_certify fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    def on_decertify(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire after certification is removed."""
        event = TriggerEvent(
            trigger_type=TriggerType.ON_DECERTIFY,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_decertify fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    # =========================================================================
    # Maturity Triggers
    # =========================================================================

    def on_maturity_change(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        from_level: Optional[int] = None,
        to_level: Optional[int] = None,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire when an entity's maturity level changes."""
        data = dict(entity_data or {})
        data["from_maturity_level"] = from_level
        data["to_maturity_level"] = to_level
        event = TriggerEvent(
            trigger_type=TriggerType.ON_MATURITY_CHANGE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=data,
            user_email=user_email,
        )
        logger.info(
            f"on_maturity_change fired for {entity_type.value} '{entity_id}': "
            f"level {from_level} -> {to_level}"
        )
        return self.fire_trigger(event, blocking=blocking)

    # =========================================================================
    # Request Triggers
    # =========================================================================

    def on_request_review(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire when a review is requested for an entity.
        
        Used for datasets, data contracts, and data products when a user
        requests a steward or domain owner review.
        
        Args:
            entity_type: Type of entity (dataset, data_contract, data_product)
            entity_id: ID of the entity
            entity_name: Name of the entity
            entity_data: Entity data including request details (message, requester, etc.)
            user_email: User requesting the review
            scope_type: Scope type (project, catalog, domain)
            scope_id: Scope ID
            blocking: Execute synchronously
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_REQUEST_REVIEW,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        logger.info(f"on_request_review fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    def on_request_access(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire when access is requested for an entity.
        
        Used for access grants, project access, and role access requests.
        
        Args:
            entity_type: Type of entity (access_grant, project, etc.)
            entity_id: ID of the entity or request
            entity_name: Name of the entity
            entity_data: Request details (duration, permission level, justification, etc.)
            user_email: User requesting access
            scope_type: Scope type
            scope_id: Scope ID
            blocking: Execute synchronously
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_REQUEST_ACCESS,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        logger.info(f"on_request_access fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    def on_request_publish(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire when publish or deployment is requested.
        
        Used for data contracts when requesting to publish to marketplace
        or deploy to a catalog.
        
        Args:
            entity_type: Type of entity (data_contract)
            entity_id: ID of the entity
            entity_name: Name of the entity
            entity_data: Request details (target catalog, justification, etc.)
            user_email: User requesting publish
            scope_type: Scope type
            scope_id: Scope ID
            blocking: Execute synchronously
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_REQUEST_PUBLISH,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        logger.info(f"on_request_publish fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    def on_request_status_change(
        self,
        entity_type: EntityType,
        entity_id: str,
        from_status: str,
        to_status: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        *,
        blocking: bool = True,
    ) -> List[WorkflowExecution]:
        """Fire when a status change is requested (but not yet applied).
        
        Used when users request a status transition that requires approval,
        e.g., draft -> published for datasets or contracts.
        
        Args:
            entity_type: Type of entity
            entity_id: ID of the entity
            from_status: Current status
            to_status: Requested target status
            entity_name: Name of the entity
            entity_data: Request details (justification, etc.)
            user_email: User requesting the change
            scope_type: Scope type
            scope_id: Scope ID
            blocking: Execute synchronously
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_REQUEST_STATUS_CHANGE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
            from_status=from_status,
            to_status=to_status,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        logger.info(
            f"on_request_status_change fired for {entity_type.value} '{entity_id}': "
            f"'{from_status}' -> '{to_status}' by {user_email}"
        )
        return self.fire_trigger(event, blocking=blocking)

    # =========================================================================
    # Job Lifecycle Triggers
    # =========================================================================

    def on_job_success(
        self,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire when a background job completes successfully.
        
        Args:
            entity_id: Job run ID
            entity_name: Job name
            entity_data: Job details (workflow_id, run_id, duration, etc.)
            user_email: User who triggered the job
            blocking: Execute synchronously (default False for async)
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_JOB_SUCCESS,
            entity_type=EntityType.JOB,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_job_success fired for job '{entity_name}' (run {entity_id})")
        return self.fire_trigger(event, blocking=blocking)

    def on_job_failure(
        self,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire when a background job fails.
        
        Args:
            entity_id: Job run ID
            entity_name: Job name
            entity_data: Job details (workflow_id, run_id, error_message, etc.)
            user_email: User who triggered the job
            blocking: Execute synchronously (default False for async)
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_JOB_FAILURE,
            entity_type=EntityType.JOB,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_job_failure fired for job '{entity_name}' (run {entity_id})")
        return self.fire_trigger(event, blocking=blocking)

    # =========================================================================
    # Subscription Triggers
    # =========================================================================

    def on_subscribe(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire when a user subscribes to an entity.
        
        Args:
            entity_type: Type of entity (dataset, data_product)
            entity_id: ID of the entity
            entity_name: Name of the entity
            entity_data: Subscription details (subscriber_email, reason, etc.)
            user_email: User subscribing
            blocking: Execute synchronously (default False for async)
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_SUBSCRIBE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_subscribe fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    def on_unsubscribe(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire when a user unsubscribes from an entity.
        
        Args:
            entity_type: Type of entity (dataset, data_product)
            entity_id: ID of the entity
            entity_name: Name of the entity
            entity_data: Subscription details
            user_email: User unsubscribing
            blocking: Execute synchronously (default False for async)
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_UNSUBSCRIBE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_unsubscribe fired for {entity_type.value} '{entity_id}' by {user_email}")
        return self.fire_trigger(event, blocking=blocking)

    # =========================================================================
    # Access Lifecycle Triggers
    # =========================================================================

    def on_expiring(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire when an entity is about to expire.
        
        Used for access grants, subscriptions, or any time-limited resources.
        Typically triggered by a scheduled job checking for expiring items.
        
        Args:
            entity_type: Type of entity (access_grant, etc.)
            entity_id: ID of the entity
            entity_name: Name or description of the entity
            entity_data: Details including expiration date, days remaining, etc.
            user_email: User affected by expiration
            blocking: Execute synchronously (default False for async)
            
        Returns:
            List of workflow executions
        """
        event = TriggerEvent(
            trigger_type=TriggerType.ON_EXPIRING,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_expiring fired for {entity_type.value} '{entity_id}'")
        return self.fire_trigger(event, blocking=blocking)

    def on_revoke(
        self,
        entity_type: EntityType,
        entity_id: str,
        entity_name: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
        revoked_by: Optional[str] = None,
        *,
        blocking: bool = False,
    ) -> List[WorkflowExecution]:
        """Fire when access or a resource is revoked.
        
        Used for access grants when an admin revokes access before expiration.
        
        Args:
            entity_type: Type of entity (access_grant, etc.)
            entity_id: ID of the entity
            entity_name: Name or description of the entity
            entity_data: Details about the revocation (reason, etc.)
            user_email: User whose access was revoked
            revoked_by: User who performed the revocation
            blocking: Execute synchronously (default False for async)
            
        Returns:
            List of workflow executions
        """
        if entity_data is None:
            entity_data = {}
        entity_data['revoked_by'] = revoked_by
        
        event = TriggerEvent(
            trigger_type=TriggerType.ON_REVOKE,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            entity_data=entity_data,
            user_email=user_email,
        )
        logger.info(f"on_revoke fired for {entity_type.value} '{entity_id}' (revoked by {revoked_by})")
        return self.fire_trigger(event, blocking=blocking)


def get_trigger_registry(db: Session) -> TriggerRegistry:
    """Get a trigger registry instance.

    Args:
        db: Database session

    Returns:
        TriggerRegistry instance
    """
    return TriggerRegistry(db)


def fire_trigger_safe(
    db: Session,
    method: str,
    *,
    entity_type: EntityType,
    entity_id: str,
    entity_name: Optional[str] = None,
    entity_data: Optional[Dict[str, Any]] = None,
    user_email: Optional[str] = None,
    from_status: Optional[str] = None,
    to_status: Optional[str] = None,
    blocking: bool = False,
) -> None:
    """Fire a trigger method on the registry, logging and swallowing errors.

    Convenience wrapper that eliminates repetitive try/except blocks in routes.

    Args:
        db: Database session
        method: Name of the TriggerRegistry method (e.g. "on_create", "on_delete")
        entity_type: Entity type enum value
        entity_id: ID of the entity
        entity_name: Display name of the entity
        entity_data: Additional entity data dict
        user_email: User performing the action
        from_status: Previous status (for status-change triggers)
        to_status: New status (for status-change triggers)
        blocking: Whether to execute synchronously
    """
    try:
        registry = get_trigger_registry(db)
        kwargs: Dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "entity_name": entity_name,
            "entity_data": entity_data,
            "user_email": user_email,
        }
        if from_status is not None:
            kwargs["from_status"] = from_status
        if to_status is not None:
            kwargs["to_status"] = to_status
        if method not in ("before_create", "before_update", "before_status_change"):
            kwargs["blocking"] = blocking
        getattr(registry, method)(**kwargs)
    except Exception as e:
        logger.warning(f"{method} trigger failed for {entity_type.value} {entity_id}: {e}")


# ============================================================================
# Entity Data Enrichment Helpers
# ============================================================================
#
# Workflow authors reference entity attributes in webhook ``body_template``s
# via ``${entity.<field>}`` substitution. For data-product triggers we
# pre-resolve the underlying DP's output ports into structured records so
# templates can reach catalog/schema/table without each author re-parsing
# ODPS ``asset_identifier`` strings.


def enrich_entity_data_with_data_product(
    entity_data: Dict[str, Any],
    data_product,
) -> Dict[str, Any]:
    """Enrich ``entity_data`` with output-port-derived fields from a DP.

    Adds two keys (only when not already supplied — caller wins):

    - ``output_ports``: list of ``{name, catalog, schema, table, fqn}``
      dicts, one per OutputPortDb whose ``asset_identifier`` parses as
      a 3-part Unity Catalog reference (``catalog.schema.table``). Ports
      without a usable identifier are skipped so the workflow author
      never sees half-formed rows.
    - ``catalogs``: sorted, deduplicated list of catalog names across
      every usable output port. Empty list when the DP has no parseable
      ports.

    The function is intentionally tolerant: a missing ``output_ports``
    relationship, ``None`` identifiers, or non-3-part identifiers are
    all logged at debug-level and silently skipped. Failures here must
    never break the trigger-fire path that wraps this call.

    Args:
        entity_data: The entity_data dict to mutate. Returned for
            convenience; mutation is in place. Caller-supplied keys
            (``output_ports``/``catalogs``) are preserved.
        data_product: Resolved ``DataProductDb`` row. May be ``None``,
            in which case the function is a no-op.

    Returns:
        The (possibly mutated) ``entity_data`` dict.
    """
    if data_product is None:
        return entity_data

    ports = getattr(data_product, 'output_ports', None) or []
    parsed_ports: List[Dict[str, Any]] = []
    catalogs_seen: set = set()

    for port in ports:
        identifier = getattr(port, 'asset_identifier', None)
        if not identifier or not isinstance(identifier, str):
            continue
        parts = identifier.split('.')
        # Require exactly catalog.schema.table — anything else is a
        # non-UC asset (file path, job id, etc.) and isn't useful to a
        # webhook template that wants per-catalog grants.
        if len(parts) != 3:
            logger.debug(
                "Skipping output port '%s' on DP %s: asset_identifier "
                "'%s' did not parse as catalog.schema.table",
                getattr(port, 'name', '?'),
                getattr(data_product, 'id', '?'),
                identifier,
            )
            continue
        catalog, schema, table = parts
        parsed_ports.append({
            'name': getattr(port, 'name', None) or '',
            'catalog': catalog,
            'schema': schema,
            'table': table,
            'fqn': identifier,
        })
        catalogs_seen.add(catalog)

    if 'output_ports' not in entity_data:
        entity_data['output_ports'] = parsed_ports
    if 'catalogs' not in entity_data:
        entity_data['catalogs'] = sorted(catalogs_seen)

    return entity_data

