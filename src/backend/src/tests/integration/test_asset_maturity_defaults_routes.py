"""The optional default maturity ladder for table and view assets (#1316)."""
import uuid

import pytest
from databricks.sdk.service.catalog import ColumnInfo, TableInfo

from src.common import workflow_triggers
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.compliance import CompliancePolicyDb
from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.maturity import MaturityLevelDb

FQN = 'main.sales.orders'
LADDER = ['Prerequisite', '1 star', '2 stars', '3 stars']
DESCRIPTION = 'Every order placed in the shop, one row per order, loaded each night.'


@pytest.fixture(autouse=True)
def no_triggers(monkeypatch):
    monkeypatch.setattr(workflow_triggers.TriggerRegistry, 'on_maturity_change',
                        lambda self, **kwargs: [])


def _asset_levels(db):
    return (db.query(MaturityLevelDb).filter_by(entity_type='Asset')
            .order_by(MaturityLevelDb.level_order).all())


def _owned_asset(db, description=DESCRIPTION):
    asset_type = db.query(AssetTypeDb).filter_by(name='Table').first()
    if asset_type is None:
        asset_type = AssetTypeDb(name='Table')
        db.add(asset_type)
        db.flush()
    asset = AssetDb(name=f'orders-{uuid.uuid4().hex[:6]}', asset_type_id=asset_type.id,
                    platform='databricks', location=FQN, status='active',
                    description=description)
    role = BusinessRoleDb(id=uuid.uuid4(), name=f'Owner {uuid.uuid4().hex[:6]}')
    domain = DataDomain(id=str(uuid.uuid4()), name=f'Sales {uuid.uuid4().hex[:6]}',
                        created_by='admin@example.com')
    db.add_all([asset, role, domain])
    db.flush()
    db.add_all([
        BusinessOwnerDb(object_type='asset', object_id=str(asset.id),
                        user_email='owner@example.com', role_id=role.id, is_active=True),
        EntityDomainAssociationDb(domain_id=domain.id, entity_type='asset',
                                  entity_id=str(asset.id), is_primary=True),
    ])
    db.flush()
    return asset


class TestAssetDefaultLadder:
    def test_loads_the_ladder_once(self, client, db_session):
        response = client.post('/api/maturity-levels/asset-defaults')

        assert response.status_code == 200, response.text
        body = response.json()
        assert body['created'] == 4
        assert [lv['name'] for lv in body['levels']] == LADDER
        assert {lv['entity_type'] for lv in body['levels']} == {'Asset'}
        assert [lv['level_order'] for lv in body['levels']] == [1, 2, 3, 4]
        assert all(lv['gates'] for lv in body['levels'])
        policies = db_session.query(CompliancePolicyDb).filter(
            CompliancePolicyDb.slug.like('maturity-asset-%')).all()
        assert len(policies) == sum(len(lv['gates']) for lv in body['levels'])
        assert {p.category for p in policies} == {'Maturity'}

        again = client.post('/api/maturity-levels/asset-defaults')

        assert again.status_code == 200, again.text
        assert again.json()['created'] == 0
        assert [lv.name for lv in _asset_levels(db_session)] == LADDER

    def test_reloading_after_deleting_the_levels_reuses_the_gate_policies(
            self, client, db_session):
        client.post('/api/maturity-levels/asset-defaults')
        policy_count = db_session.query(CompliancePolicyDb).count()
        for level in _asset_levels(db_session):
            assert client.delete(f'/api/maturity-levels/{level.id}').status_code == 204

        response = client.post('/api/maturity-levels/asset-defaults')

        assert response.status_code == 200, response.text
        assert response.json()['created'] == 4
        assert db_session.query(CompliancePolicyDb).count() == policy_count

    def test_does_not_touch_other_ladders(self, client, db_session):
        db_session.add(MaturityLevelDb(level_order=1, name='Accessible', entity_type='all'))
        db_session.flush()

        client.post('/api/maturity-levels/asset-defaults')

        assert db_session.query(MaturityLevelDb).filter_by(entity_type='all').count() == 1

    def test_a_documented_table_reaches_the_level_its_gates_allow(
            self, client, db_session, mock_workspace_client):
        client.post('/api/maturity-levels/asset-defaults')
        asset = _owned_asset(db_session)
        # Half of the columns documented: "1 star", not "2 stars"
        mock_workspace_client.tables.get.return_value = TableInfo(full_name=FQN, columns=[
            ColumnInfo(name='id', comment='Order id', type_text='bigint'),
            ColumnInfo(name='amount', comment=None, type_text='decimal'),
        ])

        report = client.post(f'/api/assets/{asset.id}/maturity/evaluate').json()

        assert report['achieved_level_name'] == '1 star'
        assert report['achieved_level_order'] == 2
        failed = [g['policy_name'] for g in report['levels'][2]['gates'] if not g['passed']]
        assert '[Asset maturity L3] Every column has a comment' in failed

    def test_a_short_description_stays_at_the_prerequisite(
            self, client, db_session, mock_workspace_client):
        client.post('/api/maturity-levels/asset-defaults')
        asset = _owned_asset(db_session, description='Orders')
        mock_workspace_client.tables.get.return_value = TableInfo(full_name=FQN, columns=[
            ColumnInfo(name='id', comment='Order id', type_text='bigint'),
        ])

        report = client.get(f'/api/assets/{asset.id}/maturity').json()

        assert report['achieved_level_name'] == 'Prerequisite'
