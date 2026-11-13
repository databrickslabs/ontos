"""Status gates follow the Stage Category, not the seeded stage keys (#1213).

Publishing, publication requests, certification, subscriptions, versioning
and the asset search index read the category of the entity's stage, so a
custom group whose active stage is ``live`` (or whose retired stage is
``sunset``) behaves like the default one. A group can't have a move from a
stage to itself, and the entity lifecycle route reads contracts by the
contracts' own read rule.

The test user is an admin (``test_admins``).
"""
import uuid

import pytest

from src.controller.lifecycle_service import lifecycle_service
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb


@pytest.fixture(autouse=True)
def fresh_cache():
    lifecycle_service.invalidate()
    yield
    lifecycle_service.invalidate()


def _stage(key, category, order, initial=False):
    return {'key': key, 'label': key.title(), 'category': category, 'order': order,
            'is_initial': initial}


def _live_group(client, entity_type):
    """``intake -> live -> sunset``: no seeded key but the first."""
    res = client.post('/api/lifecycle-stage-groups', json={
        'name': f'Live {entity_type}', 'entity_type': entity_type,
        'stages': [_stage('intake', 'draft', 0, True), _stage('live', 'active', 1),
                   _stage('sunset', 'retired', 2)],
        'transitions': [{'from_key': 'intake', 'to_key': 'live'},
                        {'from_key': 'live', 'to_key': 'sunset'}],
    })
    assert res.status_code == 201, res.text
    return res.json()['id']


def _product(db, status, group_id=None):
    pid = str(uuid.uuid4())
    db.add(DataProductDb(id=pid, name=f'P {pid[:8]}', version='1.0.0', status=status,
                         api_version='v1.0.0', kind='DataProduct',
                         lifecycle_stage_group_id=group_id))
    db.commit()
    return pid


def _contract(db, status, group_id=None, **extra):
    cid = str(uuid.uuid4())
    db.add(DataContractDb(id=cid, name=f'C {cid[:8]}', version='1.0.0', status=status,
                          lifecycle_stage_group_id=group_id, **extra))
    db.commit()
    return cid


def test_a_product_in_a_custom_active_stage_can_request_publication(client, db_session):
    pid = _product(db_session, 'live', _live_group(client, 'data_product'))
    res = client.post(f'/api/data-products/{pid}/request-publish', json={'scope': 'organization'})
    assert res.status_code == 202, res.text


def test_a_product_in_a_custom_draft_stage_cant_request_publication(client, db_session):
    pid = _product(db_session, 'intake', _live_group(client, 'data_product'))
    res = client.post(f'/api/data-products/{pid}/request-publish', json={'scope': 'organization'})
    assert res.status_code == 409


def test_an_active_contract_can_request_publication(client, db_session):
    # Default lifecycle: approved and active are both publishable
    for status in ('approved', 'active'):
        cid = _contract(db_session, status)
        res = client.post(f'/api/data-contracts/{cid}/request-publish', json={})
        assert res.status_code == 200, (status, res.text)
    cid = _contract(db_session, 'proposed')
    assert client.post(f'/api/data-contracts/{cid}/request-publish', json={}).status_code == 409


def test_a_contract_in_a_custom_active_stage_is_published(client, db_session):
    cid = _contract(db_session, 'live', _live_group(client, 'data_contract'))
    res = client.post(f'/api/data-contracts/{cid}/request-publish', json={})
    assert res.status_code == 200, res.text
    assert lifecycle_service.contract_publishable(db_session, db_session.get(DataContractDb, cid))


def test_a_contract_in_a_custom_active_stage_can_be_certified(client, db_session):
    from src.db_models.certification_levels import CertificationLevelDb

    level = CertificationLevelDb(id=uuid.uuid4(), level_order=91, name="Gold test")
    db_session.add(level)
    db_session.commit()
    cid = _contract(db_session, 'live', _live_group(client, 'data_contract'))
    res = client.post(f'/api/data-contracts/{cid}/certify', json={"certification_level": 91})
    assert res.status_code != 409, res.text


def test_a_product_in_a_custom_active_stage_is_subscribable(client, db_session):
    pid = _product(db_session, 'live', _live_group(client, 'data_product'))
    res = client.post(f'/api/data-products/{pid}/subscribe', json={})
    assert res.status_code == 200, res.text


def test_a_move_from_a_stage_to_itself_is_refused(client):
    res = client.post('/api/lifecycle-stage-groups', json={
        'name': 'Self', 'entity_type': 'data_product',
        'stages': [_stage('draft', 'draft', 0, True), _stage('active', 'active', 1)],
        'transitions': [{'from_key': 'draft', 'to_key': 'active'},
                        {'from_key': 'active', 'to_key': 'active'}],
    })
    assert res.status_code == 400
    assert res.json()['detail']['code'] == 'lifecycle_transition_self'
    assert res.json()['detail']['params'] == {'key': 'active'}


def test_a_custom_retired_stage_leaves_the_asset_search_index(client, db_session):
    from src.controller.assets_manager import AssetsManager
    from src.db_models.assets import AssetDb, AssetTypeDb

    group_id = _live_group(client, 'asset')
    asset_type = AssetTypeDb(id=uuid.uuid4(), name=f'Type {uuid.uuid4().hex[:6]}')
    db_session.add(asset_type)
    asset = AssetDb(id=uuid.uuid4(), name='orders', asset_type_id=asset_type.id,
                    status='sunset', lifecycle_stage_group_id=group_id)
    db_session.add(asset)
    db_session.commit()
    db_session.refresh(asset)
    assert AssetsManager()._build_search_index_item(asset) is None


class TestContractReaders:
    """Read/Write on data contracts, not Admin: the contracts' read rule applies."""

    @pytest.fixture
    def not_admin(self, monkeypatch):
        from src.common.features import FeatureAccessLevel
        from src.routes import lifecycle_stage_groups_routes as routes

        async def has_level(feature_id, level, user, request):
            return level != FeatureAccessLevel.ADMIN

        async def not_feature_admin(**kwargs):
            return False

        monkeypatch.setattr(routes, 'has_feature_permission', has_level)
        monkeypatch.setattr('src.common.authorization.is_user_feature_admin',
                            not_feature_admin)

    def test_a_version_of_the_callers_contract_family_reads(
        self, client, db_session, mock_test_user, not_admin,
    ):
        # The caller owns v1; v2 (in review, no owner of its own) is in the same family
        v1 = _contract(db_session, 'proposed', draft_owner_id=mock_test_user.email)
        v2 = _contract(db_session, 'proposed', version_family_id=v1)
        res = client.get(f'/api/lifecycle/data_contract/{v2}')
        assert res.status_code == 200, res.text
        assert res.json()['stage']['category'] == 'review'

    def test_someone_elses_personal_draft_reads_as_missing(self, client, db_session, not_admin):
        cid = _contract(db_session, 'draft', draft_owner_id='someone@example.com')
        assert client.get(f'/api/lifecycle/data_contract/{cid}').status_code == 404
