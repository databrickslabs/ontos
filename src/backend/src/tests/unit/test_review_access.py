"""Unit tests for ``caller_reviews_entity`` (#1117): who can decide a review reads it."""
import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common import review_access
from src.common.review_access import caller_reviews_entity
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb
from src.db_models.notifications import NotificationDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb, WorkflowStepExecutionDb,
)
from src.models.users import UserInfo

PRODUCT = 'p-1'


def _user(email, groups=()):
    return UserInfo(email=email, username=email, user=email, ip='127.0.0.1', groups=list(groups))


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
    db, *, reviewer='rev@example.com', requester='owner@example.com',
    fqn=f'product:{PRODUCT}', status='queued', by_workflow=True,
):
    review = DataAssetReviewRequestDb(
        id=str(uuid.uuid4()), requester_email=requester, reviewer_email=reviewer, status=status,
    )
    db.add(review)
    db.flush()
    db.add(ReviewedAssetDb(
        id=str(uuid.uuid4()), review_request_id=review.id, asset_fqn=fqn,
        asset_type='data_product',
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
    db, *, entity_id=PRODUCT, entity_type='data_product', status='paused',
    recipient='approver@example.com', requester='owner@example.com',
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
        recipient=recipient, action_type='workflow_approval',
        action_payload=json.dumps({'execution_id': execution.id, 'step_id': 'approve'}),
    ))
    db.flush()
    return execution


def _notifications(*, grants=None):
    """A notifications manager whose access check grants ``grants`` (recipient
    == caller email by default)."""
    manager = MagicMock()

    def _access(db, notification, user_info):
        if grants is not None:
            return grants
        return notification.recipient == user_info.email

    manager.can_user_access_notification.side_effect = _access
    return manager


class TestAssetReviewer:
    def test_the_reviewer_of_an_open_workflow_review_reads(self, db_session):
        _asset_review(db_session)

        assert caller_reviews_entity(
            db_session, None, _user('Rev@Example.com'), 'data_product', PRODUCT,
        ) is True

    @pytest.mark.parametrize('status', ['in_review'])
    def test_in_review_still_counts(self, db_session, status):
        _asset_review(db_session, status=status)

        assert caller_reviews_entity(
            db_session, None, _user('rev@example.com'), 'data_product', PRODUCT,
        ) is True

    @pytest.mark.parametrize('status', ['approved', 'needs_review', 'denied', 'cancelled'])
    def test_a_closed_review_does_not_count(self, db_session, status):
        _asset_review(db_session, status=status)

        assert caller_reviews_entity(
            db_session, None, _user('rev@example.com'), 'data_product', PRODUCT,
        ) is False

    def test_someone_else_is_not_the_reviewer(self, db_session):
        _asset_review(db_session)

        assert caller_reviews_entity(
            db_session, None, _user('other@example.com'), 'data_product', PRODUCT,
        ) is False

    def test_a_review_of_another_product_does_not_count(self, db_session):
        _asset_review(db_session, fqn='product:p-10')

        assert caller_reviews_entity(
            db_session, None, _user('rev@example.com'), 'data_product', PRODUCT,
        ) is False

    def test_a_review_no_workflow_created_does_not_count(self, db_session):
        _asset_review(db_session, by_workflow=False)

        assert caller_reviews_entity(
            db_session, None, _user('rev@example.com'), 'data_product', PRODUCT,
        ) is False

    def test_the_requester_reviewing_themselves_does_not_count(self, db_session):
        _asset_review(db_session, requester='rev@example.com')

        assert caller_reviews_entity(
            db_session, None, _user('rev@example.com'), 'data_product', PRODUCT,
        ) is False


class TestPendingApproval:
    def test_a_recipient_of_the_paused_approval_reads(self, db_session):
        _paused_approval(db_session)

        assert caller_reviews_entity(
            db_session, _notifications(), _user('approver@example.com'), 'data_product', PRODUCT,
        ) is True

    def test_a_non_recipient_does_not(self, db_session):
        _paused_approval(db_session)

        assert caller_reviews_entity(
            db_session, _notifications(), _user('other@example.com'), 'data_product', PRODUCT,
        ) is False

    @pytest.mark.parametrize('status', ['succeeded', 'failed', 'cancelled', 'running'])
    def test_an_execution_no_longer_paused_does_not_count(self, db_session, status):
        _paused_approval(db_session, status=status)

        assert caller_reviews_entity(
            db_session, _notifications(grants=True), _user('approver@example.com'),
            'data_product', PRODUCT,
        ) is False

    @pytest.mark.parametrize('entity_type, entity_id', [
        ('data_product', 'p-10'),  # contains the id as a substring
        ('data_contract', PRODUCT),
    ])
    def test_an_approval_of_another_entity_does_not_count(
        self, db_session, entity_type, entity_id,
    ):
        _paused_approval(db_session, entity_type=entity_type, entity_id=entity_id)

        assert caller_reviews_entity(
            db_session, _notifications(grants=True), _user('approver@example.com'),
            'data_product', PRODUCT,
        ) is False

    def test_the_requester_of_an_owner_approval_does_not_count(self, db_session):
        execution = _paused_approval(db_session, requester='approver@example.com')
        step = db_session.query(WorkflowStepDb).filter_by(
            workflow_id=execution.workflow_id,
        ).one()
        step.config = json.dumps({'approvers': 'DomainOwner'})
        db_session.flush()

        assert caller_reviews_entity(
            db_session, _notifications(grants=True), _user('approver@example.com'),
            'data_product', PRODUCT,
        ) is False

    def test_no_notifications_manager_denies(self, db_session):
        _paused_approval(db_session)

        assert caller_reviews_entity(
            db_session, None, _user('approver@example.com'), 'data_product', PRODUCT,
        ) is False


class TestFailsClosed:
    def test_an_error_denies(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError('db down')

        monkeypatch.setattr(review_access, '_is_open_asset_reviewer', _boom)

        assert caller_reviews_entity(
            MagicMock(), None, _user('rev@example.com'), 'data_product', PRODUCT,
        ) is False

    def test_no_user_denies(self):
        assert caller_reviews_entity(MagicMock(), None, None, 'data_product', PRODUCT) is False


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

        _asset_review(db_session)
        product = SimpleNamespace(
            id=PRODUCT, status='under_review', draft_owner_id='owner@example.com',
            owner_team_id=None, project_id=None,
        )

        assert _caller_can_read_product(
            self._request(), db_session, _user('rev@example.com'), None, product,
        ) is True
        assert _caller_can_read_product(
            self._request(), db_session, _user('other@example.com'), None, product,
        ) is False
