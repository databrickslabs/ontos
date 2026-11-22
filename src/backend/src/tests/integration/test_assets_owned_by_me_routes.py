"""GET /api/assets?owned_by_me=true: the caller's owned assets, paginated, never widened."""
import uuid

import pytest

from src.controller.assets_manager import AssetsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.routes import assets_routes

ME = 'test@example.com'  # the client fixture's mock_test_user


@pytest.fixture
def owned(db_session):
    asset_type = AssetTypeDb(name=f'Table-{uuid.uuid4().hex[:6]}', category='data')
    role = BusinessRoleDb(name=f'Owner-{uuid.uuid4().hex[:6]}')
    db_session.add_all([asset_type, role])
    db_session.flush()
    rows = {}
    for name, platform in [('mine_a', 'databricks'), ('mine_b', 'powerbi'),
                           ('mine_c', 'databricks'), ('theirs', 'databricks'),
                           ('theirs_bi', 'powerbi')]:
        rows[name] = AssetDb(name=name, asset_type_id=asset_type.id, platform=platform,
                             status='active', description=f'{name} text')
    db_session.add_all(rows.values())
    db_session.flush()
    for name, email in [('mine_a', ME), ('mine_b', ME), ('mine_c', ME),
                        ('theirs', 'other@example.com'), ('theirs_bi', 'other@example.com')]:
        db_session.add(BusinessOwnerDb(object_type='asset', object_id=str(rows[name].id),
                                       user_email=email, role_id=role.id))
    db_session.flush()
    return rows


def _names(body):
    return {item['name'] for item in body['items']}


def test_owner_sees_only_their_assets(client, owned):
    res = client.get('/api/assets', params={'owned_by_me': 'true'})
    assert res.status_code == 200
    body = res.json()
    assert _names(body) == {'mine_a', 'mine_b', 'mine_c'}
    assert body['total'] == 3
    assert {item['description'] for item in body['items']} == {
        'mine_a text', 'mine_b text', 'mine_c text'}


def test_pages_keep_the_full_total(client, owned):
    first = client.get('/api/assets', params={'owned_by_me': 'true', 'skip': 0, 'limit': 2})
    rest = client.get('/api/assets', params={'owned_by_me': 'true', 'skip': 2, 'limit': 2})
    assert first.json()['total'] == 3 and rest.json()['total'] == 3
    assert len(first.json()['items']) == 2 and len(rest.json()['items']) == 1
    assert _names(first.json()) | _names(rest.json()) == {'mine_a', 'mine_b', 'mine_c'}


def test_combines_with_an_existing_filter(client, owned):
    res = client.get('/api/assets', params={'owned_by_me': 'true', 'platform': 'powerbi'})
    assert _names(res.json()) == {'mine_b'}
    assert res.json()['total'] == 1


def test_without_the_flag_nothing_changes(client, owned):
    res = client.get('/api/assets', params={'limit': 500})
    assert {'mine_a', 'theirs'} <= _names(res.json())


def test_non_owner_gets_an_empty_page(client, owned, db_session):
    db_session.query(BusinessOwnerDb).filter(BusinessOwnerDb.user_email == ME).delete()
    db_session.flush()
    res = client.get('/api/assets', params={'owned_by_me': 'true'})
    assert res.status_code == 200
    assert res.json()['items'] == [] and res.json()['total'] == 0


def test_scoped_user_is_narrowed_never_widened(client, owned, monkeypatch):
    """Below READ_WRITE (#347) the DP scoping still applies; the filter intersects it."""
    monkeypatch.setattr(assets_routes, '_user_has_assets_feature', lambda *a, **k: False)
    monkeypatch.setattr(assets_routes, '_get_data_products_manager', lambda request: object())
    allowed = [owned['mine_a'].id, owned['theirs'].id]
    monkeypatch.setattr(AssetsManager, 'resolve_accessible_asset_ids',
                        lambda self, db, **kw: allowed)
    res = client.get('/api/assets', params={'owned_by_me': 'true'})
    assert _names(res.json()) == {'mine_a'}
    assert res.json()['total'] == 1
    # Without the flag the scoped user still sees exactly what #347 allows.
    res = client.get('/api/assets')
    assert _names(res.json()) == {'mine_a', 'theirs'}
