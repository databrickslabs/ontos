"""The asset routes answer a lifecycle refusal with a 400 and its code (#1213)."""
import pytest

from src.controller.lifecycle_service import lifecycle_service
from src.db_models.assets import AssetDb, AssetTypeDb


def _type(db, name='Table'):
    found = db.query(AssetTypeDb).filter(AssetTypeDb.name == name).first()
    if found is None:
        found = AssetTypeDb(name=name, category='data')
        db.add(found)
        db.flush()
    return found


def _code(response):
    body = response.json()
    detail = body.get('detail')
    return body.get('code') or (detail.get('code') if isinstance(detail, dict) else None)


def _stage(key, category, order, initial=False):
    return {'key': key, 'label': key.title(), 'category': category, 'color': None,
            'order': order, 'is_initial': initial}


@pytest.fixture
def one_way_asset(db_session):
    """An asset in a group that goes ``draft -> live -> gone`` only."""
    group = lifecycle_service.save_group(db_session, {
        'name': 'One way', 'description': None, 'entity_type': 'asset',
        'is_default_for_type': False,
        'stages': [_stage('draft', 'draft', 0, True), _stage('live', 'active', 1),
                   _stage('gone', 'retired', 2)],
        'transitions': [{'from_key': 'draft', 'to_key': 'live'},
                        {'from_key': 'live', 'to_key': 'gone'}],
    }, 'admin')
    row = AssetDb(name='orders', asset_type_id=_type(db_session).id, platform='databricks',
                  location='main.sales.orders', status='draft',
                  lifecycle_stage_group_id=group.id)
    db_session.add(row)
    db_session.commit()
    return row


def test_a_refused_status_move_is_a_400_with_its_code(client, one_way_asset):
    response = client.put(f'/api/assets/{one_way_asset.id}', json={'status': 'gone'})

    assert response.status_code == 400, response.text
    assert _code(response) == 'invalid_status_transition'


def test_an_unknown_status_on_create_is_a_400_with_its_code(client, db_session):
    response = client.post('/api/assets', json={
        'name': 'orders', 'asset_type_id': str(_type(db_session).id),
        'platform': 'databricks', 'location': 'main.sales.orders', 'status': 'in_use'})

    assert response.status_code == 400, response.text
    assert _code(response) == 'invalid_status'
