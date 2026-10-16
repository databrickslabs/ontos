"""Requesting a data product review without naming a reviewer (#972).

The product page sends only a message, so ``reviewer_email`` is optional and
the review workflow's ``create_asset_review`` step resolves the reviewer, with
the same resolver as the approval steps (e.g. 'DomainOwner').
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from src.common.workflow_executor import CreateAssetReviewStepHandler, StepContext
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb
from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.models.users import UserInfo
from src.routes.data_product_routes import request_product_review


def test_a_review_can_be_requested_with_only_a_message():
    manager = MagicMock()
    manager.request_review.return_value = {'status': 'success'}
    request = MagicMock()
    request.json = AsyncMock(return_value={'message': 'Please review', 'wizard_data': {}})
    user = UserInfo(email='rita@example.com', username='rita', user='Rita',
                    ip='127.0.0.1', groups=[])

    result = asyncio.run(request_product_review(
        product_id='p-1', request=request, db=MagicMock(), audit_manager=MagicMock(),
        current_user=user, manager=manager, _=True,
    ))

    assert result == {'status': 'success'}
    kwargs = manager.request_review.call_args.kwargs
    assert kwargs['reviewer_email'] is None
    assert kwargs['message'] == 'Please review'
    # The review record needs an email, which the username isn't always
    assert kwargs['requester_email'] == 'rita@example.com'


def _context(entity_id, entity_data=None, requester='rita@example.com'):
    trigger = SimpleNamespace(
        entity_type='data_product', entity_id=entity_id, entity_name='AML',
        entity_data=entity_data or {}, user_email=requester,
    )
    return StepContext(
        entity={'name': 'AML'}, entity_type='data_product', entity_id=entity_id,
        entity_name='AML', user_email=requester, trigger_context=trigger,
        execution_id='x-1', workflow_id='w-1', workflow_name='Data Product Review Request',
        step_results={},
    )


def _domain_with_owners(db, entity_id, *emails):
    domain = DataDomain(id=str(uuid.uuid4()), name=f'domain-{uuid.uuid4().hex[:6]}',
                        created_by='admin')
    db.add(domain)
    db.flush()
    db.add(EntityDomainAssociationDb(
        domain_id=domain.id, entity_id=entity_id, entity_type='data_product', is_primary=True,
    ))
    role = BusinessRoleDb(id=uuid.uuid4(), name=f'Lead {uuid.uuid4().hex[:6]}')
    db.add(role)
    db.flush()
    for email in emails:
        db.add(BusinessOwnerDb(
            id=uuid.uuid4(), object_type='data_domain', object_id=domain.id,
            user_email=email, role_id=role.id, is_active=True,
        ))
    db.flush()


def _create_review(db, reviewer_role, context):
    handler = CreateAssetReviewStepHandler(db, {'reviewer_role': reviewer_role})
    result = handler.execute(context)
    assert result.passed, result.error
    return db.get(DataAssetReviewRequestDb, result.data['review_id'])


def test_a_domain_owner_other_than_the_requester_reviews(db_session):
    product_id = str(uuid.uuid4())
    _domain_with_owners(db_session, product_id, 'rita@example.com', 'frank@example.com')

    review = _create_review(db_session, 'DomainOwner', _context(product_id))

    assert review.reviewer_email == 'frank@example.com'
    assert review.requester_email == 'rita@example.com'


def test_a_reviewer_named_in_the_request_wins(db_session):
    product_id = str(uuid.uuid4())
    _domain_with_owners(db_session, product_id, 'frank@example.com')

    review = _create_review(
        db_session, 'DomainOwner',
        _context(product_id, entity_data={'reviewer_email': 'steward@example.com'}),
    )

    assert review.reviewer_email == 'steward@example.com'


def test_a_role_falls_back_to_one_of_its_members(db_session):
    handler = CreateAssetReviewStepHandler(db_session, {'reviewer_role': 'DomainOwner'})
    context = _context(str(uuid.uuid4()))
    resolved = [('Data Steward', 'role-1')]  # e.g. a domain without owners

    with patch('src.common.workflow_executor._resolve_role_to_users', return_value=resolved), \
            patch.object(CreateAssetReviewStepHandler, '_resolve_reviewer_from_role',
                         return_value='steward@example.com') as from_role:
        reviewer = handler._resolve_reviewer('DomainOwner', context, 'rita@example.com')

    assert reviewer == 'steward@example.com'
    from_role.assert_called_once_with('Data Steward', exclude='rita@example.com')


def test_the_requester_named_as_reviewer_is_ignored(db_session):
    product_id = str(uuid.uuid4())
    _domain_with_owners(db_session, product_id, 'rita@example.com', 'frank@example.com')

    review = _create_review(
        db_session, 'DomainOwner',
        _context(product_id, entity_data={'reviewer_email': 'Rita@example.com'}),
    )

    assert review.reviewer_email == 'frank@example.com'


def test_a_role_member_other_than_the_requester_reviews(db_session):
    from src.db_models.settings import AppRoleDb

    db_session.add(AppRoleDb(id=str(uuid.uuid4()), name='Data Steward',
                             assigned_groups='["data-stewards"]'))
    db_session.flush()
    users = {'u1': 'rita@example.com', 'u2': 'sam@example.com'}
    group = SimpleNamespace(members=[SimpleNamespace(value='u1'), SimpleNamespace(value='u2')])
    ws = SimpleNamespace(
        groups=SimpleNamespace(list=lambda **_: [group]),
        users=SimpleNamespace(get=lambda uid: SimpleNamespace(user_name=users[uid])),
    )
    handler = CreateAssetReviewStepHandler(db_session, {})

    with patch('src.common.workspace_client.get_workspace_client', return_value=ws):
        reviewer = handler._resolve_reviewer_from_role('Data Steward', exclude='rita@example.com')

    assert reviewer == 'sam@example.com'


def test_no_review_is_created_when_only_the_requester_could_review(db_session):
    product_id = str(uuid.uuid4())
    _domain_with_owners(db_session, product_id, 'rita@example.com')  # requester only
    handler = CreateAssetReviewStepHandler(db_session, {'reviewer_role': 'DomainOwner'})

    with patch.object(CreateAssetReviewStepHandler, '_resolve_reviewer_from_role',
                      return_value=None):
        result = handler.execute(_context(product_id))

    # The approval step that follows still decides; nobody reviews their own request
    assert result.passed
    assert result.data['review_id'] is None
    assert db_session.query(DataAssetReviewRequestDb).filter(
        DataAssetReviewRequestDb.reviewer_email == 'rita@example.com'
    ).count() == 0
