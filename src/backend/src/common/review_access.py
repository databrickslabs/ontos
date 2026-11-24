"""Read access for the pending reviewers of an entity (#1117).

Whoever can decide an open review of an entity can read that entity, even when
the read gate would otherwise deny it (an unpublished data product they don't
own), and sees it in the approvals queue. Entities: ``data_product`` and
``data_contract``. Two facts count, both created by the server, never by the
caller:

* an open asset review (``queued`` / ``in_review``) of the entity whose
  reviewer is the caller and that a workflow's ``create_asset_review`` step
  created. Reviews created through ``POST /api/data-asset-reviews`` take the
  reviewer and the requester from the request body, so they don't count:
  otherwise anyone allowed to create a review could name themselves and read
  any draft.
* a paused workflow execution for the entity, waiting at an approval step,
  that the caller may decide: the same check as ``POST
  /api/workflows/handle-approval`` (recipient, group or role member of the
  step's approval notification; not the requester of an owner approval).
  An approval notification with neither a recipient nor a role is a broadcast
  (everyone may see it) and grants nothing; nor does one whose role can't be
  resolved (deleted, or the roles can't be read), or one already handled.

This only answers "may read"; it never grants a write. It ends when the review
is closed, and for an approver when their approval notification is handled:
when the step is decided, or, on a step that waits for several approvers,
when they have decided. Every check fails closed, and runs in a savepoint so a
failed lookup doesn't abort the caller's transaction.
"""
import json
from typing import Any, Iterable, Optional, Set

from sqlalchemy.orm import Session

from src.common.logging import get_logger

logger = get_logger(__name__)

# Asset-review statuses in which the reviewer can still decide
_OPEN_REVIEW_STATUSES = ('queued', 'in_review')

# Prefix of the asset FQN of an app entity in an asset review
_FQN_PREFIXES = {'data_product': 'product:', 'data_contract': 'contract:'}


def _identities(user: Any) -> Set[str]:
    values: Iterable[Optional[str]] = (
        getattr(user, 'email', None), getattr(user, 'username', None),
    )
    return {str(v).strip().lower() for v in values if v and str(v).strip()}


def _created_by_workflow(db: Session, review_id: str) -> bool:
    """Whether a ``create_asset_review`` step execution created ``review_id``.

    Only that step type counts: others store request input in their result
    (an approval step keeps the approver's request body).
    """
    from src.db_models.process_workflows import WorkflowStepDb, WorkflowStepExecutionDb

    rows = db.query(WorkflowStepExecutionDb.result_data).join(
        WorkflowStepDb, WorkflowStepDb.id == WorkflowStepExecutionDb.step_id,
    ).filter(
        WorkflowStepDb.step_type == 'create_asset_review',
        WorkflowStepExecutionDb.result_data.contains(json.dumps(review_id)),
    ).all()
    for (raw,) in rows:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict) and data.get('review_id') == review_id:
            return True
    return False


def _is_open_asset_reviewer(
    db: Session, user: Any, entity_type: str, entity_id: str,
) -> bool:
    """An open, workflow-created asset review of the entity names the caller."""
    return entity_id in _open_asset_reviewer_ids(db, user, entity_type, [entity_id])


def _open_asset_reviewer_ids(
    db: Session, user: Any, entity_type: str, entity_ids: Iterable[str],
) -> Set[str]:
    """The ids of ``entity_ids`` with an open, workflow-created asset review naming
    the caller (one query for all of them)."""
    from sqlalchemy import func
    from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb

    prefix = _FQN_PREFIXES.get(entity_type)
    identities = _identities(user)
    ids = [str(i) for i in entity_ids if i]
    if not prefix or not identities or not ids:
        return set()
    rows = db.query(DataAssetReviewRequestDb, ReviewedAssetDb.asset_fqn).join(
        ReviewedAssetDb, ReviewedAssetDb.review_request_id == DataAssetReviewRequestDb.id,
    ).filter(
        ReviewedAssetDb.asset_fqn.in_([f"{prefix}{i}" for i in ids]),
        DataAssetReviewRequestDb.status.in_(_OPEN_REVIEW_STATUSES),
        func.lower(DataAssetReviewRequestDb.reviewer_email).in_(identities),
    ).all()
    found: Set[str] = set()
    for review, fqn in rows:
        entity_id = fqn[len(prefix):]
        if entity_id in found:
            continue
        # A requester never reviews their own request (the workflow step
        # resolves someone else), so such a row can't come from it.
        if (review.requester_email or '').strip().lower() in identities:
            continue
        if _created_by_workflow(db, review.id):
            found.add(entity_id)
    return found


def _can_decide_pending_approval(
    db: Session, notifications_manager: Any, user: Any, entity_type: str, entity_id: str,
) -> bool:
    """The caller may decide a paused approval of a workflow run for the entity."""
    return entity_id in _decidable_approval_ids(
        db, notifications_manager, user, entity_type, [entity_id],
    )


def _decidable_approval_ids(
    db: Session, notifications_manager: Any, user: Any, entity_type: str,
    entity_ids: Iterable[str],
) -> Set[str]:
    """The ids of ``entity_ids`` with a paused approval the caller may decide.

    ``_assert_caller_authorized_for_execution`` (``for_read``) only considers
    the open approval notifications of the step the run waits at that have a
    recipient or a role, and checks them with the strict
    ``can_user_access_notification``. One query finds the paused runs of all
    the ids; the check runs only for the runs of these entities.
    """
    from fastapi import HTTPException
    from sqlalchemy import or_

    from src.db_models.process_workflows import WorkflowExecutionDb, WorkflowStepDb
    from src.routes.workflows_routes import _assert_caller_authorized_for_execution

    ids = {str(i) for i in entity_ids if i}
    if notifications_manager is None or not ids:
        return set()
    # The text filter narrows the candidates in SQL; the JSON check is the exact one.
    paused = db.query(WorkflowExecutionDb).join(
        WorkflowStepDb,
        (WorkflowStepDb.workflow_id == WorkflowExecutionDb.workflow_id)
        & (WorkflowStepDb.step_id == WorkflowExecutionDb.current_step_id),
    ).filter(
        WorkflowExecutionDb.status == 'paused',
        WorkflowStepDb.step_type == 'approval',
        or_(*(WorkflowExecutionDb.trigger_context.contains(json.dumps(i)) for i in ids)),
    ).all()
    found: Set[str] = set()
    for execution in paused:
        try:
            context = json.loads(execution.trigger_context or '{}')
        except (TypeError, ValueError):
            continue
        if not isinstance(context, dict):
            continue
        entity_id = context.get('entity_id')
        if context.get('entity_type') != entity_type or entity_id not in ids:
            continue
        if entity_id in found:
            continue
        try:
            _assert_caller_authorized_for_execution(
                db=db,
                notifications_manager=notifications_manager,
                execution_id=execution.id,
                user_info=user,
                for_read=True,
            )
            found.add(entity_id)
        except HTTPException:
            continue
    return found


def pending_reviewer_ids(
    db: Session,
    user: Any,
    entity_type: str,
    entity_ids: Iterable[str],
    notifications_manager: Any = None,
) -> Set[str]:
    """``caller_is_pending_reviewer`` for many entities: the ids the caller may
    read as a pending reviewer. Two queries for all the ids, plus the checks of
    the matching rows. Fails closed (empty set)."""
    ids = [str(i) for i in entity_ids if i]
    if not user or not ids:
        return set()
    try:
        with db.begin_nested():
            found = _open_asset_reviewer_ids(db, user, entity_type, ids)
            rest = [i for i in ids if i not in found]
            if rest:
                found |= _decidable_approval_ids(
                    db, notifications_manager, user, entity_type, rest,
                )
            return found
    except Exception:
        logger.exception("Batch reviewer access check failed for %s; denying", entity_type)
        return set()


def caller_is_pending_reviewer(
    db: Session,
    user: Any,
    entity_type: str,
    entity_id: str,
    notifications_manager: Any = None,
) -> bool:
    """Whether ``user`` can decide an open review or approval of the entity.

    Without ``notifications_manager`` only the asset-review fact is checked.
    """
    if not user or not entity_id:
        return False
    try:
        # Savepoint: on Postgres a failed statement would otherwise abort the
        # caller's transaction (the approvals queue checks row after row).
        with db.begin_nested():
            if _is_open_asset_reviewer(db, user, entity_type, entity_id):
                return True
            return _can_decide_pending_approval(
                db, notifications_manager, user, entity_type, entity_id,
            )
    except Exception:
        logger.exception("Reviewer access check failed for %s %s; denying", entity_type, entity_id)
        return False
