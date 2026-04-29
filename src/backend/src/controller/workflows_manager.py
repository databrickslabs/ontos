"""
Workflows Manager for process workflow definitions.

Manages CRUD operations and loading of default workflows from YAML.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import yaml
from sqlalchemy.orm import Session

from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from src.models.process_workflows import (
    ProcessWorkflow,
    ProcessWorkflowCreate,
    ProcessWorkflowUpdate,
    WorkflowStep,
    WorkflowStepCreate,
    WorkflowTrigger,
    WorkflowScope,
    StepType,
    TriggerType,
    EntityType,
    ScopeType,
    WorkflowType,
    StepPosition,
    WorkflowValidationResult,
    StepTypeSchema,
)
from src.repositories.process_workflows_repository import process_workflow_repo
from src.common.logging import get_logger

logger = get_logger(__name__)


class WorkflowsManager:
    """Manager for process workflow definitions."""

    def __init__(self, db: Session):
        self._db = db
        self._default_workflows_path = Path(__file__).parent.parent / "data" / "default_workflows.yaml"

    def load_from_yaml(self, yaml_path: Optional[str] = None, update_existing: bool = False) -> dict:
        """Load default workflows from YAML file.
        
        Args:
            yaml_path: Path to YAML file, or None to use default
            update_existing: If True, updates existing default workflows instead of skipping
            
        Returns:
            Dict with counts: {'created': int, 'updated': int, 'skipped': int}
        """
        path = Path(yaml_path) if yaml_path else self._default_workflows_path
        
        result = {'created': 0, 'updated': 0, 'skipped': 0}
        
        if not path.exists():
            logger.warning(f"Workflows YAML not found: {path}")
            return result
        
        try:
            with open(path) as f:
                data = yaml.safe_load(f) or {}
        except Exception as e:
            logger.exception(f"Failed to load workflows YAML: {e}")
            return result
        
        workflows_data = data.get('workflows', [])
        
        for wf_data in workflows_data:
            try:
                name = wf_data.get('name')
                if not name:
                    continue
                
                # Parse trigger
                trigger_data = wf_data.get('trigger', {})
                trigger = WorkflowTrigger(
                    type=self._safe_trigger_type(trigger_data.get('type', 'manual')),
                    entity_types=[
                        et for et in
                        (self._safe_entity_type(v) for v in trigger_data.get('entity_types', []))
                        if et is not None
                    ],
                    from_status=trigger_data.get('from_status'),
                    to_status=trigger_data.get('to_status'),
                    schedule=trigger_data.get('schedule'),
                )
                
                # Parse scope
                scope_data = wf_data.get('scope', {})
                scope = WorkflowScope(
                    type=ScopeType(scope_data.get('type', 'all')),
                    ids=scope_data.get('ids', []),
                )
                
                # Parse steps
                steps = []
                for i, step_data in enumerate(wf_data.get('steps', [])):
                    step = WorkflowStepCreate(
                        step_id=step_data.get('id', f'step-{i}'),
                        name=step_data.get('name'),
                        step_type=StepType(step_data.get('type', 'pass')),
                        config=step_data.get('config', {}),
                        on_pass=step_data.get('on_pass'),
                        on_fail=step_data.get('on_fail'),
                        order=i,
                    )
                    steps.append(step)
                
                # Check if already exists
                existing = process_workflow_repo.get_by_name(self._db, name)
                
                if existing:
                    if update_existing and existing.is_default:
                        # Update existing default workflow
                        wf_type = wf_data.get('workflow_type', 'process')
                        update_data = ProcessWorkflowUpdate(
                            description=wf_data.get('description'),
                            trigger=trigger,
                            scope=scope,
                            workflow_type=WorkflowType(wf_type) if isinstance(wf_type, str) else wf_type,
                            is_active=wf_data.get('is_active', True),
                            steps=steps,
                        )
                        process_workflow_repo.update(self._db, existing.id, update_data)
                        result['updated'] += 1
                        logger.info(f"Updated default workflow: {name}")
                    else:
                        result['skipped'] += 1
                        logger.debug(f"Workflow '{name}' already exists, skipping")
                    continue
                
                # Create new workflow
                wf_type = wf_data.get('workflow_type', 'process')
                workflow = ProcessWorkflowCreate(
                    name=name,
                    description=wf_data.get('description'),
                    trigger=trigger,
                    scope=scope,
                    workflow_type=WorkflowType(wf_type) if isinstance(wf_type, str) else wf_type,
                    is_active=wf_data.get('is_active', True),
                    steps=steps,
                )
                
                process_workflow_repo.create(
                    self._db,
                    workflow,
                    is_default=wf_data.get('is_default', True),
                    created_by='system',
                )
                result['created'] += 1
                logger.info(f"Loaded default workflow: {name}")
                
            except Exception as e:
                logger.exception(f"Failed to load workflow from YAML: {e}")
                continue
        
        return result

    def list_workflows(
        self,
        *,
        is_active: Optional[bool] = None,
        workflow_type: Optional[WorkflowType] = None,
    ) -> List[ProcessWorkflow]:
        """List all workflows, optionally filtered by workflow_type (process | approval)."""
        db_workflows = process_workflow_repo.list_all(
            self._db, is_active=is_active, workflow_type=workflow_type
        )
        return [self._db_to_model(wf) for wf in db_workflows]

    def get_workflow(self, workflow_id: str) -> Optional[ProcessWorkflow]:
        """Get a workflow by ID."""
        db_workflow = process_workflow_repo.get(self._db, workflow_id)
        if not db_workflow:
            return None
        return self._db_to_model(db_workflow)

    def get_workflow_by_trigger_type(
        self, trigger_type: str, *, entity_type: Optional[str] = None
    ) -> Optional[ProcessWorkflow]:
        """Get the first active workflow for a given trigger type.

        If *entity_type* is provided the match is narrowed to workflows whose
        trigger.entity_types includes the value (or is empty — meaning "all").
        """
        db_workflow = process_workflow_repo.get_by_trigger_type(
            self._db, trigger_type, entity_type=entity_type, active_only=True
        )
        if not db_workflow:
            return None
        return self._db_to_model(db_workflow)

    def create_workflow(
        self,
        workflow: ProcessWorkflowCreate,
        *,
        created_by: Optional[str] = None,
    ) -> ProcessWorkflow:
        """Create a new workflow."""
        db_workflow = process_workflow_repo.create(
            self._db,
            workflow,
            is_default=False,
            created_by=created_by,
        )
        return self._db_to_model(db_workflow)

    def update_workflow(
        self,
        workflow_id: str,
        workflow: ProcessWorkflowUpdate,
        *,
        updated_by: Optional[str] = None,
    ) -> Optional[ProcessWorkflow]:
        """Update an existing workflow."""
        db_workflow = process_workflow_repo.update(
            self._db,
            workflow_id,
            workflow,
            updated_by=updated_by,
        )
        if not db_workflow:
            return None
        return self._db_to_model(db_workflow)

    def delete_workflow(self, workflow_id: str) -> bool:
        """Delete a workflow (non-default only)."""
        return process_workflow_repo.delete(self._db, workflow_id)

    def toggle_active(
        self,
        workflow_id: str,
        is_active: bool,
        *,
        updated_by: Optional[str] = None,
    ) -> Optional[ProcessWorkflow]:
        """Toggle workflow active status."""
        db_workflow = process_workflow_repo.toggle_active(
            self._db,
            workflow_id,
            is_active,
            updated_by=updated_by,
        )
        if not db_workflow:
            return None
        return self._db_to_model(db_workflow)

    def duplicate_workflow(
        self,
        workflow_id: str,
        new_name: str,
        *,
        created_by: Optional[str] = None,
    ) -> Optional[ProcessWorkflow]:
        """Duplicate an existing workflow with a new name."""
        existing = process_workflow_repo.get(self._db, workflow_id)
        if not existing:
            return None
        
        # Parse existing workflow
        trigger_config = json.loads(existing.trigger_config) if existing.trigger_config else {}
        scope_config = json.loads(existing.scope_config) if existing.scope_config else {}
        
        # Create new workflow
        trigger = WorkflowTrigger(
            type=self._safe_trigger_type(trigger_config.get('type', 'manual')),
            entity_types=[
                et for et in
                (self._safe_entity_type(v) for v in trigger_config.get('entity_types', []))
                if et is not None
            ],
            from_status=trigger_config.get('from_status'),
            to_status=trigger_config.get('to_status'),
            schedule=trigger_config.get('schedule'),
        )
        
        scope = WorkflowScope(
            type=ScopeType(scope_config.get('type', 'all')),
            ids=scope_config.get('ids', []),
        )
        
        steps = []
        for step in existing.steps:
            steps.append(WorkflowStepCreate(
                step_id=step.step_id,
                name=step.name,
                step_type=StepType(step.step_type),
                config=json.loads(step.config) if step.config else {},
                on_pass=step.on_pass,
                on_fail=step.on_fail,
                order=step.order,
                position=StepPosition(**json.loads(step.position)) if step.position else None,
            ))
        
        wf_type = getattr(existing, 'workflow_type', 'process')
        wf_type_enum = WorkflowType(wf_type) if isinstance(wf_type, str) and wf_type in ('process', 'approval') else WorkflowType.PROCESS
        new_workflow = ProcessWorkflowCreate(
            name=new_name,
            description=existing.description,
            trigger=trigger,
            scope=scope,
            workflow_type=wf_type_enum,
            is_active=False,  # Start inactive
            steps=steps,
        )
        
        return self.create_workflow(new_workflow, created_by=created_by)

    def get_workflows_for_trigger(
        self,
        trigger_type: TriggerType,
        entity_type: EntityType,
        *,
        scope_type: Optional[str] = None,
        scope_id: Optional[str] = None,
        from_status: Optional[str] = None,
        to_status: Optional[str] = None,
    ) -> List[ProcessWorkflow]:
        """Get active workflows matching a trigger event."""
        db_workflows = process_workflow_repo.get_for_trigger(
            self._db,
            trigger_type=trigger_type,
            entity_type=entity_type,
            scope_type=scope_type,
            scope_id=scope_id,
        )
        
        matching = []
        for wf in db_workflows:
            # Additional status filtering for on_status_change and before_status_change
            if trigger_type in (TriggerType.ON_STATUS_CHANGE, TriggerType.BEFORE_STATUS_CHANGE):
                trigger_config = json.loads(wf.trigger_config) if wf.trigger_config else {}
                wf_from = trigger_config.get('from_status')
                wf_to = trigger_config.get('to_status')
                
                if wf_from and from_status and wf_from != from_status:
                    continue
                if wf_to and to_status and wf_to != to_status:
                    continue
            
            matching.append(self._db_to_model(wf))
        
        return matching

    def validate_workflow(self, workflow: ProcessWorkflowCreate) -> WorkflowValidationResult:
        """Validate a workflow definition."""
        errors = []
        warnings = []
        
        # Check for required fields
        if not workflow.name or not workflow.name.strip():
            errors.append("Workflow name is required")
        
        if not workflow.steps:
            errors.append("Workflow must have at least one step")
        
        # Check for duplicate step IDs
        step_ids = [s.step_id for s in workflow.steps]
        if len(step_ids) != len(set(step_ids)):
            errors.append("Duplicate step IDs found")
        
        # Check step references
        step_id_set = set(step_ids)
        for step in workflow.steps:
            if step.on_pass and step.on_pass not in step_id_set:
                errors.append(f"Step '{step.step_id}' references unknown step '{step.on_pass}' in on_pass")
            if step.on_fail and step.on_fail not in step_id_set:
                errors.append(f"Step '{step.step_id}' references unknown step '{step.on_fail}' in on_fail")
        
        # Check for unreachable steps (warning only)
        reachable = set()
        if workflow.steps:
            # Start from first step
            to_visit = [workflow.steps[0].step_id]
            while to_visit:
                current = to_visit.pop()
                if current in reachable:
                    continue
                reachable.add(current)
                
                step = next((s for s in workflow.steps if s.step_id == current), None)
                if step:
                    if step.on_pass:
                        to_visit.append(step.on_pass)
                    if step.on_fail:
                        to_visit.append(step.on_fail)
            
            unreachable = step_id_set - reachable
            if unreachable:
                warnings.append(f"Unreachable steps: {', '.join(unreachable)}")
        
        # Validate step configs based on type
        for step in workflow.steps:
            step_errors = self._validate_step_config(step)
            errors.extend(step_errors)
        
        return WorkflowValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def _validate_step_config(self, step: WorkflowStepCreate) -> List[str]:
        """Validate step configuration based on type."""
        errors = []
        config = step.config or {}
        
        if step.step_type == StepType.VALIDATION:
            if not config.get('rule'):
                errors.append(f"Step '{step.step_id}': Validation step requires 'rule' in config")
        
        elif step.step_type == StepType.APPROVAL:
            if not config.get('approvers'):
                errors.append(f"Step '{step.step_id}': Approval step requires 'approvers' in config")
        
        elif step.step_type == StepType.NOTIFICATION:
            if not config.get('recipients'):
                errors.append(f"Step '{step.step_id}': Notification step requires 'recipients' in config")
            if not config.get('template'):
                errors.append(f"Step '{step.step_id}': Notification step requires 'template' in config")
        
        elif step.step_type == StepType.ASSIGN_TAG:
            if not config.get('key'):
                errors.append(f"Step '{step.step_id}': Assign tag step requires 'key' in config")
            if not config.get('value') and not config.get('value_source'):
                errors.append(f"Step '{step.step_id}': Assign tag step requires 'value' or 'value_source' in config")
        
        elif step.step_type == StepType.REMOVE_TAG:
            if not config.get('key'):
                errors.append(f"Step '{step.step_id}': Remove tag step requires 'key' in config")
        
        elif step.step_type == StepType.CONDITIONAL:
            if not config.get('condition'):
                errors.append(f"Step '{step.step_id}': Conditional step requires 'condition' in config")
        
        elif step.step_type == StepType.SCRIPT:
            if not config.get('code'):
                errors.append(f"Step '{step.step_id}': Script step requires 'code' in config")
        
        elif step.step_type == StepType.ENTITY_ACTION:
            if not config.get('action'):
                errors.append(f"Step '{step.step_id}': Entity action step requires 'action' in config")
        
        return errors

    def get_step_type_schemas(self) -> List[StepTypeSchema]:
        """Get schemas for all step types."""
        return [
            StepTypeSchema(
                type=StepType.VALIDATION,
                name="Validation",
                description="Evaluate a compliance DSL rule against the entity",
                icon="shield-check",
                config_schema={
                    "type": "object",
                    "properties": {
                        "rule": {"type": "string", "description": "Compliance DSL rule"}
                    },
                    "required": ["rule"]
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.APPROVAL,
                name="Approval",
                description="Request approval from specified approvers",
                icon="user-check",
                config_schema={
                    "type": "object",
                    "properties": {
                        "approvers": {"type": "string", "description": "Approvers: domain_owners, project_owners, email, or group"},
                        "timeout_days": {"type": "integer", "default": 7},
                        "require_all": {"type": "boolean", "default": False}
                    },
                    "required": ["approvers"]
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.NOTIFICATION,
                name="Notification",
                description="Send a notification to recipients",
                icon="bell",
                config_schema={
                    "type": "object",
                    "properties": {
                        "recipients": {"type": "string", "description": "Recipients: requester, owner, email, or group"},
                        "template": {"type": "string", "description": "Notification template name"},
                        "custom_message": {"type": "string"}
                    },
                    "required": ["recipients", "template"]
                },
                has_pass_branch=True,
                has_fail_branch=False,
            ),
            StepTypeSchema(
                type=StepType.ASSIGN_TAG,
                name="Assign Tag",
                description="Assign a tag to the entity",
                icon="tag",
                config_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Tag key"},
                        "value": {"type": "string", "description": "Static tag value"},
                        "value_source": {"type": "string", "description": "Dynamic value source: current_user, project_name"}
                    },
                    "required": ["key"]
                },
                has_pass_branch=True,
                has_fail_branch=False,
            ),
            StepTypeSchema(
                type=StepType.REMOVE_TAG,
                name="Remove Tag",
                description="Remove a tag from the entity",
                icon="tag-x",
                config_schema={
                    "type": "object",
                    "properties": {
                        "key": {"type": "string", "description": "Tag key to remove"}
                    },
                    "required": ["key"]
                },
                has_pass_branch=True,
                has_fail_branch=False,
            ),
            StepTypeSchema(
                type=StepType.CONDITIONAL,
                name="Conditional",
                description="Branch based on a condition",
                icon="git-branch",
                config_schema={
                    "type": "object",
                    "properties": {
                        "condition": {"type": "string", "description": "DSL condition expression"}
                    },
                    "required": ["condition"]
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.SCRIPT,
                name="Script",
                description="Execute custom Python or SQL script",
                icon="code",
                config_schema={
                    "type": "object",
                    "properties": {
                        "language": {"type": "string", "enum": ["python", "sql"], "default": "python"},
                        "code": {"type": "string", "description": "Script code"},
                        "timeout_seconds": {"type": "integer", "default": 60}
                    },
                    "required": ["code"]
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.USER_ACTION,
                name="User Action",
                description="Collect user input (reason, acceptances, custom fields). Used in approval workflows.",
                icon="message-square",
                config_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "description": "Step title shown in the wizard"},
                        "description": {"type": "string", "description": "Step description"},
                        "requires_input": {"type": "boolean", "description": "If true, user must enter something before continuing"},
                        "minimum_input_length": {"type": "integer", "minimum": 0, "description": "Minimum character length for the primary field"},
                        "primary_field_id": {"type": "string", "description": "Field to check for requires_input and minimum_input_length (default: first required field or 'reason')"},
                        "required_fields": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "label": {"type": "string"},
                                    "type": {"type": "string", "enum": ["text", "checkbox"]},
                                    "required": {"type": "boolean"},
                                },
                            },
                        },
                    },
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.ENTITY_ACTION,
                name="Entity Action",
                description="Performs a lifecycle action on the trigger entity (certify, publish, etc.)",
                icon="zap",
                config_schema={
                    "type": "object",
                    "properties": {
                        "action": {
                            "type": "string",
                            "enum": ["certify", "decertify", "publish", "unpublish"],
                            "description": "The action to perform on the entity",
                        },
                        "level_source": {
                            "type": "string",
                            "enum": ["from_request", "fixed", "from_approval"],
                            "default": "from_request",
                            "description": "Source for certification level (certify action only)",
                        },
                        "fixed_level": {
                            "type": "integer",
                            "description": "Fixed certification level (when level_source is 'fixed')",
                        },
                        "scope_source": {
                            "type": "string",
                            "enum": ["from_request", "fixed", "from_approval"],
                            "default": "from_request",
                            "description": "Source for publication scope (publish action only)",
                        },
                        "fixed_scope": {
                            "type": "string",
                            "enum": ["domain", "organization", "external"],
                            "description": "Fixed publication scope (when scope_source is 'fixed')",
                        },
                    },
                    "required": ["action"],
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.GENERATE_PDF,
                name="Generate PDF",
                description="Generate a PDF rendition of the agreement (non-visual, auto-advances).",
                icon="file-text",
                config_schema={
                    "type": "object",
                    "properties": {
                        "storage": {"type": "string", "title": "Storage", "enum": ["volume", "none"], "default": "none"},
                        "volume_path": {"type": "string", "title": "Volume Path"},
                    },
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.LEGAL_DOCUMENT,
                name="Legal Document",
                description="Display a legal document for the signer to review and optionally acknowledge.",
                icon="file-text",
                config_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "title": "Step Title"},
                        "description": {"type": "string", "title": "Step Description"},
                        "body_markdown": {"type": "string", "title": "Document Body (Markdown)"},
                        "require_scroll_to_end": {"type": "boolean", "title": "Require Scroll to End", "default": False},
                        "require_acknowledgement_checkbox": {"type": "boolean", "title": "Require Acknowledgement Checkbox", "default": False},
                        "acknowledgement_label": {"type": "string", "title": "Acknowledgement Label", "default": "I have read and understood the above"},
                    },
                },
                has_pass_branch=True,
                has_fail_branch=False,
            ),
            StepTypeSchema(
                type=StepType.ACKNOWLEDGEMENT_CHECKLIST,
                name="Acknowledgement Checklist",
                description="Present a list of labeled checkboxes for explicit, itemized consents.",
                icon="list-checks",
                config_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "title": "Step Title"},
                        "description": {"type": "string", "title": "Step Description"},
                        "items": {
                            "type": "array",
                            "title": "Checklist Items",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "id": {"type": "string"},
                                    "label": {"type": "string"},
                                    "required": {"type": "boolean", "default": True},
                                },
                            },
                            "maxItems": 10,
                        },
                    },
                },
                has_pass_branch=True,
                has_fail_branch=False,
            ),
            StepTypeSchema(
                type=StepType.CO_SIGNERS,
                name="Co-Signers",
                description="Collect co-signer names (record-only, no counter-signature flow).",
                icon="users",
                config_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "title": "Step Title"},
                        "description": {"type": "string", "title": "Step Description"},
                        "min_count": {"type": "integer", "title": "Minimum Co-Signers", "default": 0},
                        "max_count": {"type": "integer", "title": "Maximum Co-Signers", "default": 5},
                        "principal_type": {"type": "string", "title": "Principal Type", "enum": ["user", "group", "either"], "default": "either"},
                        "label": {"type": "string", "title": "Input Label", "default": "Add co-signer"},
                    },
                },
                has_pass_branch=True,
                has_fail_branch=False,
            ),
            StepTypeSchema(
                type=StepType.PERSIST_AGREEMENT,
                name="Persist Agreement",
                description="Materialize the agreement record (non-visual, auto-advances).",
                icon="database",
                config_schema={"type": "object", "properties": {}},
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.DELIVER,
                name="Deliver",
                description="Send the signed agreement through notification channels (non-visual, auto-advances).",
                icon="send",
                config_schema={
                    "type": "object",
                    "properties": {
                        "channels": {
                            "type": "array",
                            "title": "Delivery Channels",
                            "items": {"type": "string", "enum": ["in_app", "email", "webhook"]},
                            "default": ["in_app"],
                        },
                        "recipients": {
                            "type": "array",
                            "title": "Recipients",
                            "items": {"type": "string"},
                            "default": ["signer"],
                        },
                        "subject_template": {"type": "string", "title": "Subject Template"},
                        "body_template": {"type": "string", "title": "Body Template"},
                    },
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.GRANT_PERMISSIONS,
                name="Grant Permissions",
                description="Grant UC permissions via the SP workspace client (e.g. SELECT on a table after approval).",
                icon="key",
                config_schema={
                    "type": "object",
                    "properties": {
                        "permission_type": {
                            "type": "string",
                            "title": "Permission to Grant",
                            "description": "Which Unity Catalog privilege to grant on the target object (e.g. SELECT lets the user read data from a table).",
                            "enum": ["SELECT", "USE_SCHEMA", "USE_CATALOG", "ALL_PRIVILEGES"],
                            "default": "SELECT",
                        },
                        "target_source": {
                            "type": "string",
                            "title": "What to Grant On",
                            "description": "Where to find the target object: 'from_entity' uses the table/schema/catalog that triggered this workflow, 'from_variable' reads it from a previous step's output.",
                            "enum": ["from_entity", "from_variable"],
                            "default": "from_entity",
                        },
                        "target_variable": {
                            "type": "string",
                            "title": "Target Variable Path",
                            "description": "When granting on a variable: the dot-separated path to the target in step results (e.g. 'step_results.user_input.catalog_name'). Only used when 'What to Grant On' is 'from_variable'.",
                        },
                        "principal_source": {
                            "type": "string",
                            "title": "Who Gets Access",
                            "description": "Who receives the permission: 'requester' is the user who triggered the workflow, 'from_variable' reads the principal from a previous step (e.g. an on-behalf-of input).",
                            "enum": ["requester", "from_variable"],
                            "default": "requester",
                        },
                        "principal_variable": {
                            "type": "string",
                            "title": "Principal Variable Path",
                            "description": "When granting to a variable: the dot-separated path to the principal email in step results (e.g. 'step_results.access_request.on_behalf_of'). Only used when 'Who Gets Access' is 'from_variable'.",
                        },
                    },
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.PASS,
                name="Pass (Success)",
                description="Terminal step indicating success",
                icon="check-circle",
                config_schema={"type": "object", "properties": {}},
                has_pass_branch=False,
                has_fail_branch=False,
            ),
            StepTypeSchema(
                type=StepType.FAIL,
                name="Fail",
                description="Terminal step indicating failure",
                icon="x-circle",
                config_schema={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Failure message"}
                    }
                },
                has_pass_branch=False,
                has_fail_branch=False,
            ),
        ]

    @staticmethod
    def _safe_trigger_type(value: str) -> TriggerType:
        """Parse a trigger type string, falling back to MANUAL for unknown/legacy values."""
        try:
            return TriggerType(value)
        except ValueError:
            logger.warning("Unknown trigger type '%s' in DB — treating as MANUAL", value)
            return TriggerType.MANUAL

    @staticmethod
    def _safe_entity_type(value: str) -> EntityType:
        """Parse an entity type string, skipping unknown values."""
        try:
            return EntityType(value)
        except ValueError:
            logger.warning("Unknown entity type '%s' in DB — skipping", value)
            return None  # type: ignore[return-value]

    def _db_to_model(self, db_workflow: ProcessWorkflowDb) -> ProcessWorkflow:
        """Convert database model to Pydantic model."""
        trigger_config = json.loads(db_workflow.trigger_config) if db_workflow.trigger_config else {}
        scope_config = json.loads(db_workflow.scope_config) if db_workflow.scope_config else {}
        
        parsed_entity_types = [
            et for et in
            (self._safe_entity_type(v) for v in trigger_config.get('entity_types', []))
            if et is not None
        ]
        trigger = WorkflowTrigger(
            type=self._safe_trigger_type(trigger_config.get('type', 'manual')),
            entity_types=parsed_entity_types,
            from_status=trigger_config.get('from_status'),
            to_status=trigger_config.get('to_status'),
            schedule=trigger_config.get('schedule'),
        )
        
        scope = WorkflowScope(
            type=ScopeType(scope_config.get('type', 'all')),
            ids=scope_config.get('ids', []),
        )
        
        steps = []
        for step in db_workflow.steps:
            steps.append(WorkflowStep(
                id=step.id,
                workflow_id=step.workflow_id,
                step_id=step.step_id,
                name=step.name,
                step_type=StepType(step.step_type),
                config=json.loads(step.config) if step.config else {},
                on_pass=step.on_pass,
                on_fail=step.on_fail,
                order=step.order,
                position=StepPosition(**json.loads(step.position)) if step.position else None,
                created_at=step.created_at,
                updated_at=step.updated_at,
            ))
        
        wf_type = getattr(db_workflow, 'workflow_type', 'process')
        if isinstance(wf_type, str):
            wf_type = WorkflowType(wf_type) if wf_type in ('process', 'approval') else WorkflowType.PROCESS
        return ProcessWorkflow(
            id=db_workflow.id,
            name=db_workflow.name,
            description=db_workflow.description,
            trigger=trigger,
            scope=scope,
            workflow_type=wf_type,
            is_active=db_workflow.is_active,
            is_default=db_workflow.is_default,
            version=db_workflow.version,
            steps=steps,
            created_at=db_workflow.created_at,
            updated_at=db_workflow.updated_at,
            created_by=db_workflow.created_by,
            updated_by=db_workflow.updated_by,
        )

