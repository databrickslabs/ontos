"""Asset reviews of data products and contracts are stored with their type (#174).

The review workflow's ``create_asset_review`` step names a product or contract
by id (``product:<id>``, ``contract:<id>``) and stores it as DATA_PRODUCT /
DATA_CONTRACT, so the review editor doesn't treat it as a table.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.common.workflow_executor import CreateAssetReviewStepHandler, StepContext
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb
from src.models.data_asset_reviews import AssetType, app_entity_asset_type


def _context(entity_type, entity_id, name, entity_data=None, requester='rita@example.com'):
    trigger = SimpleNamespace(
        entity_type=entity_type, entity_id=entity_id, entity_name=name,
        entity_data=entity_data or {}, user_email=requester,
    )
    return StepContext(
        entity={'name': name}, entity_type=entity_type, entity_id=entity_id,
        entity_name=name, user_email=requester, trigger_context=trigger,
        execution_id='x-1', workflow_id='w-1', workflow_name='Review Request',
        step_results={},
    )


@pytest.mark.parametrize('entity_type, prefix, asset_type', [
    ('data_product', 'product', AssetType.DATA_PRODUCT),
    ('data_contract', 'contract', AssetType.DATA_CONTRACT),
])
def test_the_review_step_stores_the_entity_by_id_with_its_type(
    db_session, entity_type, prefix, asset_type,
):
    entity_id = str(uuid.uuid4())
    handler = CreateAssetReviewStepHandler(db_session, {'reviewer_role': 'DataSteward'})

    result = handler.execute(_context(
        entity_type, entity_id, 'Customer 360',
        entity_data={'reviewer_email': 'steward@example.com'},
    ))

    assert result.passed, result.error
    review = db_session.get(DataAssetReviewRequestDb, result.data['review_id'])
    assert review.title == 'Review of Customer 360'
    assert [(a.asset_fqn, a.asset_type) for a in review.assets] == [
        (f'{prefix}:{entity_id}', asset_type.value),
    ]


def test_app_entity_fqns_have_their_type_and_others_none():
    assert app_entity_asset_type('product:p-1') == AssetType.DATA_PRODUCT
    assert app_entity_asset_type('contract:c-1') == AssetType.DATA_CONTRACT
    assert app_entity_asset_type('main.sales.orders') is None
    assert app_entity_asset_type('dataset:main.sales.orders') is None


def test_a_review_request_types_products_and_contracts_without_a_workspace():
    manager = DataAssetReviewManager(db=MagicMock(), ws_client=None,
                                     notifications_manager=MagicMock())

    assert manager._determine_asset_type('product:p-1') == AssetType.DATA_PRODUCT
    assert manager._determine_asset_type('contract:c-1') == AssetType.DATA_CONTRACT
    # UC names still need the workspace; without it they stay tables
    assert manager._determine_asset_type('main.sales.orders') == AssetType.TABLE


def test_an_admin_reviews_when_no_steward_other_than_the_requester_is_found(db_session):
    handler = CreateAssetReviewStepHandler(db_session, {'reviewer_role': 'DataSteward'})
    context = _context('data_contract', str(uuid.uuid4()), 'Orders')
    members = {'Data Steward': None, 'Admin': 'admin@example.com'}

    with patch('src.common.workflow_executor._resolve_role_to_users',
               return_value=[('Data Steward', 'role-1')]), \
            patch.object(CreateAssetReviewStepHandler, '_resolve_reviewer_from_role',
                         side_effect=lambda role, exclude=None: members[role]) as from_role:
        reviewer = handler._resolve_reviewer('DataSteward', context, 'rita@example.com')

    assert reviewer == 'admin@example.com'
    assert [c.args[0] for c in from_role.call_args_list] == ['Data Steward', 'Admin']


def test_the_admins_are_asked_once_when_the_role_already_includes_them(db_session):
    handler = CreateAssetReviewStepHandler(db_session, {'reviewer_role': 'DomainOwner'})
    context = _context('data_product', str(uuid.uuid4()), 'AML')
    # A domain without owners: the Data Stewards and the admins (``_owner_approvers``)
    resolved = [('Data Steward', 'role-1'), ('Admin', 'role-2')]

    with patch('src.common.workflow_executor._resolve_role_to_users', return_value=resolved), \
            patch.object(CreateAssetReviewStepHandler, '_resolve_reviewer_from_role',
                         return_value=None) as from_role:
        reviewer = handler._resolve_reviewer('DomainOwner', context, 'rita@example.com')

    assert reviewer is None
    assert [c.args[0] for c in from_role.call_args_list] == ['Data Steward', 'Admin']
