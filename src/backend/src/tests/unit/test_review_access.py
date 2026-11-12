"""Unit tests for ``caller_is_pending_reviewer`` (#1117): who can decide a review reads it.

Every fact is checked for both entity types the helper serves (data products
and data contracts).
"""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common import review_access
from src.common.review_access import caller_is_pending_reviewer
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb
from src.db_models.notifications import NotificationDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb, WorkflowStepExecutionDb,
)
from src.models.users import UserInfo
from src.tests.helpers import postgres_aborts

ENTITY_ID = 'e-1'
# entity type -> asset FQN prefix in an asset review
FQN_PREFIX = {'data_product': 'product:', 'data_contract': 'contract:'}
ROLE_ID = 'role-stewards'


@pytest.fixture(params=sorted(FQN_PREFIX))
def entity_type(request):
    return request.param


def _user(email, groups=()):
    return UserInfo(email=email, username=email, user=email, ip='127.0.0.1', groups=list(groups))


def _reads(db, email, entity_type, notifications=None, entity_id=ENTITY_ID):
    return caller_is_pending_reviewer(db, _user(email), entity_type, entity_id, notifications)


def _workflow(db, step_type='approval'):
    workflow = ProcessWorkflowDb(
        id=str(uuid.uuid4()), name=f'wf-{uuid.uuid4().hex[:6]}',
        trigger_config=json.dumps({'type': 'on_request_review'}),
    )
    db.add(workflow)
    db.flush()
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, step_id='approve', step_type=step_type,
        config=json.dumps({'approvers': 'Data Steward'}), order=0,
    ))
    db.flush()
    return workflow


def _step_result(db, step_type, result_data):
    """A step execution of a ``step_type`` step that stored ``result_data``."""
    workflow = _workflow(db, step_type=step_type)
    step = db.query(WorkflowStepDb).filter_by(workflow_id=workflow.id).one()
    execution = WorkflowExecutionDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, status='paused',
    )
    db.add(execution)
    db.flush()
    db.add(WorkflowStepExecutionDb(
        id=str(uuid.uuid4()), execution_id=execution.id, step_id=step.id,
        status='succeeded', passed=True, result_data=json.dumps(result_data),
    ))
    db.flush()


def _asset_review(
    db, entity_type, *, reviewer='rev@example.com', requester='owner@example.com',
    entity_id=ENTITY_ID, status='queued', by_workflow='create_asset_review',
):
    """An asset review of the entity; ``by_workflow``: the type of the step whose
    result names the review (falsy: no step result names it)."""
    review = DataAssetReviewRequestDb(
        id=str(uuid.uuid4()), requester_email=requester, reviewer_email=reviewer, status=status,
    )
    db.add(review)
    db.flush()
    db.add(ReviewedAssetDb(
        id=str(uuid.uuid4()), review_request_id=review.id,
        asset_fqn=f'{FQN_PREFIX[entity_type]}{entity_id}', asset_type=entity_type,
    ))
    if by_workflow:
        _step_result(db, by_workflow, {'review_id': review.id, 'reviewer_email': reviewer})
    db.flush()
    return review


def _paused_approval(
    db, entity_type, *, entity_id=ENTITY_ID, status='paused',
    recipient='approver@example.com', role_id=None, requester='owner@example.com',
    handled=False,
):
    workflow = _workflow(db)
    execution = WorkflowExecutionDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, status=status, current_step_id='approve',
        trigger_context=json.dumps({
            'entity_type': entity_type, 'entity_id': entity_id, 'user_email': requester,
        }),
    )
    db.add(execution)
    _approval_notification(
        db, execution, recipient=recipient, role_id=role_id, handled=handled,
    )
    return execution


def _approval_notification(db, execution, *, recipient, role_id=None, handled=False):
    payload = {'execution_id': execution.id, 'step_id': 'approve'}
    if handled:
        payload.update({'handled': True, 'decision': 'approved', 'handled_by': recipient})
    db.add(NotificationDb(
        id=str(uuid.uuid4()), type='action_required', title='Approval Required',
        recipient=recipient, recipient_role_id=role_id, action_type='workflow_approval',
        action_payload=json.dumps(payload), read=handled,
    ))
    db.flush()


def _notifications(*, grants=None, role_members=()):
    """A notifications manager whose access check grants ``grants``; by default
    the recipient, or a member (``role_members``) of the notification's role."""
    manager = MagicMock()

    def _access(db, notification, user_info, **kwargs):
        if grants is not None:
            return grants
        if notification.recipient_role_id == ROLE_ID and user_info.email in role_members:
            return True
        return notification.recipient == user_info.email

    manager.can_user_access_notification.side_effect = _access
    return manager


def _real_notifications(roles=None):
    """The real access check; ``roles=None``: the roles can't be read."""
    from src.controller.notifications_manager import NotificationsManager

    settings = MagicMock()
    if roles is None:
        settings.list_app_roles.side_effect = RuntimeError('roles unavailable')
    else:
        settings.list_app_roles.return_value = list(roles)
    return NotificationsManager(settings_manager=settings)


STEWARD_ROLE = SimpleNamespace(id=ROLE_ID, name='Data Steward', assigned_groups=['stewards'])


class TestAssetReviewer:
    def test_the_reviewer_of_an_open_workflow_review_reads(self, db_session, entity_type):
        _asset_review(db_session, entity_type)

        assert _reads(db_session, 'Rev@Example.com', entity_type) is True

    def test_in_review_still_counts(self, db_session, entity_type):
        _asset_review(db_session, entity_type, status='in_review')

        assert _reads(db_session, 'rev@example.com', entity_type) is True

    @pytest.mark.parametrize('status', ['approved', 'needs_review', 'denied', 'cancelled'])
    def test_a_closed_review_does_not_count(self, db_session, entity_type, status):
        _asset_review(db_session, entity_type, status=status)

        assert _reads(db_session, 'rev@example.com', entity_type) is False

    def test_someone_else_is_not_the_reviewer(self, db_session, entity_type):
        _asset_review(db_session, entity_type)

        assert _reads(db_session, 'other@example.com', entity_type) is False

    def test_a_review_of_another_entity_does_not_count(self, db_session, entity_type):
        _asset_review(db_session, entity_type, entity_id='e-10')

        assert _reads(db_session, 'rev@example.com', entity_type) is False

    def test_a_review_of_the_other_entity_type_does_not_count(self, db_session, entity_type):
        other_type = next(t for t in FQN_PREFIX if t != entity_type)
        _asset_review(db_session, other_type)

        assert _reads(db_session, 'rev@example.com', entity_type) is False

    def test_a_review_no_workflow_created_does_not_count(self, db_session, entity_type):
        _asset_review(db_session, entity_type, by_workflow=None)

        assert _reads(db_session, 'rev@example.com', entity_type) is False

    def test_a_review_id_in_another_step_result_does_not_count(self, db_session, entity_type):
        """An approval step stores the approver's request body in its result,
        so a ``review_id`` there doesn't mean a workflow created the review."""
        _asset_review(db_session, entity_type, by_workflow='approval')

        assert _reads(db_session, 'rev@example.com', entity_type) is False

    def test_the_requester_reviewing_themselves_does_not_count(self, db_session, entity_type):
        _asset_review(db_session, entity_type, requester='rev@example.com')

        assert _reads(db_session, 'rev@example.com', entity_type) is False


class TestPendingApproval:
    def test_a_recipient_of_the_paused_approval_reads(self, db_session, entity_type):
        _paused_approval(db_session, entity_type)

        assert _reads(db_session, 'approver@example.com', entity_type, _notifications()) is True

    def test_a_member_of_the_approval_role_reads(self, db_session, entity_type):
        _paused_approval(db_session, entity_type, recipient=None, role_id=ROLE_ID)
        notifications = _notifications(role_members={'steward@example.com'})

        assert _reads(db_session, 'steward@example.com', entity_type, notifications) is True
        assert _reads(db_session, 'other@example.com', entity_type, notifications) is False

    def test_a_broadcast_approval_grants_nothing(self, db_session, entity_type):
        """No recipient and no role: everyone may see it, so it must not grant read."""
        _paused_approval(db_session, entity_type, recipient=None, role_id=None)

        assert _reads(
            db_session, 'anyone@example.com', entity_type, _notifications(grants=True),
        ) is False

    def test_a_non_recipient_does_not(self, db_session, entity_type):
        _paused_approval(db_session, entity_type)

        assert _reads(db_session, 'other@example.com', entity_type, _notifications()) is False

    @pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled', 'running'])
    def test_an_execution_no_longer_paused_does_not_count(self, db_session, entity_type, status):
        _paused_approval(db_session, entity_type, status=status)

        assert _reads(
            db_session, 'approver@example.com', entity_type, _notifications(grants=True),
        ) is False

    def test_an_approval_of_another_entity_does_not_count(self, db_session, entity_type):
        _paused_approval(db_session, entity_type, entity_id='e-10')  # contains the id
        other_type = next(t for t in FQN_PREFIX if t != entity_type)
        _paused_approval(db_session, other_type)

        assert _reads(
            db_session, 'approver@example.com', entity_type, _notifications(grants=True),
        ) is False

    def test_the_requester_of_an_owner_approval_does_not_count(self, db_session, entity_type):
        execution = _paused_approval(db_session, entity_type, requester='approver@example.com')
        step = db_session.query(WorkflowStepDb).filter_by(
            workflow_id=execution.workflow_id,
        ).one()
        step.config = json.dumps({'approvers': 'DomainOwner'})
        db_session.flush()

        assert _reads(
            db_session, 'approver@example.com', entity_type, _notifications(grants=True),
        ) is False

    def test_a_handled_notification_grants_nothing(self, db_session, entity_type):
        """An approver who already decided (with ``require_all`` the run stays
        paused for the others) no longer reads through that approval."""
        _paused_approval(db_session, entity_type, handled=True)

        assert _reads(db_session, 'approver@example.com', entity_type, _notifications()) is False

    def test_the_approvers_still_to_decide_keep_reading(self, db_session, entity_type):
        execution = _paused_approval(db_session, entity_type, handled=True)
        _approval_notification(db_session, execution, recipient='second@example.com')

        assert _reads(db_session, 'second@example.com', entity_type, _notifications()) is True
        assert _reads(db_session, 'approver@example.com', entity_type, _notifications()) is False

    def test_a_member_of_a_known_role_reads(self, db_session, entity_type):
        _paused_approval(db_session, entity_type, recipient=None, role_id=ROLE_ID)
        steward = _user('steward@example.com', ['stewards'])

        assert caller_is_pending_reviewer(
            db_session, steward, entity_type, ENTITY_ID, _real_notifications([STEWARD_ROLE]),
        ) is True

    def test_an_unknown_role_grants_nothing(self, db_session, entity_type):
        """A deleted role: its id resolves to no role, which must not read as a broadcast."""
        _paused_approval(db_session, entity_type, recipient=None, role_id='deleted-role')

        assert _reads(
            db_session, 'anyone@example.com', entity_type, _real_notifications([STEWARD_ROLE]),
        ) is False

    def test_unreadable_roles_grant_nothing(self, db_session, entity_type):
        _paused_approval(db_session, entity_type, recipient=None, role_id=ROLE_ID)
        steward = _user('steward@example.com', ['stewards'])
        notifications = _real_notifications(roles=None)

        assert caller_is_pending_reviewer(
            db_session, steward, entity_type, ENTITY_ID, notifications,
        ) is False
        assert _reads(db_session, 'anyone@example.com', entity_type, notifications) is False

    def test_no_notifications_manager_denies(self, db_session, entity_type):
        _paused_approval(db_session, entity_type)

        assert _reads(db_session, 'approver@example.com', entity_type) is False


class TestFailsClosed:
    def test_an_error_denies(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError('db down')

        monkeypatch.setattr(review_access, '_is_open_asset_reviewer', _boom)

        assert _reads(MagicMock(), 'rev@example.com', 'data_product') is False

    def test_a_failed_lookup_leaves_the_session_usable(self, db_session, monkeypatch):
        """The failed statement is rolled back to a savepoint, so the caller's
        session (and, on Postgres, its transaction) keeps working."""
        from sqlalchemy import text

        def _bad_sql(db, *args):
            db.execute(text('SELECT * FROM no_such_table'))

        _asset_review(db_session, 'data_product')
        with postgres_aborts(db_session):
            monkeypatch.setattr(review_access, '_is_open_asset_reviewer', _bad_sql)
            assert _reads(db_session, 'rev@example.com', 'data_product') is False
            monkeypatch.undo()

            assert _reads(db_session, 'rev@example.com', 'data_product') is True

    def test_no_user_denies(self):
        assert caller_is_pending_reviewer(MagicMock(), None, 'data_product', ENTITY_ID) is False

    def test_an_unknown_entity_type_denies(self, db_session):
        _asset_review(db_session, 'data_product')

        assert _reads(db_session, 'rev@example.com', 'dataset') is False


class TestProductReadGateUsesIt:
    def _request(self):
        auth_manager = MagicMock()
        auth_manager.get_user_effective_permissions.return_value = {}
        auth_manager.has_permission.return_value = False
        request = MagicMock()
        request.app.state.authorization_manager = auth_manager
        request.app.state.settings_manager = None
        return request

    def test_an_unpublished_product_is_readable_by_its_reviewer(self, db_session):
        from src.routes.data_product_routes import _caller_can_read_product

        _asset_review(db_session, 'data_product')
        product = SimpleNamespace(
            id=ENTITY_ID, status='under_review', draft_owner_id='owner@example.com',
            owner_team_id=None, project_id=None,
        )

        assert _caller_can_read_product(
            self._request(), db_session, _user('rev@example.com'), None, product,
        ) is True
        assert _caller_can_read_product(
            self._request(), db_session, _user('other@example.com'), None, product,
        ) is False

    def test_an_error_before_the_ownership_checks_denies(self, db_session, monkeypatch):
        from src.common import version_visibility
        from src.routes.data_product_routes import _caller_can_read_product

        def _boom(row):
            raise RuntimeError('status check failed')

        monkeypatch.setattr(version_visibility, 'is_visible_consumer', _boom)
        product = SimpleNamespace(
            id=ENTITY_ID, status='draft', draft_owner_id='owner@example.com',
            owner_team_id=None, project_id=None,
        )

        assert _caller_can_read_product(
            self._request(), db_session, _user('owner@example.com'), None, product,
        ) is False

    @pytest.mark.parametrize('lookup', ['team', 'project'])
    def test_a_failing_ownership_lookup_still_lets_the_reviewer_read(
        self, db_session, monkeypatch, lookup,
    ):
        """The ownership lookups of the shared read rule (``product_read_rule``)
        run in savepoints: a failed one denies ownership without aborting the
        transaction (Postgres) for the reviewer check after it."""
        from sqlalchemy import text

        from src.common import product_read_rule
        from src.controller.projects_manager import projects_manager
        from src.routes.data_product_routes import _caller_can_read_product

        def _failing_lookup(*args, **kwargs):
            db_session.execute(text('SELECT * FROM no_such_table'))

        if lookup == 'team':
            monkeypatch.setattr(product_read_rule, 'lookup_team_ids', _failing_lookup)
        else:
            monkeypatch.setattr(projects_manager, 'is_user_project_member', _failing_lookup)
        _asset_review(db_session, 'data_product')
        db_session.flush()
        product = SimpleNamespace(
            id=ENTITY_ID, status='under_review', draft_owner_id='owner@example.com',
            owner_team_id='team-1', project_id='project-1',
        )

        with postgres_aborts(db_session):
            assert _caller_can_read_product(
                self._request(), db_session, _user('rev@example.com'), None, product,
            ) is True

    def test_a_failing_check_does_not_hide_later_rows(self, db_session, monkeypatch):
        """On Postgres a failed statement aborts the transaction: without a
        savepoint per check, every later row of the queue would fail and be hidden."""
        from sqlalchemy import text

        from src.controller.approvals_manager import ApprovalsManager
        from src.db_models.data_products import DataProductDb
        from src.routes.data_product_routes import _caller_can_read_product

        failing, fine = 'p-failing', 'p-fine'
        for product_id in (failing, fine):
            db_session.add(DataProductDb(
                id=product_id, name=product_id, version='1', status='under_review',
                draft_owner_id='owner@example.com',
            ))
            _asset_review(db_session, 'data_product', entity_id=product_id)
        db_session.flush()
        real_check = review_access._is_open_asset_reviewer
        checked = []

        def _check(db, user, entity_type, entity_id):
            checked.append(entity_id)
            if entity_id == failing:
                db.execute(text('SELECT * FROM no_such_table'))
            return real_check(db, user, entity_type, entity_id)

        monkeypatch.setattr(review_access, '_is_open_asset_reviewer', _check)
        reviewer = _user('rev@example.com')
        request = self._request()

        with postgres_aborts(db_session):
            queue = ApprovalsManager().get_approvals_queue(
                db_session,
                can_see_contract=lambda contract: True,
                can_see_product=lambda product: _caller_can_read_product(
                    request, db_session, reviewer, None, product,
                ),
            )

        assert checked == [failing, fine]
        assert [p['id'] for p in queue['products']] == [fine]
