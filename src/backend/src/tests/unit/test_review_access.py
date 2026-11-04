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


def _asset_review(
    db, entity_type, *, reviewer='rev@example.com', requester='owner@example.com',
    entity_id=ENTITY_ID, status='queued', by_workflow=True,
):
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
        workflow = _workflow(db, step_type='create_asset_review')
        execution = WorkflowExecutionDb(
            id=str(uuid.uuid4()), workflow_id=workflow.id, status='paused',
        )
        db.add(execution)
        db.flush()
        db.add(WorkflowStepExecutionDb(
            id=str(uuid.uuid4()), execution_id=execution.id, status='succeeded', passed=True,
            result_data=json.dumps({'review_id': review.id, 'reviewer_email': reviewer}),
        ))
    db.flush()
    return review


def _paused_approval(
    db, entity_type, *, entity_id=ENTITY_ID, status='paused',
    recipient='approver@example.com', role_id=None, requester='owner@example.com',
):
    workflow = _workflow(db)
    execution = WorkflowExecutionDb(
        id=str(uuid.uuid4()), workflow_id=workflow.id, status=status, current_step_id='approve',
        trigger_context=json.dumps({
            'entity_type': entity_type, 'entity_id': entity_id, 'user_email': requester,
        }),
    )
    db.add(execution)
    db.add(NotificationDb(
        id=str(uuid.uuid4()), type='action_required', title='Approval Required',
        recipient=recipient, recipient_role_id=role_id, action_type='workflow_approval',
        action_payload=json.dumps({'execution_id': execution.id, 'step_id': 'approve'}),
    ))
    db.flush()
    return execution


def _notifications(*, grants=None, role_members=()):
    """A notifications manager whose access check grants ``grants``; by default
    the recipient, or a member (``role_members``) of the notification's role."""
    manager = MagicMock()

    def _access(db, notification, user_info):
        if grants is not None:
            return grants
        if notification.recipient_role_id == ROLE_ID and user_info.email in role_members:
            return True
        return notification.recipient == user_info.email

    manager.can_user_access_notification.side_effect = _access
    return manager


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
        _asset_review(db_session, entity_type, by_workflow=False)

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

    def test_no_notifications_manager_denies(self, db_session, entity_type):
        _paused_approval(db_session, entity_type)

        assert _reads(db_session, 'approver@example.com', entity_type) is False


class TestFailsClosed:
    def test_an_error_denies(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError('db down')

        monkeypatch.setattr(review_access, '_is_open_asset_reviewer', _boom)

        assert _reads(MagicMock(), 'rev@example.com', 'data_product') is False

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
