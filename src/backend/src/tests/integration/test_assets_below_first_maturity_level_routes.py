"""GET /api/assets?below_first_maturity_level=true: assets whose latest evaluation has no level."""
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from src.controller.assets_manager import AssetsManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.business_owners import BusinessOwnerDb
from src.db_models.business_roles import BusinessRoleDb
from src.db_models.maturity import MaturitySnapshotDb
from src.repositories.maturity_repository import maturity_repo
from src.routes import assets_routes

ME = 'test@example.com'  # the client fixture's mock_test_user
NOW = datetime.now(timezone.utc)


@pytest.fixture
def below(db_session):
    asset_type = AssetTypeDb(name=f'Table-{uuid.uuid4().hex[:6]}', category='data')
    role = BusinessRoleDb(name=f'Owner-{uuid.uuid4().hex[:6]}')
    db_session.add_all([asset_type, role])
    db_session.flush()
    rows = {name: AssetDb(name=name, asset_type_id=asset_type.id, platform='databricks',
                          status='active')
            for name in ['mine_below', 'mine_leveled', 'mine_never', 'theirs_below']}
    db_session.add_all(rows.values())
    db_session.flush()
    for name, row in rows.items():
        db_session.add(BusinessOwnerDb(
            object_type='asset', object_id=str(row.id), role_id=role.id,
            user_email='other@example.com' if name.startswith('theirs') else ME,
        ))
    maturity_repo.create(db_session, name='Prerequisite', level_order=1, entity_type='Asset')
    for name, order in [('mine_below', None), ('mine_leveled', 1), ('theirs_below', None)]:
        db_session.add(MaturitySnapshotDb(
            entity_type='Asset', entity_id=str(rows[name].id), achieved_level_order=order,
            total_levels=1, evaluated_at=NOW - timedelta(minutes=1),
        ))
    db_session.flush()
    return rows


def _names(body):
    return {item['name'] for item in body['items']}


def test_owner_gets_their_assets_below_the_first_level(client, below):
    res = client.get('/api/assets', params={
        'owned_by_me': 'true', 'below_first_maturity_level': 'true',
    })
    assert res.status_code == 200
    assert _names(res.json()) == {'mine_below'}
    assert res.json()['total'] == 1


def test_without_owned_by_me_it_lists_every_asset_below(client, below):
    res = client.get('/api/assets', params={'below_first_maturity_level': 'true', 'limit': 500})
    names = _names(res.json())
    assert {'mine_below', 'theirs_below'} <= names
    assert not names & {'mine_leveled', 'mine_never'}


def test_without_the_flag_nothing_changes(client, below):
    res = client.get('/api/assets', params={'owned_by_me': 'true'})
    assert _names(res.json()) == {'mine_below', 'mine_leveled', 'mine_never'}


def test_scoped_user_is_narrowed_never_widened(client, below, monkeypatch):
    """Below READ_WRITE (#347) the DP scoping still applies; the filter intersects it."""
    monkeypatch.setattr(assets_routes, '_user_has_assets_feature', lambda *a, **k: False)
    monkeypatch.setattr(assets_routes, '_get_data_products_manager', lambda request: object())
    allowed = [below['mine_leveled'].id, below['theirs_below'].id]
    monkeypatch.setattr(AssetsManager, 'resolve_accessible_asset_ids',
                        lambda self, db, **kw: allowed)
    res = client.get('/api/assets', params={'below_first_maturity_level': 'true'})
    assert _names(res.json()) == {'theirs_below'}
