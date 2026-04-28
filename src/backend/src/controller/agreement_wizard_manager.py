"""
Agreement Wizard Manager.

Runs approval workflows as multi-step wizards. Creates session, advances steps,
and on completion creates an agreement record and writes to entity change log
(optional PDF via todo 5).
"""

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from sqlalchemy.orm import Session

from src.controller.workflows_manager import WorkflowsManager
from src.controller.change_log_manager import ChangeLogManager
from src.models.process_workflows import ProcessWorkflow, WorkflowStep, StepType, WorkflowType
from src.models.notifications import Notification, NotificationType
from src.repositories.agreement_wizard_sessions_repository import agreement_wizard_sessions_repo
from src.repositories.agreements_repository import agreements_repo
from src.repositories.data_contracts_repository import data_contract_repo
from src.repositories.data_products_repository import data_product_repo
from src.repositories.assets_repository import asset_repo
from src.common.logging import get_logger

if TYPE_CHECKING:
    from src.controller.notifications_manager import NotificationsManager

logger = get_logger(__name__)


class AgreementWizardManager:
    """Manager for agreement wizard sessions (approval workflows as wizards)."""

    def __init__(
        self,
        db: Session,
        *,
        storage_base_path: Optional[str] = None,
        notifications_manager: Optional['NotificationsManager'] = None,
    ):
        self._db = db
        self._workflows_manager = WorkflowsManager(db)
        self._storage_base_path = storage_base_path
        self._notifications_manager = notifications_manager

    def _get_workflow_steps(self, workflow_id: str) -> Optional[List[WorkflowStep]]:
        """Get workflow steps in order; workflow must be approval type."""
        workflow = self._workflows_manager.get_workflow(workflow_id)
        if not workflow:
            return None
        if getattr(workflow, 'workflow_type', WorkflowType.PROCESS) != WorkflowType.APPROVAL:
            return None
        steps = workflow.steps or []
        return sorted(steps, key=lambda s: s.order if s.order is not None else 0)

    def _get_entity_name(self, entity_type: str, entity_id: str) -> Optional[str]:
        """Resolve display name for an entity by type and id via repositories."""
        if not entity_type or not entity_id:
            return None
        et = (entity_type or "").strip().lower()
        if et == "data_product":
            row = data_product_repo.get(self._db, entity_id)
            return row.name if row else None
        if et in ("dataset", "asset"):
            row = asset_repo.get(self._db, entity_id)
            return row.name if row else None
        if et == "data_contract":
            row = data_contract_repo.get(self._db, entity_id)
            return row.name if row else None
        return None

    def get_my_sessions(
        self,
        created_by: str,
        limit: int = 100,
        offset: int = 0,
    ) -> Tuple[List[Dict[str, Any]], int]:
        """Get sessions created by the user with entity_name resolved. Returns (sessions, total)."""
        sessions, total = agreement_wizard_sessions_repo.get_by_created_by(
            self._db, created_by, limit=limit, offset=offset
        )
        out = []
        for s in sessions:
            out.append({
                "id": s.id,
                "workflow_id": s.workflow_id,
                "entity_type": s.entity_type,
                "entity_id": s.entity_id,
                "entity_name": self._get_entity_name(s.entity_type, s.entity_id),
                "completion_action": s.completion_action,
                "status": s.status,
                "created_at": s.created_at,
                "updated_at": s.updated_at,
            })
        return out, total

    def create_session(
        self,
        workflow_id: str,
        entity_type: str,
        entity_id: str,
        *,
        completion_action: Optional[str] = None,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a new wizard session and return session_id and first step.
        Raises ValueError if workflow not found or not approval type.
        completion_action: optional, e.g. 'subscribe' — run after wizard complete.
        """
        steps = self._get_workflow_steps(workflow_id)
        if not steps:
            raise ValueError("Workflow not found or not an approval workflow")

        # Capture immutable workflow snapshot so historical agreements reflect
        # what the signer actually saw, even if the workflow is later edited.
        workflow = self._workflows_manager.get_workflow(workflow_id)
        workflow_snapshot = None
        workflow_name = None
        if workflow:
            workflow_name = workflow.name
            workflow_snapshot = json.dumps({
                "workflow_id": workflow.id,
                "name": workflow.name,
                "description": workflow.description or "",
                "workflow_type": (lambda wt: wt.value if hasattr(wt, 'value') else str(wt))(getattr(workflow, 'workflow_type', 'approval')),
                "steps": [
                    {
                        "step_id": s.step_id,
                        "name": s.name,
                        "step_type": s.step_type if isinstance(s.step_type, str) else s.step_type.value,
                        "config": json.loads(s.config) if isinstance(s.config, str) else (s.config or {}),
                        "on_pass": s.on_pass,
                        "on_fail": s.on_fail,
                        "order": s.order,
                    }
                    for s in sorted(workflow.steps or [], key=lambda x: x.order if x.order is not None else 0)
                ],
            })

        session = agreement_wizard_sessions_repo.create(
            self._db,
            workflow_id=workflow_id,
            entity_type=entity_type,
            entity_id=entity_id,
            completion_action=completion_action,
            created_by=created_by,
            workflow_snapshot=workflow_snapshot,
            workflow_name=workflow_name,
        )
        first = steps[0]
        return {
            "session_id": session.id,
            "workflow_id": workflow_id,
            "current_step": self._step_to_response(first, 0),
            "step_results": [],
        }

    def _reason_from_step_results(self, step_results: List[Dict[str, Any]]) -> Optional[str]:
        """Extract reason (or first text field) from step_results for subscribe."""
        for item in step_results:
            payload = item.get("payload") or {}
            if isinstance(payload, dict):
                reason = payload.get("reason")
                if reason and isinstance(reason, str) and reason.strip():
                    return reason.strip()
                for k, v in payload.items():
                    if isinstance(v, str) and v.strip():
                        return v.strip()
        return None

    def _step_to_response(self, step: WorkflowStep, index: int) -> Dict[str, Any]:
        """Convert WorkflowStep to API response shape."""
        return {
            "step_id": step.step_id,
            "name": step.name,
            "step_type": step.step_type.value,
            "config": step.config or {},
            "order": step.order if step.order is not None else index,
            "index": index,
        }

    def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session with current step and step_results (for Back/refresh)."""
        session = agreement_wizard_sessions_repo.get(self._db, session_id)
        if not session or session.status != "in_progress":
            return None
        steps = self._get_workflow_steps(session.workflow_id)
        if not steps:
            return None
        idx = min(session.current_step_index, len(steps) - 1)
        current = steps[idx]
        results = agreement_wizard_sessions_repo.get_step_results(session)
        return {
            "session_id": session.id,
            "workflow_id": session.workflow_id,
            "entity_type": session.entity_type,
            "entity_id": session.entity_id,
            "current_step": self._step_to_response(current, idx),
            "step_results": results,
            "status": session.status,
        }

    def _validate_user_action_payload(self, step: WorkflowStep, payload: Dict[str, Any]) -> None:
        """Validate payload for user_action step (required_fields, requires_input, minimum_input_length). Raises ValueError if invalid."""
        config = step.config or {}
        required_fields = config.get("required_fields") or []
        for field in required_fields:
            if field.get("required"):
                fid = field.get("id") or field.get("name")
                if not fid:
                    continue
                value = payload.get(fid)
                if value is None or (isinstance(value, str) and not value.strip()):
                    raise ValueError(f"Required field '{field.get('label', fid)}' is missing or empty")

        requires_input = config.get("requires_input", False)
        minimum_input_length = config.get("minimum_input_length")
        primary_field_id = (
            config.get("primary_field_id")
            or (next((f.get("id") or f.get("name") for f in required_fields if f.get("required")), None))
            or (required_fields[0].get("id") or required_fields[0].get("name") if required_fields else None)
            or "reason"
        )
        primary_value = (payload.get(primary_field_id) or "").strip() if isinstance(payload.get(primary_field_id), str) else ""
        if requires_input and not primary_value:
            raise ValueError("This step requires input.")
        if minimum_input_length is not None and minimum_input_length > 0 and len(primary_value) < minimum_input_length:
            raise ValueError(f"Input must be at least {minimum_input_length} characters (got {len(primary_value)}).")

    def _validate_legal_document_payload(self, step: WorkflowStep, payload: Dict[str, Any]) -> None:
        """Validate payload for legal_document step."""
        config = step.config or {}
        if config.get("require_scroll_to_end") and not payload.get("scrolled_to_end"):
            raise ValueError("You must scroll to the end of the document before continuing.")
        if config.get("require_acknowledgement_checkbox") and not payload.get("acknowledged"):
            raise ValueError("You must acknowledge the document before continuing.")

    def _validate_acknowledgement_checklist_payload(self, step: WorkflowStep, payload: Dict[str, Any]) -> None:
        """Validate payload for acknowledgement_checklist step."""
        config = step.config or {}
        items = config.get("items") or []
        checked_items = payload.get("items") or {}
        for item in items:
            item_id = item.get("id")
            if not item_id:
                continue
            required = item.get("required", True)  # Default required
            if required and not checked_items.get(item_id):
                raise ValueError(f"Required item '{item.get('label', item_id)}' must be checked.")

    def _validate_co_signers_payload(self, step: WorkflowStep, payload: Dict[str, Any]) -> None:
        """Validate payload for co_signers step."""
        config = step.config or {}
        min_count = config.get("min_count", 0)
        max_count = config.get("max_count", 5)
        signers = payload.get("co_signers") or []
        if not isinstance(signers, list):
            raise ValueError("co_signers must be a list.")
        if len(signers) < min_count:
            raise ValueError(f"At least {min_count} co-signer(s) required (got {len(signers)}).")
        if len(signers) > max_count:
            raise ValueError(f"At most {max_count} co-signer(s) allowed (got {len(signers)}).")

    def submit_step(
        self,
        session_id: str,
        step_id: str,
        payload: Dict[str, Any],
        *,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Validate payload, append to step_results, advance to next step.
        Returns next step or { "complete": true, "agreement_id": ..., "pdf_storage_path": ... }.
        On complete: create agreement (todo 4), change log, optional PDF (todo 5); set session completed.
        """
        session = agreement_wizard_sessions_repo.get(self._db, session_id)
        if not session or session.status != "in_progress":
            raise ValueError("Session not found or not in progress")
        steps = self._get_workflow_steps(session.workflow_id)
        if not steps:
            raise ValueError("Workflow steps not found")
        idx = session.current_step_index
        if idx >= len(steps):
            raise ValueError("Session already past last step")
        current = steps[idx]
        if current.step_id != step_id:
            raise ValueError(f"Step mismatch: expected {current.step_id}, got {step_id}")

        # Per-step-type validation
        if current.step_type == StepType.USER_ACTION:
            self._validate_user_action_payload(current, payload)
        elif current.step_type == StepType.LEGAL_DOCUMENT:
            self._validate_legal_document_payload(current, payload)
        elif current.step_type == StepType.ACKNOWLEDGEMENT_CHECKLIST:
            self._validate_acknowledgement_checklist_payload(current, payload)
        elif current.step_type == StepType.CO_SIGNERS:
            self._validate_co_signers_payload(current, payload)
        # Non-visual steps (persist_agreement, generate_pdf, deliver) skip validation

        # Execute non-visual step side effects
        if current.step_type == StepType.PERSIST_AGREEMENT:
            # Persist agreement is handled implicitly at _complete_session.
            # When this step is explicit in the workflow, we record it so
            # _complete_session knows the signer saw this step (future enhancement).
            # For now this is a no-op — the agreement is always persisted at completion.
            pass

        if current.step_type == StepType.GENERATE_PDF:
            # PDF generation is driven by the presence of a generate_pdf step in
            # the workflow — _complete_session already checks for it. Store any
            # per-step config overrides (e.g. template, watermark) in the result
            # so _complete_session can consume them.
            config = current.config or {}
            payload = {
                **payload,
                "template": config.get("template", "default"),
                "include_step_results": config.get("include_step_results", True),
            }

        if current.step_type == StepType.DELIVER:
            # Deliver step: capture delivery channel config for _complete_session.
            # Actual dispatch uses existing notification infrastructure.
            config = current.config or {}
            payload = {
                **payload,
                "channels": config.get("channels", ["in_app"]),
                "recipients": config.get("recipients", ["signer"]),
                "delivered": True,
            }

        agreement_wizard_sessions_repo.append_step_result(self._db, session_id, step_id, payload)
        session = agreement_wizard_sessions_repo.get(self._db, session_id)
        if not session:
            raise ValueError("Session not found after appending step result")

        next_step_id = current.on_pass
        if not next_step_id:
            return self._complete_session(session, created_by=created_by)
        next_idx = next((i for i, s in enumerate(steps) if s.step_id == next_step_id), None)
        if next_idx is None:
            return self._complete_session(session, created_by=created_by)
        next_step = steps[next_idx]
        if next_step.step_type == StepType.PASS and not (next_step.on_pass or next_step.on_fail):
            return self._complete_session(session, created_by=created_by)
        agreement_wizard_sessions_repo.set_current_step_index(self._db, session_id, next_idx)
        session = agreement_wizard_sessions_repo.get(self._db, session_id)
        return {
            "complete": False,
            "current_step": self._step_to_response(next_step, next_idx),
            "step_results": agreement_wizard_sessions_repo.get_step_results(session) if session else [],
        }

    def _complete_session(
        self,
        session: Any,
        *,
        created_by: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create agreement record, write change log, optional PDF (todo 5); set session completed.
        """
        step_results = agreement_wizard_sessions_repo.get_step_results(session)
        agreement = agreements_repo.create(
            self._db,
            entity_type=session.entity_type,
            entity_id=session.entity_id,
            workflow_id=session.workflow_id,
            wizard_session_id=session.id,
            step_results=step_results,
            pdf_storage_path=None,  # Todo 5: set when workflow has generate_pdf step
            created_by=created_by or session.created_by,
            workflow_snapshot=session.workflow_snapshot,
            workflow_name=session.workflow_name,
        )
        change_log_manager = ChangeLogManager()
        change_log_manager.log_change_with_details(
            self._db,
            entity_type=session.entity_type,
            entity_id=session.entity_id,
            action="APPROVAL_COMPLETED",
            username=created_by or session.created_by,
            details={"agreement_id": agreement.id, "session_id": session.id},
        )
        pdf_storage_path = agreement.pdf_storage_path
        has_generate_pdf = False
        workflow = self._workflows_manager.get_workflow(session.workflow_id)
        if workflow:
            has_generate_pdf = any(
                getattr(s, "step_type", None) == StepType.GENERATE_PDF
                for s in (workflow.steps or [])
            )
        if has_generate_pdf and workflow and self._storage_base_path:
            # Try reportlab-based PDF first, fall back to HTML-based builder
            try:
                from pathlib import Path
                from src.common.agreement_pdf import build_agreement_pdf
                out_dir = Path(self._storage_base_path) / "agreements"
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = str(out_dir / f"{agreement.id}.pdf")
                steps_with_config = [
                    {"step_id": s.step_id, "name": s.name, "step_type": s.step_type.value, "config": s.config or {}}
                    for s in (workflow.steps or [])
                ]
                build_agreement_pdf(
                    workflow_name=workflow.name,
                    entity_type=session.entity_type,
                    entity_id=session.entity_id,
                    steps_with_config=steps_with_config,
                    step_results=step_results,
                    output_path=out_path,
                )
                agreements_repo.set_pdf_storage_path(self._db, agreement.id, out_path)
                pdf_storage_path = out_path
            except Exception as e:
                logger.warning("Agreement PDF generation failed (reportlab): %s — HTML download available via API", e)
        completion_action = getattr(session, "completion_action", None)
        subscriber_email = created_by or session.created_by
        if completion_action == "subscribe" and subscriber_email:
            reason = self._reason_from_step_results(step_results)
            entity_type_lower = (session.entity_type or "").strip().lower()
            if entity_type_lower in ("data_product", "dataproduct"):
                try:
                    from src.controller.data_products_manager import DataProductsManager
                    dp_manager = DataProductsManager(self._db)
                    dp_manager.subscribe(
                        product_id=session.entity_id,
                        subscriber_email=subscriber_email,
                        reason=reason,
                        db=self._db,
                    )
                    logger.info("Subscription created for data_product %s via agreement wizard", session.entity_id)
                except Exception as e:
                    logger.warning("Subscribe (data_product) after wizard failed: %s", e)
            elif entity_type_lower in ("dataset", "asset"):
                try:
                    from src.models.entity_subscriptions import EntitySubscriptionCreate
                    from src.repositories.entity_subscriptions_repository import entity_subscription_repo
                    sub_in = EntitySubscriptionCreate(
                        entity_type="asset",
                        entity_id=str(session.entity_id),
                        subscriber_email=subscriber_email,
                        subscription_reason=reason,
                    )
                    entity_subscription_repo.create(self._db, obj_in=sub_in)
                    logger.info("Subscription created for asset %s via agreement wizard", session.entity_id)
                except Exception as e:
                    logger.warning("Subscribe (asset) after wizard failed: %s", e)

        # Deliver step: send in_app notifications to configured recipients
        self._send_delivery_notifications(
            session=session,
            workflow=workflow,
            workflow_name=workflow.name if workflow else session.workflow_name,
            agreement_id=agreement.id,
            created_by=created_by,
        )

        agreement_wizard_sessions_repo.set_completed(self._db, session.id)
        pdf_url = f"/api/approvals/agreements/{agreement.id}/pdf" if has_generate_pdf else None
        return {
            "complete": True,
            "agreement_id": agreement.id,
            "pdf_storage_path": pdf_storage_path,
            "pdf_url": pdf_url,
            "session_id": session.id,
        }

    def _send_delivery_notifications(
        self,
        session: Any,
        workflow: Any,
        workflow_name: Optional[str],
        agreement_id: str,
        created_by: Optional[str],
    ) -> None:
        """Send in_app notifications for a deliver step if present in the workflow.

        Resolves recipient tokens (``signer``, ``entity_owner``, or literal
        email addresses) and creates one notification per recipient using the
        existing NotificationsManager infrastructure.
        """
        if not self._notifications_manager:
            return
        if not workflow:
            return

        steps = workflow.steps or []
        deliver_step = next(
            (s for s in steps if getattr(s, 'step_type', None) == StepType.DELIVER),
            None,
        )
        if not deliver_step:
            return

        config = deliver_step.config if hasattr(deliver_step, 'config') else {}
        if isinstance(config, str):
            config = json.loads(config)
        config = config or {}

        channels = config.get("channels", ["in_app"])
        if "in_app" not in channels:
            return

        recipients_tokens = config.get("recipients", ["signer"])
        signer_email = created_by or getattr(session, 'created_by', None)
        entity_name = self._get_entity_name(session.entity_type, session.entity_id)
        display_name = workflow_name or "Approval workflow"
        entity_label = entity_name or f"{session.entity_type} {session.entity_id}"

        # Resolve recipient tokens to email addresses
        notification_recipients: List[str] = []
        for token in recipients_tokens:
            if token == "signer":
                if signer_email:
                    notification_recipients.append(signer_email)
            elif token == "entity_owner":
                # Best-effort: fall back to signer if we can't resolve the owner
                owner = self._resolve_entity_owner(session.entity_type, session.entity_id)
                notification_recipients.append(owner or signer_email or "")
            elif isinstance(token, str) and "@" in token:
                # Literal email address
                notification_recipients.append(token)

        # Deduplicate while preserving order, skip blanks
        seen: set = set()
        unique_recipients: List[str] = []
        for r in notification_recipients:
            if r and r not in seen:
                seen.add(r)
                unique_recipients.append(r)

        for recipient in unique_recipients:
            try:
                notification = Notification(
                    id=str(uuid.uuid4()),
                    type=NotificationType.INFO,
                    title=f"Agreement completed: {display_name}",
                    description=(
                        f"The approval workflow '{display_name}' has been completed "
                        f"for {entity_label}."
                    ),
                    recipient=recipient,
                    link=f"/approvals/agreements/{agreement_id}",
                    action_type="agreement_completed",
                    action_payload={
                        "agreement_id": agreement_id,
                        "entity_type": session.entity_type,
                        "entity_id": session.entity_id,
                    },
                    created_at=datetime.utcnow(),
                    read=False,
                    can_delete=True,
                )
                self._notifications_manager.create_notification(
                    notification=notification,
                    db=self._db,
                )
                logger.info(
                    "Delivery notification sent to %s for agreement %s",
                    recipient, agreement_id,
                )
            except Exception as e:
                logger.warning(
                    "Failed to send delivery notification to %s: %s",
                    recipient, e,
                )

    def _resolve_entity_owner(self, entity_type: str, entity_id: str) -> Optional[str]:
        """Best-effort lookup of the entity owner's email."""
        et = (entity_type or "").strip().lower()
        try:
            if et == "data_product":
                row = data_product_repo.get(self._db, entity_id)
                return getattr(row, 'owner', None) or getattr(row, 'owner_email', None) if row else None
            if et in ("dataset", "asset"):
                row = asset_repo.get(self._db, entity_id)
                return getattr(row, 'owner', None) or getattr(row, 'owner_email', None) if row else None
            if et == "data_contract":
                row = data_contract_repo.get(self._db, entity_id)
                return getattr(row, 'owner', None) or getattr(row, 'owner_email', None) if row else None
        except Exception as e:
            logger.debug("Could not resolve entity owner for %s/%s: %s", entity_type, entity_id, e)
        return None

    def abort_session(self, session_id: str) -> bool:
        """Mark session as abandoned."""
        session = agreement_wizard_sessions_repo.get(self._db, session_id)
        if not session or session.status != "in_progress":
            return False
        agreement_wizard_sessions_repo.set_abandoned(self._db, session_id)
        return True
