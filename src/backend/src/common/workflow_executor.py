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


class ValidationStepHandler(StepHandler):
    """Handler for validation steps using compliance DSL."""

    def execute(self, context: StepContext) -> StepResult:
        from src.common.compliance_dsl import evaluate_rule_on_object
        
        rule = self._config.get('rule', '')
        if not rule:
            return StepResult(passed=False, error="No rule configured")
        
        try:
            passed, message = evaluate_rule_on_object(rule, context.entity)
            return StepResult(
                passed=passed,
                message=message,
                data={'rule': rule}
            )
        except Exception as e:
            logger.exception(f"Validation step failed: {e}")
            return StepResult(
                passed=False,
                error=str(e)
            )


def _resolve_role_to_users(
    db: Session,
    role_spec: str,
    context: 'StepContext',
) -> List[tuple]:
    """Resolve a role specification to a list of (identifier, role_id_or_None) tuples.

    Handles:
    - 'requester' → original user email
    - 'owner' → entity owner
    - 'business:<uuid>' → business role → look up entity owners from business_owners table
    - '<uuid>' → app role UUID
    - 'user@email.com' → direct email
    - Legacy aliases like 'domain_owners', 'admins', etc.
    """
    from src.db_models.settings import AppRoleDb
    from src.db_models.business_roles import BusinessRoleDb
    from src.db_models.business_owners import BusinessOwnerDb

    # Map shorthand names to role names (legacy support)
    role_aliases = {
        'domain_owners': 'DomainOwner',
        'project_owners': 'ProjectOwner',
        'data_stewards': 'DataSteward',
        'admins': 'Admin',
    }

    if role_spec == 'requester':
        return [(context.user_email, None)] if context.user_email else []

    if role_spec == 'owner':
        owner = context.entity.get('owner') if context.entity else None
        return [(owner, None)] if owner else []

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

    if '@' in role_spec:
        return [(e.strip(), None) for e in role_spec.split(',')]

    # Business role: prefixed with "business:"
    if role_spec.startswith('business:'):
        br_id = role_spec[len('business:'):]
        br = db.query(BusinessRoleDb).filter(BusinessRoleDb.id == br_id).first()
        if not br:
            logger.warning(f"Business role {br_id} not found")
            return []

        # Runtime resolution: look up who holds this business role for this entity
        owners = (
            db.query(BusinessOwnerDb)
            .filter(
                BusinessOwnerDb.role_id == br.id,
                BusinessOwnerDb.object_id == context.entity_id,
                BusinessOwnerDb.is_active.is_(True),
            )
            .all()
        )

        if not owners:
            # No one assigned this role for this entity
            logger.warning(
                f"No active {br.name} assigned to {context.entity_type} "
                f"{context.entity_id} ({context.entity_name})"
            )
            return []

        return [(o.user_email, str(br.id)) for o in owners]

    # App role UUID (preferred new format)
    role_by_id = db.query(AppRoleDb).filter(AppRoleDb.id == role_spec).first()
    if role_by_id:
        return [(role_by_id.name, role_by_id.id)]

    # Fallback: role name (legacy)
    normalized = role_spec.lower().replace(' ', '')
    for r in db.query(AppRoleDb).all():
        if r.name.lower().replace(' ', '') == normalized:
            return [(r.name, r.id)]

    return [(role_spec, None)]


class ApprovalStepHandler(StepHandler):
    """Handler for approval steps - creates actionable notifications and pauses workflow."""

    def execute(self, context: StepContext) -> StepResult:
        from uuid import uuid4
        from src.models.notifications import Notification, NotificationType
        from src.repositories.notification_repository import notification_repo
        
        approvers = self._config.get('approvers', '')
        timeout_days = self._config.get('timeout_days', 7)
        require_all = self._config.get('require_all', False)
        approval_message = self._config.get('message', '')
        
        if not approvers:
            return StepResult(passed=False, error="No approvers configured")
        
        try:
            # Resolve approvers - returns list of (identifier, role_id or None)
            resolved_approvers = self._resolve_approvers(approvers, context)
            
            if not resolved_approvers:
                return StepResult(passed=False, error="Could not resolve any approvers")
            
            entity_display = context.entity_name or context.entity_id
            
            # Create actionable notification for each approver
            created_count = 0
            for approver_id, role_uuid in resolved_approvers:
                try:
                    # Build description with request details
                    description = (
                        f"Approval requested for {context.entity_type} '{entity_display}'.\n\n"
                        f"Requested by: {context.user_email or 'Unknown'}\n"
                    )
                    if approval_message:
                        description += f"\nMessage: {approval_message}"
                    if context.entity.get('message'):
                        description += f"\nMessage: {context.entity.get('message')}"
                    if context.entity.get('justification'):
                        description += f"\nJustification: {context.entity.get('justification')}"
                    
                    notification = Notification(
                        id=str(uuid4()),
                        created_at=datetime.utcnow(),
                        type=NotificationType.ACTION_REQUIRED,
                        title="Approval Required",
                        subtitle=f"{context.entity_type}: {entity_display}",
                        description=description,
                        recipient=approver_id,  # Keep for backwards compat / email recipients
                        recipient_role_id=role_uuid,  # Store role UUID if this is a role
                        action_type="workflow_approval",
                        action_payload={
                            "execution_id": context.execution_id,
                            "workflow_id": context.workflow_id,
                            "workflow_name": context.workflow_name,
                            "entity_type": context.entity_type,
                            "entity_id": context.entity_id,
                            "entity_name": context.entity_name,
                            "requester_email": context.user_email,
                            "timeout_days": timeout_days,
                        },
                        can_delete=False,  # Must respond to this notification
                        read=False,
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
            
            created_count = 0
            email_count = 0

            # --- in_app channel ---
            if 'in_app' in channels:
                for recipient_id, role_uuid in resolved_recipients:
                    try:
                        notification = Notification(
                            id=str(uuid4()),
                            created_at=datetime.utcnow(),
                            type=notification_type,
                            title=title,
                            subtitle=f"{context.entity_type}: {context.entity_name}",
                            description=message,
                            recipient=recipient_id,
                            recipient_role_id=role_uuid,
                            action_type=action_type,
                            action_payload=action_payload,
                            can_delete=can_delete,
                            read=False,
                        )
                        notification_repo.create(db=self._db, obj_in=notification)
                        created_count += 1
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
        entity_display = context.entity_name or context.entity_id
        titles = {
            'validation_failed': "Validation Failed",
            'validation_passed': "Validation Passed",
            'product_approved': "Data Product Approved",
            'product_rejected': "Data Product Rejected",
            'approval_requested': "Approval Requested",
            'request_submitted': "Request Submitted",
            'request_approved': "Request Approved",
            'request_rejected': "Request Denied",
            'dataset_updated': "Dataset Updated",
            'pii_detected': "PII Detected",
        }
        return titles.get(template, "Workflow Notification")

    def _get_template_message(self, template: str, context: StepContext) -> str:
        """Get message from template."""
        entity_display = context.entity_name or context.entity_id
        templates = {
            'validation_failed': f"Validation failed for {context.entity_type} '{entity_display}'",
            'validation_passed': f"Validation passed for {context.entity_type} '{entity_display}'",
            'product_approved': f"Data product '{entity_display}' has been approved",
            'product_rejected': f"Data product '{entity_display}' has been rejected",
            'approval_requested': f"Approval requested for {context.entity_type} '{entity_display}'",
            'request_submitted': f"Your request for {context.entity_type} '{entity_display}' has been submitted and is pending review.",
            'request_approved': f"Your request for {context.entity_type} '{entity_display}' has been approved.",
            'request_rejected': f"Your request for {context.entity_type} '{entity_display}' has been denied.",
            'dataset_updated': f"Dataset '{entity_display}' has been updated.",
            'pii_detected': f"Potential PII detected in {context.entity_type} '{entity_display}'. Please review.",
        }
        return templates.get(template, f"Workflow notification for {entity_display}")

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
            evaluator = Evaluator(context.entity)
            result = evaluator.evaluate(ast)
            
            return StepResult(
                passed=bool(result),
                message=f"Condition evaluated to: {result}",
                data={'condition': condition, 'result': result}
            )
        except Exception as e:
            logger.exception(f"Conditional step failed: {e}")
            return StepResult(passed=False, error=str(e))


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
    """Handler for policy check steps - evaluates existing compliance policy by UUID."""

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
            
            # Evaluate the policy's rule against the entity
            passed, technical_message = evaluate_rule_on_object(policy.rule, context.entity)
            
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
            return StepResult(
                passed=False, 
                error=str(e),
                data={'policy_id': policy_id}
            )


class CreateAssetReviewStepHandler(StepHandler):
    """Handler for creating data asset review requests.
    
    This step creates a formal DataAssetReview record for tracking purposes,
    useful when workflows need to integrate with the data asset review system.
    
    Config options:
        reviewer_role: Role name or UUID of the reviewer (default: 'DataSteward')
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
            
            # Resolve reviewer email from role
            reviewer_email = self._resolve_reviewer_from_role(reviewer_role)
            used_fallback = False
            if not reviewer_email:
                # Fallback: use the requester as the reviewer (self-review placeholder)
                # This allows the asset review to be created even if the role has no members
                reviewer_email = requester_email
                used_fallback = True
                logger.warning(
                    f"Could not resolve reviewer from role: {reviewer_role}. "
                    f"Using requester ({requester_email}) as fallback reviewer."
                )
            
            # Determine asset FQN
            asset_fqns = []
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
                elif entity_type == 'data_contract':
                    fqn = context.entity.get('name') or entity_data.get('name') or entity_name or entity_id
                    if fqn:
                        asset_fqns.append(f"contract:{fqn}")
                elif entity_type == 'data_product':
                    fqn = context.entity.get('name') or entity_data.get('name') or entity_name or entity_id
                    if fqn:
                        asset_fqns.append(f"product:{fqn}")
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
                ReviewRequestStatus, ReviewedAssetStatus, AssetType
            )
            from uuid import uuid4
            from datetime import datetime
            
            review_id = str(uuid4())
            
            # Build assets list
            assets_to_review = []
            for fqn in asset_fqns:
                # Determine asset type from FQN prefix
                if fqn.startswith('dataset:'):
                    asset_type = AssetType.TABLE  # Datasets map to tables
                elif fqn.startswith('contract:'):
                    asset_type = AssetType.TABLE  # Contracts map to tables
                elif fqn.startswith('product:'):
                    asset_type = AssetType.TABLE  # Products map to tables
                else:
                    asset_type = AssetType.TABLE  # Default for UC assets
                
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
                status=ReviewRequestStatus.QUEUED,
                notes=full_notes,
                created_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                assets=assets_to_review,
            )
            
            # Use repository to create
            review = data_asset_review_repo.create_with_assets(db=self._db, obj_in=full_request)
            
            fallback_note = " (using requester as fallback reviewer)" if used_fallback else ""
            logger.info(f"Created asset review {review.id} for {asset_fqns} by {reviewer_email}{fallback_note}")
            
            return StepResult(
                passed=True,
                message=f"Asset review created: {review.id}{fallback_note}",
                data={
                    'review_id': review.id,
                    'reviewer_email': reviewer_email,
                    'asset_fqns': asset_fqns,
                    'review_type': review_type,
                    'used_fallback': used_fallback,
                }
            )
            
        except Exception as e:
            logger.exception(f"Failed to create asset review: {e}")
            return StepResult(passed=False, error=str(e))
    
    def _resolve_reviewer_from_role(self, role_identifier: str) -> Optional[str]:
        """Resolve a reviewer email from a role name or UUID.
        
        Returns the email of the first user in the role's assigned groups,
        or None if no users are found.
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
                                        if user and user.user_name:
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
        
        try:
            if connection_name:
                # UC Connection mode
                result = self._execute_via_uc_connection(
                    connection_name=connection_name,
                    method=method,
                    path=path,
                    headers=resolved_headers,
                    body=body,
                    timeout_seconds=timeout_seconds,
                    success_codes=success_codes,
                    retry_count=retry_count,
                )
            else:
                # Inline mode
                result = self._execute_direct(
                    url=url,
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
        db_entity.publication_scope = scope
        db_entity.published_at = datetime.now(timezone.utc)
        db_entity.published_by = context.user_email
        self._db.add(db_entity)
        self._db.commit()
        logger.info(f"entity_action: published {entity_type} {entity_id} with scope={scope}")
        return StepResult(passed=True, message=f"Published with scope {scope}",
                          data={'publication_scope': scope})

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
            principal = context.user_email
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
        workflow_execution_repo.add_step_execution(
            self._db,
            execution_id=execution_id,
            step_id=current_step.id,
            status=StepExecutionStatus.SUCCEEDED.value if step_result else StepExecutionStatus.FAILED.value,
            passed=step_result,
            result_data={
                'approval_result': 'approved' if step_result else 'rejected',
                'responded_by': user_email,
                **(result_data or {}),
            },
            error_message=None if step_result else (result_data or {}).get('reason', 'Request denied'),
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
                        approval_entry.update(merged)
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
        
        # Count the approval step
        if step_result:
            success_count += 1
        else:
            failure_count += 1
        
        final_status = ExecutionStatus.RUNNING
        error_message = None
        
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
            )
        
        # Return updated execution
        db_execution = workflow_execution_repo.get(self._db, execution_id)
        return self._db_to_model(db_execution, workflow.name)

    def _handle_workflow_completion(
        self,
        trigger_context: Optional[TriggerContext],
        workflow: ProcessWorkflow,
        succeeded: bool,
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
                    
            # Handle data contract deploy completion
            elif entity_type == 'data_contract' and trigger_type in ('on_request_publish', 'ON_REQUEST_PUBLISH'):
                from src.repositories.data_contracts_repository import data_contract_repo
                db_contract = data_contract_repo.get(db=self._db, id=entity_id)
                if db_contract:
                    if succeeded:
                        db_contract.status = 'deployed'
                        logger.info(f"Data contract {entity_id} status updated to 'deployed' after approval")
                    else:
                        db_contract.status = 'draft'
                        logger.info(f"Data contract {entity_id} status reverted to 'draft' after rejection")
                    self._db.commit()
                    
            # Handle data product activation completion
            elif entity_type == 'data_product' and trigger_type in ('on_request_review', 'ON_REQUEST_REVIEW'):
                from src.repositories.data_products_repository import data_product_repo
                db_product = data_product_repo.get(db=self._db, id=entity_id)
                if db_product:
                    if succeeded:
                        db_product.status = 'active'
                        logger.info(f"Data product {entity_id} status updated to 'active' after approval")
                    else:
                        db_product.status = 'draft'
                        logger.info(f"Data product {entity_id} status reverted to 'draft' after rejection")
                    self._db.commit()
                    
        except Exception as e:
            logger.error(f"Error updating entity status after workflow completion: {e}", exc_info=True)
            # Don't fail the workflow for status update issues
    
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
        )

