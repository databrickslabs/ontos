"""
Workflow Executor for executing process workflows.

Handles step-by-step execution with branching, including:
- Validation steps (using compliance DSL)
- Approval steps (creates approval requests)
- Notification steps
- Tag assignment/removal
- Conditional branching
- Script execution
"""

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db_models.process_workflows import WorkflowStepDb, WorkflowExecutionDb
from src.models.process_workflows import (
    ProcessWorkflow,
    WorkflowStep,
    WorkflowExecution,
    WorkflowExecutionCreate,
    TriggerContext,
    StepType,
    ExecutionStatus,
    StepExecutionStatus,
    WorkflowStepExecutionResult,
)
from src.repositories.process_workflows_repository import workflow_execution_repo
from src.common.logging import get_logger
from src.common.workflow_notification_texts import (
    DEFAULT_TEMPLATE_MESSAGE,
    DEFAULT_TEMPLATE_TITLE,
    TEMPLATE_MESSAGES,
    TEMPLATE_TITLES,
    approval_notification_i18n,
    notification_step_i18n,
)

logger = get_logger(__name__)


def _render_template_value(value: Any) -> str:
    """Render a substitution value. Lists/dicts are JSON-serialized so webhook
    body templates can interpolate `${entity.consumer_principals}` and receive
    a valid JSON array of `{type, value}` objects (piping consumer_principals
    + on_behalf_of into the external runbook webhook body)."""
    if value is None:
        return ''
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, default=str)
        except Exception:
            return str(value)
    return str(value)


def substitute_template(template: str, context: 'StepContext') -> str:
    """Replace ${variable} and {{variable}} placeholders with context values.

    Supports:
      ${entity_name}, ${entity_type}, ${entity_id}, ${user_email},
      ${workflow_name}, ${workflow_id}, ${execution_id},
      ${entity.field}              - flat scalars + JSON-serialized lists/dicts
      ${entity.field.subfield}     - nested dict path
      ${step_results.step_id.field[.sub...]}
      ${context.<key>[.<sub>...]}  - nested path into StepContext attributes
                                     (e.g. ${context.on_behalf_of.value}).
                                     Top-level scalar attrs like
                                     ${context.entity_type} also work.
    """
    import re

    flat_subs = {
        'entity_type': context.entity_type,
        'entity_id': context.entity_id,
        'entity_name': context.entity_name or '',
        'user_email': context.user_email or '',
        'workflow_name': context.workflow_name,
        'workflow_id': context.workflow_id,
        'execution_id': context.execution_id,
    }

    def _walk_dict(obj: Any, parts: List[str]) -> Optional[str]:
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return None
            if obj is None:
                return None
        return _render_template_value(obj)

    def _lookup_context(parts: List[str]) -> Optional[str]:
        """Resolve ${context.<attr>[.<sub>...]} by walking StepContext attrs."""
        if not parts:
            return None
        head, rest = parts[0], parts[1:]
        if not hasattr(context, head):
            return None
        obj: Any = getattr(context, head)
        if obj is None:
            return None
        for part in rest:
            if isinstance(obj, dict):
                obj = obj.get(part)
            elif obj is None:
                return None
            else:
                obj = getattr(obj, part, None)
            if obj is None:
                return None
        return _render_template_value(obj)

    def _replace(match):
        var_name = match.group(1)
        # 1) flat top-level scalars
        if var_name in flat_subs:
            return _render_template_value(flat_subs[var_name])
        # 2) namespaced paths
        if '.' in var_name:
            head, _, tail = var_name.partition('.')
            parts = tail.split('.') if tail else []
            if head == 'entity':
                resolved = _walk_dict(context.entity, parts)
                if resolved is not None:
                    return resolved
            elif head == 'step_results':
                resolved = _walk_dict(context.step_results, parts)
                if resolved is not None:
                    return resolved
            elif head == 'context':
                resolved = _lookup_context(parts)
                if resolved is not None:
                    return resolved
        # leave placeholder intact when unresolved
        return match.group(0)

    # Support both ${var} and {{var}} syntax
    result = re.sub(r'\$\{([^}]+)\}', _replace, template)
    result = re.sub(r'\{\{([^}]+)\}\}', _replace, result)
    return result


@dataclass
class StepContext:
    """Context for step execution."""
    entity: Dict[str, Any]
    entity_type: str
    entity_id: str
    entity_name: Optional[str]
    user_email: Optional[str]
    trigger_context: Optional[TriggerContext]
    execution_id: str
    workflow_id: str
    workflow_name: str
    step_results: Dict[str, Any]  # Results from previous steps
    # subscribe-on-behalf-of-group/SP. Resolved via
    # ${context.on_behalf_of.value|.type|.display} in webhook bodies +
    # grant_permissions principal_variable. None when subscribing for self.
    on_behalf_of: Optional[Dict[str, str]] = None
    # Id of the step being executed (WorkflowStep.step_id), set by the
    # executor before each step
    step_id: Optional[str] = None


@dataclass
class StepResult:
    """Result of step execution."""
    passed: bool
    message: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    blocking: bool = False  # If True, workflow pauses (e.g., approval)


class StepHandler(ABC):
    """Base class for step handlers."""

    def __init__(self, db: Session, config: Dict[str, Any]):
        self._db = db
        self._config = config

    @abstractmethod
    def execute(self, context: StepContext) -> StepResult:
        """Execute the step.
        
        Args:
            context: Step execution context
            
        Returns:
            StepResult with execution outcome
        """
        pass


# Step error code of an approval rejected without a reason
APPROVAL_REJECTED = 'approval_rejected'


class _ReviewStepRefused(Exception):
    """A lifecycle step of a product review outcome was refused."""


class RuleEntityLoadError(RuntimeError):
    """The stored entity a rule needs could not be loaded.

    Carries a stable code and parameters next to the English message, so the
    UI can show the step's error in the user's language.
    """

    code = 'rule_entity_load_failed'

    def __init__(self, entity_type: Optional[str], entity_id: Optional[str]):
        self.params = {'entityType': entity_type, 'entityId': entity_id}
        super().__init__(f"Could not load {entity_type} {entity_id} to evaluate the rule")


class RuleEntityNotFoundError(RuntimeError):
    """The entity a rule is about no longer exists (or never did).

    Same shape as ``RuleEntityLoadError``: a stable code and parameters next
    to the English message.
    """

    code = 'rule_entity_not_found'

    def __init__(self, entity_type: Optional[str], entity_id: Optional[str]):
        self.params = {'entityType': entity_type, 'entityId': entity_id}
        super().__init__(f"{entity_type} {entity_id} was not found, so the rule can't be evaluated")


def _rule_step_error(error: Exception, data: Optional[Dict[str, Any]] = None) -> 'StepResult':
    """Failed result of a rule step (validation, conditional, policy check).

    Errors with a code (``RuleEntityLoadError``) also put it in the result
    data, as ``error_code`` / ``error_params``; the English text stays in
    ``error``.
    """
    data = dict(data or {})
    code = getattr(error, 'code', None)
    if code:
        data['error_code'] = code
        data['error_params'] = getattr(error, 'params', {})
    return StepResult(passed=False, error=str(error), data=data or None)


def _rule_object(db: Session, context: 'StepContext') -> Dict[str, Any]:
    """What workflow rules see as ``obj``: the stored entity plus the trigger payload.

    Trigger payloads are small (often just name and status), so a rule on any
    other field passed vacuously. For data products and data contracts the
    entity is loaded with ``entity_dict_builder`` (the fields maturity gates
    use); payload keys win, so request fields such as ``current_status`` keep
    their meaning. Other entity types get the payload unchanged, and so do
    ``before_update`` gates: their payload is the proposed change, and values
    derived from the stored row (``has_owner``, counts) would describe the
    entity before it.

    Raises when the stored entity can't be loaded, or doesn't exist (deleted
    while a workflow waited, or a wrong id): evaluating the rule on the payload
    alone could let it pass on fields the payload doesn't carry, so the step
    fails instead (its handler turns the error into a failed result).
    ``before_create`` gates keep the payload: their entity isn't stored yet.
    ``on_delete`` workflows keep it too: they fire after the row is deleted,
    so there is nothing stored to load.
    """
    from src.controller.entity_dict_builder import (
        build_data_contract_dict,
        build_data_product_dict,
    )

    payload = context.entity if isinstance(context.entity, dict) else {}
    trigger_type = getattr(getattr(context, 'trigger_context', None), 'trigger_type', None)
    if getattr(trigger_type, 'value', trigger_type) in ('before_update', 'before_create', 'on_delete'):
        return payload
    builder = {
        'data_product': build_data_product_dict,
        'data_contract': build_data_contract_dict,
    }.get((context.entity_type or '').lower())
    if not builder or not context.entity_id:
        return payload
    try:
        # Savepoint: a failed query must not leave the session that the
        # workflow and its caller keep using in an aborted transaction.
        with db.begin_nested():
            stored = builder(db, context.entity_id)
    except Exception as e:
        # The database error stays in the server log; the step result shows
        # only what failed.
        raise RuleEntityLoadError(context.entity_type, context.entity_id) from e
    if not stored:
        raise RuleEntityNotFoundError(context.entity_type, context.entity_id)
    return {**stored, **payload}


# Workflow entity types under the name compliance rules (MATCH) and
# AppEntityLoader give them, where the two differ.
_COMPLIANCE_TYPES = {'data_asset_review': 'review'}


def _proposed_tags(db: Session, tags: Any) -> Dict[str, Any]:
    """Proposed tag assignments (``AssignedTagCreate`` dicts) as AppEntityLoader's tags.

    Keyed by ``namespace/name`` and, when no other proposed tag has the same
    name, by name; the value is the assigned value, or True when it has none.
    """
    from src.db_models.tags import TagDb
    from src.models.tags import DEFAULT_NAMESPACE_NAME, TAG_NAMESPACE_SEPARATOR as SEP

    assigned = []
    for tag in tags or []:
        if not isinstance(tag, dict):
            continue
        fqn = tag.get('tag_fqn')
        if tag.get('tag_id'):
            # As in AssignedTagCreate, the id wins over the name
            stored = db.get(TagDb, tag['tag_id'])
            fqn = f"{stored.namespace_name}{SEP}{stored.name}" if stored else None
        if not fqn:
            continue
        if SEP not in fqn:
            fqn = f"{DEFAULT_NAMESPACE_NAME}{SEP}{fqn}"
        value = tag.get('assigned_value')
        assigned.append((fqn, fqn.split(SEP, 1)[1], True if value is None else value))
    # As in _tags_by_entity: the name is a key when one namespace has it
    names = [name for _, name in {(fqn, name) for fqn, name, _ in assigned}]
    values: Dict[str, Any] = {}
    for fqn, name, value in assigned:
        values[fqn] = value
        if names.count(name) == 1:
            values[name] = value
    return values


def _proposed_values(db: Session, payload: Dict[str, Any]) -> Dict[str, Any]:
    """A before_update payload's values under AppEntityLoader's keys.

    The payload is the data contract update request (ODCS field names). A
    field the request clears stays cleared (None).
    """
    proposed = {}
    if 'tags' in payload:
        proposed['tags'] = _proposed_tags(db, payload['tags'])
    if 'owner_team_id' in payload:
        proposed['owner'] = payload['owner_team_id']
    if 'descriptionPurpose' in payload or 'description' in payload:
        # As DataContractsManager stores it: descriptionPurpose, else description.purpose
        description = payload.get('description')
        purpose = description.get('purpose') if isinstance(description, dict) else description
        proposed['description'] = payload.get('descriptionPurpose') or purpose
    return proposed


def _policy_rule_object(db: Session, context: 'StepContext') -> Dict[str, Any]:
    """What a policy check's rule sees as ``obj``: the entity as a compliance run sees it.

    For the types AppEntityLoader reads, the dict it gives a run
    (``description``, ``owner``, ``tags``...) over ``_rule_object``: the
    other triggers fire on the stored entity, and their payload's
    ``description`` / ``tags`` have the request's shape, not the run's.
    Payload keys the loader doesn't have stay. ``before_update`` gates still
    see only the proposed change (see ``_rule_object``), with its values
    also under the loader's keys; ``before_create`` has no stored entity.
    """
    from src.common.compliance_entities import AppEntityLoader

    obj = _rule_object(db, context)
    payload = context.entity if isinstance(context.entity, dict) else {}
    trigger_type = getattr(getattr(context, 'trigger_context', None), 'trigger_type', None)
    trigger_type = getattr(trigger_type, 'value', trigger_type)
    if trigger_type == 'before_update':
        try:
            # Savepoint and coded error as in _rule_object (it may read tags)
            with db.begin_nested():
                proposed = _proposed_values(db, payload)
        except Exception as e:
            raise RuleEntityLoadError(context.entity_type, context.entity_id) from e
        return {**obj, **proposed}
    entity_type = (context.entity_type or '').lower()
    entity_type = _COMPLIANCE_TYPES.get(entity_type, entity_type)
    if (
        trigger_type == 'before_create'
        or entity_type not in AppEntityLoader.SUPPORTED_TYPES
        or not context.entity_id
    ):
        return obj
    try:
        loaded = AppEntityLoader(db).load_entity(entity_type, str(context.entity_id))
    except Exception as e:
        # As in _rule_object: the cause stays in the server log
        raise RuleEntityLoadError(context.entity_type, context.entity_id) from e
    return {**obj, **loaded} if loaded else obj


class ValidationStepHandler(StepHandler):
    """Handler for validation steps using compliance DSL."""

    def execute(self, context: StepContext) -> StepResult:
        from src.common.compliance_dsl import evaluate_rule_on_object
        
        rule = self._config.get('rule', '')
        if not rule:
            return StepResult(passed=False, error="No rule configured")
        
        try:
            passed, message = evaluate_rule_on_object(rule, _rule_object(self._db, context))
            # A failed rule's message is the step's error, so it is stored with
            # the step and shown under it in the execution dialog.
            return StepResult(
                passed=passed,
                message=message,
                error=None if passed else message,
                data={'rule': rule}
            )
        except Exception as e:
            logger.exception(f"Validation step failed: {e}")
            return _rule_step_error(e)


# Trigger entities that stand in for the real entity owners are assigned to.
# on_request_access fires on entity_type=access_grant, where context.entity_id
# is the request's UUID; the trigger firer puts the underlying entity under
# context.entity['entity_type'] / ['entity_id']. on_subscribe already fires on
# the data product itself, so the list is intentionally narrow.
_PROXY_ENTITY_TYPES = {'access_grant'}


def _underlying_entity(context: 'StepContext') -> Tuple[str, str]:
    """(entity_type, entity_id) that owners and Business Owners are assigned to."""
    entity = context.entity if isinstance(context.entity, dict) else {}
    if (context.entity_type or '').lower() not in _PROXY_ENTITY_TYPES or not entity:
        return context.entity_type, context.entity_id
    underlying_id = entity.get('entity_id')
    underlying_type = entity.get('entity_type')
    if not (underlying_id and underlying_type):
        logger.warning(
            "Proxy entity_type=%s has no entity.entity_type/entity_id to traverse to; "
            "falling back to context.entity_id=%s (owner lookups will likely be empty)",
            context.entity_type, context.entity_id,
        )
        return context.entity_type, context.entity_id
    logger.info(
        "Traversing proxy entity_type=%s entity_id=%s -> underlying %s=%s",
        context.entity_type, context.entity_id, underlying_type, underlying_id,
    )
    return underlying_type, underlying_id


def _requester_email(context: 'StepContext') -> Optional[str]:
    """The user who made the request the workflow handles.

    After an approval, ``resume_workflow`` sets ``context.user_email`` to the
    approver (the user acting now); the requester stays in the trigger context.
    """
    trigger_context = getattr(context, 'trigger_context', None)
    requester = getattr(trigger_context, 'user_email', None)
    if requester:
        return requester
    if context.user_email:
        _log_requester_fallback(context)
    return context.user_email


def _log_requester_fallback(context: 'StepContext') -> None:
    """Warn, once per step, that the acting user stands in for the requester.

    The trigger context has no requester, so recipients, owner exclusion and
    requester-sourced grants use the acting user, which may be someone else.
    Emails are left out of the log; the ids locate the execution.
    """
    step_id = getattr(context, 'step_id', None)
    if getattr(context, '_requester_fallback_step', None) == (step_id,):
        return
    context._requester_fallback_step = (step_id,)
    logger.warning(
        "No requester in the trigger context (workflow=%s, execution=%s, step=%s); "
        "using the acting user as the requester",
        getattr(context, 'workflow_id', None),
        getattr(context, 'execution_id', None),
        step_id,
    )


def _entity_owner_emails(db: Session, context: 'StepContext') -> List[str]:
    """Owners of the trigger entity (see ``resolve_owner_emails``)."""
    from src.repositories.entity_owners_repository import resolve_owner_emails

    return resolve_owner_emails(db, *_underlying_entity(context))


# Approver tokens used by the default workflows that have no app role in a
# default install (normalized: lowercase, no spaces or underscores).
_OWNER_APPROVER_TOKENS = {
    'domainowner': 'DomainOwner',
    'domainowners': 'DomainOwner',
    'contractapprover': 'ContractApprover',
}


def _owner_approvers(
    db: Session, role_name: str, context: 'StepContext', token: Optional[str] = None,
) -> List[tuple]:
    """Approvers for the 'DomainOwner' / 'ContractApprover' tokens.

    An app role with that name wins (an admin may have created one).
    Otherwise 'DomainOwner' resolves to the owners of the entity's domain and
    'ContractApprover' to the owners of the entity itself (the data
    contract), leaving out the requester. When nobody is left, the request
    goes to the Data Steward and Admin roles instead of a recipient no user
    matches; handle-approval refuses the requester's own decision.
    """
    from src.db_models.settings import AppRoleDb
    from src.repositories.entity_owners_repository import (
        resolve_domain_owner_emails,
        resolve_owner_emails,
    )

    role = db.query(AppRoleDb).filter(AppRoleDb.name == role_name).first()
    if role:
        return [(role.name, role.id)]
    # Also the token as written (e.g. an app role named 'Domain Owners')
    names = {role_name.lower(), (token or '').lower().replace(' ', '').replace('_', '')}
    for r in db.query(AppRoleDb).all():
        if r.name.lower().replace(' ', '').replace('_', '') in names:
            return [(r.name, r.id)]

    entity_type, entity_id = _underlying_entity(context)
    if role_name == 'DomainOwner':
        emails = resolve_domain_owner_emails(db, entity_type, entity_id)
    else:
        emails = resolve_owner_emails(db, entity_type, entity_id)
    # The requester is often an owner; they must not approve their own request.
    requester = (_requester_email(context) or '').lower()
    emails = [email for email in emails if email.lower() != requester]
    if emails:
        return [(email, None) for email in emails]

    # Fallback: the Data Stewards, and the admins, who are told that no owner
    # other than the requester was found. The requester may be a steward or an
    # admin; handle-approval refuses their own decision on an owner approval.
    logger.warning(
        "No %s other than the requester found for %s %s; "
        "requesting approval from Data Stewards and admins",
        role_name, entity_type, entity_id,
    )
    return (
        _resolve_role_to_users(db, 'data_stewards', context)
        + _resolve_role_to_users(db, 'admins', context)
    )


def _resolve_role_to_users(
    db: Session,
    role_spec: str,
    context: 'StepContext',
) -> List[tuple]:
    """Resolve a role specification to a list of (identifier, role_id_or_None) tuples.

    Handles:
    - 'requester' / 'trigger_user' → original user email
    - 'entity_owner' → owners of the trigger entity (``resolve_owner_emails``)
    - 'owner' → ``owner`` field of the trigger entity, else as 'entity_owner'
    - 'domain_owners' / 'DomainOwner' / 'ContractApprover' → see ``_owner_approvers``
    - 'business:<uuid>' → business role → look up entity owners from business_owners table
    - '<uuid>' → app role UUID
    - 'user@email.com' → direct email
    - Legacy aliases like 'data_stewards', 'admins', etc.
    - **Comma-separated list of any of the above** → recurse on each
      segment, flatten results. This is what the Workflow Designer's
      "Custom principals" toggle emits: a role/literal token from the
      Select plus any users / groups picked from the PrincipalPicker.
    """
    from src.db_models.settings import AppRoleDb
    from src.db_models.business_roles import BusinessRoleDb
    from src.db_models.business_owners import BusinessOwnerDb

    # Recursion gate for the mixed-shape list. We check for ``,`` first
    # so each segment hits the rest of this function in isolation and
    # role tokens / aliases / business: prefixes still resolve.
    if ',' in role_spec:
        out: List[tuple] = []
        seen: set = set()
        for segment in role_spec.split(','):
            seg = segment.strip()
            if not seg:
                continue
            for identifier, role_uuid in _resolve_role_to_users(db, seg, context):
                if not identifier:
                    continue
                key = (identifier, role_uuid)
                if key not in seen:
                    seen.add(key)
                    out.append((identifier, role_uuid))
        return out

    # Map shorthand names to role names (legacy support)
    role_aliases = {
        'project_owners': 'ProjectOwner',
        'data_stewards': 'DataSteward',
        'data_steward': 'DataSteward',
        'admins': 'Admin',
    }

    # 'trigger_user' is the name the default workflows use for the requester.
    if role_spec in ('requester', 'trigger_user'):
        requester = _requester_email(context)
        return [(requester, None)] if requester else []

    if role_spec == 'entity_owner':
        return [(email, None) for email in _entity_owner_emails(db, context)]

    if role_spec == 'owner':
        # Most trigger payloads (e.g. on_publish / on_unpublish) carry no
        # `owner`; fall back to the entity's owners.
        owner = context.entity.get('owner') if context.entity else None
        if owner:
            return [(owner, None)]
        return [(email, None) for email in _entity_owner_emails(db, context)]

    owner_approver = _OWNER_APPROVER_TOKENS.get(role_spec.lower().replace(' ', '').replace('_', ''))
    if owner_approver:
        return _owner_approvers(db, owner_approver, context, token=role_spec)

    if role_spec in role_aliases:
        role_name = role_aliases[role_spec]
        role = db.query(AppRoleDb).filter(AppRoleDb.name == role_name).first()
        if not role:
            # Try normalized match
            normalized = role_name.lower().replace(' ', '')
            for r in db.query(AppRoleDb).all():
                if r.name.lower().replace(' ', '') == normalized:
                    return [(r.name, r.id)]
        return [(role_name, role.id if role else None)]

    # Strip "user:" prefix emitted by the PrincipalPicker (e.g. "user:foo@bar.com").
    if role_spec.startswith('user:'):
        role_spec = role_spec[len('user:'):]

    if '@' in role_spec:
        # Pre-comma-split single email -- treat as a direct recipient.
        return [(role_spec, None)]

    # Business role: prefixed with "business:"
    if role_spec.startswith('business:'):
        br_id = role_spec[len('business:'):]
        br = db.query(BusinessRoleDb).filter(BusinessRoleDb.id == br_id).first()
        if not br:
            logger.warning(f"Business role {br_id} not found")
            return []

        _, lookup_object_id = _underlying_entity(context)

        # Runtime resolution: look up who holds this business role for this entity
        owners = (
            db.query(BusinessOwnerDb)
            .filter(
                BusinessOwnerDb.role_id == br.id,
                BusinessOwnerDb.object_id == lookup_object_id,
                BusinessOwnerDb.is_active.is_(True),
            )
            .all()
        )

        if not owners:
            # No one assigned this role for this entity
            logger.warning(
                f"No active {br.name} assigned to object_id={lookup_object_id} "
                f"(triggered on {context.entity_type} {context.entity_id} / "
                f"{context.entity_name})"
            )
            return []

        return [(o.user_email, str(br.id)) for o in owners]

    # App role UUID (preferred new format)
    role_by_id = db.query(AppRoleDb).filter(AppRoleDb.id == role_spec).first()
    if role_by_id:
        return [(role_by_id.name, role_by_id.id)]

    # Fallback: role name (legacy), ignoring case, spaces and underscores so
    # 'data_steward' matches 'Data Steward'
    normalized = role_spec.lower().replace(' ', '').replace('_', '')
    for r in db.query(AppRoleDb).all():
        if r.name.lower().replace(' ', '').replace('_', '') == normalized:
            return [(r.name, r.id)]

    return [(role_spec, None)]


# Map raw entity_type strings to human-friendly labels used in approval
# notification subtitles/descriptions. Anything not listed falls back to a
# title-cased version of the raw string.
_ENTITY_TYPE_LABELS: Dict[str, str] = {
    "data_product": "Data Product",
    "data_contract": "Data Contract",
    "data_domain": "Data Domain",
    "data_asset_review": "Data Asset Review",
    "access_grant": "Access Grant",
    "asset": "Asset",
}


def _humanize_entity_type(entity_type: Optional[str]) -> str:
    if not entity_type:
        return "Entity"
    label = _ENTITY_TYPE_LABELS.get(entity_type.lower())
    if label:
        return label
    return entity_type.replace("_", " ").title()


def _extract_approval_facets(context: "StepContext") -> Dict[str, Any]:
    """Pull readable request facets out of the trigger entity_data.

    The approval step is generic, but the most common payload — access
    grant requests — carries the underlying resource + permission/duration/
    reason inside ``context.entity`` (which is the splatted ``entity_data``
    from ``AccessGrantsManager.create_request``). We surface these so the
    notification subtitle/description and the Approve/Reject dialog can
    show meaningful context instead of bare UUIDs.

    Returns a dict of optional keys. Callers should ``dict.get`` defensively
    because non-access-grant triggers won't populate any of these.
    """
    facets: Dict[str, Any] = {}
    entity = context.entity if isinstance(context.entity, dict) else {}

    # For ``access_grant`` triggers the proxy ``entity_type`` is
    # ``access_grant``; the underlying object (data product, contract, …)
    # is carried inside ``entity_data`` and is what an approver actually
    # wants to inspect / link to.
    if context.entity_type and context.entity_type.lower() == "access_grant":
        underlying_type = entity.get("entity_type")
        underlying_id = entity.get("entity_id")
        underlying_name = (
            entity.get("entity_name")
            or entity.get("data_product_name")
        )
        if underlying_type:
            facets["underlying_entity_type"] = str(underlying_type)
        if underlying_id:
            facets["underlying_entity_id"] = str(underlying_id)
        if underlying_name:
            facets["underlying_entity_name"] = str(underlying_name)

        permission = entity.get("permission_level")
        if permission:
            facets["permission_level"] = str(permission)

        duration = entity.get("requested_duration_days")
        if isinstance(duration, (int, float)):
            facets["requested_duration_days"] = int(duration)
        elif isinstance(duration, str) and duration.strip().isdigit():
            facets["requested_duration_days"] = int(duration.strip())

        reason = entity.get("reason")
        if reason:
            facets["reason"] = str(reason)

        request_id = entity.get("request_id") or context.entity_id
        if request_id:
            facets["request_id"] = str(request_id)

    # --- Universal extras (all trigger types) ---

    on_behalf_of = entity.get("on_behalf_of")
    if isinstance(on_behalf_of, dict) and on_behalf_of.get("type") and on_behalf_of.get("value"):
        facets["on_behalf_of"] = {
            "type": str(on_behalf_of["type"]),
            "value": str(on_behalf_of["value"]),
        }

    step_results = entity.get("step_results") or entity.get("required_fields_answers")
    if isinstance(step_results, dict) and step_results:
        facets["step_results"] = step_results

    # Full entity_data for the frontend's generic key→value detail section.
    if entity:
        facets["full_payload"] = dict(entity)

    return facets


def _build_approval_subtitle(
    context: "StepContext",
    facets: Dict[str, Any],
    entity_display: str,
) -> str:
    """Readable subtitle for the approval notification card.

    Examples:
        - "Read access to Data Product: Sales Pipeline"
        - "Data Contract: orders-v1"
    """
    if context.entity_type and context.entity_type.lower() == "access_grant":
        permission = facets.get("permission_level")
        underlying_type_label = _humanize_entity_type(
            facets.get("underlying_entity_type")
        )
        if permission and facets.get("underlying_entity_name"):
            return (
                f"{permission.title()} access to {underlying_type_label}: "
                f"{facets['underlying_entity_name']}"
            )
        if facets.get("underlying_entity_name"):
            return (
                f"Access to {underlying_type_label}: "
                f"{facets['underlying_entity_name']}"
            )
        # Fallback: no underlying entity resolved — at least avoid showing
        # the raw access_grant UUID.
        return f"Access request from {_requester_email(context) or 'unknown user'}"

    return f"{_humanize_entity_type(context.entity_type)}: {entity_display}"


def _build_approval_description(
    *,
    context: "StepContext",
    facets: Dict[str, Any],
    approval_message: Optional[str],
) -> str:
    """Multi-line, label/value description for the approval notification.

    Mirrors what the dialog renders but as plain text so the bell card and
    email recipients see the same information.
    """
    lines: List[str] = []

    requester = _requester_email(context) or "Unknown"
    lines.append(f"Requester: {requester}")

    underlying_type = facets.get("underlying_entity_type")
    if underlying_type:
        resource_label = _humanize_entity_type(underlying_type)
        resource_name = (
            facets.get("underlying_entity_name")
            or facets.get("underlying_entity_id")
            or ""
        )
        if resource_name:
            lines.append(f"Resource: {resource_label} · {resource_name}")
        else:
            lines.append(f"Resource: {resource_label}")
    elif context.entity_name or context.entity_id:
        resource_label = _humanize_entity_type(context.entity_type)
        resource_name = context.entity_name or context.entity_id
        lines.append(f"Resource: {resource_label} · {resource_name}")

    permission = facets.get("permission_level")
    if permission:
        lines.append(f"Permission: {permission}")

    duration = facets.get("requested_duration_days")
    if isinstance(duration, int):
        lines.append(f"Duration: {duration} day{'s' if duration != 1 else ''}")

    reason = facets.get("reason")
    if reason:
        lines.append(f"Reason: {reason}")

    if approval_message:
        lines.append(f"Workflow message: {approval_message}")

    # Optional free-form fields carried on the entity. Mirrors the legacy
    # behaviour for non-access-grant approval payloads.
    entity = context.entity if isinstance(context.entity, dict) else {}
    msg = entity.get("message")
    if msg and msg != approval_message:
        lines.append(f"Message: {msg}")
    justification = entity.get("justification")
    if justification and justification != reason:
        lines.append(f"Justification: {justification}")

    return "\n".join(lines)


class ApprovalStepHandler(StepHandler):
    """Handler for approval steps - creates actionable notifications and pauses workflow."""

    def execute(self, context: StepContext) -> StepResult:
        from uuid import uuid4
        from src.models.notifications import Notification, NotificationType
        from src.repositories.notification_repository import notification_repo
        
        # Default workflows loaded before 'approvers' was used in the YAML
        # store the approver under 'approver_role'; accept it so existing
        # databases keep working without reloading the defaults.
        approvers = self._config.get('approvers') or self._config.get('approver_role', '')
        timeout_days = self._config.get('timeout_days', 7)
        require_all = self._config.get('require_all', False)
        approval_message = self._config.get('message', '')
        
        if not approvers:
            return StepResult(passed=False, error="No approvers configured")

        # Render ${entity_name} etc., as notification steps do.
        if approval_message:
            approval_message = substitute_template(approval_message, context)

        try:
            # Resolve approvers - returns list of (identifier, role_id or None)
            resolved_approvers = self._resolve_approvers(approvers, context)
            
            if not resolved_approvers:
                return StepResult(passed=False, error="Could not resolve any approvers")
            
            # Extract human-readable facets from the trigger's entity_data so
            # the notification + approval dialog can show the underlying
            # request (requester, resource, permission, duration, reason)
            # instead of just the proxy ``access_grant`` UUID. Best-effort —
            # the approval step is generic and only access-grant triggers
            # populate these fields today.
            facets = _extract_approval_facets(context)

            entity_display = (
                facets.get("underlying_entity_name")
                or context.entity_name
                or facets.get("underlying_entity_id")
                or context.entity_id
            )

            # Create actionable notification for each approver
            created_count = 0
            for approver_id, role_uuid in resolved_approvers:
                try:
                    subtitle = _build_approval_subtitle(context, facets, entity_display)
                    description = _build_approval_description(
                        context=context,
                        facets=facets,
                        approval_message=approval_message,
                    )
                    # Keys of its texts, so the bell shows them in the user's language
                    i18n_data = approval_notification_i18n(
                        description, self._config.get('message'), approval_message,
                        lambda name: substitute_template('${' + name + '}', context),
                        _ENTITY_TYPE_LABELS,
                    )

                    notification = Notification(
                        id=str(uuid4()),
                        created_at=datetime.utcnow(),
                        type=NotificationType.ACTION_REQUIRED,
                        title="Approval Required",
                        subtitle=subtitle,
                        description=description,
                        recipient=approver_id,  # Keep for backwards compat / email recipients
                        recipient_role_id=role_uuid,  # Store role UUID if this is a role
                        action_type="workflow_approval",
                        action_payload={
                            "execution_id": context.execution_id,
                            # The approval step this notification is for, so
                            # only its approvers can answer it
                            "step_id": context.step_id,
                            "workflow_id": context.workflow_id,
                            "workflow_name": context.workflow_name,
                            "entity_type": context.entity_type,
                            "entity_id": context.entity_id,
                            "entity_name": context.entity_name,
                            "requester_email": _requester_email(context),
                            "timeout_days": timeout_days,
                            # Structured request context for the approval
                            # dialog. All optional; only access-grant
                            # triggers populate the underlying_* / request_*
                            # fields today.
                            **facets,
                            "workflow_message": approval_message or None,
                        },
                        can_delete=False,  # Must respond to this notification
                        read=False,
                        data=i18n_data,
                    )
                    notification_repo.create(db=self._db, obj_in=notification)
                    created_count += 1
                    logger.info(f"Approval notification created for {approver_id}" + (f" (role: {role_uuid})" if role_uuid else ""))
                except Exception as e:
                    logger.warning(f"Failed to create approval notification for {approver_id}: {e}")
            
            if created_count == 0:
                return StepResult(
                    passed=False,
                    error="Failed to create approval notifications",
                    data={'approvers': [a[0] for a in resolved_approvers]}
                )
            
            # Return blocking=True to pause workflow and wait for approval
            return StepResult(
                passed=True,  # Initial pass, actual result comes when approval is handled
                message=f"Approval requested from: {', '.join(a[0] for a in resolved_approvers)}",
                data={
                    'approvers': [a[0] for a in resolved_approvers],
                    'timeout_days': timeout_days,
                    'require_all': require_all,
                    'status': 'pending',
                    'notifications_created': created_count,
                },
                blocking=True,  # Pause workflow until resume_workflow() is called
            )
        except Exception as e:
            logger.exception(f"Approval step failed: {e}")
            return StepResult(passed=False, error=str(e))

    def _resolve_approvers(self, approvers: str, context: StepContext) -> List[tuple]:
        """Resolve approver specification to list of (identifier, role_uuid) tuples."""
        return _resolve_role_to_users(self._db, approvers, context)


class NotificationStepHandler(StepHandler):
    """Handler for notification steps - sends notifications via NotificationsManager."""

    def execute(self, context: StepContext) -> StepResult:
        from uuid import uuid4
        from src.models.notifications import Notification, NotificationType
        from src.repositories.notification_repository import notification_repo
        
        recipients = self._config.get('recipients', '')
        template = self._config.get('template', '')
        custom_message = self._config.get('custom_message')
        
        if not recipients:
            return StepResult(passed=False, error="No recipients configured")
        
        try:
            # Resolve recipients
            resolved_recipients = self._resolve_recipients(recipients, context)
            
            # Build notification message with variable substitution
            raw_message = custom_message or self._get_template_message(template, context)
            message = substitute_template(raw_message, context)
            title = substitute_template(self._get_template_title(template, context), context)
            # Keys of the built-in texts, so the bell shows them in the user's language
            i18n_data = notification_step_i18n(
                template, custom_message, context.entity_type,
                context.entity_name or context.entity_id,
                lambda name: substitute_template('${' + name + '}', context),
            )
            
            # Determine notification type based on template
            notification_type = self._get_notification_type(template)
            
            # Determine if this is an actionable notification (for approvals)
            action_type = None
            action_payload = None
            can_delete = True
            
            if template in ('approval_requested', 'request_submitted'):
                # This will be handled by the approval step, not notification
                pass
            elif template in ('request_approved', 'request_rejected'):
                can_delete = True
            
            # Resolve channels: step config overrides global defaults
            channels = self._config.get('channels') or self._get_default_channels()

            # Non-blocking: strip 'email' if present in legacy/saved configs.
            # Email is out of scope in v1 (non-portable across customer environments).
            if channels and 'email' in channels:
                logger.warning(
                    "'email' channel is not supported in v1 (non-portable across customer environments). "
                    "Stripping from channels — use 'webhook' to your own email provider instead."
                )
                channels = [c for c in channels if c != 'email']
            
            # Typed-ID manual runs have no entity name: fall back to the id and
            # leave the subtitle out when neither is known.
            subtitle_ref = context.entity_name or context.entity_id
            subtitle = f"{context.entity_type}: {subtitle_ref}" if subtitle_ref else None

            created_count = 0
            email_count = 0
            # The in-app notices, so a later step can withdraw one (see
            # WorkflowExecutor._withdraw_approval_notices)
            notices: List[Dict[str, str]] = []

            # --- in_app channel ---
            if 'in_app' in channels:
                for recipient_id, role_uuid in resolved_recipients:
                    try:
                        notification = Notification(
                            id=str(uuid4()),
                            created_at=datetime.utcnow(),
                            type=notification_type,
                            title=title,
                            subtitle=subtitle,
                            description=message,
                            recipient=recipient_id,
                            recipient_role_id=role_uuid,
                            action_type=action_type,
                            action_payload=action_payload,
                            can_delete=can_delete,
                            read=False,
                            data=i18n_data,
                        )
                        notification_repo.create(db=self._db, obj_in=notification)
                        created_count += 1
                        notices.append({'id': notification.id, 'recipient': recipient_id})
                        logger.info(f"Notification created for {recipient_id}: {title}")
                    except Exception as e:
                        logger.warning(f"Failed to create notification for {recipient_id}: {e}")

            # --- email channel ---
            if 'email' in channels:
                try:
                    from src.common.email_service import EmailService
                    email_svc = EmailService.from_settings(self._db)
                    if email_svc:
                        email_addrs = [r[0] for r in resolved_recipients if '@' in r[0]]
                        if email_addrs:
                            sent = email_svc.send(
                                to=email_addrs,
                                subject=title,
                                body_text=message,
                            )
                            if sent:
                                email_count = len(email_addrs)
                    else:
                        logger.debug("Email channel requested but email not configured")
                except Exception as e:
                    logger.warning(f"Email channel failed: {e}")

            # --- webhook channel delegates to WebhookStepHandler internally ---
            if 'webhook' in channels:
                webhook_url = self._config.get('webhook_url')
                if webhook_url:
                    try:
                        import json as _json
                        import urllib.request
                        payload = _json.dumps({
                            'title': title,
                            'message': message,
                            'entity_type': context.entity_type,
                            'entity_id': context.entity_id,
                            'entity_name': context.entity_name,
                        }).encode()
                        req = urllib.request.Request(
                            webhook_url,
                            data=payload,
                            headers={'Content-Type': 'application/json'},
                            method='POST',
                        )
                        with urllib.request.urlopen(req, timeout=10):
                            pass
                    except Exception as e:
                        logger.warning(f"Webhook notification failed: {e}")

            total = created_count + email_count
            if total == 0:
                return StepResult(
                    passed=False,
                    error="Failed to create any notifications",
                    data={'recipients': [r[0] for r in resolved_recipients], 'template': template}
                )
            
            return StepResult(
                passed=True,
                message=f"Notification sent to: {', '.join(r[0] for r in resolved_recipients)}",
                data={
                    'recipients': [r[0] for r in resolved_recipients],
                    'template': template,
                    'message': message,
                    'created_count': created_count,
                    'email_count': email_count,
                    'channels': channels,
                    'notices': notices,
                }
            )
        except Exception as e:
            logger.exception(f"Notification step failed: {e}")
            return StepResult(passed=False, error=str(e))

    def _get_default_channels(self) -> List[str]:
        """Read global default notification channels from settings."""
        try:
            import json as _json
            from src.db_models.app_settings import AppSettingDb as SettingDb
            row = self._db.query(SettingDb).filter(SettingDb.key == "notification_channel_defaults").first()
            if row:
                cfg = _json.loads(row.value) if isinstance(row.value, str) else row.value
                return cfg.get("channels", ["in_app"])
        except Exception:
            pass
        return ["in_app"]

    def _resolve_recipients(self, recipients: str, context: StepContext) -> List[tuple]:
        """Resolve recipient specification to list of (identifier, role_uuid) tuples."""
        return _resolve_role_to_users(self._db, recipients, context)

    def _get_template_title(self, template: str, context: StepContext) -> str:
        """Get notification title from template."""
        return TEMPLATE_TITLES.get(template, DEFAULT_TEMPLATE_TITLE)

    def _get_template_message(self, template: str, context: StepContext) -> str:
        """Get message from template."""
        entity_display = context.entity_name or context.entity_id
        return TEMPLATE_MESSAGES.get(template, DEFAULT_TEMPLATE_MESSAGE).format(
            entity_type=context.entity_type, entity_name=entity_display,
        )

    def _get_notification_type(self, template: str) -> 'NotificationType':
        """Get notification type based on template."""
        from src.models.notifications import NotificationType
        
        if template in ('validation_failed', 'request_rejected', 'product_rejected', 'pii_detected'):
            return NotificationType.ERROR
        elif template in ('approval_requested',):
            return NotificationType.ACTION_REQUIRED
        elif template in ('validation_passed', 'request_approved', 'product_approved'):
            return NotificationType.SUCCESS
        else:
            return NotificationType.INFO


class AssignTagStepHandler(StepHandler):
    """Handler for tag assignment steps — persists via TagsManager."""

    def execute(self, context: StepContext) -> StepResult:
        key = self._config.get('key', '')
        value = self._config.get('value')
        value_source = self._config.get('value_source')
        
        if not key:
            return StepResult(passed=False, error="No tag key configured")
        
        try:
            if value_source:
                resolved_value = self._resolve_value_source(value_source, context)
            else:
                resolved_value = value
            
            if not resolved_value:
                return StepResult(passed=False, error="Could not resolve tag value")
            
            logger.info(f"Assigning tag {key}={resolved_value} to {context.entity_type} {context.entity_id}")

            # Persist via TagsManager
            persisted = False
            try:
                from src.controller.tags_manager import TagsManager
                tags_mgr = TagsManager()
                tag = tags_mgr.get_tag_by_fqn(db=self._db, fqn=key)
                if tag:
                    tags_mgr.add_tag_to_entity(
                        db=self._db,
                        entity_id=context.entity_id,
                        entity_type=context.entity_type,
                        tag_id=tag.id,
                        assigned_value=resolved_value,
                        user_email=context.user_email,
                    )
                    persisted = True
                else:
                    logger.warning(f"Tag '{key}' not found by FQN — context updated only")
            except Exception as e:
                logger.warning(f"TagsManager integration failed (context still updated): {e}")
            
            if 'tags' not in context.entity:
                context.entity['tags'] = {}
            context.entity['tags'][key] = resolved_value
            
            return StepResult(
                passed=True,
                message=f"Assigned tag {key}={resolved_value}" + (" (persisted)" if persisted else " (context only)"),
                data={'key': key, 'value': resolved_value, 'persisted': persisted}
            )
        except Exception as e:
            logger.exception(f"Assign tag step failed: {e}")
            return StepResult(passed=False, error=str(e))

    def _resolve_value_source(self, source: str, context: StepContext) -> Optional[str]:
        """Resolve dynamic value source."""
        if source == 'current_user':
            return context.user_email
        elif source == 'project_name':
            return context.entity.get('project_name') or context.entity.get('project_id')
        elif source == 'entity_name':
            return context.entity_name
        elif source == 'timestamp':
            return datetime.utcnow().isoformat()
        else:
            return None


class RemoveTagStepHandler(StepHandler):
    """Handler for tag removal steps — persists via TagsManager."""

    def execute(self, context: StepContext) -> StepResult:
        key = self._config.get('key', '')
        
        if not key:
            return StepResult(passed=False, error="No tag key configured")
        
        try:
            logger.info(f"Removing tag {key} from {context.entity_type} {context.entity_id}")

            # Persist via TagsManager
            persisted = False
            try:
                from src.controller.tags_manager import TagsManager
                tags_mgr = TagsManager()
                tag = tags_mgr.get_tag_by_fqn(db=self._db, fqn=key)
                if tag:
                    ok = tags_mgr.remove_tag_from_entity(
                        db=self._db,
                        entity_id=context.entity_id,
                        entity_type=context.entity_type,
                        tag_id=tag.id,
                        user_email=context.user_email,
                    )
                    persisted = ok
                else:
                    logger.warning(f"Tag '{key}' not found by FQN — context updated only")
            except Exception as e:
                logger.warning(f"TagsManager integration failed (context still updated): {e}")
            
            if 'tags' in context.entity and key in context.entity['tags']:
                del context.entity['tags'][key]
            
            return StepResult(
                passed=True,
                message=f"Removed tag {key}" + (" (persisted)" if persisted else " (context only)"),
                data={'key': key, 'persisted': persisted}
            )
        except Exception as e:
            logger.exception(f"Remove tag step failed: {e}")
            return StepResult(passed=False, error=str(e))


class ConditionalStepHandler(StepHandler):
    """Handler for conditional branching steps."""

    def execute(self, context: StepContext) -> StepResult:
        from src.common.compliance_dsl import Lexer, Parser, Evaluator
        
        condition = self._config.get('condition', '')
        if not condition:
            return StepResult(passed=False, error="No condition configured")
        
        try:
            # Parse and evaluate condition
            lexer = Lexer(condition)
            tokens = lexer.tokenize()
            parser = Parser(tokens)
            ast = parser.parse_expression()
            evaluator = Evaluator(_rule_object(self._db, context))
            result = evaluator.evaluate(ast)
            
            return StepResult(
                passed=bool(result),
                message=f"Condition evaluated to: {result}",
                data={'condition': condition, 'result': result}
            )
        except Exception as e:
            logger.exception(f"Conditional step failed: {e}")
            return _rule_step_error(e)


class ScriptStepHandler(StepHandler):
    """Handler for script execution steps."""

    def execute(self, context: StepContext) -> StepResult:
        language = self._config.get('language', 'python')
        code = self._config.get('code', '')
        timeout_seconds = self._config.get('timeout_seconds', 60)
        
        if not code:
            return StepResult(passed=False, error="No code configured")
        
        try:
            if language == 'python':
                result = self._execute_python(code, context, timeout_seconds)
            elif language == 'sql':
                result = self._execute_sql(code, context, timeout_seconds)
            else:
                return StepResult(passed=False, error=f"Unsupported language: {language}")
            
            return result
        except Exception as e:
            logger.exception(f"Script step failed: {e}")
            return StepResult(passed=False, error=str(e))

    _SAFE_BUILTINS = {
        'len': len, 'str': str, 'int': int, 'float': float, 'bool': bool,
        'list': list, 'dict': dict, 'tuple': tuple, 'set': set,
        'range': range, 'enumerate': enumerate, 'zip': zip,
        'sorted': sorted, 'reversed': reversed,
        'min': min, 'max': max, 'sum': sum, 'abs': abs, 'round': round,
        'any': any, 'all': all,
        'isinstance': isinstance, 'type': type,
        'print': print, 'repr': repr, 'hasattr': hasattr, 'getattr': getattr,
        'ValueError': ValueError, 'TypeError': TypeError, 'KeyError': KeyError,
        'True': True, 'False': False, 'None': None,
    }

    def _execute_python(self, code: str, context: StepContext, timeout: int) -> StepResult:
        """Execute Python code with safe builtins and a thread-based timeout."""
        import threading

        safe_globals = {
            '__builtins__': self._SAFE_BUILTINS,
            'entity': context.entity.copy(),
            'entity_type': context.entity_type,
            'entity_id': context.entity_id,
            'entity_name': context.entity_name,
            'user_email': context.user_email,
            'step_results': context.step_results.copy(),
        }

        local_vars: Dict[str, Any] = {}
        exec_error: List[Exception] = []

        def _run():
            try:
                exec(code, safe_globals, local_vars)
            except Exception as e:
                exec_error.append(e)

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=timeout)

        if thread.is_alive():
            return StepResult(passed=False, error=f"Script timed out after {timeout}s")

        if exec_error:
            return StepResult(passed=False, error=str(exec_error[0]))

        result = local_vars.get('result', {'passed': True})
        if isinstance(result, dict):
            return StepResult(
                passed=result.get('passed', True),
                message=result.get('message'),
                data=result.get('data'),
            )
        return StepResult(passed=bool(result))

    def _execute_sql(self, code: str, context: StepContext, timeout: int) -> StepResult:
        """Execute SQL via Databricks statement_execution API."""
        try:
            from src.common.workspace_client import get_workspace_client
            ws = get_workspace_client()

            # Resolve SQL warehouse ID from settings
            from src.db_models.app_settings import AppSettingDb as SettingDb
            import json as _json
            wh_row = self._db.query(SettingDb).filter(SettingDb.key == "sql_warehouse_id").first()
            if not wh_row or not wh_row.value:
                return StepResult(passed=False, error="No SQL warehouse configured in Settings")
            warehouse_id = wh_row.value.strip().strip('"')

            # Substitute variables in SQL
            resolved_sql = substitute_template(code, context)

            resp = ws.statement_execution.execute_statement(
                statement=resolved_sql,
                warehouse_id=warehouse_id,
                wait_timeout="50s",
            )

            status_state = resp.status.state.value if resp.status else "UNKNOWN"
            if status_state in ("SUCCEEDED",):
                row_count = resp.manifest.total_row_count if resp.manifest else 0
                return StepResult(
                    passed=True,
                    message=f"SQL executed successfully ({row_count} rows)",
                    data={
                        'sql': resolved_sql,
                        'row_count': row_count,
                        'state': status_state,
                    },
                )
            else:
                error_msg = ""
                if resp.status and resp.status.error:
                    error_msg = resp.status.error.message or str(resp.status.error)
                return StepResult(
                    passed=False,
                    error=f"SQL execution {status_state}: {error_msg}",
                    data={'sql': resolved_sql, 'state': status_state},
                )
        except Exception as e:
            logger.exception(f"SQL execution failed: {e}")
            return StepResult(passed=False, error=str(e))


class PassStepHandler(StepHandler):
    """Handler for terminal success steps."""

    def execute(self, context: StepContext) -> StepResult:
        return StepResult(passed=True, message="Workflow completed successfully")


class FailStepHandler(StepHandler):
    """Handler for terminal failure steps."""

    def execute(self, context: StepContext) -> StepResult:
        message = self._config.get('message', 'Workflow failed')
        return StepResult(passed=False, message=message)


class DeliveryStepHandler(StepHandler):
    """Handler for delivery steps - triggers change delivery via DeliveryService.
    
    Config options:
        change_type: Type of change (grant, revoke, tag_assign, etc.)
        modes: Optional list of delivery modes (direct, indirect, manual)
                If not specified, uses configured defaults
    """

    def execute(self, context: StepContext) -> StepResult:
        from src.controller.delivery_service import (
            get_delivery_service, 
            DeliveryPayload, 
            DeliveryChangeType,
            DeliveryMode,
        )
        
        change_type_str = self._config.get('change_type', 'grant')
        modes_str = self._config.get('modes', [])  # Empty = use defaults
        
        try:
            # Parse change type
            try:
                change_type = DeliveryChangeType(change_type_str)
            except ValueError:
                change_type = DeliveryChangeType.GRANT  # Default
            
            # Parse modes if specified
            modes = None
            if modes_str:
                modes = []
                for m in modes_str:
                    try:
                        modes.append(DeliveryMode(m))
                    except ValueError:
                        logger.warning(f"Unknown delivery mode: {m}")
            
            # Build payload from context
            payload = DeliveryPayload(
                change_type=change_type,
                entity_type=context.entity_type,
                entity_id=context.entity_id,
                data={
                    'entity': context.entity,
                    **self._config.get('data', {}),
                },
                user=context.user_email,
            )
            
            # Get delivery service and execute
            try:
                delivery_service = get_delivery_service()
            except RuntimeError:
                return StepResult(
                    passed=False,
                    error="Delivery service not initialized"
                )
            
            results = delivery_service.deliver(payload, modes=modes)
            
            if results.all_success:
                return StepResult(
                    passed=True,
                    message=f"Delivered via {len(results.results)} mode(s)",
                    data=results.to_dict()
                )
            elif results.any_success:
                return StepResult(
                    passed=True,
                    message=f"Partially delivered ({len([r for r in results.results if r.success])}/{len(results.results)} modes succeeded)",
                    data=results.to_dict()
                )
            else:
                return StepResult(
                    passed=False,
                    error="; ".join(results.errors) if results.errors else "All delivery modes failed",
                    data=results.to_dict()
                )
                
        except Exception as e:
            logger.exception(f"Delivery step failed: {e}")
            return StepResult(passed=False, error=str(e))


class PolicyCheckStepHandler(StepHandler):
    """Handler for policy check steps - evaluates existing compliance policy by UUID.

    As a compliance run does, the policy's MATCH and WHERE select the
    entities it applies to: a policy that doesn't select the step's entity
    passes it with ``not_applicable`` and ``reason`` (``match_type`` /
    ``where``) in the result data.
    """

    def execute(self, context: StepContext) -> StepResult:
        from src.db_models.compliance import CompliancePolicyDb
        from src.common.compliance_dsl import evaluate_rule_on_object
        
        policy_id = self._config.get('policy_id', '')
        if not policy_id:
            return StepResult(passed=False, error="No policy_id configured")
        
        try:
            # Look up policy by UUID
            policy = self._db.get(CompliancePolicyDb, policy_id)
            if not policy:
                return StepResult(
                    passed=False, 
                    error=f"Policy not found: {policy_id}",
                    data={'policy_id': policy_id}
                )
            
            # Skip inactive policies (treated as pass)
            if not policy.is_active:
                return StepResult(
                    passed=True, 
                    message=f"Policy '{policy.name}' is inactive, skipped",
                    data={'policy_id': policy_id, 'policy_name': policy.name, 'skipped': True}
                )
            
            parsed = self._parsed_rule(policy)
            if not self._match_selects(parsed, context):
                return self._not_applicable(policy, context, 'match_type')
            rule_object = _policy_rule_object(self._db, context)
            if not self._where_selects(parsed, policy, rule_object):
                return self._not_applicable(policy, context, 'where')

            # Evaluate the policy's rule against the entity
            passed, technical_message = evaluate_rule_on_object(policy.rule, rule_object)
            
            # Combine human-readable failure message with technical details
            if passed:
                message = technical_message
            else:
                # Show human-readable message first, then technical details
                if policy.failure_message:
                    message = f"{policy.failure_message}\n\nTechnical: {technical_message}"
                else:
                    message = technical_message
            
            return StepResult(
                passed=passed,
                message=message,
                data={
                    'policy_id': policy_id, 
                    'policy_name': policy.name, 
                    'rule': policy.rule,
                    'severity': policy.severity,
                    'failure_message': policy.failure_message,
                    'technical_message': technical_message,
                }
            )
        except Exception as e:
            logger.exception(f"Policy check step failed: {e}")
            return _rule_step_error(e, {'policy_id': policy_id})

    # MATCH and WHERE select the entities a compliance run checks; a policy
    # doesn't apply to an entity they don't select. A rule without MATCH
    # applies to any entity, and so does MATCH (obj:Object).

    @staticmethod
    def _parsed_rule(policy) -> Optional[Dict[str, Any]]:
        """The parsed rule, or None if it doesn't parse (ASSERT then fails it, as before)."""
        from src.common.compliance_dsl import parse_rule

        try:
            return parse_rule(policy.rule, source=f"policy {policy.id}")
        except ValueError:
            return None

    @staticmethod
    def _match_selects(parsed: Optional[Dict[str, Any]], context: StepContext) -> bool:
        match_type = ((parsed or {}).get('match_type') or '').lower()
        entity_type = (context.entity_type or '').lower()
        return match_type in ('', 'object', _COMPLIANCE_TYPES.get(entity_type, entity_type))

    @staticmethod
    def _where_selects(
        parsed: Optional[Dict[str, Any]], policy, rule_object: Dict[str, Any]
    ) -> bool:
        """Whether WHERE selects the entity; one it can't evaluate is excluded, as in a run."""
        from src.common.compliance_dsl import Evaluator

        where = (parsed or {}).get('where_clause')
        if where is None:
            return True
        try:
            return bool(Evaluator(rule_object).evaluate(where))
        except Exception:
            logger.exception(f"Failed to evaluate the WHERE clause of policy {policy.id}")
            return False

    @staticmethod
    def _not_applicable(policy, context: StepContext, reason: str) -> StepResult:
        return StepResult(
            passed=True,
            message=f"Policy '{policy.name}' does not apply to this {context.entity_type}",
            data={
                'policy_id': policy.id,
                'policy_name': policy.name,
                'not_applicable': True,
                'reason': reason,
            },
        )


class CreateAssetReviewStepHandler(StepHandler):
    """Handler for creating data asset review requests.
    
    This step creates a formal DataAssetReview record for tracking purposes,
    useful when workflows need to integrate with the data asset review system.
    
    Config options:
        reviewer_role: Who reviews (default: 'DataSteward'): any approver
            spec ``_resolve_role_to_users`` accepts (e.g. 'DomainOwner', an
            email), or a role name / UUID whose group members are looked up.
            A ``reviewer_email`` in the request wins.
        review_type: Type of review (default: 'standard')  
        notes: Additional notes for the review
        use_entity_as_asset: If true, uses the trigger entity as the asset to review
    """

    def execute(self, context: StepContext) -> StepResult:
        # Imports moved to where they're used below
        
        reviewer_role = self._config.get('reviewer_role', 'DataSteward')
        review_type = self._config.get('review_type', 'standard')
        notes = self._config.get('notes', '')
        use_entity_as_asset = self._config.get('use_entity_as_asset', True)
        
        try:
            # Get requester from trigger context (TriggerContext is a Pydantic model, not a dict)
            tc = context.trigger_context
            requester_email = tc.user_email if tc else None
            if not requester_email:
                requester_email = 'system@app.local'
            
            reviewer_email = self._resolve_reviewer(reviewer_role, context, requester_email)
            if not reviewer_email:
                # Nobody but the requester: they must not review their own request.
                # No asset review is created; the approval step that follows decides.
                logger.warning(
                    "No reviewer other than the requester found for role %s; "
                    "no asset review created", reviewer_role,
                )
                return StepResult(
                    passed=True,
                    message=(
                        f"No reviewer other than the requester found for {reviewer_role}; "
                        "no asset review created"
                    ),
                    data={'review_id': None, 'reviewer_email': None},
                )
            
            # Determine asset FQN
            asset_fqns = []
            title = None
            if use_entity_as_asset:
                # Try to get FQN from entity (TriggerContext attributes)
                entity_type = tc.entity_type if tc else ''
                entity_id = tc.entity_id if tc else ''
                entity_name = tc.entity_name if tc else ''
                
                # Debug logging
                logger.info(f"CreateAssetReview: entity_type={entity_type}, entity_id={entity_id}, entity_name={entity_name}")
                logger.info(f"CreateAssetReview: context.entity={context.entity}")
                logger.info(f"CreateAssetReview: tc.entity_data={tc.entity_data if tc else None}")
                
                # Build FQN based on entity - check both context.entity and trigger context entity_data
                entity_data = tc.entity_data if tc and tc.entity_data else {}
                
                if entity_type in ['asset', 'table', 'view']:
                    # For assets/tables/views, try to get fqn from entity data
                    fqn = (context.entity.get('fqn') or context.entity.get('table_fqn') or 
                           entity_data.get('fqn') or entity_data.get('table_fqn') or 
                           entity_name or entity_id)
                    if fqn:
                        asset_fqns.append(fqn)
                elif entity_type in ('data_contract', 'data_product'):
                    # App entities are reviewed by id (names change and aren't unique)
                    prefix = 'contract' if entity_type == 'data_contract' else 'product'
                    if entity_id:
                        asset_fqns.append(f"{prefix}:{entity_id}")
                        title = f"Review of {entity_name or entity_id}"[:200]
                else:
                    # Generic fallback
                    fqn = entity_name or entity_id
                    if fqn:
                        asset_fqns.append(f"{entity_type}:{fqn}")
            
            if not asset_fqns:
                return StepResult(
                    passed=False,
                    error="Could not determine asset FQN for review. Ensure entity has a name or fqn."
                )
            
            # Construct notes with review type
            full_notes = f"[{review_type}] {notes}".strip() if notes else f"[{review_type}] Created by workflow"
            
            # Create the review request using repository with proper API models
            from src.repositories.data_asset_reviews_repository import data_asset_review_repo
            from src.models.data_asset_reviews import (
                DataAssetReviewRequest, ReviewedAsset, 
                ReviewRequestStatus, ReviewedAssetStatus, AssetType, app_entity_asset_type,
            )
            from uuid import uuid4
            from datetime import datetime
            
            review_id = str(uuid4())
            
            # Build assets list
            assets_to_review = []
            for fqn in asset_fqns:
                # Contracts and products by their prefix; datasets and UC assets are tables
                asset_type = app_entity_asset_type(fqn) or AssetType.TABLE
                
                assets_to_review.append(ReviewedAsset(
                    id=str(uuid4()),
                    asset_fqn=fqn,
                    asset_type=asset_type,
                    status=ReviewedAssetStatus.PENDING,
                    updated_at=datetime.utcnow(),
                ))
            
            # Create full request model
            full_request = DataAssetReviewRequest(
                id=review_id,
                requester_email=requester_email,
                reviewer_email=reviewer_email,
                title=title,
                status=ReviewRequestStatus.QUEUED,
                notes=full_notes,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                assets=assets_to_review,
            )
            
            # Use repository to create
            review = data_asset_review_repo.create_with_assets(db=self._db, obj_in=full_request)
            
            logger.info(f"Created asset review {review.id} for {asset_fqns} by {reviewer_email}")
            
            return StepResult(
                passed=True,
                message=f"Asset review created: {review.id}",
                data={
                    'review_id': review.id,
                    'reviewer_email': reviewer_email,
                    'asset_fqns': asset_fqns,
                    'review_type': review_type,
                }
            )
            
        except Exception as e:
            logger.exception(f"Failed to create asset review: {e}")
            return StepResult(passed=False, error=str(e))
    
    def _resolve_reviewer(
        self, reviewer_role: str, context: StepContext, requester_email: str,
    ) -> Optional[str]:
        """The reviewer's email: the one named in the request, else the first
        person ``reviewer_role`` resolves to other than the requester (as the
        approval steps resolve it), else a member of the groups of the role it
        resolves to (or of ``reviewer_role`` itself), else an admin."""
        tc = context.trigger_context
        requester = requester_email.lower()
        requested = (tc.entity_data or {}).get('reviewer_email') if tc else None
        if requested and requested.lower() != requester:
            return requested
        if requested:
            logger.warning("Ignoring reviewer_email: the requester can't review their own request")
        roles = []
        for recipient, role_id in _resolve_role_to_users(self._db, reviewer_role, context):
            if role_id is not None:
                roles.append(recipient)
            elif '@' in recipient and recipient.lower() != requester:
                return recipient
        # A role (e.g. Data Stewards when a domain has no owner): one of its members,
        # and the admins last, as for owner approvals (``_owner_approvers``)
        roles = roles or [reviewer_role]
        if not any(r.lower().replace(' ', '').replace('_', '') == 'admin' for r in roles):
            roles.append('Admin')
        for role_name in roles:
            reviewer = self._resolve_reviewer_from_role(role_name, exclude=requester_email)
            if reviewer:
                return reviewer
        return None

    def _resolve_reviewer_from_role(
        self, role_identifier: str, exclude: Optional[str] = None,
    ) -> Optional[str]:
        """Resolve a reviewer email from a role name or UUID.
        
        Returns the email of the first user in the role's assigned groups
        other than ``exclude`` (the requester), or None if no users are found.
        """
        from src.db_models.settings import AppRoleDb
        from uuid import UUID
        
        try:
            # Try to find role by UUID first, then by name
            role = None
            try:
                # Check if it's a valid UUID
                UUID(role_identifier)
                role = self._db.query(AppRoleDb).filter(AppRoleDb.id == role_identifier).first()
            except ValueError:
                # Not a UUID, try by name (flexible matching)
                role = self._db.query(AppRoleDb).filter(AppRoleDb.name == role_identifier).first()
                if not role:
                    # Try normalized matching
                    normalized = role_identifier.lower().replace(' ', '').replace('_', '')
                    all_roles = self._db.query(AppRoleDb).all()
                    for r in all_roles:
                        r_normalized = r.name.lower().replace(' ', '').replace('_', '')
                        if r_normalized == normalized:
                            role = r
                            break
            
            if not role:
                logger.warning(f"Role not found: {role_identifier}")
                return None
            
            if not role.assigned_groups:
                logger.warning(f"Role {role.name} has no assigned groups")
                return None
            
            # Get first user from first assigned group
            try:
                from src.common.workspace_client import get_workspace_client
                ws = get_workspace_client()
                
                for group_name in role.assigned_groups:
                    # List group members
                    members = list(ws.groups.list(filter=f'displayName eq "{group_name}"'))
                    if members:
                        group = members[0]
                        if hasattr(group, 'members') and group.members:
                            for member in group.members:
                                if hasattr(member, 'value'):
                                    # Get user by ID
                                    try:
                                        user = ws.users.get(member.value)
                                        if (
                                            user and user.user_name
                                            and user.user_name.lower() != (exclude or '').lower()
                                        ):
                                            return user.user_name
                                    except Exception:
                                        continue
                
            except Exception as e:
                logger.warning(f"Failed to resolve users from groups: {e}")
            
            # Fallback: return None if we couldn't resolve
            return None
            
        except Exception as e:
            logger.exception(f"Failed to resolve reviewer from role: {e}")
            return None


class WebhookStepHandler(StepHandler):
    """Handler for webhook steps - calls external HTTP endpoints.
    
    Supports two modes:
    1. UC Connection mode: Uses Unity Catalog HTTP Connection via SDK
    2. Inline mode: Direct HTTP calls using httpx
    """

    def execute(self, context: StepContext) -> StepResult:
        import re
        
        connection_name = self._config.get('connection_name')
        url = self._config.get('url')
        method = self._config.get('method', 'POST').upper()
        path = self._config.get('path', '')
        headers = self._config.get('headers', {}) or {}
        body_template = self._config.get('body_template')
        timeout_seconds = self._config.get('timeout_seconds', 30)
        success_codes = self._config.get('success_codes')
        retry_count = self._config.get('retry_count', 0)

        # Caller-supplied extras forwarded into the UC HTTPConnection call
        # (issue #401). All support the same template substitution as
        # body_template / headers; absent or empty fields are no-ops, so
        # legacy configs are unaffected.
        additional_headers = self._config.get('additional_headers', {}) or {}
        additional_query_params = self._config.get('additional_query_params', {}) or {}
        path_suffix = self._config.get('path_suffix')

        # Validate configuration
        if not connection_name and not url:
            return StepResult(
                passed=False,
                error="Webhook requires either 'connection_name' (UC Connection) or 'url' (inline mode)"
            )

        # Substitute template variables in body
        body = None
        if body_template:
            body = self._substitute_template(body_template, context)

        # Substitute template variables in headers
        resolved_headers = {}
        for key, value in headers.items():
            resolved_headers[key] = self._substitute_template(value, context)

        # Merge additional_headers (caller-supplied extras win on key collision).
        for key, value in additional_headers.items():
            resolved_headers[key] = self._substitute_template(value, context)

        # Resolve additional_query_params (values, not keys, are templated).
        resolved_query_params: Dict[str, str] = {}
        for key, value in additional_query_params.items():
            resolved_query_params[key] = self._substitute_template(value, context)

        # Resolve path_suffix and merge with the configured path.
        resolved_path_suffix = (
            self._substitute_template(path_suffix, context) if path_suffix else ''
        )
        effective_path = self._compose_path(
            base_path=path or '',
            suffix=resolved_path_suffix,
            query_params=resolved_query_params,
        )

        try:
            if connection_name:
                # UC Connection mode
                result = self._execute_via_uc_connection(
                    connection_name=connection_name,
                    method=method,
                    path=effective_path,
                    headers=resolved_headers,
                    body=body,
                    timeout_seconds=timeout_seconds,
                    success_codes=success_codes,
                    retry_count=retry_count,
                )
            else:
                # Inline mode — append path_suffix and query params to the URL.
                effective_url = self._compose_url(
                    base_url=url,
                    suffix=resolved_path_suffix,
                    query_params=resolved_query_params,
                )
                result = self._execute_direct(
                    url=effective_url,
                    method=method,
                    headers=resolved_headers,
                    body=body,
                    timeout_seconds=timeout_seconds,
                    success_codes=success_codes,
                    retry_count=retry_count,
                )

            return result

        except Exception as e:
            logger.exception(f"Webhook step failed: {e}")
            return StepResult(passed=False, error=str(e))

    @staticmethod
    def _compose_path(base_path: str, suffix: str, query_params: Dict[str, str]) -> str:
        """Combine `base_path`, optional `suffix`, and optional `query_params` into
        a single path string for the UC HTTPConnection call.

        - If both `base_path` and `suffix` are empty, returns '/' (existing behavior).
        - Avoids duplicated slashes at the join.
        - Query string is appended last, URL-encoded.
        """
        from urllib.parse import urlencode

        # Strip surrounding whitespace to forgive UI input.
        base = (base_path or '').strip()
        suf = (suffix or '').strip()

        if base and suf:
            # Ensure exactly one slash between base and suffix.
            if base.endswith('/') and suf.startswith('/'):
                combined = base + suf[1:]
            elif not base.endswith('/') and not suf.startswith('/'):
                combined = base + '/' + suf
            else:
                combined = base + suf
        else:
            combined = base or suf

        if not combined:
            combined = '/'

        if query_params:
            sep = '&' if '?' in combined else '?'
            combined = f"{combined}{sep}{urlencode(query_params, doseq=True)}"

        return combined

    @staticmethod
    def _compose_url(base_url: str, suffix: str, query_params: Dict[str, str]) -> str:
        """Combine `base_url` with optional path `suffix` and `query_params`.

        Inline-mode counterpart to ``_compose_path``. The suffix is inserted into
        the URL's path component (before any existing query string) with single
        normalizing slashes, then ``query_params`` are appended last.
        """
        from urllib.parse import urlencode, urlsplit, urlunsplit

        url = base_url
        suf = (suffix or '').strip()
        if suf:
            parts = urlsplit(url)
            base_path = parts.path or ''
            if base_path and suf:
                if base_path.endswith('/') and suf.startswith('/'):
                    combined = base_path + suf[1:]
                elif not base_path.endswith('/') and not suf.startswith('/'):
                    combined = base_path + '/' + suf
                else:
                    combined = base_path + suf
            else:
                combined = base_path or suf
            url = urlunsplit((parts.scheme, parts.netloc, combined, parts.query, parts.fragment))
        if query_params:
            sep = '&' if '?' in url else '?'
            url = f"{url}{sep}{urlencode(query_params, doseq=True)}"
        return url

    def _substitute_template(self, template: str, context: StepContext) -> str:
        """Delegate to module-level substitute_template."""
        return substitute_template(template, context)

    def _execute_via_uc_connection(
        self,
        connection_name: str,
        method: str,
        path: str,
        headers: Dict[str, str],
        body: Optional[str],
        timeout_seconds: int,
        success_codes: Optional[List[int]],
        retry_count: int,
    ) -> StepResult:
        """Execute HTTP request via Unity Catalog Connection."""
        from src.common.workspace_client import get_workspace_client
        from databricks.sdk.service.serving import ExternalFunctionRequestHttpMethod
        
        try:
            ws = get_workspace_client()
            
            # Map method string to enum
            method_map = {
                'GET': ExternalFunctionRequestHttpMethod.GET,
                'POST': ExternalFunctionRequestHttpMethod.POST,
                'PUT': ExternalFunctionRequestHttpMethod.PUT,
                'PATCH': ExternalFunctionRequestHttpMethod.PATCH,
                'DELETE': ExternalFunctionRequestHttpMethod.DELETE,
            }
            http_method = method_map.get(method, ExternalFunctionRequestHttpMethod.POST)
            
            # Parse body as JSON if provided
            json_body = None
            if body:
                try:
                    import json
                    json_body = json.loads(body)
                except json.JSONDecodeError:
                    # If not valid JSON, treat as raw string
                    logger.warning(f"Body is not valid JSON, sending as-is")
                    json_body = {"data": body}
            
            # Execute with retry
            last_error = None
            for attempt in range(retry_count + 1):
                try:
                    response = ws.serving_endpoints.http_request(
                        conn=connection_name,
                        method=http_method,
                        path=path or '/',
                        headers=headers if headers else None,
                        json=json_body,
                    )
                    
                    # Check success based on status code
                    status_code = getattr(response, 'status_code', 200)
                    if self._is_success(status_code, success_codes):
                        return StepResult(
                            passed=True,
                            message=f"Webhook succeeded via UC Connection '{connection_name}'",
                            data={
                                'connection_name': connection_name,
                                'method': method,
                                'path': path,
                                'status_code': status_code,
                                'response': str(response)[:500],  # Truncate for safety
                            }
                        )
                    else:
                        last_error = f"HTTP {status_code}"
                        
                except Exception as e:
                    last_error = str(e)
                    if attempt < retry_count:
                        logger.warning(f"Webhook attempt {attempt + 1} failed: {e}, retrying...")
                        continue
            
            return StepResult(
                passed=False,
                error=f"Webhook failed after {retry_count + 1} attempt(s): {last_error}",
                data={'connection_name': connection_name, 'method': method, 'path': path}
            )
            
        except ImportError as e:
            logger.warning(f"UC Connection HTTP not available: {e}")
            return StepResult(
                passed=False,
                error=f"UC Connection HTTP feature not available: {e}"
            )
        except Exception as e:
            logger.exception(f"UC Connection webhook failed: {e}")
            return StepResult(passed=False, error=str(e))

    def _execute_direct(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        body: Optional[str],
        timeout_seconds: int,
        success_codes: Optional[List[int]],
        retry_count: int,
    ) -> StepResult:
        """Execute HTTP request directly using httpx."""
        try:
            import httpx
        except ImportError:
            # Fallback to urllib if httpx not available
            return self._execute_direct_urllib(
                url, method, headers, body, timeout_seconds, success_codes, retry_count
            )
        
        # Parse body as JSON if possible
        json_body = None
        content = None
        if body:
            try:
                import json
                json_body = json.loads(body)
            except json.JSONDecodeError:
                content = body
        
        last_error = None
        for attempt in range(retry_count + 1):
            try:
                with httpx.Client(timeout=timeout_seconds) as client:
                    response = client.request(
                        method=method,
                        url=url,
                        headers=headers if headers else None,
                        json=json_body,
                        content=content if not json_body else None,
                    )
                    
                    if self._is_success(response.status_code, success_codes):
                        return StepResult(
                            passed=True,
                            message=f"Webhook succeeded: {method} {url}",
                            data={
                                'url': url,
                                'method': method,
                                'status_code': response.status_code,
                                'response': response.text[:500],  # Truncate for safety
                            }
                        )
                    else:
                        last_error = f"HTTP {response.status_code}: {response.text[:200]}"
                        
            except Exception as e:
                last_error = str(e)
                if attempt < retry_count:
                    logger.warning(f"Webhook attempt {attempt + 1} failed: {e}, retrying...")
                    continue
        
        return StepResult(
            passed=False,
            error=f"Webhook failed after {retry_count + 1} attempt(s): {last_error}",
            data={'url': url, 'method': method}
        )

    def _execute_direct_urllib(
        self,
        url: str,
        method: str,
        headers: Dict[str, str],
        body: Optional[str],
        timeout_seconds: int,
        success_codes: Optional[List[int]],
        retry_count: int,
    ) -> StepResult:
        """Fallback HTTP execution using urllib (no external deps)."""
        import urllib.request
        import urllib.error
        
        last_error = None
        for attempt in range(retry_count + 1):
            try:
                req = urllib.request.Request(
                    url,
                    data=body.encode('utf-8') if body else None,
                    headers=headers or {},
                    method=method,
                )
                
                with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                    status_code = response.getcode()
                    response_body = response.read().decode('utf-8')[:500]
                    
                    if self._is_success(status_code, success_codes):
                        return StepResult(
                            passed=True,
                            message=f"Webhook succeeded: {method} {url}",
                            data={
                                'url': url,
                                'method': method,
                                'status_code': status_code,
                                'response': response_body,
                            }
                        )
                    else:
                        last_error = f"HTTP {status_code}"
                        
            except urllib.error.HTTPError as e:
                if self._is_success(e.code, success_codes):
                    return StepResult(
                        passed=True,
                        message=f"Webhook succeeded: {method} {url}",
                        data={'url': url, 'method': method, 'status_code': e.code}
                    )
                last_error = f"HTTP {e.code}: {e.reason}"
            except Exception as e:
                last_error = str(e)
                if attempt < retry_count:
                    logger.warning(f"Webhook attempt {attempt + 1} failed: {e}, retrying...")
                    continue
        
        return StepResult(
            passed=False,
            error=f"Webhook failed after {retry_count + 1} attempt(s): {last_error}",
            data={'url': url, 'method': method}
        )

    def _is_success(self, status_code: int, success_codes: Optional[List[int]]) -> bool:
        """Check if status code indicates success."""
        if success_codes:
            return status_code in success_codes
        # Default: 2xx is success
        return 200 <= status_code < 300


class EntityActionStepHandler(StepHandler):
    """Performs lifecycle actions (certify, publish, etc.) on the trigger entity.

    Config:
        action: certify | decertify | publish | unpublish | set_publication_scope
        level_source: from_request | fixed | from_approval  (certify only)
        fixed_level: int  (when level_source == fixed)
        scope_source: from_request | fixed | from_approval  (publish only)
        fixed_scope: str  (when scope_source == fixed)
    """

    # Same rules as the set-publication-scope routes.
    PUBLISHABLE_STATUSES = {
        'data_product': {'active'},
        'data_contract': {'approved', 'active'},
    }

    def execute(self, context: StepContext) -> StepResult:
        from datetime import datetime, timezone

        action = self._config.get('action')
        if not action:
            return StepResult(passed=False, error="No action configured for entity_action step")

        entity_type = context.entity_type
        entity_id = context.entity_id

        try:
            if action in ('certify', 'decertify'):
                return self._handle_certification(action, entity_type, entity_id, context)
            elif action in ('publish', 'set_publication_scope'):
                return self._handle_publication(entity_type, entity_id, context)
            elif action == 'unpublish':
                return self._handle_unpublish(entity_type, entity_id, context)
            else:
                return StepResult(passed=False, error=f"Unknown entity_action: {action}")
        except Exception as e:
            logger.exception(f"entity_action step failed: {e}")
            return StepResult(passed=False, error=str(e))

    def _resolve_level(self, context: StepContext) -> Optional[int]:
        source = self._config.get('level_source', 'from_request')
        if source == 'fixed':
            return self._config.get('fixed_level')
        elif source == 'from_approval':
            for step_data in reversed(list(context.step_results.values())):
                if isinstance(step_data, dict) and 'certification_level' in step_data:
                    return step_data['certification_level']
            return None
        else:  # from_request
            entity = context.entity or {}
            return entity.get('requested_certification_level') or entity.get('certification_level')

    def _resolve_scope(self, context: StepContext) -> str:
        source = self._config.get('scope_source', 'from_request')
        if source == 'fixed':
            return self._config.get('fixed_scope', 'organization')
        elif source == 'from_approval':
            for step_data in reversed(list(context.step_results.values())):
                if isinstance(step_data, dict) and 'publication_scope' in step_data:
                    return step_data['publication_scope']
            return 'organization'
        else:  # from_request
            entity = context.entity or {}
            return entity.get('requested_scope') or entity.get('publication_scope') or 'organization'

    def _get_db_entity(self, entity_type: str, entity_id: str):
        if entity_type in ('data_product', 'DataProduct'):
            from src.repositories.data_products_repository import data_product_repo
            return data_product_repo.get(db=self._db, id=entity_id), 'data_product'
        elif entity_type in ('data_contract', 'DataContract'):
            from src.repositories.data_contracts_repository import data_contract_repo
            return data_contract_repo.get(db=self._db, id=entity_id), 'data_contract'
        elif entity_type in ('asset', 'Asset', 'dataset', 'Dataset'):
            from src.repositories.assets_repository import asset_repo
            return asset_repo.get(db=self._db, id=entity_id), 'asset'
        return None, entity_type

    def _handle_certification(self, action: str, entity_type: str, entity_id: str, context: StepContext) -> StepResult:
        from datetime import datetime, timezone
        db_entity, resolved_type = self._get_db_entity(entity_type, entity_id)
        if not db_entity:
            return StepResult(passed=False, error=f"{entity_type} {entity_id} not found")

        if action == 'certify':
            level = self._resolve_level(context)
            if level is None:
                return StepResult(passed=False, error="Could not resolve certification level")
            db_entity.certification_level = level
            db_entity.certified_at = datetime.now(timezone.utc)
            db_entity.certified_by = context.user_email
            db_entity.certification_notes = (context.entity or {}).get('certification_notes') or \
                                            (context.entity or {}).get('message')
            self._db.add(db_entity)
            self._db.commit()
            logger.info(f"entity_action: certified {entity_type} {entity_id} at level {level}")
            return StepResult(passed=True, message=f"Certified at level {level}",
                              data={'certification_level': level})
        else:  # decertify
            db_entity.certification_level = None
            db_entity.inherited_certification_level = None
            db_entity.certified_at = None
            db_entity.certified_by = None
            db_entity.certification_notes = None
            if hasattr(db_entity, 'certification_expires_at'):
                db_entity.certification_expires_at = None
            self._db.add(db_entity)
            self._db.commit()
            logger.info(f"entity_action: decertified {entity_type} {entity_id}")
            return StepResult(passed=True, message="Certification removed")

    def _handle_publication(self, entity_type: str, entity_id: str, context: StepContext) -> StepResult:
        from datetime import datetime, timezone
        db_entity, resolved_type = self._get_db_entity(entity_type, entity_id)
        if not db_entity:
            return StepResult(passed=False, error=f"{entity_type} {entity_id} not found")

        scope = self._resolve_scope(context)
        # Approval can come days after the request: re-check the live status
        # with the same rules as the set-publication-scope routes.
        allowed = self.PUBLISHABLE_STATUSES.get(resolved_type)
        status = (getattr(db_entity, 'status', None) or '').lower()
        if scope != 'none' and allowed and status not in allowed:
            return StepResult(
                passed=False,
                error=f"Cannot publish {resolved_type} in status '{status}' "
                      f"(allowed: {', '.join(sorted(allowed))})",
            )
        was_published = (getattr(db_entity, 'publication_scope', None) or 'none').lower() != 'none'
        db_entity.publication_scope = scope
        if scope == 'none':
            # Unpublishing: clear the publication metadata, as unpublish does
            db_entity.published_at = None
            db_entity.published_by = None
        else:
            db_entity.published_at = datetime.now(timezone.utc)
            db_entity.published_by = context.user_email
        self._db.add(db_entity)
        self._db.commit()
        logger.info(f"entity_action: published {entity_type} {entity_id} with scope={scope}")
        failed_trigger = self._fire_publication_trigger(
            resolved_type, entity_id, db_entity, scope, was_published, context,
        )
        message = f"Published with scope {scope}"
        data = {'publication_scope': scope}
        if failed_trigger:
            # The publication stands; say in the step result that its workflows didn't run
            message += f"; the {failed_trigger} workflows did not run"
            data['trigger_failed'] = failed_trigger
        return StepResult(passed=True, message=message, data=data)

    def _fire_publication_trigger(
        self, entity_type: str, entity_id: str, db_entity: Any, scope: str,
        was_published: bool, context: StepContext,
    ) -> Optional[str]:
        """Fire ``on_publish`` / ``on_unpublish`` when the publication changed.

        Same rule as the set-publication-scope routes: ``on_publish`` only when
        the entity wasn't published yet, ``on_unpublish`` only when it was.
        The publication is already committed, so a trigger error doesn't undo
        it; it is logged as an error because those workflows didn't run, and
        the failed trigger (``'on_publish'`` / ``'on_unpublish'``) is returned
        so the step result says so. Returns None otherwise.
        """
        from src.common.workflow_triggers import get_trigger_registry
        from src.models.process_workflows import EntityType as WFEntityType

        wf_type = {
            'data_product': WFEntityType.DATA_PRODUCT,
            'data_contract': WFEntityType.DATA_CONTRACT,
        }.get(entity_type)
        publishing = scope != 'none'
        if not wf_type or publishing == was_published:
            return None
        name = getattr(db_entity, 'name', None) or context.entity_name
        try:
            registry = get_trigger_registry(self._db)
            if publishing:
                registry.on_publish(
                    entity_type=wf_type,
                    entity_id=entity_id,
                    entity_name=name,
                    entity_data={
                        'name': name,
                        'status': getattr(db_entity, 'status', None),
                        'publication_scope': scope,
                        'published_by': context.user_email,
                    },
                    user_email=context.user_email,
                )
            else:
                registry.on_unpublish(
                    wf_type, entity_id, entity_name=name, user_email=context.user_email,
                )
        except Exception:
            trigger = 'on_publish' if publishing else 'on_unpublish'
            logger.exception(
                "Publication trigger failed for %s %s; its %s workflows did not run",
                entity_type, entity_id, trigger,
            )
            return trigger
        return None

    def _handle_unpublish(self, entity_type: str, entity_id: str, context: StepContext) -> StepResult:
        db_entity, resolved_type = self._get_db_entity(entity_type, entity_id)
        if not db_entity:
            return StepResult(passed=False, error=f"{entity_type} {entity_id} not found")

        db_entity.publication_scope = 'none'
        db_entity.published_at = None
        db_entity.published_by = None
        self._db.add(db_entity)
        self._db.commit()
        logger.info(f"entity_action: unpublished {entity_type} {entity_id}")
        return StepResult(passed=True, message="Unpublished")


class GrantPermissionsStepHandler(StepHandler):
    """Handler for grant_permissions steps — grants UC permissions via the SP workspace client."""

    # Map Ontos entity types to Databricks SecurableType values
    _ENTITY_TYPE_TO_SECURABLE = {
        'table': 'TABLE',
        'view': 'TABLE',       # Views use TABLE securable type in UC
        'schema': 'SCHEMA',
        'catalog': 'CATALOG',
    }

    def execute(self, context: StepContext) -> StepResult:
        from src.models.process_workflows import GrantPermissionsStepConfig

        try:
            config = GrantPermissionsStepConfig(**self._config)
        except Exception as e:
            return StepResult(passed=False, error=f"Invalid grant_permissions config: {e}")

        permission_type = config.permission_type

        # --- Resolve target (securable object) ---
        target_full_name: Optional[str] = None
        securable_type_str: Optional[str] = None

        if config.target_source == 'from_entity':
            # Build full name from entity context.
            # For UC objects the fully-qualified name (catalog.schema.table) is
            # required.  entity_id typically carries the full name while
            # entity.name / entity_name may only hold the short leaf name, so
            # prefer entity_id and full_name over the short name fields.
            target_full_name = (
                context.entity.get('full_name')
                or context.entity_id
                or context.entity.get('name')
                or context.entity_name
            )
            # Determine securable type from entity_type
            et = context.entity_type.lower().replace(' ', '_')
            securable_type_str = self._ENTITY_TYPE_TO_SECURABLE.get(et)
        elif config.target_source == 'from_variable':
            if not config.target_variable:
                return StepResult(passed=False, error="target_variable is required when target_source=from_variable")
            target_full_name = self._resolve_variable(config.target_variable, context)
        else:
            return StepResult(passed=False, error=f"Unknown target_source: {config.target_source}")

        if not target_full_name:
            return StepResult(passed=False, error="Could not resolve target securable object")

        # Infer securable type from dot-segment count if not already determined
        if not securable_type_str:
            securable_type_str = self._infer_securable_type(target_full_name)

        if not securable_type_str:
            return StepResult(
                passed=False,
                error=(
                    f"Cannot determine SecurableType for entity_type='{context.entity_type}' "
                    f"and target='{target_full_name}'. grant_permissions is only supported for "
                    "UC objects (catalog, schema, table, view)."
                ),
            )

        # --- Resolve principal (who to grant to) ---
        principal: Optional[str] = None

        if config.principal_source == 'requester':
            principal = _requester_email(context)
        elif config.principal_source == 'from_variable':
            if not config.principal_variable:
                return StepResult(passed=False, error="principal_variable is required when principal_source=from_variable")
            principal = self._resolve_variable(config.principal_variable, context)
        elif '@' in config.principal_source:
            # Literal email / group name
            principal = config.principal_source
        else:
            return StepResult(passed=False, error=f"Unknown principal_source: {config.principal_source}")

        if not principal:
            return StepResult(passed=False, error="Could not resolve principal for permission grant")

        # --- Call Databricks grants API via SP workspace client ---
        try:
            from src.common.workspace_client import get_workspace_client
            ws = get_workspace_client()
        except Exception as e:
            logger.warning(f"grant_permissions: workspace client unavailable, skipping grant: {e}")
            return StepResult(
                passed=True,
                message=f"Workspace client unavailable — grant skipped ({e})",
                data={
                    'skipped': True,
                    'target': target_full_name,
                    'principal': principal,
                    'permission': permission_type,
                    'securable_type': securable_type_str,
                },
            )

        try:
            # Use the UC REST API directly instead of ws.grants.update() because
            # newer SDK versions (>=0.95) route through a managed-catalog RPC
            # that rejects TABLE as a securable type.  The REST endpoint
            # PATCH /api/2.1/unity-catalog/permissions/{type}/{full_name} works
            # reliably across all SDK versions.
            import urllib.parse

            securable_lower = securable_type_str.lower()  # e.g. "table", "schema"
            encoded_name = urllib.parse.quote(target_full_name, safe='')
            path = f"/api/2.1/unity-catalog/permissions/{securable_lower}/{encoded_name}"

            body = {
                "changes": [
                    {
                        "add": [permission_type],
                        "principal": principal,
                    }
                ]
            }

            # CachingWorkspaceClient delegates unknown attrs to the inner SDK
            # client; api_client.do() issues a raw HTTP request.
            ws.api_client.do("PATCH", path, body=body)

            msg = f"Granted {permission_type} on {securable_type_str} '{target_full_name}' to {principal}"
            logger.info(f"grant_permissions: {msg}")
            return StepResult(
                passed=True,
                message=msg,
                data={
                    'target': target_full_name,
                    'principal': principal,
                    'permission': permission_type,
                    'securable_type': securable_type_str,
                },
            )
        except Exception as e:
            logger.exception(f"grant_permissions: failed to grant {permission_type} on '{target_full_name}' to {principal}: {e}")
            return StepResult(
                passed=False,
                error=f"Grant failed: {e}",
                data={
                    'target': target_full_name,
                    'principal': principal,
                    'permission': permission_type,
                    'securable_type': securable_type_str,
                },
            )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_variable(path: str, context: 'StepContext') -> Optional[str]:
        """Walk a dot-separated path into the step context.

        Supported namespaces:
          step_results.<step_id>.<field>[.<sub>...]
          context.<attr>[.<sub>...]   e.g. context.on_behalf_of.value
                                            
          entity.<field>[.<sub>...]
        Bare paths default to step_results for backward compatibility with
        existing GrantPermissions configs.
        """
        if not path:
            return None
        parts = path.split('.')
        head = parts[0]

        if head == 'context':
            obj: Any = context
            for part in parts[1:]:
                if obj is None:
                    return None
                if isinstance(obj, dict):
                    obj = obj.get(part)
                else:
                    obj = getattr(obj, part, None)
            return str(obj) if obj is not None else None

        if head == 'entity':
            obj = context.entity
            for part in parts[1:]:
                if isinstance(obj, dict):
                    obj = obj.get(part)
                else:
                    return None
                if obj is None:
                    return None
            return str(obj) if obj is not None else None

        # default: step_results. Strip leading 'step_results' prefix if present.
        if head == 'step_results':
            parts = parts[1:]
        obj = context.step_results
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return None
            if obj is None:
                return None
        return str(obj) if obj is not None else None

    @staticmethod
    def _infer_securable_type(full_name: str) -> Optional[str]:
        """Infer SecurableType from the number of dot-separated segments.

        catalog              → CATALOG
        catalog.schema       → SCHEMA
        catalog.schema.table → TABLE
        """
        segments = full_name.split('.')
        if len(segments) == 1:
            return 'CATALOG'
        elif len(segments) == 2:
            return 'SCHEMA'
        elif len(segments) >= 3:
            return 'TABLE'
        return None


class WorkflowExecutor:
    """Executes process workflows."""

    # Step handler registry
    HANDLERS: Dict[str, type] = {
        'validation': ValidationStepHandler,
        'approval': ApprovalStepHandler,
        'notification': NotificationStepHandler,
        'assign_tag': AssignTagStepHandler,
        'remove_tag': RemoveTagStepHandler,
        'conditional': ConditionalStepHandler,
        'script': ScriptStepHandler,
        'pass': PassStepHandler,
        'fail': FailStepHandler,
        'policy_check': PolicyCheckStepHandler,
        'delivery': DeliveryStepHandler,
        'create_asset_review': CreateAssetReviewStepHandler,
        'webhook': WebhookStepHandler,
        'entity_action': EntityActionStepHandler,
        'grant_permissions': GrantPermissionsStepHandler,
    }

    def __init__(self, db: Session):
        self._db = db

    def execute_workflow(
        self,
        workflow: ProcessWorkflow,
        entity: Dict[str, Any],
        *,
        entity_type: str,
        entity_id: str,
        entity_name: Optional[str] = None,
        user_email: Optional[str] = None,
        trigger_context: Optional[TriggerContext] = None,
        blocking: bool = True,
        execution_id: Optional[str] = None,
    ) -> WorkflowExecution:
        """Execute a workflow against an entity.
        
        Args:
            workflow: Workflow to execute
            entity: Entity data dictionary
            entity_type: Type of entity
            entity_id: Entity identifier
            entity_name: Entity name (optional)
            user_email: User who triggered the workflow
            trigger_context: Full trigger context
            blocking: If True, run synchronously; if False, queue for async execution
            execution_id: Optional existing execution ID to reuse (for retries)
            
        Returns:
            WorkflowExecution with results
        """
        # Reuse existing execution or create new one
        if execution_id:
            db_execution = workflow_execution_repo.get(self._db, execution_id)
            if not db_execution:
                raise ValueError(f"Execution {execution_id} not found")
            # Reset execution state for retry
            db_execution.status = ExecutionStatus.RUNNING.value
            db_execution.started_at = datetime.now()
            db_execution.finished_at = None
            db_execution.error_message = None
            db_execution.current_step_id = None
            self._db.commit()
        else:
            # Create new execution record
            execution_create = WorkflowExecutionCreate(
                workflow_id=workflow.id,
                trigger_context=trigger_context,
                triggered_by=user_email,
            )
            db_execution = workflow_execution_repo.create(self._db, execution_create)
        
        # : pull on_behalf_of off the trigger entity_data if the caller
        # supplied it (e.g. subscribe-on-behalf-of-group). Falls back to None
        # for self-subscribe / non-subscribe triggers.
        on_behalf_of = None
        if isinstance(entity, dict):
            obo = entity.get('on_behalf_of')
            if isinstance(obo, dict):
                on_behalf_of = obo

        # Build step context
        context = StepContext(
            entity=entity.copy(),
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            user_email=user_email,
            trigger_context=trigger_context,
            execution_id=db_execution.id,
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            step_results={},
            on_behalf_of=on_behalf_of,
        )

        # Build step lookup
        steps_by_id = {s.step_id: s for s in workflow.steps}
        
        # Execute steps
        success_count = 0
        failure_count = 0
        current_step_id = workflow.steps[0].step_id if workflow.steps else None
        final_status = ExecutionStatus.RUNNING
        error_message = None
        
        while current_step_id:
            step = steps_by_id.get(current_step_id)
            if not step:
                error_message = f"Step not found: {current_step_id}"
                final_status = ExecutionStatus.FAILED
                break
            
            # Execute step
            start_time = time.time()
            result = self._execute_step(step, context)
            duration_ms = (time.time() - start_time) * 1000
            
            # Record step execution
            step_status = StepExecutionStatus.SUCCEEDED if result.passed else StepExecutionStatus.FAILED
            workflow_execution_repo.add_step_execution(
                self._db,
                execution_id=db_execution.id,
                step_id=step.id,
                step_key=step.step_id,
                step_name=step.name,
                status=step_status.value,
                passed=result.passed,
                result_data=result.data,
                error_message=result.error,
                duration_ms=duration_ms,
            )
            
            # Store result in context for subsequent steps
            context.step_results[step.step_id] = {
                'passed': result.passed,
                'message': result.message,
                'data': result.data,
            }
            
            # Update counters
            if result.passed:
                success_count += 1
            else:
                failure_count += 1
            
            # Check for blocking step (e.g., approval)
            if result.blocking:
                final_status = ExecutionStatus.PAUSED
                workflow_execution_repo.update_status(
                    self._db,
                    db_execution.id,
                    status=final_status.value,
                    current_step_id=current_step_id,
                    success_count=success_count,
                    failure_count=failure_count,
                )
                break
            
            # Determine next step
            if result.passed:
                current_step_id = step.on_pass
            else:
                current_step_id = step.on_fail
            
            # If no next step, we're done
            if not current_step_id:
                if result.passed:
                    final_status = ExecutionStatus.SUCCEEDED
                else:
                    final_status = ExecutionStatus.FAILED
                    error_message = result.message or result.error
        
        # Finalize execution
        if final_status != ExecutionStatus.PAUSED:
            workflow_execution_repo.update_status(
                self._db,
                db_execution.id,
                status=final_status.value,
                success_count=success_count,
                failure_count=failure_count,
                error_message=error_message,
                finished_at=datetime.utcnow(),
            )
        
        # Return execution with results
        db_execution = workflow_execution_repo.get(self._db, db_execution.id)
        return self._db_to_model(db_execution, workflow.name)

    def resume_workflow(
        self,
        execution_id: str,
        step_result: bool,
        *,
        result_data: Optional[Dict[str, Any]] = None,
        user_email: Optional[str] = None,
    ) -> Optional[WorkflowExecution]:
        """Resume a paused workflow after approval/external action.
        
        When a workflow pauses at a blocking step (e.g., approval), this method
        resumes execution from where it left off, using the step_result to
        determine which branch (on_pass or on_fail) to follow.
        
        Args:
            execution_id: ID of paused execution
            step_result: Result of the paused step (True=approved, False=rejected)
            result_data: Additional result data from the approval response
            user_email: Email of user who responded to the approval
            
        Returns:
            Updated WorkflowExecution, or None if execution not found/not paused
        """
        db_execution = workflow_execution_repo.get(self._db, execution_id)
        if not db_execution or db_execution.status != 'paused':
            logger.warning(f"Cannot resume workflow {execution_id}: not found or not paused")
            return None
        
        # Get workflow
        from src.repositories.process_workflows_repository import process_workflow_repo
        db_workflow = process_workflow_repo.get(self._db, db_execution.workflow_id)
        if not db_workflow:
            logger.error(f"Workflow {db_execution.workflow_id} not found for execution {execution_id}")
            return None
        
        # Convert to ProcessWorkflow model
        from src.controller.workflows_manager import WorkflowsManager
        workflows_manager = WorkflowsManager(self._db)
        workflow = workflows_manager._db_to_model(db_workflow)
        
        # Build step lookup
        steps_by_id = {s.step_id: s for s in workflow.steps}
        
        # Find the current (paused) step
        current_step_id = db_execution.current_step_id
        if not current_step_id or current_step_id not in steps_by_id:
            logger.error(f"Current step {current_step_id} not found in workflow")
            return None
        
        current_step = steps_by_id[current_step_id]
        
        # Record the approval result for the paused step
        denied_without_reason = not step_result and not (result_data or {}).get('reason')
        workflow_execution_repo.add_step_execution(
            self._db,
            execution_id=execution_id,
            step_id=current_step.id,
            step_key=current_step.step_id,
            step_name=current_step.name,
            status=StepExecutionStatus.SUCCEEDED.value if step_result else StepExecutionStatus.FAILED.value,
            passed=step_result,
            result_data={
                'approval_result': 'approved' if step_result else 'rejected',
                'responded_by': user_email,
                **(result_data or {}),
                # A rejection without a reason: the UI translates the code,
                # the English text stays in error_message
                **(
                    {'error_code': APPROVAL_REJECTED, 'error_params': {}}
                    if denied_without_reason else {}
                ),
            },
            # The approve routes send reason None when the approver wrote none
            error_message=None if step_result else ((result_data or {}).get('reason') or 'Request denied'),
            duration_ms=0,  # Approval duration not tracked this way
        )
        
        # Determine next step based on approval result
        next_step_id = current_step.on_pass if step_result else current_step.on_fail
        
        logger.info(
            f"Resuming workflow {execution_id} from step '{current_step_id}' "
            f"({'approved' if step_result else 'rejected'}) -> next step: {next_step_id}"
        )
        
        # Rebuild trigger context
        trigger_context = None
        if db_execution.trigger_context:
            try:
                tc_data = json.loads(db_execution.trigger_context)
                trigger_context = TriggerContext(**tc_data)
            except (json.JSONDecodeError, TypeError):
                pass
        
        # Rebuild step context from execution
        # Get entity data from trigger context or create minimal context
        entity_data = {}
        if trigger_context and trigger_context.entity_data:
            entity_data = trigger_context.entity_data
        
        # Restore on_behalf_of from persisted entity_data (subscribe).
        on_behalf_of = None
        if isinstance(entity_data, dict):
            obo = entity_data.get('on_behalf_of')
            if isinstance(obo, dict):
                on_behalf_of = obo

        context = StepContext(
            entity=entity_data.copy(),
            entity_type=trigger_context.entity_type if trigger_context else 'unknown',
            entity_id=trigger_context.entity_id if trigger_context else execution_id,
            entity_name=trigger_context.entity_name if trigger_context else None,
            user_email=user_email or (trigger_context.user_email if trigger_context else None),
            trigger_context=trigger_context,
            execution_id=execution_id,
            workflow_id=workflow.id,
            workflow_name=workflow.name,
            step_results={current_step_id: {
                'passed': step_result,
                'decision': 'approved' if step_result else 'rejected',
                # Flatten result_data so ${step_results.approve.reason} works directly
                **(result_data or {}),
            }},
            on_behalf_of=on_behalf_of,
        )

        # Cross-workflow variable propagation (#291):
        # When the approval step was backed by a wizard session (approval flow),
        # the user may have entered data (e.g. workspaceId, reason).  Merge those
        # wizard step_results into context.step_results under the approval step's
        # step_id so subsequent process-workflow steps can reference them via
        # ${step_results.<approval_step_id>.<field>}.
        # Per PR #315 review: the executor goes through AgreementWizardManager
        # rather than the wizard-sessions repo directly. The manager method
        # encapsulates the lookup + step_results extraction.
        if trigger_context and step_result:
            try:
                from src.controller.agreement_wizard_manager import AgreementWizardManager

                wizard_mgr = AgreementWizardManager(self._db)
                wizard_results = wizard_mgr.get_completed_session_step_results(
                    entity_type=trigger_context.entity_type,
                    entity_id=trigger_context.entity_id,
                )
                if wizard_results:
                    # Flatten all wizard-collected fields under the
                    # approval step's ID.  Keys from later wizard steps
                    # override earlier ones if they collide (last-write
                    # wins), which matches user expectation that the most
                    # recent input is authoritative.
                    merged: Dict[str, str] = {}
                    for wr in wizard_results:
                        wizard_payload = wr.get("payload", {})
                        for key, value in wizard_payload.items():
                            if isinstance(value, (str, int, float, bool)):
                                merged[key] = str(value)
                    if merged:
                        approval_entry = context.step_results.setdefault(
                            current_step_id, {}
                        )
                        # The wizard is the requester's: its fields never replace
                        # the approver's decision (passed, decision, message,
                        # reason), which ${step_results.<approval>.reason} names.
                        for key, value in merged.items():
                            if key not in approval_entry:
                                approval_entry[key] = value
                        logger.info(
                            "Merged %d wizard field(s) into step_results.%s",
                            len(merged),
                            current_step_id,
                        )
            except Exception as e:
                # Non-fatal: workflow continues even if propagation fails
                logger.warning(
                    "Failed to propagate wizard results for execution %s: %s",
                    execution_id,
                    e,
                )

        # Continue execution from next step
        success_count = db_execution.success_count
        failure_count = db_execution.failure_count
        
        # Count the approval step. The pause already counted it as passed (the
        # pending approval's result passes), so an approval keeps that count and
        # a rejection moves it to the failures.
        if not step_result:
            success_count = max(success_count - 1, 0)
            failure_count += 1
        
        final_status = ExecutionStatus.RUNNING
        error_message = None
        
        # The approval was the last step for this decision: the execution ends here.
        if not next_step_id:
            if step_result:
                final_status = ExecutionStatus.SUCCEEDED
            else:
                final_status = ExecutionStatus.FAILED
                error_message = (result_data or {}).get('reason') or 'Request denied'
        
        while next_step_id:
            step = steps_by_id.get(next_step_id)
            if not step:
                error_message = f"Step not found: {next_step_id}"
                final_status = ExecutionStatus.FAILED
                break
            
            # Execute step
            start_time = time.time()
            result = self._execute_step(step, context)
            duration_ms = (time.time() - start_time) * 1000
            
            # Record step execution
            step_status = StepExecutionStatus.SUCCEEDED if result.passed else StepExecutionStatus.FAILED
            workflow_execution_repo.add_step_execution(
                self._db,
                execution_id=execution_id,
                step_id=step.id,
                step_key=step.step_id,
                step_name=step.name,
                status=step_status.value,
                passed=result.passed,
                result_data=result.data,
                error_message=result.error,
                duration_ms=duration_ms,
            )
            
            # Store result in context for subsequent steps
            context.step_results[step.step_id] = {
                'passed': result.passed,
                'message': result.message,
                'data': result.data,
            }
            
            # Update counters
            if result.passed:
                success_count += 1
            else:
                failure_count += 1
            
            # Check for another blocking step
            if result.blocking:
                final_status = ExecutionStatus.PAUSED
                workflow_execution_repo.update_status(
                    self._db,
                    execution_id,
                    status=final_status.value,
                    current_step_id=next_step_id,
                    success_count=success_count,
                    failure_count=failure_count,
                )
                break
            
            # Determine next step
            if result.passed:
                next_step_id = step.on_pass
            else:
                next_step_id = step.on_fail
            
            # If no next step, we're done
            if not next_step_id:
                if result.passed:
                    final_status = ExecutionStatus.SUCCEEDED
                else:
                    final_status = ExecutionStatus.FAILED
                    error_message = result.message or result.error
        
        # Finalize execution if not paused again
        if final_status != ExecutionStatus.PAUSED:
            workflow_execution_repo.update_status(
                self._db,
                execution_id,
                status=final_status.value,
                current_step_id=None,
                success_count=success_count,
                failure_count=failure_count,
                error_message=error_message,
                finished_at=datetime.utcnow(),
            )
            
            # Handle entity status updates based on workflow outcome
            self._handle_workflow_completion(
                trigger_context=trigger_context,
                workflow=workflow,
                succeeded=(final_status == ExecutionStatus.SUCCEEDED),
                responded_by=user_email,
                approved=step_result,
                execution_id=execution_id,
            )
        
        # Return updated execution
        db_execution = workflow_execution_repo.get(self._db, execution_id)
        return self._db_to_model(db_execution, workflow.name)

    def _apply_contract_review_decision(
        self,
        trigger_context: TriggerContext,
        contract_id: str,
        approved: bool,
        responded_by: Optional[str],
        execution_id: Optional[str] = None,
    ) -> None:
        """Set a reviewed contract to ``approved`` or back to ``draft``.

        Goes through ``transition_status``, so the lifecycle rules, the
        before_status_change gates and the on_status_change trigger apply as on
        the contract page. A contract that is no longer under review (decided
        from the contract page meanwhile) is left alone. If the change can't be
        applied, the approver is told: the workflow has already recorded the
        decision.
        """
        from src.controller.data_contracts_manager import get_live_contracts_manager
        from src.repositories.data_contracts_repository import data_contract_repo

        target_status = 'approved' if approved else 'draft'
        contract = data_contract_repo.get(db=self._db, id=contract_id)
        if not contract:
            return
        current_status = (contract.status or '').lower()
        if current_status == target_status:
            return
        if current_status not in ('proposed', 'under_review'):
            reason = f"the contract is not under review (status '{current_status}')"
            logger.warning(
                "Review decision for data contract %s not applied: %s", contract_id, reason,
            )
            self._notify_status_not_changed(
                trigger_context, target_status, reason, responded_by,
                'notUnderReview', {'currentStatus': current_status},
            )
            return
        try:
            get_live_contracts_manager().transition_status(
                db=self._db, contract_id=contract_id, new_status=target_status,
                current_user=responded_by,
            )
        except ValueError as e:
            logger.warning(
                "Review decision for data contract %s not applied: %s", contract_id, e,
            )
            self._notify_status_not_changed(
                trigger_context, target_status, str(e), responded_by,
                'notApplied', {'reason': str(e)}, error=e,
            )
            # The workflow has already told the requester the review was
            # decided; say that the contract's status didn't follow. An
            # "approved" notice of this run would contradict it, so it goes.
            if approved:
                self._withdraw_approval_notices(execution_id, trigger_context.user_email)
            self._notify_status_not_changed(
                trigger_context, target_status, str(e), trigger_context.user_email,
                'requesterNotApplied', {'reason': str(e)}, error=e,
                description=(
                    f"The review of your contract was decided, but the contract was not "
                    f"set to '{target_status}': {e}"
                ),
            )
            return
        logger.info(
            "Data contract %s moved to '%s' after its review was decided",
            contract_id, target_status,
        )

    # Notification templates that tell the requester their request was approved
    _APPROVAL_NOTICE_TEMPLATES = ('request_approved', 'product_approved')

    def _withdraw_approval_notices(self, execution_id: Optional[str], recipient: Optional[str]) -> int:
        """Delete the "approved" notices this run sent ``recipient``.

        Used when the approved status change was refused afterwards (e.g. by a
        status gate): the requester then gets only the "not applied" notice
        instead of two that contradict each other. Runs recorded before the
        notification steps kept their notice ids have nothing to withdraw.
        """
        if not execution_id or not recipient:
            return 0
        from src.db_models.notifications import NotificationDb
        from src.db_models.process_workflows import WorkflowStepExecutionDb

        ids = []
        runs = (
            self._db.query(WorkflowStepExecutionDb)
            .filter(WorkflowStepExecutionDb.execution_id == execution_id)
            .filter(WorkflowStepExecutionDb.passed.is_(True))
            .all()
        )
        for run in runs:
            try:
                data = json.loads(run.result_data) if isinstance(run.result_data, str) else run.result_data
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(data, dict) or data.get('template') not in self._APPROVAL_NOTICE_TEMPLATES:
                continue
            ids.extend(
                notice.get('id') for notice in data.get('notices') or []
                if isinstance(notice, dict) and notice.get('recipient') == recipient and notice.get('id')
            )
        if not ids:
            return 0
        removed = (
            self._db.query(NotificationDb)
            .filter(NotificationDb.id.in_(ids))
            .delete(synchronize_session=False)
        )
        self._db.commit()
        logger.info("Withdrew %d approval notice(s) of execution %s", removed, execution_id)
        return removed

    @staticmethod
    def _coded_error_i18n(error: Optional[Exception]) -> Dict[str, Any]:
        """``data.i18n`` entries for the reason a status change was refused.

        A refusal the app raises with a code (a blocking gate, a gate that
        couldn't be evaluated, an invalid transition) is sent as
        ``error = {code, message, params}``, so the bell can show the reason in
        the user's language the same way the status change dialogs do. Any
        other error keeps only its English text in ``params.reason``.
        """
        from src.common.api_errors import CodedValueError

        if not isinstance(error, CodedValueError):
            return {}
        return {'error': {
            'code': error.code, 'message': str(error), 'params': error.params or {},
        }}

    def _notify_status_not_changed(
        self,
        trigger_context: TriggerContext,
        target_status: str,
        reason: str,
        responded_by: Optional[str],
        description_key: str,
        params: Dict[str, str],
        error: Optional[Exception] = None,
        description: Optional[str] = None,
    ) -> None:
        """Warn ``responded_by`` that a review decision didn't change the contract.

        The English texts are stored; ``data.i18n`` carries the keys of the
        frontend's ``notifications`` namespace so the bell can translate them,
        the namespace of the contract status labels, and the coded error of a
        refused transition (see ``_coded_error_i18n``).
        """
        if not responded_by:
            return
        from uuid import uuid4
        from src.models.notifications import Notification, NotificationType
        from src.repositories.notification_repository import notification_repo

        notification_repo.create(db=self._db, obj_in=Notification(
            id=str(uuid4()),
            created_at=datetime.utcnow(),
            type=NotificationType.WARNING,
            title="Contract status not changed",
            subtitle=trigger_context.entity_name or trigger_context.entity_id,
            description=description or (
                f"Your review decision was recorded, but the contract was not set to "
                f"'{target_status}': {reason}"
            ),
            recipient=responded_by,
            can_delete=True,
            data={'i18n': {
                'title': 'notifications:contractStatusNotChanged.title',
                'description': f'notifications:contractStatusNotChanged.{description_key}',
                'params': {'toStatus': target_status, **params},
                'statusNamespace': 'data-contracts',
                **self._coded_error_i18n(error),
            }},
        ))
        self._db.commit()

    def _handle_workflow_completion(
        self,
        trigger_context: Optional[TriggerContext],
        workflow: ProcessWorkflow,
        succeeded: bool,
        responded_by: Optional[str] = None,
        approved: Optional[bool] = None,
        execution_id: Optional[str] = None,
    ) -> None:
        """Handle entity status updates when a workflow completes.
        
        Based on the trigger type and entity type, update the entity's status
        to reflect the workflow outcome (e.g., asset -> "active" on approval).
        """
        if not trigger_context:
            return
        
        entity_type = trigger_context.entity_type
        entity_id = trigger_context.entity_id
        trigger_type = workflow.trigger.type if workflow.trigger else None
        
        if not entity_type or not entity_id or not trigger_type:
            return
        
        try:
            # Handle asset review completion (covers former dataset reviews)
            if entity_type in ('asset', 'dataset') and trigger_type in ('on_request_review', 'ON_REQUEST_REVIEW'):
                from src.repositories.assets_repository import asset_repo
                db_asset = asset_repo.get(db=self._db, id=entity_id)
                if db_asset:
                    if succeeded:
                        db_asset.status = 'active'
                        logger.info(f"Asset {entity_id} status updated to 'active' after review approval")
                    else:
                        db_asset.status = 'draft'
                        logger.info(f"Asset {entity_id} status reverted to 'draft' after review rejection")
                    self._db.commit()
                    
            # Data contract deploy request decided by an approver: record it in
            # the change log, as the legacy handle-deploy flow does. A
            # workflow without an approval step decides nothing, so nothing is
            # recorded. The contract status is left alone: the lifecycle has no
            # "deployed" status, and an approval doesn't deploy anything.
            elif (entity_type == 'data_contract'
                  and trigger_type in ('on_request_deploy', 'ON_REQUEST_DEPLOY')
                  and approved is not None):
                from src.controller.change_log_manager import change_log_manager
                # The approver's choice, not the run's outcome: a later step
                # (e.g. a notification) can fail after an approval.
                decision = 'approve' if approved else 'deny'
                change_log_manager.log_change_with_details(
                    self._db,
                    entity_type='data_contract',
                    entity_id=entity_id,
                    action=f'deploy_{decision}',
                    username=responded_by,
                    details={
                        'approver_email': responded_by,
                        'decision': decision,
                        'workflow': workflow.name,
                        'requester_email': trigger_context.user_email,
                        'summary': f"Deploy request {'approved' if approved else 'denied'} "
                                   f"via workflow '{workflow.name}'",
                    },
                )
                self._db.commit()
                    
            # Data contract review decided by an approver: approve the contract,
            # or return it to draft, as the contract page's approve / reject
            # endpoints do. A workflow without an approval step decides nothing.
            elif (entity_type == 'data_contract'
                  and trigger_type in ('on_request_review', 'ON_REQUEST_REVIEW')
                  and approved is not None):
                self._apply_contract_review_decision(
                    trigger_context, entity_id, approved, responded_by,
                    execution_id=execution_id,
                )
                    
            # Handle data product activation completion
            elif entity_type == 'data_product' and trigger_type in ('on_request_review', 'ON_REQUEST_REVIEW'):
                self._apply_product_review_outcome(
                    trigger_context, entity_id, succeeded, responded_by,
                    execution_id=execution_id,
                )

            # Approved status change request: apply the requested transition,
            # with the same validation and gates as a direct status change
            elif (entity_type == 'data_product'
                  and trigger_type in ('on_request_status_change', 'ON_REQUEST_STATUS_CHANGE')):
                approved_request = succeeded if approved is None else approved
                target_status = trigger_context.to_status or (
                    trigger_context.entity_data or {}
                ).get('target_status')
                if approved_request and target_status:
                    self._apply_requested_status_change(
                        trigger_context, entity_id, target_status, responded_by,
                        execution_id=execution_id,
                    )
                    
        except Exception as e:
            logger.error(f"Error updating entity status after workflow completion: {e}", exc_info=True)
            # Don't fail the workflow for status update issues
    
    # A reviewed product goes active through the lifecycle steps it still
    # needs, or back to draft; each step is a transition_status call.
    _PRODUCT_ACTIVATION_STEPS = {
        'proposed': ['under_review', 'approved', 'active'],
        'under_review': ['approved', 'active'],
        'approved': ['active'],
    }

    def _apply_product_review_outcome(
        self,
        trigger_context: TriggerContext,
        product_id: str,
        succeeded: bool,
        responded_by: Optional[str],
        execution_id: Optional[str] = None,
    ) -> None:
        """Activate a reviewed data product, or return it to draft.

        The outcome is the run's, as before: a succeeded review activates the
        product, any other ending returns it to draft. Each status step goes
        through ``transition_status``, so the lifecycle rules and the
        before_status_change gates apply to each step as for a change from the
        product page. on_status_change fires once for the whole change (e.g.
        under_review -> active), not once per step, so a workflow on an
        intermediate step (approved -> active, like the default Data Product
        Publish Approval) doesn't start a second approval for a product its
        review just activated. A product that is no longer in review (changed
        meanwhile) is left alone. If a step is refused (e.g. a gate blocks),
        the product stays where it got to (the trigger fires for the part that
        was applied) and the requester is told, since the workflow has
        already ended.
        """
        from src.common.app_state import get_app_state_manager
        from src.controller.data_products_manager import DataProductsManager
        from src.db_models.data_products import DataProductDb

        product = self._db.get(DataProductDb, product_id)
        if product is None:
            return
        current_status = (product.status or 'draft').lower()
        target_status = 'active' if succeeded else 'draft'
        if current_status == target_status:
            return
        if succeeded:
            steps = self._PRODUCT_ACTIVATION_STEPS.get(current_status)
        else:
            steps = [target_status] if current_status in self._PRODUCT_ACTIVATION_STEPS else None
        if not steps:
            logger.warning(
                "Review outcome of data product %s not applied: it is no longer in review "
                "(status '%s')",
                product_id, current_status,
            )
            return

        manager = DataProductsManager(
            db=self._db, notifications_manager=get_app_state_manager('notifications_manager'),
        )
        search_manager = get_app_state_manager('search_manager')
        if search_manager:
            manager.set_search_manager(search_manager)
        applied: List[str] = []
        try:
            self._run_product_review_steps(
                manager, trigger_context, product_id, steps, target_status, responded_by, applied,
            )
        except _ReviewStepRefused:
            # The requester was told the change wasn't applied; an "approved"
            # notice of this run would contradict it, so it goes.
            if succeeded:
                self._withdraw_approval_notices(execution_id, trigger_context.user_email)
        except SQLAlchemyError:
            # The steps before the failed one are committed; the session must
            # be usable again to fire their trigger below
            self._db.rollback()
            raise
        finally:
            # Also after an unexpected error, for the steps already applied
            reached_status = applied[-1] if applied else current_status
            if reached_status != current_status:
                manager.fire_status_change_trigger(
                    product_id, product.name, current_status, reached_status, responded_by,
                )
        if reached_status == target_status:
            logger.info(
                "Data product %s moved to '%s' after its review",
                product_id, target_status,
            )

    def _run_product_review_steps(
        self,
        manager,
        trigger_context: TriggerContext,
        product_id: str,
        steps: List[str],
        target_status: str,
        responded_by: Optional[str],
        applied: List[str],
    ) -> None:
        """Apply the review's lifecycle steps without per-step triggers.

        Each applied step is appended to ``applied``. Raises
        ``_ReviewStepRefused`` when a step is refused, after telling the
        requester and the approver.
        """
        for step in steps:
            try:
                manager.transition_status(
                    product_id, step, responded_by, fire_status_change_trigger=False,
                )
                applied.append(step)
            except ValueError as e:
                logger.warning(
                    "Review outcome of data product %s: the change to '%s' was refused: %s",
                    product_id, step, e,
                )
                self._notify_status_change_not_applied(
                    trigger_context, product_id,
                    f"The review of the data product was decided, but the change to "
                    f"'{target_status}' could not be applied: {e}",
                    recipients=[trigger_context.user_email, responded_by],
                    description_key='reviewNotApplied',
                    params={'toStatus': target_status, 'reason': str(e)},
                    error=e,
                )
                raise _ReviewStepRefused() from e

    def _apply_requested_status_change(
        self,
        trigger_context: TriggerContext,
        product_id: str,
        target_status: str,
        responded_by: Optional[str],
        execution_id: Optional[str] = None,
    ) -> None:
        """Apply an approved status change request to a data product.

        Uses the app's notifications and search managers, so subscribers are
        notified and the search index is updated as for a direct status
        change. The request is applied only while the product still has the
        status it was made from: if the status changed meanwhile, the approval
        was about a different situation, so nothing is applied and the
        requester and approver are told. A product that already has the
        requested status (e.g. the completion ran twice) is left as is. If the
        transition is refused (e.g. a before_status_change gate blocks), the
        requester is told, since the workflow has already reported the request
        as approved.
        """
        from src.common.app_state import get_app_state_manager
        from src.controller.data_products_manager import DataProductsManager
        from src.db_models.data_products import DataProductDb

        product = self._db.get(DataProductDb, product_id)
        if product is None:
            logger.warning(
                "Approved status change of data product %s: the product no longer exists",
                product_id,
            )
            return
        current_status = (product.status or '').lower()
        if current_status == target_status.lower():
            logger.info(
                "Data product %s already has status '%s'; approved status change not reapplied",
                product_id, target_status,
            )
            return
        requested_from = trigger_context.from_status or (
            trigger_context.entity_data or {}
        ).get('from_status')
        if requested_from and current_status != requested_from.lower():
            logger.warning(
                "Approved status change of data product %s from '%s' to '%s' not applied: "
                "its status is now '%s'",
                product_id, requested_from, target_status, current_status,
            )
            # The "approved" notice of this run would contradict the one below
            self._withdraw_approval_notices(execution_id, trigger_context.user_email)
            self._notify_status_change_not_applied(
                trigger_context, product_id,
                f"The request to change the status from '{requested_from}' to "
                f"'{target_status}' was approved, but the status is now "
                f"'{current_status}', so the change was not applied. "
                f"Request it again if it is still needed.",
                recipients=[trigger_context.user_email, responded_by],
                description_key='statusChanged',
                params={
                    'fromStatus': requested_from, 'toStatus': target_status,
                    'currentStatus': current_status,
                },
            )
            return

        manager = DataProductsManager(
            db=self._db, notifications_manager=get_app_state_manager('notifications_manager'),
        )
        search_manager = get_app_state_manager('search_manager')
        if search_manager:
            manager.set_search_manager(search_manager)
        try:
            manager.transition_status(product_id, target_status, responded_by)
        except ValueError as e:
            logger.warning(
                "Approved status change of data product %s to '%s' could not be applied: %s",
                product_id, target_status, e,
            )
            self._withdraw_approval_notices(execution_id, trigger_context.user_email)
            self._notify_status_change_not_applied(
                trigger_context, product_id,
                f"Your request to change the status to '{target_status}' was approved, "
                f"but the change could not be applied: {e}",
                recipients=[trigger_context.user_email],
                description_key='refused',
                params={'toStatus': target_status, 'reason': str(e)},
                error=e,
            )
            return
        logger.info(
            "Data product %s moved to '%s' after its status change request was approved",
            product_id, target_status,
        )

    def _notify_status_change_not_applied(
        self,
        trigger_context: TriggerContext,
        product_id: str,
        description: str,
        recipients: List[Optional[str]],
        description_key: str,
        params: Dict[str, Any],
        error: Optional[Exception] = None,
    ) -> None:
        """Tell the given people that an approved status change was not applied.

        The English texts are stored; ``data.i18n`` carries the keys of the
        ``notifications`` namespace and their parameters, so the UI can show
        them in the user's language.
        """
        from uuid import uuid4
        from src.models.notifications import Notification, NotificationType
        from src.repositories.notification_repository import notification_repo

        sent = set()
        for recipient in recipients:
            if not recipient or recipient in sent:
                continue
            sent.add(recipient)
            notification_repo.create(db=self._db, obj_in=Notification(
                id=str(uuid4()),
                created_at=datetime.utcnow(),
                type=NotificationType.WARNING,
                title="Status change not applied",
                subtitle=trigger_context.entity_name or product_id,
                description=description,
                recipient=recipient,
                can_delete=True,
                data={'i18n': {
                    'title': 'notifications:statusChangeNotApplied.title',
                    'description': f'notifications:statusChangeNotApplied.{description_key}',
                    'params': params,
                    'statusNamespace': 'data-products',
                    **self._coded_error_i18n(error),
                }},
            ))
        if sent:
            self._db.commit()

    def _execute_step(self, step: WorkflowStep, context: StepContext) -> StepResult:
        """Execute a single step."""
        step_type = step.step_type.value if hasattr(step.step_type, 'value') else step.step_type
        handler_class = self.HANDLERS.get(step_type)
        
        if not handler_class:
            return StepResult(passed=False, error=f"Unknown step type: {step_type}")
        
        try:
            # Handle config - may be a JSON string from DB or already a dict
            config = step.config or {}
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except json.JSONDecodeError:
                    config = {}
            
            handler = handler_class(self._db, config)
            context.step_id = step.step_id
            return handler.execute(context)
        except Exception as e:
            logger.exception(f"Step execution failed: {e}")
            return StepResult(passed=False, error=str(e))

    def _db_to_model(self, db_execution: WorkflowExecutionDb, workflow_name: str) -> WorkflowExecution:
        """Convert database execution to model."""
        trigger_context = None
        if db_execution.trigger_context:
            try:
                tc_data = json.loads(db_execution.trigger_context)
                trigger_context = TriggerContext(**tc_data)
            except (json.JSONDecodeError, TypeError):
                pass
        
        step_executions = []
        for se in db_execution.step_executions:
            step_executions.append(WorkflowStepExecutionResult(
                id=se.id,
                step_id=se.step_id,
                step_key=se.step_key,
                step_name=se.step_name,
                status=StepExecutionStatus(se.status),
                passed=se.passed,
                result_data=json.loads(se.result_data) if se.result_data else None,
                error_message=se.error_message,
                duration_ms=se.duration_ms,
                started_at=se.started_at,
                finished_at=se.finished_at,
            ))
        
        return WorkflowExecution(
            id=db_execution.id,
            workflow_id=db_execution.workflow_id,
            trigger_context=trigger_context,
            status=ExecutionStatus(db_execution.status),
            current_step_id=db_execution.current_step_id,
            success_count=db_execution.success_count,
            failure_count=db_execution.failure_count,
            error_message=db_execution.error_message,
            started_at=db_execution.started_at,
            finished_at=db_execution.finished_at,
            triggered_by=db_execution.triggered_by,
            step_executions=step_executions,
            workflow_name=workflow_name,
            entity_type=trigger_context.entity_type if trigger_context else None,
            entity_id=trigger_context.entity_id if trigger_context else None,
            entity_name=trigger_context.entity_name if trigger_context else None,
        )

