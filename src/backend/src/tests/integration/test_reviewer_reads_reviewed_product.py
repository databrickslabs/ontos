"""Reviewers can read the data product they review (#1117).

The real flow: a producer requests a review naming a reviewer, the default
"Data Product Review Request" workflow creates the asset review and pauses at
its approval step. Whoever can decide (the named reviewer, the members of the
role the approval is addressed to) reads the product; nobody else does, and
nobody gains a write.

A refused request rolls back the test's transaction (``get_db`` rolls back on
any exception), so each test ends with its only refusal.
"""
import uuid

import pytest

PRODUCER = ('producer@example.com', ['data-producers'])
# Data Producer too (data-products read/write), but doesn't own the product
OTHER_PRODUCER = ('other.producer@example.com', ['data-producers'])
# Data Consumers: read-only on data products, not addressed by the approval
REVIEWER = ('reviewer@example.com', ['data-consumers'])
OTHER_CONSUMER = ('other@example.com', ['data-consumers'])
STEWARD = ('steward@example.com', ['data-stewards'])
ADMIN = ('test@example.com', ['test_admins'])


@pytest.fixture(autouse=True)
def default_workflows(db_session):
    """The default "Data Product Review Request" workflow, as at startup."""
    from src.controller.workflows_manager import WorkflowsManager

    WorkflowsManager(db=db_session).load_from_yaml()


@pytest.fixture
def as_user(mock_test_user):
    def _switch(identity):
        email, groups = identity
        mock_test_user.email = email
        mock_test_user.username = email
        mock_test_user.user = email
        mock_test_user.groups = list(groups)
    yield _switch
    _switch(ADMIN)
    mock_test_user.username = 'test_user'
    mock_test_user.user = 'test_user'


def _create_draft(client, as_user, name):
    as_user(PRODUCER)
    product_id = str(uuid.uuid4())
    response = client.post('/api/data-products', json={
        'id': product_id, 'name': name, 'version': '1.0.0',
        'productType': 'sourceAligned', 'status': 'draft',
        'description': {'purpose': 'Reviewer read access test'},
    })
    assert response.status_code in (200, 201), response.text
    return product_id


def _request_review(client, as_user, product_id, reviewer_email):
    as_user(PRODUCER)
    response = client.post(
        f'/api/data-products/{product_id}/request-review',
        json={'reviewer_email': reviewer_email},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result.get('workflow_status') == 'paused', result
    return result


def _review_id(db_session, product_id):
    from src.db_models.data_asset_reviews import DataAssetReviewRequestDb, ReviewedAssetDb

    [review] = db_session.query(DataAssetReviewRequestDb).join(ReviewedAssetDb).filter(
        ReviewedAssetDb.asset_fqn == f'product:{product_id}',
    ).all()
    return review.id


def _get(client, as_user, identity, product_id):
    as_user(identity)
    return client.get(f'/api/data-products/{product_id}').status_code


@pytest.fixture
def reviewed(client, as_user):
    """A draft under review, ``REVIEWER`` named; the approval goes to the Data
    Stewards (no domain owner)."""
    product_id = _create_draft(client, as_user, 'Reviewed product')
    return product_id, _request_review(client, as_user, product_id, REVIEWER[0])


def _approval_notifications(db_session, execution_id):
    from src.db_models.notifications import NotificationDb

    return [
        n for n in db_session.query(NotificationDb).filter_by(action_type='workflow_approval')
        if execution_id in (n.action_payload or '')
    ]


def _queued_product_ids(client, as_user, identity):
    as_user(identity)
    response = client.get('/api/approvals/queue')
    assert response.status_code == 200, response.text
    return {p['id'] for p in response.json()['products']}


class TestReviewerReadsReviewedProduct:
    def test_the_named_reviewer_reads_the_product(self, client, as_user, reviewed):
        product_id, _ = reviewed

        assert _get(client, as_user, REVIEWER, product_id) == 200
        assert _get(client, as_user, PRODUCER, product_id) == 200

    def test_a_member_of_the_approval_role_reads_the_product(
        self, client, as_user, db_session, reviewed,
    ):
        product_id, result = reviewed
        # The approval is addressed to the Data Steward role, not to the steward
        notifications = _approval_notifications(db_session, result['execution_id'])
        assert notifications
        assert all(n.recipient_role_id and n.recipient != STEWARD[0] for n in notifications)

        assert _get(client, as_user, STEWARD, product_id) == 200

    def test_a_broadcast_approval_grants_nothing(self, client, as_user, db_session, reviewed):
        """An approval notification with no recipient and no role is visible to
        everyone, so it must not open the product to anyone."""
        product_id, result = reviewed
        assert _get(client, as_user, STEWARD, product_id) == 200
        for notification in _approval_notifications(db_session, result['execution_id']):
            notification.recipient = None
            notification.recipient_role_id = None
        db_session.commit()

        assert _get(client, as_user, STEWARD, product_id) == 404

    @pytest.mark.parametrize('case', ['deleted-role', 'roles-unreadable'])
    def test_an_unresolvable_approval_role_grants_nothing(
        self, client, as_user, db_session, monkeypatch, reviewed, case,
    ):
        """An approval addressed by role id only, whose role can't be resolved
        (deleted, or the roles can't be read), must not read as a broadcast."""
        product_id, result = reviewed
        for notification in _approval_notifications(db_session, result['execution_id']):
            notification.recipient = None
            if case == 'deleted-role':
                notification.recipient_role_id = 'deleted-role'
        db_session.commit()
        if case == 'roles-unreadable':
            from unittest.mock import MagicMock

            # Only the approval check's role lookup fails
            unreadable = MagicMock()
            unreadable.list_app_roles.side_effect = RuntimeError('roles unavailable')
            monkeypatch.setattr(
                client.app.state.notifications_manager, '_settings_manager', unreadable,
            )

        assert _get(client, as_user, REVIEWER, product_id) == 200  # the asset review
        assert _get(client, as_user, OTHER_CONSUMER, product_id) == 404

    def test_someone_who_cannot_decide_still_gets_404(self, client, as_user, reviewed):
        product_id, _ = reviewed

        assert _get(client, as_user, OTHER_CONSUMER, product_id) == 404

    def test_the_reviewer_of_another_review_gets_404(self, client, as_user, reviewed):
        first, _ = reviewed
        second = _create_draft(client, as_user, 'Second product')
        _request_review(client, as_user, second, OTHER_CONSUMER[0])

        assert _get(client, as_user, REVIEWER, first) == 200
        assert _get(client, as_user, OTHER_CONSUMER, second) == 200
        assert _get(client, as_user, REVIEWER, second) == 404

    @pytest.mark.parametrize('method', ['put', 'delete'])
    def test_the_reviewer_gets_no_write(self, client, as_user, reviewed, method):
        product_id, _ = reviewed
        as_user(REVIEWER)
        product = client.get(f'/api/data-products/{product_id}').json()

        if method == 'put':
            response = client.put(
                f'/api/data-products/{product_id}', json={**product, 'name': 'Renamed'},
            )
        else:
            response = client.delete(f'/api/data-products/{product_id}')

        assert response.status_code == 403

    def test_the_product_is_not_listed_for_the_reviewer(self, client, as_user, reviewed):
        product_id, _ = reviewed
        as_user(REVIEWER)

        response = client.get('/api/data-products')

        assert response.status_code == 200
        assert product_id not in {p.get('id') for p in response.json()}

    @pytest.mark.parametrize('status', ['approved', 'needs_review', 'denied', 'cancelled'])
    def test_a_closed_review_no_longer_grants_read(
        self, client, as_user, db_session, reviewed, status,
    ):
        from src.db_models.data_asset_reviews import DataAssetReviewRequestDb

        product_id, _ = reviewed
        assert _get(client, as_user, REVIEWER, product_id) == 200
        # Set directly: PUT /api/data-asset-reviews/{id}/status answers 500 on
        # development (it calls the manager with a keyword the manager lacks).
        db_session.query(DataAssetReviewRequestDb).filter_by(
            id=_review_id(db_session, product_id),
        ).update({'status': status})
        db_session.commit()

        assert _get(client, as_user, REVIEWER, product_id) == 404

    def test_a_deleted_review_no_longer_grants_read(self, client, as_user, db_session, reviewed):
        product_id, _ = reviewed
        review_id = _review_id(db_session, product_id)
        as_user(ADMIN)
        assert client.delete(f'/api/data-asset-reviews/{review_id}').status_code == 204

        assert _get(client, as_user, REVIEWER, product_id) == 404

    def test_a_decided_approval_no_longer_grants_read(self, client, as_user, reviewed):
        product_id, result = reviewed
        assert _get(client, as_user, STEWARD, product_id) == 200

        as_user(STEWARD)
        response = client.post('/api/workflows/handle-approval', json={
            'execution_id': result['execution_id'], 'approved': False, 'reason': 'Not yet',
        })
        assert response.status_code == 200, response.text

        assert _get(client, as_user, STEWARD, product_id) == 404

    def test_a_review_created_through_the_api_grants_nothing(self, client, as_user):
        """``POST /api/data-asset-reviews`` takes reviewer and requester from the
        body, so naming yourself must not open someone else's draft."""
        product_id = _create_draft(client, as_user, 'Self-named review target')
        as_user(STEWARD)
        response = client.post('/api/data-asset-reviews', json={
            'requester_email': PRODUCER[0],
            'reviewer_email': STEWARD[0],
            'asset_fqns': [f'product:{product_id}'],
        })
        assert response.status_code == 201, response.text

        assert _get(client, as_user, STEWARD, product_id) == 404


class TestRequestReviewNeedsOwnership:
    """Requesting a review names the reviewer, who then reads the product, so
    only the product's owners (or an admin) may request it (#1117)."""

    def test_an_admin_may_request_the_review_of_any_draft(self, client, as_user):
        product_id = _create_draft(client, as_user, 'Admin-requested review')
        as_user(ADMIN)
        response = client.post(
            f'/api/data-products/{product_id}/request-review',
            json={'reviewer_email': REVIEWER[0]},
        )
        assert response.status_code == 200, response.text

        assert _get(client, as_user, REVIEWER, product_id) == 200

    def test_a_writer_who_does_not_own_the_draft_is_refused(self, client, as_user):
        product_id = _create_draft(client, as_user, 'Not yours to submit')
        as_user(OTHER_PRODUCER)
        response = client.post(
            f'/api/data-products/{product_id}/request-review',
            json={'reviewer_email': OTHER_PRODUCER[0]},
        )

        # Same answer as reading it: the draft's existence isn't disclosed. That
        # nothing changed is checked by the route's unit test (a refusal rolls
        # back this test's transaction).
        assert response.status_code == 404, response.text


class TestApprovalsQueue:
    """``GET /api/approvals/queue`` lists a product only to who may open it (#1117)."""

    def test_whoever_can_decide_sees_the_product(self, client, as_user, reviewed):
        product_id, _ = reviewed

        for identity in (REVIEWER, STEWARD, PRODUCER, ADMIN):
            assert product_id in _queued_product_ids(client, as_user, identity), identity

    def test_someone_who_cannot_open_it_does_not(self, client, as_user, reviewed):
        product_id, _ = reviewed

        assert product_id not in _queued_product_ids(client, as_user, OTHER_CONSUMER)

    def test_the_entry_goes_once_the_approval_is_decided(self, client, as_user, reviewed):
        product_id, result = reviewed
        assert product_id in _queued_product_ids(client, as_user, STEWARD)

        as_user(STEWARD)
        response = client.post('/api/workflows/handle-approval', json={
            'execution_id': result['execution_id'], 'approved': False, 'reason': 'Not yet',
        })
        assert response.status_code == 200, response.text

        assert product_id not in _queued_product_ids(client, as_user, STEWARD)

    def test_a_proposed_product_without_a_review_is_listed_to_its_owner_only(
        self, client, as_user,
    ):
        product_id = _create_draft(client, as_user, 'Submitted without a workflow')
        as_user(PRODUCER)
        response = client.post(f'/api/data-products/{product_id}/submit-review')
        assert response.status_code == 200, response.text

        assert product_id in _queued_product_ids(client, as_user, PRODUCER)
        assert product_id in _queued_product_ids(client, as_user, ADMIN)
        assert product_id not in _queued_product_ids(client, as_user, STEWARD)
        assert product_id not in _queued_product_ids(client, as_user, OTHER_CONSUMER)

    def test_contracts_are_still_listed_to_contract_readers(
        self, client, as_user, db_session,
    ):
        """``GET /api/data-contracts/{id}`` has no gate beyond data-contracts
        read on this branch, so the queue keeps listing contracts."""
        from src.db_models.data_contracts import DataContractDb

        contract_id = str(uuid.uuid4())
        db_session.add(DataContractDb(
            id=contract_id, name='Proposed contract', version='1.0.0', status='proposed',
        ))
        db_session.commit()
        as_user(OTHER_CONSUMER)

        response = client.get('/api/approvals/queue')

        assert response.status_code == 200, response.text
        assert contract_id in {c['id'] for c in response.json()['contracts']}
