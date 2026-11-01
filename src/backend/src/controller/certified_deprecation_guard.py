"""Deprecating a certified data product or contract needs an approved request.

The certified guard of the lifecycle PRD (``prd-lifecycle-tag-automation-and-
deprecation.md``, *Approvals and notices*). ``transition_status`` of products
and contracts runs it through ``run_status_gates``, before the gates
(``check_certified_deprecation``): a direct move to
``deprecated`` of an entity whose ``certification_level`` is set is refused
with ``certified_deprecation_requires_approval``. It is enforced in code, not
a workflow, so it holds in every installation without admin action.

The way through is a status change request. Its approval applies the status
inside ``approved_status_change`` (for that entity only), which the guard
accepts when the decision counts as an approval:

- a product's request, approved at the approval step of the Status Change
  Request workflow (``on_request_status_change``) by one of its approvers,
  through ``handle-approval`` (not a plain resume of the execution);
- a product's or contract's pending request (the ``status_change_requested``
  change log entry, same target status) approved with ``handle-status-change``
  by a user with Admin on the feature.

In both, the approver must not be the requester. Otherwise the guard refuses
with ``certified_deprecation_approval_refused`` and the reason.

The guard can be switched off per domain, data product or data contract with
a ``GateExemptions`` value, the same ``disabled_for`` switch status gates
have, resolved by the same ``gate_exemption``. It is stored in
``app_settings``, since the guard is no workflow. Each skip is logged and
audited as ``GATE_SKIPPED``, like a skipped gate. Imports create entities and
never transition them, so they are not guarded.
"""
import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterable, Iterator, Optional, Tuple

from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.models.process_workflows import EntityType, GateExemptions
from src.repositories.app_settings_repository import app_settings_repo

logger = get_logger(__name__)

# app_settings key of the guard's switch (a GateExemptions as JSON)
GUARD_SETTING_KEY = 'certified_deprecation_guard_disabled_for'

# Audit details name the guard where a skipped gate names its workflow
GUARD_NAME = 'certified_deprecation'

def _entity_model(entity_type: str):
    """The DB model of a guarded entity type (products and contracts), or None."""
    if entity_type == EntityType.DATA_PRODUCT.value:
        from src.db_models.data_products import DataProductDb
        return DataProductDb
    if entity_type == EntityType.DATA_CONTRACT.value:
        from src.db_models.data_contracts import DataContractDb
        return DataContractDb
    return None

# The (entity_type, entity_id) whose status change decision is being applied,
# and why it doesn't count as an approval (None when it does)
_approved_change: ContextVar[Optional[Tuple[str, str, Optional[str]]]] = ContextVar(
    'certified_deprecation_approved_change', default=None,
)

# Set while the handle-approval route resumes a workflow: the approval step is
# being decided by one of its approvers (checked per execution there), not by
# a plain resume of the execution. Holds the approver's email and username.
_eligible_approver: ContextVar[Optional[frozenset]] = ContextVar(
    'certified_deprecation_eligible_approver', default=None,
)

# Why a status change decision doesn't count as an approval for the guard
NOT_ADMIN = 'not_admin'
NO_PENDING_REQUEST = 'no_pending_request'
TARGET_MISMATCH = 'target_mismatch'
SELF_APPROVAL = 'self_approval'
NO_APPROVER = 'no_approver'


class CertifiedDeprecationRequiresApprovalError(CodedValueError):
    """A certified product or contract can't be deprecated directly."""

    code = 'certified_deprecation_requires_approval'


class CertifiedDeprecationApprovalRefusedError(CodedValueError):
    """A decision on a certified deprecation that doesn't count as an approval.

    ``reason``: ``not_admin``, ``no_pending_request``, ``target_mismatch``,
    ``self_approval`` or ``no_approver`` (the approval step wasn't decided by
    one of its approvers).
    """

    code = 'certified_deprecation_approval_refused'


def guard_refusal_status(error: Exception, default: int) -> int:
    """The HTTP status of a refused status change: 400 for the guard's refusals.

    Every route answers the guard with 400, as Change Status answers an
    invalid transition; other errors keep the route's ``default``.
    """
    refusals = (CertifiedDeprecationRequiresApprovalError, CertifiedDeprecationApprovalRefusedError)
    return 400 if isinstance(error, refusals) else default


class GateExemptionNotFoundError(CodedValueError):
    """The guard's switch names a domain, product or contract that doesn't exist."""

    code = 'gate_exemption_not_found'


@contextmanager
def approved_status_change(
    entity_type: str, entity_id: str, refusal: Optional[str] = None,
) -> Iterator[None]:
    """Apply a decided status change request of one entity.

    Inside, the guard accepts the deprecation of that entity (and of no
    other, so a workflow that the change fires can't deprecate another
    certified entity unasked). With a ``refusal`` (one of the reasons above)
    the decision doesn't count as an approval: the guard refuses it with
    ``certified_deprecation_approval_refused`` and that reason.
    """
    token = _approved_change.set((entity_type, str(entity_id), refusal))
    try:
        yield
    finally:
        _approved_change.reset(token)


def _identities(ids: Iterable[Optional[str]]) -> frozenset:
    return frozenset(str(i).strip().lower() for i in ids if i)


@contextmanager
def eligible_approver(*approver_ids: Optional[str]) -> Iterator[None]:
    """Mark a workflow resume as decided by an approver of its approval step.

    Entered by ``POST /api/workflows/handle-approval`` after its per-execution
    check, with the approver's email and username; a resume through any other
    route doesn't count for the guard.
    """
    token = _eligible_approver.set(_identities(approver_ids))
    try:
        yield
    finally:
        _eligible_approver.reset(token)


def workflow_approval_refusal(approved: Optional[bool], requester: Optional[str]) -> Optional[str]:
    """Why a Status Change Request run's ending doesn't approve a certified deprecation.

    It counts when the approval step was decided (``approved is True``) by
    one of its approvers through handle-approval, who isn't the requester.
    """
    approver = _eligible_approver.get()
    if approved is not True or approver is None:
        return NO_APPROVER
    if requester and requester.strip().lower() in approver:
        return SELF_APPROVAL
    return None


def handle_decision_refusal(
    db: Session,
    entity_type: str,
    entity_id: str,
    target_status: str,
    by_admin: bool,
    *approver_ids: Optional[str],
) -> Optional[str]:
    """Why a ``handle-status-change`` approval doesn't count for the guard, or None.

    Only an admin of the feature approves, and only a pending request of
    someone else (``status_change_decision_refusal``).
    """
    if not by_admin:
        return NOT_ADMIN
    return status_change_decision_refusal(db, entity_type, entity_id, target_status, approver_ids)


def _decided_target(entry: Any) -> str:
    return str((entry.details or {}).get('target_status') or '').lower()


def status_change_decision_refusal(
    db: Session,
    entity_type: str,
    entity_id: str,
    target_status: str,
    approver_ids: Iterable[Optional[str]],
) -> Optional[str]:
    """Why approving with ``handle-status-change`` doesn't count for the guard, or None.

    The request record is the ``status_change_requested`` change log entry
    both managers write with every request (notifications can be deleted,
    and products' requests have none). It counts when the latest request
    of the entity asks for ``target_status``, was made from the entity's
    current status, hasn't been decided yet (fewer ``status_change_approve``
    / ``status_change_deny`` entries for that target than requests) and
    wasn't made by the approver (``approver_ids``: their email and username).
    """
    from src.controller.change_log_manager import change_log_manager

    target = (target_status or '').lower()
    requests = change_log_manager.get_changes_for_entity(
        db, entity_type, entity_id, action='status_change_requested', limit=200,
    )
    if not requests:
        return NO_PENDING_REQUEST
    latest = requests[0].details or {}
    if _decided_target(requests[0]) != target:
        return TARGET_MISMATCH
    model = _entity_model(entity_type)
    entity = db.get(model, entity_id) if model is not None else None
    requested_from = str(latest.get('from_status') or latest.get('current_status') or '')
    current = str(getattr(entity, 'status', '') or 'draft').lower()
    if requested_from and requested_from.lower() != current:
        return NO_PENDING_REQUEST
    decided = sum(
        1
        for action in ('status_change_approve', 'status_change_deny')
        for entry in change_log_manager.get_changes_for_entity(
            db, entity_type, entity_id, action=action, limit=200,
        )
        if _decided_target(entry) == target
    )
    if decided >= sum(1 for entry in requests if _decided_target(entry) == target):
        return NO_PENDING_REQUEST
    requester = str(latest.get('requester_email') or '').strip().lower()
    if requester and requester in _identities(approver_ids):
        return SELF_APPROVAL
    return None


def guard_exemptions(db: Session) -> GateExemptions:
    """Where the guard is switched off; nothing (guard on everywhere) by default.

    A stored value that can't be read switches nothing off.
    """
    raw = app_settings_repo.get_by_key(db, GUARD_SETTING_KEY)
    if not raw:
        return GateExemptions()
    try:
        return GateExemptions.model_validate(json.loads(raw))
    except (TypeError, ValueError) as e:
        logger.error(
            "The certified deprecation guard's switch can't be read, so the guard "
            "applies everywhere: %s", e,
        )
        return GateExemptions()


def save_guard_exemptions(db: Session, exemptions: GateExemptions) -> GateExemptions:
    """Store where the guard is switched off; every listed entity must exist."""
    from src.common.workflow_triggers import unknown_gate_exemptions

    unknown = unknown_gate_exemptions(db, exemptions)
    if unknown:
        kind, missing = unknown[0]
        raise GateExemptionNotFoundError(
            f"disabled_for: unknown {kind.replace('_', ' ')} '{missing}'",
            kind=kind, id=missing,
        )
    app_settings_repo.set(db, GUARD_SETTING_KEY, exemptions.model_dump_json())
    return exemptions


def _report_skip(
    entity_type: str, entity_id: str, from_status: str, to_status: str,
    user_email: Optional[str], reason: Tuple[str, str],
) -> None:
    """Log and audit a deprecation the guard let through because it is switched off."""
    kind, ref = reason
    logger.info(
        "Certified deprecation guard skipped for %s '%s' (%s -> %s): switched off for %s '%s'",
        entity_type, entity_id, from_status, to_status, kind, ref,
    )
    try:
        from src.controller.audit_manager import log_system_action
        log_system_action(
            username=user_email or 'system',
            feature='process-workflows',
            action='GATE_SKIPPED',
            success=True,
            details={
                'entity_type': entity_type,
                'entity_id': entity_id,
                'from_status': from_status,
                'to_status': to_status,
                'guard': GUARD_NAME,
                'disabled_for': {'kind': kind, 'id': ref},
            },
        )
    except Exception as audit_err:  # The audit must never change the decision
        logger.error("Could not audit the skipped guard: %s", audit_err, exc_info=True)


def check_certified_deprecation(db: Session, event: Any) -> None:
    """Refuse a direct deprecation of a certified product or contract.

    ``event`` is the transition's ``TriggerEvent`` (``run_status_gates``
    calls this before the gates). Passes for any other target status or entity
    type, an uncertified entity, the approved request being applied
    (``approved_status_change``) and an entity the guard is switched off for
    (audited).
    """
    if (event.to_status or '').lower() != 'deprecated':
        return
    entity_type = event.entity_type.value
    model = _entity_model(entity_type)
    if model is None:
        return
    entity_id = str(event.entity_id)
    entity = db.get(model, entity_id)
    if entity is None or entity.certification_level is None:
        return
    decision = _approved_change.get()
    if decision is not None and decision[:2] == (entity_type, entity_id):
        if decision[2] is None:
            return
        raise CertifiedDeprecationApprovalRefusedError(
            f"The approval of this request doesn't count for the certified "
            f"{entity_type.replace('_', ' ')} '{entity.name}' ({decision[2]}): it needs a "
            f"pending status change request, approved by an admin who didn't make it.",
            reason=decision[2],
            entityType=entity_type,
            entityId=entity_id,
            entityName=entity.name,
        )
    from src.common.workflow_triggers import gate_exemption

    reason = gate_exemption(db, event, guard_exemptions(db))
    if reason:
        _report_skip(
            entity_type, entity_id, event.from_status, event.to_status, event.user_email, reason,
        )
        return
    label = 'data product' if entity_type == 'data_product' else 'data contract'
    raise CertifiedDeprecationRequiresApprovalError(
        f"The {label} '{entity.name}' is certified: deprecating it needs an approved "
        f"status change request. Request the status change instead.",
        entityType=entity_type,
        entityId=entity_id,
        entityName=entity.name,
        certificationLevel=entity.certification_level,
    )
