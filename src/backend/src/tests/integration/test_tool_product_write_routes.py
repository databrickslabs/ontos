"""Ask Ontos changes a data product only where the REST routes let the same user.

The same Read/Write user, through ``PUT /api/data-products/{id}`` and through
``POST /api/llm-search/chat`` with a scripted LLM calling the product tools:
- a published product they don't own: PUT answers 403, the tool refuses and the
  product is unchanged;
- a draft they create through the chat: they are its draft owner, so PUT lets
  them edit it, as a draft created with ``POST /api/data-products``.
"""
import json
import uuid
from types import SimpleNamespace

import pytest

from src.app import app
from src.common import config as config_module
from src.common.authorization import get_user_details_from_sdk
from src.controller.llm_search_manager import LLMSearchManager
from src.db_models.data_products import DataProductDb
from src.db_models.settings import AppRoleDb
from src.models.users import UserInfo

# Spelled out so the tests run (and fail) on a tree without the constant.
PRODUCT_EDIT_NOT_ALLOWED_CODE = 'product_edit_not_allowed'


def _response(*, content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _ScriptedLLM:
    def __init__(self, script):
        self._script = list(script)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        return self._script.pop(0)


@pytest.fixture
def writer(client, db_session, test_settings, monkeypatch):
    """A user whose only role gives Read/Write on data-products, signed in."""
    test_settings.LLM_ENABLED = True
    test_settings.LLM_ENDPOINT = 'test-endpoint'
    test_settings.LLM_SYSTEM_PROMPT = None
    monkeypatch.setattr(config_module, 'get_settings', lambda: test_settings)
    group = f'product-writer-{uuid.uuid4().hex[:6]}'
    db_session.add(AppRoleDb(
        id=str(uuid.uuid4()), name=f'Product writer {group}', description='test role',
        feature_permissions=json.dumps({'data-products': 'Read/Write'}),
        assigned_groups=json.dumps([group]), home_sections='[]',
        approval_privileges='{}', is_admin=False,
    ))
    db_session.commit()
    user = UserInfo(email=f'{group}@example.com', username=f'{group}@example.com',
                    user=group, ip='127.0.0.1', groups=[group])

    async def _user():
        return user

    app.dependency_overrides[get_user_details_from_sdk] = _user
    app.state.data_products_manager._update_search_index = lambda *a, **k: None
    return user


def _chat(client, monkeypatch, tool, args):
    call = SimpleNamespace(id='call-1', function=SimpleNamespace(
        name=tool, arguments=json.dumps(args)))
    llm = _ScriptedLLM([_response(tool_calls=[call]), _response(content='Done.')])
    monkeypatch.setattr(LLMSearchManager, '_get_openai_client',
                        lambda self, user_token=None: llm)
    resp = client.post('/api/llm-search/chat', json={'content': f'Run {tool}'})
    assert resp.status_code == 200, resp.text
    sources = [s for s in resp.json()['sources'] if s['tool'] == tool]
    assert len(sources) == 1, resp.json()['sources']
    return sources[0]


def _put(client, product_id, **fields):
    body = {'apiVersion': 'v1.0.0', 'kind': 'DataProduct', 'id': product_id,
            'name': fields.pop('name'), 'version': '1.0.0', 'status': fields.pop('status'),
            **fields}
    # Skip the versioning prompt for non-draft products: the ownership rule is tested.
    return client.put(f'/api/data-products/{product_id}', json=body,
                      headers={'X-Force-Update': 'true'})


def test_a_non_owner_edits_a_published_product_neither_way(client, writer, monkeypatch):
    manager = app.state.data_products_manager
    product = manager.create_product({
        'apiVersion': 'v1.0.0', 'kind': 'DataProduct', 'id': str(uuid.uuid4()),
        'name': 'Someone else product', 'version': '1.0.0', 'status': 'active',
        'draft_owner_id': 'olga@example.com',
    })

    source = _chat(client, monkeypatch, 'update_data_product',
                   {'product_id': product.id, 'description': 'changed through the chat'})
    assert source['success'] is False
    assert source['error_code'] == PRODUCT_EDIT_NOT_ALLOWED_CODE
    stored = manager.get_product(product.id)
    assert stored.description is None or not stored.description.purpose

    # Last: the refused request rolls back the test's shared session.
    resp = _put(client, product.id, name=product.name, status='active',
                description={'purpose': 'changed through PUT'})
    assert resp.status_code == 403, resp.text


def test_the_creator_of_a_chat_draft_edits_it_with_put(
    client, db_session, writer, monkeypatch
):
    name = f'Chat draft {uuid.uuid4().hex[:6]}'
    source = _chat(client, monkeypatch, 'create_draft_data_product',
                   {'name': name, 'description': 'made in the chat', 'domain': 'Sales'})
    assert source['success'] is True, source
    created = db_session.query(DataProductDb).filter_by(name=name).one()
    assert created.draft_owner_id == writer.email

    resp = _put(client, created.id, name='Chat draft renamed', status='draft')
    assert resp.status_code == 200, resp.text
    assert app.state.data_products_manager.get_product(created.id).name == 'Chat draft renamed'
