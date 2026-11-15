"""Notes, links, documents and cost items of an asset follow the asset's access rules (#1342).

Every route that reads or changes them is called as the default roles (Admin,
Data Steward, Data Consumer) and as a custom role with only ``assets``
READ_WRITE. The other entity types keep the ``data-domains`` check.

A refused request rolls back the test's transaction (the request's session
rolls back on any error, roles included), so each test makes at most one
refused call, as its last call.
"""
import time
import uuid
from io import BytesIO
from types import SimpleNamespace

import pytest

from src.app import app
from src.common import workspace_client
from src.common.features import FeatureAccessLevel
from src.controller.assets_manager import AssetsManager
from src.controller.costs_manager import CostsManager
from src.controller.metadata_manager import MetadataManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.metadata import DocumentMetadataDb, RichTextMetadataDb
from src.models.costs import CostItem, CostItemCreate
from src.models.metadata import (
    LinkCreate, MetadataAttachmentCreate, RichText, RichTextCreate,
)
from src.models.settings import AppRoleCreate

ASSETS_ONLY = 'Assets only (#1342)'
OTHER_TYPES = ['data_domain', 'data_product', 'data_contract']
MONTH = '2026-01'


@pytest.fixture
def asset(db_session):
    asset_type = AssetTypeDb(name=f'Type {uuid.uuid4().hex[:8]}', category='data')
    db_session.add(asset_type)
    db_session.flush()
    row = AssetDb(name='orders', asset_type_id=asset_type.id, platform='databricks')
    db_session.add(row)
    db_session.flush()
    return row


@pytest.fixture
def ws(monkeypatch, mock_workspace_client):
    """Workspace client for uploads and downloads (get_workspace_client's mock hook)."""
    monkeypatch.setenv('MOCK_WORKSPACE_CLIENT', 'true')
    monkeypatch.setitem(
        workspace_client._CLIENT_CACHE, 'mock_ws', (mock_workspace_client, 'mock', time.time()),
    )
    monkeypatch.setattr(
        MetadataManager, 'ensure_volume_path',
        lambda self, ws, settings, base_dir: '/Volumes/c/s/v',
    )
    mock_workspace_client.files.download.side_effect = None
    mock_workspace_client.files.download.return_value = SimpleNamespace(
        contents=BytesIO(b'file bytes'),
    )
    return mock_workspace_client


def _seed(db, entity_type: str, entity_id: str) -> dict:
    """One note, link, document and cost item on an entity."""
    metadata = MetadataManager()
    note = metadata.create_rich_text(db, data=RichTextCreate(
        entity_type=entity_type, entity_id=entity_id, title='Note', content_markdown='Body',
    ), user_email='seed@example.com')
    link = metadata.create_link(db, data=LinkCreate(
        entity_type=entity_type, entity_id=entity_id, title='Link', url='https://example.com',
    ), user_email='seed@example.com')
    doc = DocumentMetadataDb(
        entity_type=entity_type, entity_id=entity_id, title='Doc', original_filename='a.txt',
        content_type='text/plain', size_bytes=4, storage_path='/Volumes/c/s/v/a.txt',
    )
    db.add(doc)
    db.commit()
    cost = CostsManager().create(db, data=CostItemCreate(
        entity_type=entity_type, entity_id=entity_id, cost_center='OTHER', amount_cents=100,
        start_month='2026-01-01',
    ), user_email='seed@example.com')
    return {
        'note': str(note.id), 'link': str(link.id), 'doc': str(doc.id), 'cost': str(cost.id),
        # Attached by the attach route, then detached by the detach route.
        'attached': str(uuid.uuid4()),
    }


def _requests(entity_type: str, entity_id: str, ids: dict):
    """(name, kind, method, url, request kwargs) for every route of #1342, in a runnable order."""
    q = {'entity_id': entity_id}
    base = f'/api/entities/{entity_type}'
    body = {'entity_type': entity_type, 'entity_id': entity_id}
    return [
        ('list notes', 'read', 'GET', f'{base}/rich-texts', {'params': q}),
        ('list links', 'read', 'GET', f'{base}/links', {'params': q}),
        ('list documents', 'read', 'GET', f'{base}/documents', {'params': q}),
        ('list attachments', 'read', 'GET', f'{base}/attachments', {'params': q}),
        ('merged metadata', 'read', 'GET', f'{base}/metadata/merged', {'params': q}),
        ('document', 'read', 'GET', f"/api/documents/{ids['doc']}", {}),
        ('document content', 'read', 'GET', f"/api/documents/{ids['doc']}/content", {}),
        ('list costs', 'read', 'GET', f'{base}/{entity_id}/cost-items', {}),
        ('cost summary', 'read', 'GET', f'{base}/{entity_id}/cost-items/summary',
         {'params': {'month': MONTH}}),
        ('create note', 'write', 'POST', f'{base}/rich-texts',
         {'params': q, 'json': {**body, 'title': 'N', 'content_markdown': 'B'}}),
        ('update note', 'write', 'PUT', f"/api/rich-texts/{ids['note']}",
         {'json': {'title': 'N2'}}),
        ('create link', 'write', 'POST', f'{base}/links',
         {'params': q, 'json': {**body, 'title': 'L', 'url': 'https://example.org'}}),
        ('update link', 'write', 'PUT', f"/api/links/{ids['link']}", {'json': {'title': 'L2'}}),
        ('upload document', 'write', 'POST', f'{base}/documents',
         {'params': q, 'data': {'title': 'D'},
          'files': {'file': ('d.txt', b'data', 'text/plain')}}),
        ('attach', 'write', 'POST', f'{base}/attachments',
         {'params': q, 'json': {'asset_type': 'rich_text', 'asset_id': ids['attached']}}),
        ('detach', 'write', 'DELETE', f"{base}/attachments/rich_text/{ids['attached']}",
         {'params': q}),
        ('update cost', 'write', 'PUT', f"/api/cost-items/{ids['cost']}",
         {'json': {'title': 'C2'}}),
        ('delete note', 'write', 'DELETE', f"/api/rich-texts/{ids['note']}", {}),
        ('delete link', 'write', 'DELETE', f"/api/links/{ids['link']}", {}),
        ('delete document', 'write', 'DELETE', f"/api/documents/{ids['doc']}", {}),
        ('delete cost', 'write', 'DELETE', f"/api/cost-items/{ids['cost']}", {}),
        # Last: its audit entry fails to write (quarantined in conftest, _AUDIT_UUID), and
        # that rolls the test's transaction back.
        ('create cost', 'write', 'POST', f'{base}/{entity_id}/cost-items',
         {'json': {**body, 'cost_center': 'OTHER', 'amount_cents': 5,
                   'start_month': '2026-02-01'}}),
    ]


_PLACEHOLDER_IDS = dict.fromkeys(('note', 'link', 'doc', 'cost', 'attached'), 'x')
ROUTES = [(r[0], r[1]) for r in _requests('asset', 'x', _PLACEHOLDER_IDS)]
READ_ROUTES = [name for name, kind in ROUTES if kind == 'read']
WRITE_ROUTES = [name for name, kind in ROUTES if kind == 'write']
# Routes with {entity_type} in the path; the others address a row by its id.
ENTITY_ROUTES = [
    r[0] for r in _requests('asset', 'x', _PLACEHOLDER_IDS) if r[3].startswith('/api/entities/')
]
ROW_ROUTES = [name for name, _kind in ROUTES if name not in ENTITY_ROUTES]


def _request(entity_type, entity_id, ids, route):
    return next(r for r in _requests(entity_type, entity_id, ids) if r[0] == route)


@pytest.fixture
def act_as(client, mock_test_user):
    """Apply a role to the test user, as the role switcher does."""
    settings_manager = app.state.settings_manager

    def _act_as(role_name: str):
        if role_name == ASSETS_ONLY:
            role = settings_manager.get_app_role_by_name(ASSETS_ONLY) or \
                settings_manager.create_app_role(AppRoleCreate(
                    name=ASSETS_ONLY,
                    feature_permissions={'assets': FeatureAccessLevel.READ_WRITE},
                ))
        else:
            role = settings_manager.get_app_role_by_name(role_name)
        assert role is not None, role_name
        settings_manager.set_applied_role_override_for_user(
            mock_test_user.email, str(role.id), caller_is_admin=True,
        )
        return role

    yield _act_as
    settings_manager.set_applied_role_override_for_user(mock_test_user.email, None)


def _call(client, method, url, kwargs):
    return client.request(method, url, **kwargs)


def _code(response):
    detail = response.json().get('detail')
    return detail.get('code') if isinstance(detail, dict) else None


def test_the_default_roles_are_what_this_file_assumes(client, act_as):
    """Only Admin has ``assets``; the Steward writes and the Consumer reads ``data-domains``."""
    steward = act_as('Data Steward').feature_permissions
    consumer = act_as('Data Consumer').feature_permissions
    assert steward.get('data-domains') == FeatureAccessLevel.READ_WRITE
    assert consumer.get('data-domains') == FeatureAccessLevel.READ_ONLY
    assert steward.get('assets', FeatureAccessLevel.NONE) == FeatureAccessLevel.NONE
    assert consumer.get('assets', FeatureAccessLevel.NONE) == FeatureAccessLevel.NONE


# --- Assets ---------------------------------------------------------------------

@pytest.mark.parametrize('role', ['Admin', ASSETS_ONLY])
def test_assets_read_write_reads_and_writes_everything(client, db_session, asset, ws, act_as, role):
    """Attaching also needs data-domains READ: see the attachments section."""
    ids = _seed(db_session, 'asset', str(asset.id))
    act_as(role)

    for name, _kind, method, url, kwargs in _requests('asset', str(asset.id), ids):
        if role == ASSETS_ONLY and name in ('attach', 'detach'):
            continue
        response = _call(client, method, url, kwargs)
        assert response.status_code < 300, (name, response.status_code, response.text)


def test_a_role_resolved_from_the_users_group_reads_and_writes(
        client, db_session, asset, ws, mock_test_user):
    """The other tests apply a role as the role switcher does; here it comes from a group."""
    app.state.settings_manager.create_app_role(AppRoleCreate(
        name='Assets by group (#1342)', assigned_groups=['asset-editors'],
        feature_permissions={'assets': FeatureAccessLevel.READ_WRITE},
    ))
    mock_test_user.groups = ['asset-editors']
    ids = _seed(db_session, 'asset', str(asset.id))

    for name, _kind, method, url, kwargs in _requests('asset', str(asset.id), ids):
        if name in ('attach', 'detach'):
            continue
        response = _call(client, method, url, kwargs)
        assert response.status_code < 300, (name, response.status_code, response.text)


@pytest.mark.parametrize('role', ['Data Steward', 'Data Consumer'])
@pytest.mark.parametrize('route', ENTITY_ROUTES)
def test_without_assets_every_entity_route_is_403(
        client, db_session, asset, ws, act_as, role, route):
    """Neither role has ``assets``, and the asset is linked to no product."""
    ids = _seed(db_session, 'asset', str(asset.id))
    act_as(role)
    _name, kind, method, url, kwargs = _request('asset', str(asset.id), ids, route)

    response = _call(client, method, url, kwargs)

    assert response.status_code == 403, response.text
    assert _code(response) == ('asset_read_denied' if kind == 'read' else 'asset_write_denied')
    ws.files.upload.assert_not_called()


def test_the_checks_use_the_startup_wired_assets_manager(
        client, db_session, asset, act_as, monkeypatch):
    """Not the module-level singleton: the checks see the manager the app wired."""
    calls = []

    class Wired(AssetsManager):
        def asset_exists(self, db, asset_id):
            calls.append(asset_id)
            return super().asset_exists(db, asset_id)

    monkeypatch.setattr(app.state, 'assets_manager', Wired())
    act_as('Admin')

    response = client.get('/api/entities/asset/rich-texts', params={'entity_id': str(asset.id)})

    assert response.status_code == 200, response.text
    assert calls == [asset.id]


@pytest.mark.parametrize('role', ['Data Steward', 'Data Consumer'])
@pytest.mark.parametrize('route', ROW_ROUTES)
def test_without_assets_a_row_by_id_answers_as_an_unknown_row(
        client, db_session, asset, ws, act_as, role, route):
    """The data-domains check, then 404: a row id doesn't tell that it is an asset's."""
    ids = _seed(db_session, 'asset', str(asset.id))
    act_as(role)
    _name, kind, method, url, kwargs = _request('asset', str(asset.id), ids, route)

    response = _call(client, method, url, kwargs)

    if role == 'Data Consumer' and kind == 'write':
        _assert_data_domains_refusal(response)
    else:
        assert response.status_code == 404, response.text
        assert response.json()['detail'].endswith(' not found')


@pytest.fixture
def linked_to_an_accessible_product(monkeypatch, asset):
    """The #347 rule answers yes for this asset (its own tests cover how it decides)."""
    monkeypatch.setattr(
        AssetsManager, 'is_asset_accessible',
        lambda self, db, *, asset_id, data_products_manager, is_admin: asset_id == asset.id,
    )


def test_a_consumer_reads_an_asset_of_an_accessible_product(
        client, db_session, asset, ws, act_as, linked_to_an_accessible_product):
    ids = _seed(db_session, 'asset', str(asset.id))
    act_as('Data Consumer')

    for name, kind, method, url, kwargs in _requests('asset', str(asset.id), ids):
        if kind == 'read':
            response = _call(client, method, url, kwargs)
            assert response.status_code == 200, (name, response.text)


@pytest.mark.parametrize('route', WRITE_ROUTES)
def test_a_consumer_still_cannot_change_an_asset_of_an_accessible_product(
        client, db_session, asset, ws, act_as, linked_to_an_accessible_product, route):
    ids = _seed(db_session, 'asset', str(asset.id))
    act_as('Data Consumer')
    _name, _kind, method, url, kwargs = _request('asset', str(asset.id), ids, route)

    response = _call(client, method, url, kwargs)

    assert response.status_code == 403, response.text
    assert _code(response) == 'asset_write_denied'


def _unknown_asset_calls(entity_id):
    q = {'entity_id': entity_id}
    body = {'entity_type': 'asset', 'entity_id': entity_id}
    return {
        'create note': ('POST', '/api/entities/asset/rich-texts', {
            'params': q, 'json': {**body, 'title': 'N', 'content_markdown': 'B'}}),
        'list notes': ('GET', '/api/entities/asset/rich-texts', {'params': q}),
        'list links': ('GET', '/api/entities/asset/links', {'params': q}),
        'list documents': ('GET', '/api/entities/asset/documents', {'params': q}),
        'upload document': ('POST', '/api/entities/asset/documents', {
            'params': q, 'data': {'title': 'D'},
            'files': {'file': ('d.txt', b'data', 'text/plain')}}),
        'list costs': ('GET', f'/api/entities/asset/{entity_id}/cost-items', {}),
        'create cost': ('POST', f'/api/entities/asset/{entity_id}/cost-items', {'json': {
            **body, 'cost_center': 'OTHER', 'amount_cents': 5, 'start_month': '2026-02-01'}}),
    }


@pytest.mark.parametrize('role', ['Admin', ASSETS_ONLY])
@pytest.mark.parametrize('entity_id', ['8d1f4c52-6a43-4f7e-9d1e-2b9b0e6f1a77', 'not-a-uuid'])
@pytest.mark.parametrize('route', list(_unknown_asset_calls('x')))
def test_an_unknown_asset_is_404(client, ws, act_as, role, entity_id, route):
    act_as(role)
    method, url, kwargs = _unknown_asset_calls(entity_id)[route]

    response = _call(client, method, url, kwargs)

    assert response.status_code == 404, response.text
    assert _code(response) == 'asset_not_found'
    assert response.json()['detail']['params'] == {'assetId': entity_id}
    ws.files.upload.assert_not_called()


def test_an_unknown_asset_stays_403_for_a_user_who_cannot_read_assets(client, act_as):
    act_as('Data Consumer')
    response = client.get('/api/entities/asset/rich-texts', params={'entity_id': 'not-a-uuid'})
    assert response.status_code == 403
    assert _code(response) == 'asset_read_denied'


def test_a_row_of_a_deleted_asset_can_still_be_removed(client, db_session, act_as):
    """Rows addressed by their own id don't need the asset to exist."""
    ids = _seed(db_session, 'asset', str(uuid.uuid4()))
    act_as(ASSETS_ONLY)

    assert client.delete(f"/api/rich-texts/{ids['note']}").status_code == 204


# --- Other entity types: unchanged (data-domains) -------------------------------

@pytest.mark.parametrize('entity_type', OTHER_TYPES)
def test_the_steward_still_reads_and_writes_other_entities(
        client, db_session, ws, act_as, entity_type):
    """No existence check, no ``assets`` needed: ``data-domains`` READ_WRITE is enough."""
    ids = _seed(db_session, entity_type, 'any-entity-id')
    act_as('Data Steward')

    for name, _kind, method, url, kwargs in _requests(entity_type, 'any-entity-id', ids):
        response = _call(client, method, url, kwargs)
        assert response.status_code < 300, (name, response.status_code, response.text)


@pytest.mark.parametrize('entity_type', OTHER_TYPES)
def test_the_consumer_still_reads_other_entities(client, db_session, ws, act_as, entity_type):
    ids = _seed(db_session, entity_type, 'any-entity-id')
    act_as('Data Consumer')

    for name, kind, method, url, kwargs in _requests(entity_type, 'any-entity-id', ids):
        if kind == 'read':
            response = _call(client, method, url, kwargs)
            assert response.status_code == 200, (name, response.text)


def _assert_data_domains_refusal(response):
    assert response.status_code == 403, response.text
    assert response.json()['detail'].startswith(
        "Insufficient permissions for feature 'data-domains'"
    )


def _spread(routes):
    """Every route once, the entity types taken in turn (the check doesn't depend on them)."""
    return [(OTHER_TYPES[i % len(OTHER_TYPES)], route) for i, route in enumerate(routes)]


@pytest.mark.parametrize('entity_type, route', _spread(WRITE_ROUTES))
def test_the_consumer_still_cannot_write_other_entities(
        client, db_session, ws, act_as, entity_type, route):
    ids = _seed(db_session, entity_type, 'any-entity-id')
    act_as('Data Consumer')
    _name, _kind, method, url, kwargs = _request(entity_type, 'any-entity-id', ids, route)

    _assert_data_domains_refusal(_call(client, method, url, kwargs))


@pytest.mark.parametrize('entity_type, route', _spread(READ_ROUTES + WRITE_ROUTES))
def test_assets_alone_gives_nothing_on_other_entities(
        client, db_session, ws, act_as, entity_type, route):
    ids = _seed(db_session, entity_type, 'any-entity-id')
    act_as(ASSETS_ONLY)
    _name, _kind, method, url, kwargs = _request(entity_type, 'any-entity-id', ids, route)

    _assert_data_domains_refusal(_call(client, method, url, kwargs))


# --- Merged metadata with contract_ids --------------------------------------
# The route also returns the inheritable metadata of the named contracts, which
# the asset rules don't cover: naming contracts still needs data-domains.

def _contract_note(db) -> str:
    note = MetadataManager().create_rich_text(db, data=RichTextCreate(
        entity_type='data_contract', entity_id='contract-1', title='Contract note',
        content_markdown='Body',
    ), user_email='seed@example.com')
    return str(note.id)


def _merged(client, asset, **params):
    return client.get('/api/entities/asset/metadata/merged',
                      params={'entity_id': str(asset.id), **params})


def test_assets_alone_cannot_read_a_contract_through_merged_metadata(
        client, db_session, asset, act_as):
    _contract_note(db_session)
    act_as(ASSETS_ONLY)

    _assert_data_domains_refusal(_merged(client, asset, contract_ids='contract-1'))


def test_assets_alone_reads_merged_metadata_without_contracts(
        client, db_session, asset, act_as):
    act_as(ASSETS_ONLY)

    assert _merged(client, asset, contract_ids=' , ').status_code == 200


@pytest.mark.parametrize('role', ['Admin', 'Data Steward'])
def test_data_domains_still_reads_a_contract_through_merged_metadata(
        client, db_session, asset, act_as, linked_to_an_accessible_product, role):
    """The Steward reads the asset through its product, and the contract with data-domains."""
    note_id = _contract_note(db_session)
    act_as(role)

    response = _merged(client, asset, contract_ids='contract-1')

    assert response.status_code == 200, response.text
    assert note_id in [rt['id'] for rt in response.json()['rich_texts']]


# --- Attachments --------------------------------------------------------------
# The row to attach is picked by id (shared library or another entity's row),
# and merged metadata then returns it to every reader of the asset.

def test_assets_alone_cannot_attach_a_contract_note_to_an_asset(
        client, db_session, asset, act_as):
    note_id = _contract_note(db_session)
    act_as(ASSETS_ONLY)

    response = client.post('/api/entities/asset/attachments', params={'entity_id': str(asset.id)},
                           json={'asset_type': 'rich_text', 'asset_id': note_id})

    _assert_data_domains_refusal(response)


@pytest.mark.parametrize('asset_type, seed_key', [
    ('rich_text', 'note'), ('link', 'link'), ('document', 'doc'),
])
@pytest.mark.parametrize('entity_type', OTHER_TYPES)
def test_a_steward_cannot_attach_a_row_of_an_asset_to_another_entity(
        client, db_session, asset, ws, act_as, entity_type, asset_type, seed_key):
    """The attached row would be returned to every data-domains reader of the entity."""
    ids = _seed(db_session, 'asset', str(asset.id))
    act_as('Data Steward')

    response = client.post(f'/api/entities/{entity_type}/attachments',
                           params={'entity_id': 'target-1'},
                           json={'asset_type': asset_type, 'asset_id': ids[seed_key]})

    assert response.status_code == 403, response.text
    assert _code(response) == 'asset_read_denied'


def test_a_steward_attaches_a_row_of_an_accessible_asset_to_another_entity(
        client, db_session, asset, ws, act_as, linked_to_an_accessible_product):
    ids = _seed(db_session, 'asset', str(asset.id))
    act_as('Data Steward')

    response = client.post('/api/entities/data_product/attachments',
                           params={'entity_id': 'target-1'},
                           json={'asset_type': 'rich_text', 'asset_id': ids['note']})

    assert response.status_code == 201, response.text


def test_a_steward_attaches_a_row_of_another_entity_to_a_product(
        client, db_session, act_as):
    note_id = _contract_note(db_session)
    act_as('Data Steward')

    response = client.post('/api/entities/data_product/attachments',
                           params={'entity_id': 'target-1'},
                           json={'asset_type': 'rich_text', 'asset_id': note_id})

    assert response.status_code == 201, response.text


def test_attaching_an_unknown_row_to_another_entity_keeps_working(client, act_as):
    act_as('Data Steward')

    response = client.post('/api/entities/data_product/attachments',
                           params={'entity_id': 'target-1'},
                           json={'asset_type': 'rich_text', 'asset_id': str(uuid.uuid4())})

    assert response.status_code == 201, response.text


@pytest.mark.parametrize('body', [
    {'asset_type': 'note', 'asset_id': 'x'}, {'asset_id': 'x'}, {'asset_type': 'link'}, [1],
])
def test_a_malformed_attach_body_is_left_to_the_route_validation(client, act_as, body):
    act_as('Data Steward')

    response = client.post('/api/entities/data_product/attachments',
                           params={'entity_id': 'target-1'}, json=body)

    assert response.status_code == 422, response.text


def test_a_row_that_cannot_be_loaded_is_not_attached_to_another_entity(
        client, db_session, asset, ws, act_as, monkeypatch):
    ids = _seed(db_session, 'asset', str(asset.id))

    def broken(self, db, id):
        raise RuntimeError('database unavailable')

    monkeypatch.setattr(type(MetadataManager()._rich_text_repo), 'get', broken)
    act_as('Data Steward')

    response = client.post('/api/entities/data_product/attachments',
                           params={'entity_id': 'target-1'},
                           json={'asset_type': 'rich_text', 'asset_id': ids['note']})

    assert response.status_code == 500, response.text
    assert MetadataManager().list_attachments(
        db_session, entity_type='data_product', entity_id='target-1') == []


def test_attaching_a_row_of_another_asset_to_an_asset_needs_assets_read_write(
        client, db_session, asset, ws, act_as):
    """With assets READ_WRITE the source asset is readable: the check is in depth."""
    other = AssetDb(name='other', asset_type_id=asset.asset_type_id, platform='databricks')
    db_session.add(other)
    db_session.flush()
    ids = _seed(db_session, 'asset', str(other.id))
    act_as('Admin')

    response = client.post('/api/entities/asset/attachments', params={'entity_id': str(asset.id)},
                           json={'asset_type': 'rich_text', 'asset_id': ids['note']})

    assert response.status_code == 201, response.text


def test_assets_alone_still_detaches_from_an_asset(client, db_session, asset, act_as):
    note_id = _contract_note(db_session)
    MetadataManager().attach_shared_asset(
        db_session, entity_type='asset', entity_id=str(asset.id),
        data=MetadataAttachmentCreate(asset_type='rich_text', asset_id=note_id),
        user_email='seed@example.com',
    )
    act_as(ASSETS_ONLY)

    response = client.delete(f'/api/entities/asset/attachments/rich_text/{note_id}',
                             params={'entity_id': str(asset.id)})

    assert response.status_code == 204, response.text


# --- Rows addressed by id: fallbacks ----------------------------------------

@pytest.mark.parametrize('role, expected', [('Data Steward', 404), ('Data Consumer', 403)])
def test_an_unknown_row_gets_the_data_domains_check_then_404(client, act_as, role, expected):
    act_as(role)

    response = client.put(f'/api/rich-texts/{uuid.uuid4()}', json={'title': 'N2'})

    assert response.status_code == expected, response.text
    if expected == 403:
        _assert_data_domains_refusal(response)


def test_a_failing_row_lookup_fails_the_request(client, act_as, monkeypatch):
    """No fallback to the data-domains check: the request fails instead (500)."""
    def broken(self, db, id):
        raise RuntimeError('database unavailable')

    monkeypatch.setattr(type(MetadataManager()._rich_text_repo), 'get', broken)
    act_as('Data Steward')

    response = client.delete(f'/api/rich-texts/{uuid.uuid4()}')

    assert response.status_code == 500, response.text


@pytest.mark.parametrize('row', ['note', 'cost'])
def test_a_steward_cannot_delete_an_asset_row_its_response_model_cannot_load(
        client, db_session, asset, act_as, monkeypatch, row):
    """The check reads the stored row's entity, not the converted response model."""
    ids = _seed(db_session, 'asset', str(asset.id))

    def unloadable(*args, **kwargs):
        raise ValueError('created_at is missing')

    monkeypatch.setattr(RichText, 'from_orm', unloadable)
    monkeypatch.setattr(CostItem, 'model_validate', unloadable)
    act_as('Data Steward')
    url = f"/api/rich-texts/{ids['note']}" if row == 'note' else f"/api/cost-items/{ids['cost']}"

    response = client.delete(url)

    # The asset isn't readable: answered as an unknown row (see above).
    assert response.status_code == 404, response.text


@pytest.mark.parametrize('method', ['PUT', 'DELETE'])
def test_a_steward_cannot_change_an_asset_note_by_id(
        client, db_session, asset, act_as, method):
    ids = _seed(db_session, 'asset', str(asset.id))
    act_as('Data Steward')

    response = client.request(method, f"/api/rich-texts/{ids['note']}",
                              **({'json': {'title': 'N2'}} if method == 'PUT' else {}))

    # The asset isn't readable: answered as an unknown row (see above).
    assert response.status_code == 404, response.text


@pytest.mark.parametrize('method', ['PUT', 'DELETE'])
def test_by_id_writes_follow_the_write_rule_first(
        client, db_session, asset, mock_test_user, method):
    """``assets`` READ_WRITE from an email-assigned role: the write check grants it.

    The read check doesn't resolve those roles yet (#1355); writes by id must not
    depend on it, as creating the row doesn't.
    """
    app.state.settings_manager.create_app_role(AppRoleCreate(
        name='Assets by email (#1342)', assigned_users=[mock_test_user.email],
        feature_permissions={'assets': FeatureAccessLevel.READ_WRITE},
    ))
    mock_test_user.groups = ['no-role-group']
    ids = _seed(db_session, 'asset', str(asset.id))

    response = client.request(method, f"/api/rich-texts/{ids['note']}",
                              **({'json': {'title': 'N2'}} if method == 'PUT' else {}))

    assert response.status_code < 300, response.text


def _shared_asset_note(db):
    """A shared library note created from an asset page: type ``asset``, no asset id."""
    return str(MetadataManager().create_shared_rich_text(db, data=RichTextCreate(
        entity_type='asset', entity_id='ignored', title='Shared', content_markdown='Body',
    ), user_email='seed@example.com').id)


@pytest.mark.parametrize('method', ['PUT', 'DELETE'])
def test_a_shared_row_typed_asset_keeps_the_data_domains_rule_by_id(
        client, db_session, act_as, method):
    note_id = _shared_asset_note(db_session)
    act_as('Data Steward')

    response = client.request(method, f'/api/rich-texts/{note_id}',
                              **({'json': {'title': 'N2'}} if method == 'PUT' else {}))

    assert response.status_code < 300, response.text


def test_a_steward_attaches_a_shared_row_typed_asset_to_a_product(client, db_session, act_as):
    note_id = _shared_asset_note(db_session)
    act_as('Data Steward')

    response = client.post('/api/entities/data_product/attachments',
                           params={'entity_id': 'product-1'},
                           json={'asset_type': 'rich_text', 'asset_id': note_id})

    assert response.status_code == 201, response.text


# --- Entity type in the path: exact, from the supported list -------------------

@pytest.mark.parametrize('entity_type', ['Asset', 'ASSET', ' asset', 'assets', 'unknown'])
@pytest.mark.parametrize('route', ENTITY_ROUTES)
def test_an_unsupported_entity_type_is_422(
        client, db_session, asset, ws, act_as, entity_type, route):
    """Rows are stored under the exact type: ``Asset`` would skip the asset rules."""
    ids = _seed(db_session, 'asset', str(asset.id))
    act_as('Data Steward')
    _name, _kind, method, url, kwargs = _request(entity_type, str(asset.id), ids, route)

    response = _call(client, method, url, kwargs)

    assert response.status_code == 422, response.text
    assert _code(response) == 'entity_type_not_supported'
    assert response.json()['detail']['params'] == {'entityType': entity_type}
    ws.files.upload.assert_not_called()


# Written out, not taken from ENTITY_TYPES: a type dropped from it must fail here. The
# compliance policy, concept and collection pages show the metadata panel too.
@pytest.mark.parametrize('entity_type', [
    'data_domain', 'data_product', 'data_contract', 'dataset', 'compliance_policy', 'concept',
    'collection',
])
def test_every_supported_non_asset_type_keeps_the_data_domains_rule(
        client, act_as, entity_type):
    act_as('Data Steward')

    for url, kwargs in [
        (f'/api/entities/{entity_type}/rich-texts', {'params': {'entity_id': 'x'}}),
        (f'/api/entities/{entity_type}/attachments', {'params': {'entity_id': 'x'}}),
        (f'/api/entities/{entity_type}/x/cost-items', {}),
    ]:
        response = client.get(url, **kwargs)
        assert response.status_code == 200, (url, response.text)


@pytest.mark.parametrize('method', ['PUT', 'DELETE'])
def test_a_row_stored_under_another_casing_of_asset_gets_the_asset_rules(
        client, db_session, asset, act_as, method):
    """Rows written before the type check, under ``Asset``, are still an asset's rows."""
    note = RichTextMetadataDb(
        entity_type='Asset', entity_id=str(asset.id), title='Note', content_markdown='Body',
    )
    db_session.add(note)
    db_session.commit()
    act_as('Data Steward')

    response = client.request(method, f'/api/rich-texts/{note.id}',
                              **({'json': {'title': 'N2'}} if method == 'PUT' else {}))

    # The asset isn't readable: answered as an unknown row (see above).
    assert response.status_code == 404, response.text
