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

# Prefix of the asset FQN of an Authority Relation in an asset review
AUTHORITY_RELATION_FQN_PREFIX = 'authority-relation://'

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
    from sqlalchemy import func

    from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb

    prefix = _FQN_PREFIXES.get(entity_type)
    identities = _identities(user)
    if not prefix or not identities:
        return False
    reviews = db.query(DataAssetReviewRequestDb).join(
        ReviewedAssetDb, ReviewedAssetDb.review_request_id == DataAssetReviewRequestDb.id,
    ).filter(
        ReviewedAssetDb.asset_fqn == f"{prefix}{entity_id}",
        DataAssetReviewRequestDb.status.in_(_OPEN_REVIEW_STATUSES),
        func.lower(DataAssetReviewRequestDb.reviewer_email).in_(identities),
    ).all()
    for review in reviews:
        # A requester never reviews their own request (the workflow step
        # resolves someone else), so such a row can't come from it.
        if (review.requester_email or '').strip().lower() in identities:
            continue
        if _created_by_workflow(db, review.id):
            return True
    return False


def _can_decide_pending_approval(
    db: Session, notifications_manager: Any, user: Any, entity_type: str, entity_id: str,
) -> bool:
    """The caller may decide a paused approval of a workflow run for the entity.

    ``_assert_caller_authorized_for_execution`` (``for_read``) only considers
    the open approval notifications of the step the run waits at that have a
    recipient or a role, and checks them with the strict
    ``can_user_access_notification``.
    """
    from fastapi import HTTPException

    from src.db_models.process_workflows import WorkflowExecutionDb, WorkflowStepDb
    from src.routes.workflows_routes import _assert_caller_authorized_for_execution

    if notifications_manager is None:
        return False
    # The text filter narrows the candidates in SQL; the JSON check is the exact one.
    paused = db.query(WorkflowExecutionDb).join(
        WorkflowStepDb,
        (WorkflowStepDb.workflow_id == WorkflowExecutionDb.workflow_id)
        & (WorkflowStepDb.step_id == WorkflowExecutionDb.current_step_id),
    ).filter(
        WorkflowExecutionDb.status == 'paused',
        WorkflowStepDb.step_type == 'approval',
        WorkflowExecutionDb.trigger_context.contains(json.dumps(entity_id)),
    ).all()
    for execution in paused:
        try:
            context = json.loads(execution.trigger_context or '{}')
        except (TypeError, ValueError):
            continue
        if not isinstance(context, dict):
            continue
        if context.get('entity_type') != entity_type or context.get('entity_id') != entity_id:
            continue
        try:
            _assert_caller_authorized_for_execution(
                db=db,
                notifications_manager=notifications_manager,
                execution_id=execution.id,
                user_info=user,
                for_read=True,
            )
            return True
        except HTTPException:
            continue
    return False


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


def authority_relation_fqn(relation_id: str) -> str:
    """The asset FQN of an Authority Relation's asset review."""
    return f"{AUTHORITY_RELATION_FQN_PREFIX}{relation_id}"


def authority_relation_id_of(fqns: Iterable[str]) -> Optional[str]:
    """The Authority Relation id when every FQN is an ``authority-relation://`` reference to one AR."""
    fqns = list(fqns)
    if not fqns or not all(f.startswith(AUTHORITY_RELATION_FQN_PREFIX) for f in fqns):
        return None
    ids = {f[len(AUTHORITY_RELATION_FQN_PREFIX):].split('#')[0] for f in fqns}
    return ids.pop() if len(ids) == 1 else None


def caller_is_named_authority_reviewer(db: Session, user: Any, request_id: str) -> bool:
    """Whether ``user`` is a named reviewer of an Authority Relation Asset Review, in any status.

    The reviewer is recorded on the AR's affirmation that ``start_review`` linked to the
    request, and matched like ``submit_review`` matches (a group member counts). Both
    facts are server-created, so the request body can't name a reviewer (R5, #1306).
    It stays true after the reviewer submits, so they can still open their request.
    Read only; fails closed in a savepoint.
    """
    from src.controller.authority_resolution_manager import principal_matches
    from src.db_models.authority_resolution import AuthorityAffirmationDb
    from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb

    if user is None or not request_id:
        return False
    try:
        with db.begin_nested():
            if db.query(DataAssetReviewRequestDb.id).filter(DataAssetReviewRequestDb.id == request_id).first() is None:
                return False
            ar_assets = db.query(ReviewedAssetDb).filter(
                ReviewedAssetDb.review_request_id == request_id,
                ReviewedAssetDb.asset_fqn.startswith(AUTHORITY_RELATION_FQN_PREFIX),
            ).all()
            for asset in ar_assets:
                relation_id = authority_relation_id_of([asset.asset_fqn])
                if relation_id is None:
                    continue
                affirmations = db.query(AuthorityAffirmationDb).filter(
                    AuthorityAffirmationDb.relation_id == relation_id,
                    AuthorityAffirmationDb.review_request_id == request_id,
                    AuthorityAffirmationDb.is_reviewer.is_(True),
                ).all()
                if any(principal_matches(a.principal, a.principal_type, user) for a in affirmations):
                    return True
            return False
    except Exception:
        logger.exception("Authority reviewer access check failed for request %s; denying", request_id)
        return False
