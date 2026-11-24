"""An approval step past its ``timeout_days`` is reminded once (#1119, notify only).

The step is marked overdue (``overdue_since`` on its open approval notifications, so My
Actions can show it), and its approvers and the requester get one reminder each. The
workflow stays paused: nothing approves, rejects or escalates it, and later passes don't
remind again. The workflow scheduler looks for overdue steps once per slot across instances.
"""
import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import sessionmaker

from src.controller.approval_timeouts_manager import (
    remind_overdue_approvals, timeout_days_of,
)
from src.controller.workflow_scheduler import (
    APPROVAL_TIMEOUTS_TASK_KEY, WorkflowScheduler,
)
from src.db_models.notifications import NotificationDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowExecutionDb
from src.db_models.scheduler_claims import SchedulerClaimDb

ASKED = datetime(2026, 11, 2, 9, 0, tzinfo=timezone.utc)
ROLE_ID = 'role-steward'


def _paused(db, *, timeout_days=3, status='paused', step_id='approve', targets=None,
            asked=ASKED):
    workflow = ProcessWorkflowDb(
        id=str(uuid.uuid4()), name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger_config=json.dumps({'type': 'manual'}),
    )
    db.add(workflow)
    db.flush()
    execution = WorkflowExecutionDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, status=status, current_step_id=step_id,
        trigger_context=json.dumps({
            'entity_type': 'data_product', 'entity_id': 'p1', 'trigger_type': 'manual',
            'user_email': 'rita@example.com',
        }),
    )
    db.add(execution)
    for recipient, role_id in targets or [('ana@example.com', None), ('Data Steward', ROLE_ID)]:
        payload = {
            'execution_id': execution.id, 'step_id': step_id, 'workflow_name': 'Review',
            'entity_type': 'data_product', 'entity_id': 'p1', 'entity_name': 'Orders',
            'requester_email': 'rita@example.com',
        }
        if timeout_days is not None:
            payload['timeout_days'] = timeout_days
        db.add(NotificationDb(
            id=str(uuid.uuid4()), type='action_required', title='Approval Required',
            recipient=recipient, recipient_role_id=role_id, action_type='workflow_approval',
            action_payload=json.dumps(payload), read=False, can_delete=False, created_at=asked,
        ))
    db.flush()
    return execution


def _reminders(db):
    db.expire_all()
    return [
        n for n in db.query(NotificationDb).all()
        if n.action_type is None and 'approval_overdue' in json.loads(n.data or '{}')
    ]


def _approvals(db, execution_id):
    db.expire_all()
    return [
        n for n in db.query(NotificationDb).filter_by(action_type='workflow_approval').all()
        if json.loads(n.action_payload)['execution_id'] == execution_id
    ]


class TestRemindOverdueApprovals:
    def test_not_before_the_timeout(self, db_session):
        _paused(db_session)

        assert remind_overdue_approvals(db_session, ASKED + timedelta(days=3, seconds=-1)) == 0
        assert _reminders(db_session) == []

    def test_reminds_the_approvers_and_the_requester_once(self, db_session):
        execution = _paused(db_session)
        now = ASKED + timedelta(days=3)

        assert remind_overdue_approvals(db_session, now) == 1

        reminders = _reminders(db_session)
        assert sorted((r.recipient, r.recipient_role_id) for r in reminders) == sorted([
            ('ana@example.com', None), ('Data Steward', ROLE_ID), ('rita@example.com', None),
        ])
        by_recipient = {r.recipient: r for r in reminders}
        approver = json.loads(by_recipient['ana@example.com'].data)
        assert approver['i18n'] == {
            'title': 'notifications:approvalOverdue.approverTitle',
            'description': 'notifications:approvalOverdue.approverDescription',
            'params': {'name': 'Orders', 'count': 3},
        }
        assert approver['approval_overdue'] == {
            'execution_id': execution.id, 'step_id': 'approve',
        }
        requester = json.loads(by_recipient['rita@example.com'].data)
        assert requester['i18n']['title'] == 'notifications:approvalOverdue.requesterTitle'
        assert {r.type for r in reminders} == {'warning'}
        # The step is marked overdue and still waits for its approvers
        assert {
            json.loads(n.action_payload).get('overdue_since') for n in _approvals(
                db_session, execution.id)
        } == {now.isoformat()}
        db_session.expire_all()
        assert db_session.get(WorkflowExecutionDb, execution.id).status == 'paused'
        assert all(not json.loads(n.action_payload).get('handled')
                   for n in _approvals(db_session, execution.id))

        # Later passes don't remind again
        assert remind_overdue_approvals(db_session, now + timedelta(days=5)) == 0
        assert len(_reminders(db_session)) == 3

    def test_only_paused_executions_and_their_current_step(self, db_session):
        _paused(db_session, status='succeeded')
        moved_on = _paused(db_session, step_id='first')
        moved_on.current_step_id = 'second'
        db_session.flush()

        assert remind_overdue_approvals(db_session, ASKED + timedelta(days=30)) == 0

    def test_decided_targets_are_not_reminded(self, db_session):
        execution = _paused(db_session)
        [decided] = [n for n in _approvals(db_session, execution.id) if n.recipient_role_id]
        decided.action_payload = json.dumps(
            {**json.loads(decided.action_payload), 'handled': True})
        db_session.flush()

        remind_overdue_approvals(db_session, ASKED + timedelta(days=3))

        assert sorted(r.recipient for r in _reminders(db_session)) == [
            'ana@example.com', 'rita@example.com',
        ]

    def test_default_is_seven_days(self, db_session):
        _paused(db_session, timeout_days=None)

        assert remind_overdue_approvals(db_session, ASKED + timedelta(days=6)) == 0
        assert remind_overdue_approvals(db_session, ASKED + timedelta(days=7)) == 1

    def test_timeout_days_values(self):
        assert timeout_days_of({}) == 7
        assert timeout_days_of({'timeout_days': '2'}) == 2
        assert timeout_days_of({'timeout_days': 0}) is None
        assert timeout_days_of({'timeout_days': -1}) is None
        assert timeout_days_of({'timeout_days': None}) is None
        assert timeout_days_of({'timeout_days': True}) is None


class _Sessions:
    def __init__(self, db):
        self._factory = sessionmaker(bind=db.get_bind(), autoflush=False,
                                     join_transaction_mode='create_savepoint')

    def __call__(self):
        return self._factory()


def _claims(db):
    db.expire_all()
    return db.query(SchedulerClaimDb).filter_by(task_key=APPROVAL_TIMEOUTS_TASK_KEY).all()


class TestSchedulerLooksForOverdueApprovals:
    def test_once_per_slot_across_instances(self, db_session):
        _paused(db_session)
        db_session.commit()
        now = ASKED + timedelta(days=4)
        first = WorkflowScheduler(_Sessions(db_session), instance_id='a')
        second = WorkflowScheduler(_Sessions(db_session), instance_id='b')

        first.run_once(now)  # the first pass reads the database: it looks
        second.run_once(now + timedelta(minutes=1))  # same slot: claimed by 'a'

        assert len(_reminders(db_session)) == 3
        [claim] = _claims(db_session)
        assert (claim.claimed_by, claim.outcome) == ('a', {'status': 'done', 'reminded': 1})

    def test_without_requests_it_doesnt_look_again(self, db_session):
        first = WorkflowScheduler(_Sessions(db_session), instance_id='a')
        first.run_once(ASKED)
        _paused(db_session)
        db_session.commit()

        first.run_once(ASKED + timedelta(days=4))  # no request woke the database

        assert _reminders(db_session) == []
        assert len(_claims(db_session)) == 1

    def test_a_request_makes_it_look(self, db_session):
        scheduler = WorkflowScheduler(_Sessions(db_session), instance_id='a')
        scheduler.run_once(ASKED)
        _paused(db_session)
        db_session.commit()
        later = ASKED + timedelta(days=4)
        scheduler._clock = lambda: later

        scheduler.note_database_activity()
        scheduler.run_once(later)

        assert len(_reminders(db_session)) == 3

    def test_can_be_turned_off(self, db_session):
        _paused(db_session)
        db_session.commit()
        scheduler = WorkflowScheduler(
            _Sessions(db_session), instance_id='a', remind_overdue_approvals=False,
        )

        scheduler.run_once(ASKED + timedelta(days=4))

        assert _reminders(db_session) == []
        assert _claims(db_session) == []
