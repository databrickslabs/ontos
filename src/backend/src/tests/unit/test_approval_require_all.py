"""Unit tests for ``require_all`` approvals (#1119): the decision tally of
``WorkflowExecutor.record_required_approval`` and the recipient check of
``NotificationsManager.user_is_recipient``."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import WorkflowExecutor, approver_key
from src.controller.notifications_manager import NotificationsManager
from src.db_models.notifications import NotificationDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb, WorkflowStepExecutionDb,
)
from src.models.users import UserInfo


def _paused(db, *, pause_data, config=None, status='paused', step_type='approval'):
    workflow = ProcessWorkflowDb(
        id=str(uuid.uuid4()), name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger_config=json.dumps({'type': 'manual'}),
    )
    db.add(workflow)
    db.flush()
    step = WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, step_id='approve', step_type=step_type,
        config=json.dumps(config or {'approvers': 'x'}), on_pass='ok', on_fail='no', order=0,
    )
    db.add(step)
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, step_id='ok', step_type='pass', order=1,
    ))
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, step_id='no', step_type='fail', order=2,
    ))
    execution = WorkflowExecutionDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, status=status, current_step_id='approve',
        success_count=1,
        trigger_context=json.dumps({
            'entity_type': 'data_product', 'entity_id': 'p1', 'trigger_type': 'manual',
            'user_email': 'requester@example.com',
        }),
    )
    db.add(execution)
    db.flush()
    if pause_data is not None:
        db.add(WorkflowStepExecutionDb(
            id=str(uuid.uuid4()), execution_id=execution.id, step_id=step.id,
            step_key='approve', status='succeeded', passed=True,
            result_data=json.dumps(pause_data),
        ))
    db.flush()
    return execution


def _users(*entries):
    return [{'approver': a, 'role_id': r} for a, r in entries]


def _decides_for(*names):
    return lambda approver, role_id: approver in names


def _record(db, execution, approved=True, *names, user='u@example.com'):
    return WorkflowExecutor(db).record_required_approval(
        execution.id, approved, decides_for=_decides_for(*names), user_email=user,
    )


class TestTally:
    def test_pending_until_everyone_approved(self, db_session):
        execution = _paused(db_session, pause_data={
            'require_all': True, 'resolved_approvers': _users(('a@x.com', None), ('b@x.com', None)),
        })

        first = _record(db_session, execution, True, 'a@x.com', user='a@x.com')
        second = _record(db_session, execution, True, 'b@x.com', user='b@x.com')

        assert (first['outcome'], first['pending_approvers']) == ('pending', 1)
        assert (second['outcome'], second['pending_approvers']) == ('approved', 0)
        stored = json.loads(db_session.query(WorkflowStepExecutionDb).filter_by(
            execution_id=execution.id,
        ).one().result_data)
        assert [(d['key'], d['decided_by']) for d in stored['decisions']] == [
            ('principal:a@x.com', 'a@x.com'), ('principal:b@x.com', 'b@x.com'),
        ]
        # The pause record keeps its own data
        assert stored['require_all'] is True and len(stored['resolved_approvers']) == 2

    def test_a_rejection_ends_it(self, db_session):
        execution = _paused(db_session, pause_data={
            'require_all': True, 'resolved_approvers': _users(('a@x.com', None), ('b@x.com', None)),
        })

        assert _record(db_session, execution, False, 'a@x.com')['outcome'] == 'rejected'

    def test_the_same_approver_twice(self, db_session):
        execution = _paused(db_session, pause_data={
            'require_all': True, 'resolved_approvers': _users(('a@x.com', None), ('b@x.com', None)),
        })
        _record(db_session, execution, True, 'a@x.com')

        again = _record(db_session, execution, False, 'a@x.com')

        assert again['outcome'] == 'already_decided'
        assert [d['decision'] for d in again['decisions']] == ['approved']

    def test_a_caller_who_is_several_approvers_decides_for_each(self, db_session):
        execution = _paused(db_session, pause_data={
            'require_all': True,
            'resolved_approvers': _users(('a@x.com', None), ('team', None), ('b@x.com', None)),
        })

        result = _record(db_session, execution, True, 'a@x.com', 'team')

        assert (result['outcome'], result['pending_approvers']) == ('pending', 1)

    def test_the_owners_of_a_business_role_decide_once_for_it(self, db_session):
        execution = _paused(db_session, pause_data={
            'require_all': True,
            'resolved_approvers': _users(
                ('o1@x.com', 'br-1'), ('o2@x.com', 'br-1'), ('a@x.com', None),
            ),
        })

        first = _record(db_session, execution, True, 'o2@x.com')
        other_owner = _record(db_session, execution, True, 'o1@x.com')

        assert (first['outcome'], first['pending_approvers']) == ('pending', 1)
        assert first['decisions'][0]['key'] == approver_key('o2@x.com', 'br-1') == 'role:br-1'
        assert other_owner['outcome'] == 'already_decided'

    def test_someone_who_is_none_of_them_decides_for_the_rest(self, db_session):
        execution = _paused(db_session, pause_data={
            'require_all': True, 'resolved_approvers': _users(('a@x.com', None), ('b@x.com', None)),
        })
        _record(db_session, execution, True, 'a@x.com')

        result = _record(db_session, execution, True, user='admin@x.com')

        assert result['outcome'] == 'approved'
        assert [d['approver'] for d in result['decisions']] == ['a@x.com', 'b@x.com']

    def test_approvals_paused_before_the_upgrade_use_the_notifications(self, db_session):
        execution = _paused(db_session, pause_data={'require_all': True, 'approvers': ['?']})
        for recipient, role_id in (('a@x.com', None), ('Data Steward', 'role-1')):
            db_session.add(NotificationDb(
                id=str(uuid.uuid4()), type='action_required', title='Approval Required',
                recipient=recipient, recipient_role_id=role_id, action_type='workflow_approval',
                action_payload=json.dumps({'execution_id': execution.id, 'step_id': 'approve'}),
            ))
        db_session.flush()

        result = _record(db_session, execution, True, 'Data Steward')

        assert (result['outcome'], result['pending_approvers']) == ('pending', 1)
        assert result['decisions'][0]['key'] == 'role:role-1'


class TestNotRequireAll:
    @pytest.mark.parametrize('pause_data, config', [
        ({'require_all': False}, {'require_all': True}),  # the paused value wins
        ({}, {'require_all': False}),
        ({}, {}),
        ({'require_all': 'false'}, {}),
    ])
    def test_returns_none(self, db_session, pause_data, config):
        execution = _paused(db_session, pause_data=pause_data, config=config)

        assert _record(db_session, execution, True, 'a@x.com') is None

    @pytest.mark.parametrize('pause_data, config', [
        ({}, {'require_all': True}),
        ({'require_all': 'true'}, {}),
    ])
    def test_require_all_from_the_config_or_a_string(self, db_session, pause_data, config):
        execution = _paused(db_session, pause_data={
            **pause_data, 'resolved_approvers': _users(('a@x.com', None), ('b@x.com', None)),
        }, config=config)

        assert _record(db_session, execution, True, 'a@x.com')['outcome'] == 'pending'

    @pytest.mark.parametrize('kwargs', [
        {'status': 'succeeded'}, {'status': 'running'}, {'step_type': 'notification'},
    ])
    def test_not_paused_at_an_approval(self, db_session, kwargs):
        execution = _paused(db_session, pause_data={'require_all': True}, **kwargs)

        assert _record(db_session, execution, True, 'a@x.com') is None

    def test_no_pause_record(self, db_session):
        execution = _paused(db_session, pause_data=None, config={'require_all': True})

        assert _record(db_session, execution, True, 'a@x.com') is None


class TestResume:
    def test_only_the_last_decision_completes_the_workflow(self, db_session):
        """The workflow's outcome (e.g. a status change and its certified
        guard) is applied once, by the decision that ends the step, with
        that approver as the responder."""
        execution = _paused(db_session, pause_data={
            'require_all': True, 'resolved_approvers': _users(('a@x.com', None), ('b@x.com', None)),
        })
        executor = WorkflowExecutor(db_session)

        with patch.object(WorkflowExecutor, '_handle_workflow_completion') as completion:
            first = _record(db_session, execution, True, 'a@x.com', user='a@x.com')
            assert first['outcome'] == 'pending'
            completion.assert_not_called()

            assert _record(db_session, execution, True, 'b@x.com', user='b@x.com')[
                'outcome'] == 'approved'
            result = executor.resume_workflow(execution.id, True, user_email='b@x.com')

        assert result.status.value == 'succeeded'
        completion.assert_called_once()
        assert completion.call_args.kwargs['responded_by'] == 'b@x.com'
        latest = db_session.query(WorkflowStepExecutionDb).filter_by(
            execution_id=execution.id, step_key='approve',
        ).order_by(WorkflowStepExecutionDb.started_at.desc()).all()
        recorded = [json.loads(r.result_data) for r in latest if 'approval_result' in (
            r.result_data or '')]
        assert [d['approver'] for d in recorded[0]['decisions']] == ['a@x.com', 'b@x.com']


def _manager(roles):
    settings_manager = MagicMock()
    settings_manager.list_app_roles.return_value = roles
    return NotificationsManager(settings_manager=settings_manager)


def _role(role_id, name, groups):
    return SimpleNamespace(id=role_id, name=name, assigned_groups=groups)


def _user(email, groups=()):
    return UserInfo(email=email, username=email, user=email, ip='127.0.0.1', groups=list(groups))


class TestUserIsRecipient:
    ROLES = [
        _role('r-admin', 'Admin', ['admins']),
        _role('r-steward', 'Data Steward', ['stewards']),
        _role('r-empty', 'Empty Role', []),
    ]

    @pytest.mark.parametrize('recipient, role_id, user, expected', [
        ('A@x.com', None, _user('a@x.com'), True),
        ('b@x.com', None, _user('a@x.com'), False),
        ('team-x', None, _user('a@x.com', ['team-x']), True),
        ('team-x', None, _user('a@x.com', ['team-y']), False),
        ('Data Steward', 'r-steward', _user('a@x.com', ['stewards']), True),
        ('Data Steward', 'r-steward', _user('a@x.com', ['other']), False),
        ('DataSteward', None, _user('a@x.com', ['stewards']), True),  # legacy role name
        # An admin is not every recipient here, only of the Admin role
        ('Data Steward', 'r-steward', _user('boss@x.com', ['admins']), False),
        ('b@x.com', None, _user('boss@x.com', ['admins']), False),
        ('Admin', 'r-admin', _user('boss@x.com', ['admins']), True),
        # A role without groups falls back to the admins, as for access
        ('Empty Role', 'r-empty', _user('boss@x.com', ['admins']), True),
        ('Empty Role', 'r-empty', _user('a@x.com', ['stewards']), False),
        (None, None, _user('a@x.com'), False),
    ])
    def test_cases(self, recipient, role_id, user, expected):
        assert _manager(self.ROLES).user_is_recipient(recipient, role_id, user) is expected
