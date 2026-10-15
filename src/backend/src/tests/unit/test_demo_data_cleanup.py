"""clear_references removes what blocks deleting demo rows (#1044).

Rows created after the demo was loaded have ids that aren't in the demo
packs; when they reference demo rows through a foreign key without ON DELETE
action, the demo teardown couldn't delete those rows.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import uuid

from src.db_models.compliance import CompliancePolicyDb, ComplianceResultDb, ComplianceRunDb
from src.db_models.data_products import CustomPropertyDb, DataProductDb
from src.db_models.teams import TeamDb
from src.utils.demo_data_cleanup import clear_references


def _id():
    return str(uuid.uuid4())


def _product(db, owner_team_id=None):
    product = DataProductDb(
        id=_id(), api_version='v1.0.0', kind='DataProduct', status='active',
        name=f'p-{uuid.uuid4().hex[:8]}', version='1.0.0', owner_team_id=owner_team_id,
    )
    db.add(product)
    db.flush()
    return product


def test_required_references_are_deleted(db_session):
    demo, other = _product(db_session), _product(db_session)
    db_session.add_all([
        CustomPropertyDb(id=_id(), product_id=demo.id, property='costCenter', value='CC-1'),
        CustomPropertyDb(id=_id(), product_id=other.id, property='costCenter', value='CC-2'),
    ])
    db_session.flush()

    deleted, nulled = clear_references(db_session, 'data_products', 'id', [demo.id])

    assert deleted == {'data_product_custom_properties': 1}
    assert nulled == {}
    remaining = db_session.query(CustomPropertyDb).all()
    assert [p.product_id for p in remaining if p.product_id in (demo.id, other.id)] == [other.id]


def test_references_of_deleted_rows_are_cleared_first(db_session):
    policy = CompliancePolicyDb(
        id=_id(), name=f'policy-{uuid.uuid4().hex[:8]}',
        rule="MATCH (p:data_product) ASSERT p.status = 'active'",
        category='Governance', severity='low', is_active=True,
    )
    db_session.add(policy)
    db_session.flush()
    run = ComplianceRunDb(id=_id(), policy_id=policy.id, status='succeeded')
    db_session.add(run)
    db_session.flush()
    db_session.add_all([
        ComplianceResultDb(id=_id(), run_id=run.id, object_type='data_product',
                           object_id=_id(), passed=True)
        for _ in range(2)
    ])
    db_session.flush()

    deleted, _ = clear_references(db_session, 'compliance_policies', 'id', [policy.id])

    assert deleted == {'compliance_results': 2, 'compliance_runs': 1}
    assert db_session.query(ComplianceRunDb).filter_by(policy_id=policy.id).count() == 0


def test_optional_references_are_detached(db_session):
    team = TeamDb(id=_id(), name=f'demo-team-{uuid.uuid4().hex[:8]}', created_by='system@demo',
                  updated_by='system@demo')
    db_session.add(team)
    db_session.flush()
    users_product = _product(db_session, owner_team_id=team.id)

    deleted, nulled = clear_references(db_session, 'teams', 'id', [team.id])

    assert nulled.get('data_products') == 1
    assert 'data_products' not in deleted
    db_session.refresh(users_product)
    assert users_product.owner_team_id is None


def test_nothing_to_clear(db_session):
    assert clear_references(db_session, 'data_products', 'id', []) == ({}, {})
    assert clear_references(db_session, 'data_products', 'id', [_id()]) == ({}, {})


def test_self_references_within_the_deleted_rows_are_left_alone(db_session):
    from src.db_models.data_domains import DataDomain

    parent = DataDomain(id=_id(), name=f'd-{uuid.uuid4().hex[:8]}', created_by='system@demo')
    db_session.add(parent)
    db_session.flush()
    demo_child = DataDomain(id=_id(), name=f'd-{uuid.uuid4().hex[:8]}', parent_id=parent.id,
                            created_by='system@demo')
    users_child = DataDomain(id=_id(), name=f'd-{uuid.uuid4().hex[:8]}', parent_id=parent.id,
                             created_by='user@example.com')
    db_session.add_all([demo_child, users_child])
    db_session.flush()

    _, nulled = clear_references(db_session, 'data_domains', 'id', [parent.id, demo_child.id])

    assert nulled == {'data_domains': 1}
    db_session.refresh(users_child)
    db_session.refresh(demo_child)
    assert users_child.parent_id is None
    assert demo_child.parent_id == parent.id
