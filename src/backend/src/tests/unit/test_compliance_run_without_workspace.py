"""A compliance run doesn't need a workspace client for app entities (#1043).

``run_policy_inline`` created the workspace client before evaluating
anything, so when it couldn't be created (e.g. expired credentials) every
run failed with no results, even for rules on data products. Rules that cover
Unity Catalog types, ``Object`` included, still fail: passing them after
evaluating only the app entities would report green for objects never checked.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid
from unittest.mock import patch

import pytest

from src.controller.compliance_manager import ComplianceManager
from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb
from src.db_models.data_products import DataProductDb

NO_CLIENT = 'src.common.workspace_client.get_workspace_client'


@pytest.fixture
def product(db_session):
    product = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
        status='active', name=f'p-{uuid.uuid4().hex[:8]}', version='1.0.0',
    )
    db_session.add(product)
    db_session.flush()
    return product


def _run(db, rule, client=None):
    policy = CompliancePolicyDb(
        id=str(uuid.uuid4()), name=f'policy-{uuid.uuid4().hex[:8]}', rule=rule,
        category='Governance', severity='low', is_active=True,
    )
    db.add(policy)
    db.flush()
    unavailable = (
        {'return_value': None} if client == 'none'
        else {'side_effect': RuntimeError('cannot get access token')}
    )
    with patch(NO_CLIENT, **unavailable):
        run = ComplianceManager().run_policy_inline(db, policy=policy)
    results = db.query(ComplianceResultDb).filter(ComplianceResultDb.run_id == run.id).all()
    return run, {r.object_id: r.passed for r in results}


def test_app_entity_rules_run_without_a_workspace_client(db_session, product):
    run, results = _run(db_session, "MATCH (p:data_product) ASSERT p.status = 'active'")

    assert run.status == 'succeeded'
    assert results[product.id] is True


def test_object_rules_fail_without_a_workspace_client(db_session, product):
    # Object covers the Unity Catalog types too: evaluating only the data
    # products and recording a success would hide that tables went unchecked.
    run, results = _run(db_session, "MATCH (o:Object) ASSERT o.name != ''")

    assert run.status == 'failed'
    assert 'cannot get access token' in run.error_message
    assert results == {}


def test_unity_catalog_rules_still_fail_without_a_workspace_client(db_session, product):
    run, results = _run(db_session, "MATCH (t:table) ASSERT t.owner != ''")

    assert run.status == 'failed'
    assert 'cannot get access token' in run.error_message
    assert results == {}


def test_a_client_factory_returning_none_counts_as_unavailable(db_session, product):
    run, results = _run(db_session, "MATCH (o:Object) ASSERT o.name != ''", client='none')

    assert run.status == 'failed'
    assert 'workspace client unavailable' in run.error_message
    assert results == {}


def test_app_entity_rules_run_when_the_factory_returns_none(db_session, product):
    run, results = _run(db_session, "MATCH (p:data_product) ASSERT p.status = 'active'", client='none')

    assert run.status == 'succeeded'
    assert results[product.id] is True


@pytest.mark.parametrize('client', ['raises', 'none'])
def test_the_unavailable_client_error_carries_a_code_for_the_ui(client):
    # The run stores the code (error_code / error_params) where the backend
    # supports it, so the UI shows the message in the user's language.
    policy = CompliancePolicyDb(id='p', name='p', rule="MATCH (o:Object) ASSERT o.name != ''")
    unavailable = (
        {'return_value': None} if client == 'none'
        else {'side_effect': RuntimeError('cannot get access token')}
    )
    with patch(NO_CLIENT, **unavailable), pytest.raises(Exception) as e:
        ComplianceManager()._workspace_client_for(['table'], policy)

    assert e.value.error_code == 'workspace_client_unavailable'
    assert e.value.error_params['detail']
