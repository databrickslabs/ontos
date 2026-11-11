"""
Workflows Manager for process workflow definitions.

Manages CRUD operations and loading of default workflows from YAML.
"""

import json
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
import yaml
from sqlalchemy import text
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
    GateErrorMode,
    GateExemptions,
    EntityType,
    ScopeType,
    WorkflowType,
    StepPosition,
    CodedMessage,
    WorkflowValidationIssue,
    WorkflowValidationResult,
    StepTypeSchema,
    TemplateVarDescriptor,
    TemplateVarGroup,
    TemplateVarsResponse,
)
from src.repositories.process_workflows_repository import process_workflow_repo
from src.common.logging import get_logger
from src.common.workflow_step_config import check_condition, check_script_config

logger = get_logger(__name__)

# Advisory lock key for loading the default workflows (any constant, unique in the app)
_DEFAULTS_LOCK_KEY = 7_340_001_016

# Entity types a shipped default workflow gained after installs already had it
# stored: (app_settings key, workflow name, entity type). Startup seeding skips
# workflows that exist, so ``add_default_entity_types`` adds each type to the
# stored default once, and nothing else of it, keeping the admin's edits
# (steps, approvers, activation). The key records that it ran, so a type an
# admin removes later stays removed.
_DEFAULT_ENTITY_TYPE_ADDITIONS = (
    # Contract status change requests go through the product's workflow (#1120)
    ('default_workflow_added_status_change_request_data_contract',
     'Status Change Request', 'data_contract'),
)

# (workflow, unknown entity types) already warned about by ``_split_entity_types``, oldest
# first; bounded, so a long-running process doesn't keep every key it ever logged
_WARNED_UNKNOWN_ENTITY_TYPES: "OrderedDict[tuple, None]" = OrderedDict()
_WARNED_UNKNOWN_ENTITY_TYPES_MAX = 1024


def _first_unknown_entity_type_warning(key: tuple) -> bool:
    """Record ``key`` as warned about; True the first time (as long as it's remembered)."""
    if key in _WARNED_UNKNOWN_ENTITY_TYPES:
        _WARNED_UNKNOWN_ENTITY_TYPES.move_to_end(key)
        return False
    _WARNED_UNKNOWN_ENTITY_TYPES[key] = None
    while len(_WARNED_UNKNOWN_ENTITY_TYPES) > _WARNED_UNKNOWN_ENTITY_TYPES_MAX:
        _WARNED_UNKNOWN_ENTITY_TYPES.popitem(last=False)
    return True


def _partition_entity_types(values: Any) -> tuple[List[EntityType], List[str]]:
    """Stored entity types as (known, unknown); any stored value, hashable or not, is kept."""
    known: List[EntityType] = []
    unknown: List[str] = []
    for value in values or []:
        try:
            known.append(EntityType(value))
        except ValueError:
            unknown.append(str(value))
    return known, unknown

# Trigger types no event fires: manual runs go by workflow id
# (POST /api/workflows/{id}/execute) and nothing runs ``scheduled`` triggers yet,
# so two active workflows of these types can't consume the same event.
_NON_EVENT_TRIGGER_TYPES = frozenset({TriggerType.MANUAL.value, TriggerType.SCHEDULED.value})
# Trigger types whose from/to status filters narrow the events they match.
_STATUS_FILTERED_TRIGGER_TYPES = frozenset({
    TriggerType.ON_STATUS_CHANGE.value, TriggerType.BEFORE_STATUS_CHANGE.value,
})


def _json_object(raw: Optional[str]) -> Dict[str, Any]:
    """A stored JSON config; NULL, the text ``'null'`` or a non-object value read as ``{}``."""
    value = json.loads(raw or '{}')
    return value if isinstance(value, dict) else {}


def _stored_trigger(trigger: WorkflowTrigger | Dict[str, Any] | None) -> Optional[Dict[str, Any]]:
    """A trigger as the stored config reads, unknown entity types in ``entity_types``."""
    if isinstance(trigger, WorkflowTrigger):
        return json.loads(trigger.stored_config_json())
    return trigger


# Value sources the assign_tag step resolves (AssignTagStepHandler._resolve_value_source).
ASSIGN_TAG_VALUE_SOURCES = ('current_user', 'project_name', 'entity_name', 'timestamp')


def _missing(step: WorkflowStepCreate, text: str, fields: List[str]) -> CodedMessage:
    """A step config error for required settings, with the step and fields as params."""
    return CodedMessage(f"Step '{step.step_id}': {text}", 'step_config_missing',
                        step=step.step_id, fields=fields)


def _step_issue(step: WorkflowStepCreate, issue: Dict[str, Any]) -> CodedMessage:
    """A Conditional / Script check's issue (workflow_step_config), keeping its code."""
    return CodedMessage(f"Step '{step.step_id}': {issue['message']}", issue['code'],
                        **{**(issue.get('params') or {}), 'step': step.step_id})


class WorkflowsManager:
    """Manager for process workflow definitions."""

    def __init__(
        self,
        db: Session,
        *,
        trigger_entity_types: Optional[Dict[str, List[str]]] = None,
    ):
        """``trigger_entity_types``: entity types each trigger type has a dispatch site
        for (an empty list = any). Given by the workflow routes, which own that map;
        without it ``trigger_save_errors`` doesn't check trigger/entity pairs.
        """
        self._db = db
        self._default_workflows_path = Path(__file__).parent.parent / "data" / "default_workflows.yaml"
        self._trigger_entity_types = trigger_entity_types

    def load_from_yaml(
        self,
        yaml_path: Optional[str] = None,
        update_existing: bool = False,
        requests_only_active: bool = False,
    ) -> dict:
        """Load default workflows from YAML file.
        
        Args:
            yaml_path: Path to YAML file, or None to use default
            update_existing: If True, updates existing default workflows instead of skipping
            requests_only_active: If True, workflows created now keep the YAML's
                ``is_active`` only when a request starts them (``on_request_*``);
                all others (event-driven automation, ``for_*`` UI wizards) are
                created inactive. Used at startup, so an upgrade doesn't turn
                on new automatic behavior. Existing workflows are not changed.
            
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

        # Several processes (replicas, a rolling deploy) can seed at startup
        # at the same time; serialize them so the name check below sees the
        # rows another process created.
        with self._defaults_lock():
            return self._load_workflows(
                workflows_data, result, update_existing, requests_only_active
            )

    def add_default_entity_types(self) -> int:
        """Add the entity types of ``_DEFAULT_ENTITY_TYPE_ADDITIONS`` not added yet.

        Only to a stored default (``is_default``) that lists entity types (an
        empty list already matches every type) without this one. Run at
        startup after the defaults are seeded; a fresh install has the type
        from the YAML already, and only records the key. Returns how many
        workflows changed.
        """
        from src.repositories.app_settings_repository import app_settings_repo

        changed = 0
        with self._defaults_lock():
            for key, name, entity_type in _DEFAULT_ENTITY_TYPE_ADDITIONS:
                if app_settings_repo.get_by_key(self._db, key):
                    continue
                workflow = process_workflow_repo.get_by_name(self._db, name)
                trigger = _json_object(workflow.trigger_config) if workflow else {}
                types = list(trigger.get('entity_types') or [])
                if workflow is not None and workflow.is_default and types \
                        and entity_type not in types:
                    trigger['entity_types'] = [*types, entity_type]
                    workflow.trigger_config = json.dumps(trigger)
                    workflow.version += 1
                    workflow.updated_by = 'system'
                    changed += 1
                    logger.info("Default workflow '%s' now covers %s", name, entity_type)
                # Commits the workflow change with the key
                app_settings_repo.set(self._db, key, 'done')
        return changed

    @contextmanager
    def _defaults_lock(self):
        """Hold a Postgres advisory lock while the defaults are loaded.

        Taken on a dedicated connection, since the repository commits after
        each workflow. A no-op on other databases (tests use SQLite).
        """
        engine = self._db.get_bind()
        if engine.dialect.name != 'postgresql':
            yield
            return
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_advisory_lock(:key)"), {'key': _DEFAULTS_LOCK_KEY})
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:key)"), {'key': _DEFAULTS_LOCK_KEY})

    def _load_workflows(
        self,
        workflows_data: List[Dict[str, Any]],
        result: dict,
        update_existing: bool,
        requests_only_active: bool,
    ) -> dict:
        for wf_data in workflows_data:
            try:
                name = wf_data.get('name')
                if not name:
                    continue
                
                # Parse trigger
                trigger_data = wf_data.get('trigger', {})
                entity_types, unknown_types = self._split_entity_types(
                    trigger_data.get('entity_types'), name,
                )
                trigger = WorkflowTrigger(
                    type=self._safe_trigger_type(trigger_data.get('type', 'manual')),
                    entity_types=entity_types,
                    unknown_entity_types=unknown_types,
                    from_status=trigger_data.get('from_status'),
                    to_status=trigger_data.get('to_status'),
                    schedule=trigger_data.get('schedule'),
                    on_error=self._safe_gate_error_mode(trigger_data.get('on_error')),
                    disabled_for=self._safe_gate_exemptions(trigger_data.get('disabled_for')),
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
                is_active = wf_data.get('is_active', True)
                if requests_only_active and not trigger.type.value.startswith('on_request_'):
                    is_active = False
                workflow = ProcessWorkflowCreate(
                    name=name,
                    description=wf_data.get('description'),
                    trigger=trigger,
                    scope=scope,
                    workflow_type=WorkflowType(wf_type) if isinstance(wf_type, str) else wf_type,
                    is_active=is_active,
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

    def policy_reference_errors(self, steps: Iterable[Any]) -> List[CodedMessage]:
        """Errors for ``policy_check`` steps whose policy doesn't exist.

        An active workflow with such a step fails at run time ("Policy not
        found") on every event it handles, so it can't be activated. A step
        with no ``policy_id`` (a template still to be configured) counts too.
        """
        from src.common.workflow_step_config import policy_id_of

        checks = [
            (step.step_id, policy_id_of(step.config))
            for step in steps
            if step.step_type == StepType.POLICY_CHECK
        ]
        if not checks:
            return []
        from src.db_models.compliance import CompliancePolicyDb

        wanted = {policy_id for _, policy_id in checks if policy_id}
        found = set()
        if wanted:
            found = {
                row[0] for row in
                self._db.query(CompliancePolicyDb.id)
                .filter(CompliancePolicyDb.id.in_(wanted)).all()
            }
        return [
            CodedMessage(
                f"Step '{step_id}': the policy to check "
                + (f"'{policy_id}' does not exist" if policy_id else "is not selected"),
                'policy_check_policy_missing', step=step_id, policyId=policy_id,
            )
            for step_id, policy_id in checks
            if policy_id not in found
        ]

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

    @staticmethod
    def _activation_scopes_overlap(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
        """Whether two scopes can consume the same event at runtime.

        Trigger callers currently do not supply scope metadata, so
        ``get_for_trigger`` does not filter scoped workflows. The one-to-one
        ``for_*`` lookup ignores scope as well. Until runtime events carry a
        scope, every pair of scopes therefore has to be treated as overlapping.
        """
        return True

    @staticmethod
    def activation_trigger_key(trigger: WorkflowTrigger | Dict[str, Any] | None) -> tuple:
        """The trigger fields ``activation_conflicts_for`` reads, for change detection.

        Other fields (``schedule``, ``on_error``, ``disabled_for``) don't change
        which events a workflow matches, so editing them needs no new check.
        """
        data = _stored_trigger(trigger)
        data = data or {}
        trigger_type = data.get('type')
        statuses = (
            (data.get('from_status'), data.get('to_status'))
            if trigger_type in _STATUS_FILTERED_TRIGGER_TYPES else (None, None)
        )
        return (trigger_type, frozenset(data.get('entity_types') or []), *statuses)

    def activation_conflicts_for(
        self,
        trigger: WorkflowTrigger | Dict[str, Any],
        scope: WorkflowScope | Dict[str, Any] | None,
        *,
        exclude_workflow_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Active workflows that can match the supplied trigger and scope.

        Empty entity type lists and status filters are wildcards, matching the
        trigger runtime. Scope is deliberately conservative because current
        trigger events do not carry the metadata needed to filter it.
        ``manual`` and ``scheduled`` workflows never conflict: no event fires
        them, a manual run targets one workflow by id.
        """
        target_trigger = _stored_trigger(trigger)
        target_trigger = target_trigger or {}
        if target_trigger.get('type') in _NON_EVENT_TRIGGER_TYPES:
            return []
        target_entities = self._firing_entity_types(target_trigger)
        if target_entities == set():
            return []  # it matches no event, so no other workflow consumes its events
        target_entities = target_entities or set()
        target_scope = scope.model_dump(mode='json') if isinstance(scope, WorkflowScope) else (scope or {'type': 'all'})

        conflicts = []
        query = self._db.query(ProcessWorkflowDb).filter(ProcessWorkflowDb.is_active.is_(True))
        if exclude_workflow_id:
            query = query.filter(ProcessWorkflowDb.id != exclude_workflow_id)
        candidates = query.all()
        for candidate in candidates:
            try:
                trigger = _json_object(candidate.trigger_config)
                scope = _json_object(candidate.scope_config)
            except (json.JSONDecodeError, TypeError):
                continue
            if trigger.get('type') != target_trigger.get('type'):
                continue
            # Only the entity types an event fires for: a stored trigger matching no event
            # (only unknown types, or pairs no code fires) consumes no event
            entities = self._firing_entity_types(trigger)
            if entities == set():
                continue
            entities = entities or set()
            if target_entities and entities and not target_entities & entities:
                continue
            if not self._activation_scopes_overlap(target_scope, scope):
                continue
            if target_trigger.get('type') in _STATUS_FILTERED_TRIGGER_TYPES:
                if any(
                    target_trigger.get(field) and trigger.get(field)
                    and target_trigger[field] != trigger[field]
                    for field in ('from_status', 'to_status')
                ):
                    continue
            conflicts.append({
                'id': candidate.id,
                'name': candidate.name,
                'trigger_type': trigger.get('type'),
                'entity_types': sorted(target_entities & entities) if target_entities and entities
                    else sorted(target_entities or entities),
                'scope_type': scope.get('type', 'all'),
            })
        return conflicts

    def activation_conflicts(self, workflow_id: str) -> List[Dict[str, Any]]:
        """Active workflows that can match the same event as ``workflow_id``."""
        target = process_workflow_repo.get(self._db, workflow_id)
        if not target:
            return []
        try:
            trigger = _json_object(target.trigger_config)
            scope = _json_object(target.scope_config)
        except (json.JSONDecodeError, TypeError):
            return []
        return self.activation_conflicts_for(
            trigger, scope, exclude_workflow_id=workflow_id,
        )

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
        
        # Create new workflow; unknown entity types are copied as stored, so the copy
        # matches no more events than the original
        entity_types, unknown_types = self._split_entity_types(
            trigger_config.get('entity_types'), existing.id,
        )
        trigger = WorkflowTrigger(
            type=self._safe_trigger_type(trigger_config.get('type', 'manual')),
            entity_types=entity_types,
            unknown_entity_types=unknown_types,
            from_status=trigger_config.get('from_status'),
            to_status=trigger_config.get('to_status'),
            schedule=trigger_config.get('schedule'),
            on_error=self._safe_gate_error_mode(trigger_config.get('on_error')),
            disabled_for=self._safe_gate_exemptions(trigger_config.get('disabled_for')),
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
            errors.append(CodedMessage("Workflow name is required", 'workflow_name_required'))

        if not workflow.steps:
            errors.append(CodedMessage("Workflow must have at least one step", 'workflow_steps_required'))

        # Check for duplicate step IDs
        step_ids = [s.step_id for s in workflow.steps]
        if len(step_ids) != len(set(step_ids)):
            errors.append(CodedMessage("Duplicate step IDs found", 'duplicate_step_ids'))

        # Check step references
        step_id_set = set(step_ids)
        for step in workflow.steps:
            for field, target in (('on_pass', step.on_pass), ('on_fail', step.on_fail)):
                if target and target not in step_id_set:
                    errors.append(CodedMessage(
                        f"Step '{step.step_id}' references unknown step '{target}' in {field}",
                        'step_unknown_reference', step=step.step_id, target=target, field=field,
                    ))
        
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

        errors.extend(self._validate_gate_exemptions(workflow.trigger))
        
        return WorkflowValidationResult(
            valid=len(errors) == 0,
            errors=errors,
            warnings=warnings,
        )

    def trigger_widening_errors(
        self, stored: WorkflowTrigger, new: Optional[WorkflowTrigger],
    ) -> List[str]:
        """An update that turns a stored trigger matching no event into "any entity".

        The stored trigger lists entity types, and none of them fires: each is unknown,
        or (with the trigger/entity map) a known type its trigger type never fires for.
        Without the map only a trigger of unknown types counts. Saving it with no
        entity types at all would match every entity of its trigger type. Refused
        unless the new trigger type fires for any entity anyway (an empty list in the
        map). Emptying a trigger that has a type that fires is not refused.
        """
        if new is None or new.entity_types or new.unknown_entity_types:
            return []
        if not self._matches_no_event(stored):
            return []
        if self._trigger_entity_types is not None \
                and not self._trigger_entity_types.get(new.type.value):
            return []
        return [CodedMessage(
            "Pick at least one entity type: the trigger matched no event, "
            "and no entity type would match every entity",
            'trigger_entity_type_required', triggerType=new.type.value,
        )]

    def _matches_no_event(self, trigger: WorkflowTrigger | Dict[str, Any]) -> bool:
        """The trigger lists entity types and none fires (see ``trigger_widening_errors``)."""
        return self._firing_entity_types(trigger) == set()

    def _firing_entity_types(
        self, trigger: WorkflowTrigger | Dict[str, Any] | None,
    ) -> Optional[set]:
        """The listed entity types an event can fire the trigger for; None = any entity.

        An empty set: the trigger lists entity types and none fires. Without the map,
        or for a trigger type that fires for any entity, every known type fires; an
        unknown value never does.
        """
        data = _stored_trigger(trigger) or {}
        values = data.get('entity_types')
        if not values:
            return None  # an empty list matches any entity
        known, _ = _partition_entity_types(values)
        allowed = (self._trigger_entity_types or {}).get(data.get('type')) or []
        return {et.value for et in known if not allowed or et.value in allowed}

    @staticmethod
    def _trigger_matches(left: WorkflowTrigger, right: WorkflowTrigger) -> bool:
        """Same trigger type and entity types (known and unknown), in any order."""
        return (left.type == right.type
                and set(left.entity_types) == set(right.entity_types)
                and set(left.unknown_entity_types) == set(right.unknown_entity_types))

    def trigger_save_errors(
        self, new: Optional[WorkflowTrigger], stored: Optional[WorkflowTrigger] = None,
    ) -> List[str]:
        """Trigger/entity errors of a create (``stored`` None) or an update.

        Only trigger changes are checked: an update that doesn't send the trigger, or
        sends the stored one again, is not, so stored workflows (an unknown type, a pair
        no code fires) keep working and can be edited. A changed trigger may keep the
        stored unknown values and pairs while its trigger type stays the same; any other
        unknown value (a known type sent as unknown too, since ``stored_config_json``
        would merge it into ``entity_types``) and any new pair no code fires is refused,
        and so is emptying a trigger of only unknown types (``trigger_widening_errors``).
        """
        if new is None or (stored is not None and self._trigger_matches(new, stored)):
            return []
        same_type = stored is not None and stored.type == new.type
        kept_unknown = set(stored.unknown_entity_types) if same_type else set()
        kept_known = set(stored.entity_types) if same_type else set()
        trigger_type = new.type.value
        errors: List[str] = [
            CodedMessage(
                f"Entity type '{value}' is listed as unknown on the trigger: "
                "remove it to change the trigger",
                'trigger_entity_type_unknown', triggerType=trigger_type, entityType=value,
            )
            for value in new.unknown_entity_types if value not in kept_unknown
        ]
        allowed = (self._trigger_entity_types or {}).get(trigger_type) or []
        if allowed:
            errors.extend(
                CodedMessage(
                    f"Trigger '{trigger_type}' never fires for entity type '{et.value}'",
                    'trigger_entity_type_unsupported',
                    triggerType=trigger_type, entityType=et.value,
                )
                for et in new.entity_types if et.value not in allowed and et not in kept_known
            )
        if stored is not None:
            errors.extend(self.trigger_widening_errors(stored, new))
        return errors

    def stored_trigger_warnings(self, trigger: WorkflowTrigger) -> List[CodedMessage]:
        """Entity types of a stored trigger that match no event; the workflow is kept as is.

        Each unknown value (``stored_entity_type_unknown``), and, with the trigger/entity
        map, each known type its trigger type never fires for
        (``stored_entity_type_unsupported``). Params: ``triggerType``, ``entityType``.
        """
        trigger_type = trigger.type.value
        warnings = [
            CodedMessage(
                f"Entity type '{value}' no longer exists: it matches no event",
                'stored_entity_type_unknown', triggerType=trigger_type, entityType=value,
            )
            for value in trigger.unknown_entity_types
        ]
        allowed = (self._trigger_entity_types or {}).get(trigger_type) or []
        if allowed:
            warnings.extend(
                CodedMessage(
                    f"Trigger '{trigger_type}' never fires for entity type '{et.value}'",
                    'stored_entity_type_unsupported',
                    triggerType=trigger_type, entityType=et.value,
                )
                for et in trigger.entity_types if et.value not in allowed
            )
        return warnings

    def log_unmatched_trigger_entity_types(self) -> int:
        """Warn once per stored workflow whose trigger lists entity types that match no event.

        Run at startup. The log line has the workflow id, name, trigger type and the
        entity types; the workflows are not changed or deactivated. Returns how many
        workflows were warned about.
        """
        warned = 0
        for db_workflow in process_workflow_repo.list_all(self._db):
            try:
                # This warning covers the unknown values too: skip the one of reads
                _, unknown = _partition_entity_types(
                    _json_object(db_workflow.trigger_config).get('entity_types'),
                )
                _first_unknown_entity_type_warning((db_workflow.id, tuple(unknown)))
                workflow = self._db_to_model(db_workflow)
            except Exception:
                # One unreadable row must not stop the check of the others
                logger.warning("Could not check the trigger of workflow %s", db_workflow.id,
                               exc_info=True)
                continue
            if not workflow.trigger_warnings:
                continue
            warned += 1
            logger.warning(
                "Workflow %s (%r, %s, trigger %s) lists entity types that match no event: "
                "unknown %s, not fired for this trigger %s. It is kept as stored.",
                workflow.id, workflow.name, 'active' if workflow.is_active else 'inactive',
                workflow.trigger.type.value,
                [w.params['entityType'] for w in workflow.trigger_warnings
                 if w.code == 'stored_entity_type_unknown'],
                [w.params['entityType'] for w in workflow.trigger_warnings
                 if w.code == 'stored_entity_type_unsupported'],
            )
        return warned

    def _validate_gate_exemptions(self, trigger: WorkflowTrigger) -> List[str]:
        """``disabled_for`` is for status gates only, and must name existing entities."""
        exemptions = trigger.disabled_for
        if exemptions is None or exemptions.is_empty():
            return []
        if trigger.type != TriggerType.BEFORE_STATUS_CHANGE:
            return [CodedMessage(
                "Only before_status_change workflows can be switched off per domain, "
                "data product or data contract (disabled_for)",
                'gate_exemptions_wrong_trigger', triggerType=trigger.type.value,
            )]
        from src.common.workflow_triggers import unknown_gate_exemptions

        labels = {'domain': 'domain', 'data_product': 'data product',
                  'data_contract': 'data contract'}
        return [
            CodedMessage(
                f"disabled_for: unknown {labels[kind]} '{missing}'",
                'gate_exemption_not_found', kind=kind, id=missing,
            )
            for kind, missing in unknown_gate_exemptions(self._db, exemptions)
        ]

    def _validate_step_config(self, step: WorkflowStepCreate) -> List[str]:
        """Validate step configuration based on type."""
        errors = []
        config = step.config or {}

        if step.step_type == StepType.VALIDATION:
            if not config.get('rule'):
                errors.append(_missing(step, "Validation step requires 'rule' in config", ['rule']))

        elif step.step_type == StepType.APPROVAL:
            if not config.get('approvers'):
                errors.append(_missing(step, "Approval step requires 'approvers' in config", ['approvers']))

        elif step.step_type == StepType.NOTIFICATION:
            if not config.get('recipients'):
                errors.append(_missing(step, "Notification step requires 'recipients' in config", ['recipients']))
            if not config.get('template'):
                errors.append(_missing(step, "Notification step requires 'template' in config", ['template']))

        elif step.step_type == StepType.ASSIGN_TAG:
            if not config.get('key'):
                errors.append(_missing(step, "Assign tag step requires 'key' in config", ['key']))
            # Neither 'value' nor 'value_source' assigns the tag key-only. An empty
            # fixed value is an unfinished step, not "no value".
            value_source = config.get('value_source')
            if not value_source and 'value' in config and config.get('value') in ('', None):
                errors.append(_missing(step, "Assign tag step has an empty 'value': enter one or remove it to assign the tag without a value", ['value']))
            if value_source and value_source not in ASSIGN_TAG_VALUE_SOURCES:
                errors.append(CodedMessage(
                    f"Step '{step.step_id}': unknown value source '{value_source}'",
                    'assign_tag_value_source_unknown',
                    step=step.step_id, source=value_source, supported=list(ASSIGN_TAG_VALUE_SOURCES),
                ))

        elif step.step_type == StepType.REMOVE_TAG:
            if not config.get('key'):
                errors.append(_missing(step, "Remove tag step requires 'key' in config", ['key']))

        elif step.step_type == StepType.CONDITIONAL:
            issue = check_condition(config.get('condition'))
            if issue:
                errors.append(_step_issue(step, issue))

        elif step.step_type == StepType.SCRIPT:
            for issue in check_script_config(config):
                errors.append(_step_issue(step, issue))

        elif step.step_type == StepType.ENTITY_ACTION:
            if not config.get('action'):
                errors.append(_missing(step, "Entity action step requires 'action' in config", ['action']))

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
                        "value": {"type": "string", "description": "Static tag value; leave out (and value_source) to assign the tag without a value"},
                        "value_source": {"type": "string", "description": "Dynamic value source: current_user, project_name, entity_name, timestamp (wins over value)"}
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
                        "storage": {
                            "type": "string",
                            "title": "Storage Destination",
                            "description": "Where to store the generated PDF: 'volume' saves to a Databricks Volume for permanent archival, 'none' generates on-demand at download time only.",
                            "enum": ["volume", "none"],
                            "default": "none",
                        },
                        "volume_path": {
                            "type": "string",
                            "title": "Volume Path",
                            "description": "Databricks Volume path for storing the PDF (e.g. /Volumes/catalog/schema/volume_name).",
                            "x-visible-when": {"field": "storage", "value": "volume"},
                        },
                    },
                },
                has_pass_branch=True,
                has_fail_branch=True,
            ),
            StepTypeSchema(
                type=StepType.ON_BEHALF_OF,
                name="On Behalf Of",
                description="Capture whether the requester is acting for themselves or on behalf of a group/SP. Lands in step_results AND the session row, so the auto-subscribe path picks it up unchanged.",
                icon="users",
                config_schema={
                    "type": "object",
                    "properties": {
                        "title": {"type": "string", "title": "Step Title", "default": "Who are you requesting access for?"},
                        "description": {"type": "string", "title": "Step Description"},
                        "allow_self": {"type": "boolean", "title": "Allow self-requests", "default": True},
                        "allow_user_groups": {"type": "boolean", "title": "Allow groups the user is in", "default": True},
                        "allow_free_text": {"type": "boolean", "title": "Allow free-text group/SP entry", "default": True},
                        "require_justification": {"type": "boolean", "title": "Require justification", "default": False},
                    },
                },
                has_pass_branch=True,
                has_fail_branch=False,
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
                config_schema={
                    "type": "object",
                    "description": "Saves the agreement record to the database at this point in the flow. Place this before Generate PDF if you want the PDF to include a stored agreement ID, or after if you want to verify PDF generation succeeded first. When omitted from a workflow, the agreement is saved automatically at the end.",
                    "properties": {},
                },
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
                            "description": "The dot-separated path to the target in step results (e.g. 'step_results.user_input.catalog_name').",
                            "x-visible-when": {"field": "target_source", "value": "from_variable"},
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
                            "description": "The dot-separated path to the principal email in step results (e.g. 'step_results.access_request.on_behalf_of').",
                            "x-visible-when": {"field": "principal_source", "value": "from_variable"},
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

    # ========================================================================
    # Template Variable Inspector
    # ========================================================================
    #
    # Static registry of ``${...}`` variables surfaced to workflow authors
    # in the designer's webhook body_template panel. The registry is
    # hand-curated rather than introspected because the underlying source
    # of truth (each manager's entity_data enrichment) lives in three
    # different files and has no schema. Drift is the obvious risk; the
    # mitigation lives in ``tests/unit/test_template_vars_registry.py``
    # which walks every descriptor path through ``substitute_template``
    # against a realistic fixture and fails CI if any path doesn't
    # resolve. When you add a new field to a manager's entity_data,
    # update ``_build_template_var_registry`` here too.

    def _build_template_var_registry(
        self,
    ) -> Dict[tuple, List[TemplateVarGroup]]:
        """Build the (trigger, entity_type) → groups lookup.

        Returns a fresh dict per call so callers can mutate without
        affecting other consumers. Could be cached if it shows up in
        profiling, but it's only hit from the GET endpoint.
        """
        # Variables that always exist regardless of trigger — surfaced
        # in their own group so the inspector can collapse them by
        # default once authors get familiar.
        flat_group = TemplateVarGroup(
            namespace="flat",
            description=(
                "Universal variables available in every workflow. Map "
                "to attributes on the workflow execution itself."
            ),
            variables=[
                TemplateVarDescriptor(
                    path="entity_type",
                    type="string",
                    description="Type slug of the triggering entity (e.g. ``data_product``).",
                    sample="data_product",
                ),
                TemplateVarDescriptor(
                    path="entity_id",
                    type="string",
                    description="Stable identifier of the triggering entity.",
                    sample="prd-2f1a-...-9c",
                ),
                TemplateVarDescriptor(
                    path="entity_name",
                    type="string",
                    description="Human-readable name of the triggering entity.",
                    sample="customer_360",
                ),
                TemplateVarDescriptor(
                    path="user_email",
                    type="string",
                    description="Email of the user whose action fired the trigger.",
                    sample="alice@example.com",
                ),
                TemplateVarDescriptor(
                    path="workflow_name",
                    type="string",
                    description="Name of the workflow this step belongs to.",
                    sample="Access Request Notification",
                ),
                TemplateVarDescriptor(
                    path="workflow_id",
                    type="string",
                    description="Database ID of the workflow.",
                    sample="wf-7e3d-...-22",
                ),
                TemplateVarDescriptor(
                    path="execution_id",
                    type="string",
                    description="Database ID of the current workflow execution.",
                    sample="exe-4a1b-...-08",
                ),
            ],
        )

        # ----- on_request_access × data_product -----
        # Entity-data shape comes from
        # ``AccessGrantsManager.create_request`` →
        # ``enrich_entity_data_with_data_product``.
        on_request_access_dp_entity = TemplateVarGroup(
            namespace="entity",
            description=(
                "Fields on the access-grant request and the underlying "
                "data product. ``output_ports`` / ``catalogs`` are "
                "resolved from the DP's UC asset identifiers."
            ),
            variables=[
                TemplateVarDescriptor(
                    path="entity.request_id",
                    type="string",
                    description="Access-grant request ID.",
                    sample="agr-3f...-c1",
                ),
                TemplateVarDescriptor(
                    path="entity.entity_type",
                    type="string",
                    description="Underlying entity type the user requested access to.",
                    sample="data_product",
                ),
                TemplateVarDescriptor(
                    path="entity.entity_id",
                    type="string",
                    description="ID of the underlying entity (data product) being requested.",
                    sample="prd-2f...-9c",
                ),
                TemplateVarDescriptor(
                    path="entity.entity_name",
                    type="string",
                    description="Display name of the underlying entity.",
                    sample="customer_360",
                ),
                TemplateVarDescriptor(
                    path="entity.requested_duration_days",
                    type="number",
                    description="How many days of access the requester asked for.",
                    sample=30,
                ),
                TemplateVarDescriptor(
                    path="entity.permission_level",
                    type="enum",
                    description="Permission level requested.",
                    sample="READ",
                    enum_values=["READ", "WRITE", "MANAGE"],
                ),
                TemplateVarDescriptor(
                    path="entity.reason",
                    type="string",
                    description="Free-text justification from the requester.",
                    sample="Need to validate Q3 churn metrics.",
                ),
                TemplateVarDescriptor(
                    path="entity.data_product_name",
                    type="string",
                    description="Name of the data product being requested.",
                    sample="customer_360",
                ),
                TemplateVarDescriptor(
                    path="entity.consumer_principals",
                    type="array",
                    description=(
                        "Configured access groups / service principals on "
                        "the data product. Each item is "
                        "``{type, value}`` where type is ``group`` or "
                        "``service_principal``. Downstream provisioners "
                        "add the requester into these principals."
                    ),
                    sample=[
                        {"type": "group", "value": "data_product_consumers"},
                    ],
                ),
                TemplateVarDescriptor(
                    path="entity.output_ports",
                    type="array",
                    description=(
                        "Per-output-port records parsed from the DP's "
                        "asset identifiers. Each item has ``name``, "
                        "``catalog``, ``schema``, ``table``, ``fqn``."
                    ),
                    sample=[
                        {
                            "name": "customers",
                            "catalog": "main",
                            "schema": "marts",
                            "table": "customers",
                            "fqn": "main.marts.customers",
                        }
                    ],
                ),
                TemplateVarDescriptor(
                    path="entity.catalogs",
                    type="array",
                    description=(
                        "Sorted, deduplicated catalog names across "
                        "every output port. Useful for per-catalog "
                        "grant requests."
                    ),
                    sample=["main", "prod"],
                ),
            ],
        )

        # ----- Context group: ${context.on_behalf_of.*} -----
        # Populated by the wizard's on_behalf_of step (or directly by the
        # subscribe-on-behalf API). Indicates whether the requester is
        # acting for themselves, a group they belong to, or another
        # principal — the "is this a user or a group?" signal external
        # provisioners need to dispatch correctly.
        on_behalf_of_context = TemplateVarGroup(
            namespace="context",
            description=(
                "Workflow execution context. ``on_behalf_of`` carries "
                "the requester's intent: are they acting for themselves, "
                "for a group, or for a service principal?"
            ),
            variables=[
                TemplateVarDescriptor(
                    path="context.on_behalf_of.type",
                    type="enum",
                    description=(
                        "Whether the requester is acting for themselves, "
                        "a group they belong to, or another principal. "
                        "External provisioners route based on this."
                    ),
                    sample="group",
                    enum_values=["user", "group", "service_principal"],
                ),
                TemplateVarDescriptor(
                    path="context.on_behalf_of.value",
                    type="string",
                    description=(
                        "Principal identifier — email when ``type=user``, "
                        "group name when ``type=group``, application ID "
                        "when ``type=service_principal``."
                    ),
                    sample="data_product_consumers",
                ),
                TemplateVarDescriptor(
                    path="context.on_behalf_of.display",
                    type="string",
                    description=(
                        "Human-readable label for the principal "
                        "(e.g. ``Group: analysts``). Use in user-facing "
                        "messages; use ``.value`` for machine routing."
                    ),
                    sample="Group: data_product_consumers",
                ),
            ],
        )

        # ----- on_subscribe × data_product -----
        # Entity-data shape comes from
        # ``DataProductsManager.subscribe`` (mirrors the access-grant
        # enrichment).
        on_subscribe_dp_entity = TemplateVarGroup(
            namespace="entity",
            description=(
                "Fields on the subscription event and the underlying "
                "data product."
            ),
            variables=[
                TemplateVarDescriptor(
                    path="entity.product_id",
                    type="string",
                    description="ID of the data product being subscribed to.",
                    sample="prd-2f...-9c",
                ),
                TemplateVarDescriptor(
                    path="entity.subscriber_email",
                    type="string",
                    description="Email of the user creating the subscription.",
                    sample="alice@example.com",
                ),
                TemplateVarDescriptor(
                    path="entity.reason",
                    type="string",
                    description="Optional reason supplied with the subscription.",
                    sample="Onboarding analytics dashboard.",
                ),
                TemplateVarDescriptor(
                    path="entity.data_product_name",
                    type="string",
                    description="Name of the data product being subscribed to.",
                    sample="customer_360",
                ),
                TemplateVarDescriptor(
                    path="entity.consumer_principals",
                    type="array",
                    description=(
                        "Configured access groups / service principals "
                        "on the data product. Each item is "
                        "``{type, value}``."
                    ),
                    sample=[
                        {"type": "group", "value": "data_product_consumers"},
                    ],
                ),
                TemplateVarDescriptor(
                    path="entity.on_behalf_of",
                    type="object",
                    description=(
                        "Same payload as ``${context.on_behalf_of}`` but "
                        "also persisted onto the subscription record. "
                        "Use ``${entity.on_behalf_of.type}`` etc."
                    ),
                    sample={
                        "type": "group",
                        "value": "data_product_consumers",
                        "display": "Group: data_product_consumers",
                    },
                ),
                TemplateVarDescriptor(
                    path="entity.output_ports",
                    type="array",
                    description=(
                        "Per-output-port records (see "
                        "``on_request_access`` for shape)."
                    ),
                    sample=[
                        {
                            "name": "customers",
                            "catalog": "main",
                            "schema": "marts",
                            "table": "customers",
                            "fqn": "main.marts.customers",
                        }
                    ],
                ),
                TemplateVarDescriptor(
                    path="entity.catalogs",
                    type="array",
                    description="Sorted, deduplicated catalog names across every output port.",
                    sample=["main", "prod"],
                ),
            ],
        )

        # NOTE: the trigger fires with entity_type=ACCESS_GRANT (the AGR
        # is the proxy entity; the data product is the *target*, referenced
        # via enriched entity_data fields like ${entity.entity_id} and
        # ${entity.catalogs}). Workflows that listen to on_request_access
        # therefore filter on access_grant, not data_product.
        return {
            (TriggerType.ON_REQUEST_ACCESS, EntityType.ACCESS_GRANT): [
                on_request_access_dp_entity,
                on_behalf_of_context,
                flat_group,
            ],
            (TriggerType.ON_SUBSCRIBE, EntityType.DATA_PRODUCT): [
                on_subscribe_dp_entity,
                on_behalf_of_context,
                flat_group,
            ],
        }

    def get_template_vars(
        self,
        trigger_type: TriggerType,
        entity_type: EntityType,
    ) -> TemplateVarsResponse:
        """Return the ``${...}`` variables available for a given trigger.

        Used by the workflow designer to render a side panel next to
        webhook ``body_template`` editors so authors know what's in
        scope. Combinations without curated descriptors return an empty
        ``groups`` list — the UI surfaces a friendly "no descriptors
        yet" state rather than treating that as an error.

        Args:
            trigger_type: The trigger the workflow listens for.
            entity_type: The entity type the trigger targets.

        Returns:
            ``TemplateVarsResponse`` with grouped descriptors. Always a
            valid response — never raises ``HTTPException``.
        """
        registry = self._build_template_var_registry()
        groups = registry.get((trigger_type, entity_type), [])
        return TemplateVarsResponse(
            trigger=trigger_type,
            entity_type=entity_type,
            groups=groups,
        )

    @staticmethod
    def _safe_trigger_type(value: str) -> TriggerType:
        """Parse a trigger type string, falling back to MANUAL for unknown/legacy values."""
        try:
            return TriggerType(value)
        except ValueError:
            logger.warning("Unknown trigger type '%s' in DB — treating as MANUAL", value)
            return TriggerType.MANUAL

    @staticmethod
    def _safe_gate_error_mode(value: Optional[str]) -> GateErrorMode:
        """Parse a gate's ``on_error``, falling back to FAIL_OPEN when unset or unknown."""
        if not value:
            return GateErrorMode.FAIL_OPEN
        try:
            return GateErrorMode(value)
        except ValueError:
            logger.warning("Unknown gate on_error '%s' in DB — treating as fail_open", value)
            return GateErrorMode.FAIL_OPEN

    @staticmethod
    def _safe_gate_exemptions(value: Any) -> GateExemptions:
        """Parse a gate's ``disabled_for``; an unset or unreadable value switches nothing off."""
        if not value:
            return GateExemptions()
        try:
            return GateExemptions.model_validate(value)
        except Exception:
            logger.warning("Unreadable gate disabled_for %r in DB — ignoring it", value)
            return GateExemptions()

    @staticmethod
    def _split_entity_types(
        values: Optional[List[Any]], workflow: Optional[str],
    ) -> tuple[List[EntityType], List[str]]:
        """Stored entity types as (known, unknown), keeping the unknown values as stored.

        An unknown value (a removed type such as ``dataset``) matches no event: matching
        reads the stored list, which keeps it. Dropping it would turn a list of unknown
        types into ``[]``, which matches every entity. Warned about once per workflow
        and set of values, not on every read.
        """
        known, unknown = _partition_entity_types(values)
        if unknown and _first_unknown_entity_type_warning((workflow, tuple(unknown))):
            logger.warning(
                "Workflow %s lists unknown entity types %s: they match no event",
                workflow, unknown,
            )
        return known, unknown

    def _db_to_model(self, db_workflow: ProcessWorkflowDb) -> ProcessWorkflow:
        """Convert database model to Pydantic model."""
        trigger_config = json.loads(db_workflow.trigger_config) if db_workflow.trigger_config else {}
        scope_config = json.loads(db_workflow.scope_config) if db_workflow.scope_config else {}
        
        entity_types, unknown_types = self._split_entity_types(
            trigger_config.get('entity_types'), db_workflow.id,
        )
        trigger = WorkflowTrigger(
            type=self._safe_trigger_type(trigger_config.get('type', 'manual')),
            entity_types=entity_types,
            unknown_entity_types=unknown_types,
            from_status=trigger_config.get('from_status'),
            to_status=trigger_config.get('to_status'),
            schedule=trigger_config.get('schedule'),
            on_error=self._safe_gate_error_mode(trigger_config.get('on_error')),
            disabled_for=self._safe_gate_exemptions(trigger_config.get('disabled_for')),
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
            trigger_warnings=[
                WorkflowValidationIssue(code=w.code, message=str(w), params=w.params)
                for w in self.stored_trigger_warnings(trigger)
            ],
        )

