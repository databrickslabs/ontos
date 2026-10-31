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
accepts:

- a product's request, approved in the Status Change Request workflow
  (``on_request_status_change``), applied by the workflow executor;
- a product's or contract's request approved with ``handle-status-change``
  by a user with Admin on the feature.

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
from typing import Any, Iterator, Optional, Tuple

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

# The (entity_type, entity_id) whose approved status change is being applied
_approved_change: ContextVar[Optional[Tuple[str, str]]] = ContextVar(
    'certified_deprecation_approved_change', default=None,
)


class CertifiedDeprecationRequiresApprovalError(CodedValueError):
    """A certified product or contract can't be deprecated directly."""

    code = 'certified_deprecation_requires_approval'


class GateExemptionNotFoundError(CodedValueError):
    """The guard's switch names a domain, product or contract that doesn't exist."""

    code = 'gate_exemption_not_found'


@contextmanager
def approved_status_change(
    entity_type: str, entity_id: str, accepted: bool = True,
) -> Iterator[None]:
    """Apply an approved status change request of one entity.

    Inside, the guard accepts the deprecation of that entity (and of no
    other, so a workflow that the change fires can't deprecate another
    certified entity unasked). ``accepted=False`` makes it a no-op, for a
    decision that doesn't count as an approval (e.g. not by an admin).
    """
    if not accepted:
        yield
        return
    token = _approved_change.set((entity_type, str(entity_id)))
    try:
        yield
    finally:
        _approved_change.reset(token)


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
    if _approved_change.get() == (entity_type, entity_id):
        return
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
