"""Unit tests for PR K — per-execution authorization on
``POST /api/workflows/handle-approval``.

Two halves:

1. **Dispatch pin** — the `for_approval_response` entry in
   ``WIZARD_PERMISSION_DISPATCH`` must be ``None`` (authenticated only,
   #971), and ``POST /handle-approval`` has no feature-level gate.
   (The catch-all `test_dispatch_expected_features` in
   ``test_wizard_permission_dispatch.py`` already pins this; we repeat
   the assertion here so the file documents PR K end to end.)

2. **Helper behavior** — ``_assert_caller_authorized_for_execution``
   must:
     - 403 when no notification exists for the given execution
     - 403 when notifications exist but none of them grant access to the
       caller (different recipient, no role overlap)
     - return matching notifications when the caller is the direct
       recipient
     - return matching notifications when the caller's groups overlap
       the recipient role's ``assigned_groups``

Why this matters: the outer ``PermissionChecker('notifications', RW)``
gate alone would let any user with ``notifications:RW`` approve any
paused execution by guessing the ``execution_id`` — horizontal
privilege escalation. This per-execution check is the real authorization.
"""
# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from src.models.notifications import Notification
from src.models.process_workflows import TriggerType
from src.models.users import UserInfo
from src.routes.workflows_routes import (
    WIZARD_PERMISSION_DISPATCH,
    _assert_caller_authorized_for_execution,
    _find_approval_notifications_for_execution,
    _mark_step_notifications_handled,
    handle_workflow_approval,
)


# ---------------------------------------------------------------------------
# 1. Dispatch pin
# ---------------------------------------------------------------------------


def test_dispatch_for_approval_response_is_authenticated_only() -> None:
    """#971 — the former ``("notifications", READ_ONLY)`` gate could not be
    granted to non-admin roles (``notifications`` is admin-only), so it
    rejected every non-admin approver. The real authorization is the
    per-execution check (``_assert_caller_authorized_for_execution``)."""
    assert WIZARD_PERMISSION_DISPATCH[TriggerType.FOR_APPROVAL_RESPONSE.value] is None


def test_handle_approval_has_no_feature_permission_gate() -> None:
    """#971 — ``POST /handle-approval`` must not depend on a
    ``PermissionChecker``: approvers holding only a business role have no
    app role, so any feature-level gate would reject them."""
    from src.common.authorization import PermissionChecker
    from src.routes.workflows_routes import router

    [route] = [
        r for r in router.routes
        if getattr(r, 'path', '') == '/api/workflows/handle-approval'
    ]
    checkers = [
        d.call for d in route.dependant.dependencies
        if isinstance(d.call, PermissionChecker)
    ]
    assert checkers == []


# ---------------------------------------------------------------------------
# 2. Helper behavior — _find_approval_notifications_for_execution
# ---------------------------------------------------------------------------


def _make_notif_row(
    *,
    notif_id: str,
    execution_id: str | None,
    recipient: str | None = None,
    recipient_role_id: str | None = None,
    action_type: str = 'workflow_approval',
) -> SimpleNamespace:
    """Build an attribute-accessible stand-in for a ``NotificationDb`` row.

    ``Notification.model_validate`` reads via ``from_attributes=True`` so
    a ``SimpleNamespace`` is sufficient — no need to instantiate the SQLA
    declarative model.
    """
    payload = {'execution_id': execution_id} if execution_id else None
    return SimpleNamespace(
        id=notif_id,
        type='action_required',
        title='Approval needed',
        subtitle=None,
        description=None,
        message=None,
        link=None,
        created_at=datetime.utcnow(),
        updated_at=None,
        read=False,
        can_delete=True,
        recipient=recipient,
        recipient_role_id=recipient_role_id,
        recipient_role_name=None,
        target_roles=None,
        action_type=action_type,
        action_payload=json.dumps(payload) if payload else None,
        data=None,
    )


def _mock_db_with_rows(rows: list) -> MagicMock:
    """Wire a MagicMock so ``db.query(NotificationDb).filter(...).all()``
    returns ``rows``."""
    db = MagicMock()
    query = MagicMock()
    flt = MagicMock()
    flt.all.return_value = rows
    query.filter.return_value = flt
    db.query.return_value = query
    return db


def test_find_returns_only_rows_matching_execution() -> None:
    rows = [
        _make_notif_row(notif_id='n1', execution_id='exec-A'),
        _make_notif_row(notif_id='n2', execution_id='exec-B'),
        _make_notif_row(notif_id='n3', execution_id='exec-A'),
    ]
    db = _mock_db_with_rows(rows)
    matches = _find_approval_notifications_for_execution(db, 'exec-A')
    assert {n.id for n in matches} == {'n1', 'n3'}


def test_find_skips_rows_with_unparseable_payload() -> None:
    bad = _make_notif_row(notif_id='bad', execution_id='exec-A')
    bad.action_payload = "{not-json"
    good = _make_notif_row(notif_id='good', execution_id='exec-A')
    db = _mock_db_with_rows([bad, good])
    matches = _find_approval_notifications_for_execution(db, 'exec-A')
    assert [n.id for n in matches] == ['good']


# ---------------------------------------------------------------------------
# 2. Helper behavior — _assert_caller_authorized_for_execution
# ---------------------------------------------------------------------------


def _user(email: str = 'alice@example.com', groups: list[str] | None = None) -> UserInfo:
    return UserInfo(
        email=email,
        username=email.split('@')[0],
        user=email.split('@')[0].title(),
        ip='127.0.0.1',
        groups=groups or [],
    )


def test_assert_403_when_no_notification_exists_for_execution() -> None:
    """Impossible-to-approve case: a caller asks to approve an execution
    that has zero matching notifications. Must 403 even for admin users
    — there is literally nothing to approve."""
    db = _mock_db_with_rows([])
    manager = MagicMock()
    manager.can_user_access_notification.return_value = True  # would say yes if asked

    with pytest.raises(HTTPException) as exc:
        _assert_caller_authorized_for_execution(
            db=db,
            notifications_manager=manager,
            execution_id='exec-A',
            user_info=_user('alice@example.com'),
        )
    assert exc.value.status_code == 403
    assert "not an authorized approver" in exc.value.detail
    # Manager should NOT have been asked — there were no candidates.
    manager.can_user_access_notification.assert_not_called()


def test_assert_200_when_caller_is_direct_recipient() -> None:
    """Notification with ``recipient='alice@example.com'``; caller is
    Alice. Manager returns True for Alice → helper returns matches."""
    rows = [_make_notif_row(
        notif_id='n1', execution_id='exec-A', recipient='alice@example.com',
    )]
    db = _mock_db_with_rows(rows)
    manager = MagicMock()

    def access(*, db, notification: Notification, user_info: UserInfo) -> bool:
        return notification.recipient == user_info.email
    manager.can_user_access_notification.side_effect = access

    matches = _assert_caller_authorized_for_execution(
        db=db,
        notifications_manager=manager,
        execution_id='exec-A',
        user_info=_user('alice@example.com'),
    )
    assert [m.id for m in matches] == ['n1']
    manager.can_user_access_notification.assert_called_once()


def test_assert_403_when_caller_is_not_recipient_and_no_role_match() -> None:
    """Bob tries to approve a notification addressed to Alice (no role
    overlap). Must 403 — horizontal privilege escalation prevented."""
    rows = [_make_notif_row(
        notif_id='n1', execution_id='exec-A', recipient='alice@example.com',
    )]
    db = _mock_db_with_rows(rows)
    manager = MagicMock()
    manager.can_user_access_notification.return_value = False  # deny

    with pytest.raises(HTTPException) as exc:
        _assert_caller_authorized_for_execution(
            db=db,
            notifications_manager=manager,
            execution_id='exec-A',
            user_info=_user('bob@example.com'),
        )
    assert exc.value.status_code == 403
    assert "not an authorized approver" in exc.value.detail


def test_assert_200_via_recipient_role_membership() -> None:
    """Notification has ``recipient_role_id`` set; caller is in that
    role's ``assigned_groups``. Manager grants access → helper returns
    matches. Models the Business-Owner-as-role-member path that PR K
    is specifically enabling."""
    rows = [_make_notif_row(
        notif_id='n1',
        execution_id='exec-A',
        recipient_role_id='role-business-owners',
    )]
    db = _mock_db_with_rows(rows)
    manager = MagicMock()

    def access(*, db, notification: Notification, user_info: UserInfo) -> bool:
        # Mimic real manager: role grants access if caller's groups
        # overlap role.assigned_groups (here pre-resolved as 'sales-team').
        if notification.recipient_role_id == 'role-business-owners':
            return 'sales-team' in (user_info.groups or [])
        return False
    manager.can_user_access_notification.side_effect = access

    matches = _assert_caller_authorized_for_execution(
        db=db,
        notifications_manager=manager,
        execution_id='exec-A',
        user_info=_user('carol@example.com', groups=['sales-team']),
    )
    assert [m.id for m in matches] == ['n1']


def test_assert_short_circuits_on_first_match() -> None:
    """Two candidate notifications; first grants access, second
    shouldn't be asked. Light optimization guard — order is whatever
    the DB returns, but if ANY grant access the helper returns
    immediately."""
    rows = [
        _make_notif_row(notif_id='n1', execution_id='exec-A', recipient='alice@example.com'),
        _make_notif_row(notif_id='n2', execution_id='exec-A', recipient='alice@example.com'),
    ]
    db = _mock_db_with_rows(rows)
    manager = MagicMock()
    manager.can_user_access_notification.return_value = True

    matches = _assert_caller_authorized_for_execution(
        db=db,
        notifications_manager=manager,
        execution_id='exec-A',
        user_info=_user('alice@example.com'),
    )
    assert len(matches) == 2  # _find_ returns both; auth returns both for downstream
    # Only one access check needed before returning success
    assert manager.can_user_access_notification.call_count == 1


def test_assert_ignores_approval_notifications_without_recipient() -> None:
    """An approval notification with neither recipient nor role is a
    broadcast for ``can_user_access_notification`` (everyone may see it).
    It must not let anyone approve the execution."""
    rows = [_make_notif_row(notif_id='n1', execution_id='exec-A')]
    db = _mock_db_with_rows(rows)
    manager = MagicMock()
    manager.can_user_access_notification.return_value = True  # broadcast: visible to all

    with pytest.raises(HTTPException) as exc:
        _assert_caller_authorized_for_execution(
            db=db,
            notifications_manager=manager,
            execution_id='exec-A',
            user_info=_user('mallory@example.com'),
        )

    assert exc.value.status_code == 403
    manager.can_user_access_notification.assert_not_called()


def test_assert_uses_only_addressed_approval_notifications() -> None:
    """With a broadcast and an addressed notification for the same
    execution, only the addressed one can authorize."""
    rows = [
        _make_notif_row(notif_id='broadcast', execution_id='exec-A'),
        _make_notif_row(notif_id='n1', execution_id='exec-A', recipient='alice@example.com'),
    ]
    db = _mock_db_with_rows(rows)
    manager = MagicMock()

    def access(*, db, notification: Notification, user_info: UserInfo) -> bool:
        return not notification.recipient or notification.recipient == user_info.email
    manager.can_user_access_notification.side_effect = access

    with pytest.raises(HTTPException):
        _assert_caller_authorized_for_execution(
            db=db, notifications_manager=manager, execution_id='exec-A',
            user_info=_user('mallory@example.com'),
        )
    matches = _assert_caller_authorized_for_execution(
        db=db, notifications_manager=manager, execution_id='exec-A',
        user_info=_user('alice@example.com'),
    )
    assert [m.id for m in matches] == ['n1']



# --- Only the approvers of the pending step may answer -----------------------


def _db_with(rows: list, pending_step: str | None) -> MagicMock:
    """``db.query(NotificationDb)`` returns ``rows``; the execution query
    returns ``pending_step`` as its current step."""
    from src.db_models.process_workflows import WorkflowExecutionDb

    notifications = _mock_db_with_rows(rows).query.return_value
    execution = MagicMock()
    execution.filter.return_value.first.return_value = (pending_step,)
    db = MagicMock()
    db.query.side_effect = lambda what: (
        execution if getattr(what, 'class_', None) is WorkflowExecutionDb else notifications
    )
    return db


def _step_row(notif_id: str, recipient: str, step_id: str | None) -> SimpleNamespace:
    row = _make_notif_row(notif_id=notif_id, execution_id='exec-A', recipient=recipient)
    payload = {'execution_id': 'exec-A'}
    if step_id:
        payload['step_id'] = step_id
    row.action_payload = json.dumps(payload)
    return row


def _by_recipient() -> MagicMock:
    manager = MagicMock()
    manager.can_user_access_notification.side_effect = (
        lambda *, db, notification, user_info: notification.recipient == user_info.email
    )
    return manager


def test_an_earlier_steps_approver_cannot_answer_a_later_step() -> None:
    db = _db_with([
        _step_row('n-a', 'alice@example.com', 'approve-a'),
        _step_row('n-b', 'bob@example.com', 'approve-b'),
    ], pending_step='approve-b')

    with pytest.raises(HTTPException) as err:
        _assert_caller_authorized_for_execution(
            db=db, notifications_manager=_by_recipient(), execution_id='exec-A',
            user_info=_user('alice@example.com'),
        )
    assert err.value.status_code == 403

    matches = _assert_caller_authorized_for_execution(
        db=db, notifications_manager=_by_recipient(), execution_id='exec-A',
        user_info=_user('bob@example.com'),
    )
    assert [m.id for m in matches] == ['n-b']


def test_notifications_without_a_step_still_count() -> None:
    # Created before approvals recorded their step (pending at upgrade time)
    db = _db_with([_step_row('n-old', 'alice@example.com', None)], pending_step='approve-b')

    matches = _assert_caller_authorized_for_execution(
        db=db, notifications_manager=_by_recipient(), execution_id='exec-A',
        user_info=_user('alice@example.com'),
    )
    assert [m.id for m in matches] == ['n-old']


def test_the_executor_passes_the_step_id_to_its_handler() -> None:
    from src.common.workflow_executor import StepContext, StepResult, WorkflowExecutor

    seen = {}

    class Handler:
        def __init__(self, db, config):
            pass

        def execute(self, context):
            seen['step_id'] = context.step_id
            return StepResult(passed=True)

    executor = WorkflowExecutor(MagicMock())
    executor.HANDLERS = {'approval': Handler}
    step = SimpleNamespace(step_id='approve-b', step_type='approval', config={})
    context = StepContext(
        entity={}, entity_type='data_product', entity_id='p-1', entity_name='P',
        user_email='requester@example.com', trigger_context=None, execution_id='exec-A',
        workflow_id='wf-1', workflow_name='W', step_results={},
    )

    executor._execute_step(step, context)

    assert seen['step_id'] == 'approve-b'


# --- Deciding a step leaves the next step's approval open ---------------------


def test_marking_handled_skips_other_steps() -> None:
    rows = [
        _step_row('n-a', 'alice@example.com', 'approve-a'),
        _step_row('n-b', 'bob@example.com', 'approve-b'),
        _step_row('n-old', 'carol@example.com', None),
    ]

    _mark_step_notifications_handled(
        _mock_db_with_rows(rows), 'exec-A', 'approve-a', True, 'alice@example.com',
    )

    marked = {r.id: (r.read, json.loads(r.action_payload).get('handled_by')) for r in rows}
    assert marked == {
        'n-a': (True, 'alice@example.com'),
        'n-b': (False, None),
        'n-old': (True, 'alice@example.com'),  # no step recorded: as before
    }


def test_approving_a_step_leaves_the_next_steps_notification_open() -> None:
    from src.db_models.process_workflows import WorkflowExecutionDb

    rows = [_step_row('n-a', 'alice@example.com', 'approve-a')]
    db = _db_with(rows, pending_step='approve-a')

    def resume_workflow(**kwargs):
        # The workflow pauses at the next approval step and notifies Bob
        rows.append(_step_row('n-b', 'bob@example.com', 'approve-b'))
        db.query(WorkflowExecutionDb).filter.return_value.first.return_value = ('approve-b',)
        return SimpleNamespace(id='exec-A', status=SimpleNamespace(value='paused'))

    executor = MagicMock()
    executor.resume_workflow.side_effect = resume_workflow
    request = MagicMock()
    request.json = AsyncMock(
        return_value={'execution_id': 'exec-A', 'approved': True, 'message': 'ok'}
    )

    asyncio.run(handle_workflow_approval(
        request=request, db=db, audit_manager=MagicMock(),
        current_user=_user('alice@example.com'), executor=executor,
        notifications_manager=_by_recipient(),
    ))

    assert [(r.id, r.read) for r in rows] == [('n-a', True), ('n-b', False)]
    assert 'handled' not in json.loads(rows[1].action_payload)
