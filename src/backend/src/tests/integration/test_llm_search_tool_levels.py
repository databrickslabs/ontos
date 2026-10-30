"""Ask Ontos runs a tool that changes data only with the level of its REST route.

Through ``POST /api/llm-search/chat`` with a scripted LLM that asks for
``delete_data_product``: a consumer (data-products read-only) is refused with a
coded tool result and the product stays; an admin (data-products admin, the level
of ``DELETE /api/data-products/{id}``) deletes it.
"""
import json
import uuid
from types import SimpleNamespace

import pytest

from src.app import app
from src.common import config as config_module
from src.common.authorization import get_user_details_from_sdk
from src.controller.llm_search_manager import LLMSearchManager
from src.db_models.settings import AppRoleDb
from src.models.users import UserInfo

# The code of src.tools.base.TOOL_NOT_PERMITTED_CODE, spelled out so the test
# runs (and fails) on a tree without it.
TOOL_NOT_PERMITTED_CODE = 'tool_not_permitted'


def _response(*, content=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class _ScriptedLLM:
    def __init__(self, script):
        self._script = list(script)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        return self._script.pop(0)


def _add_role(db_session, group, level):
    db_session.add(AppRoleDb(
        id=str(uuid.uuid4()),
        name=f'Tool level {level} {uuid.uuid4().hex[:6]}',
        description='test role',
        feature_permissions=json.dumps({'data-products': level}),
        assigned_groups=json.dumps([group]),
        home_sections='[]',
        approval_privileges='{}',
        is_admin=False,
    ))
    db_session.commit()


@pytest.fixture
def chat_as(client, db_session, test_settings, monkeypatch):
    """Chat as a user whose only role gives ``level`` on data-products."""
    test_settings.LLM_ENABLED = True
    test_settings.LLM_ENDPOINT = 'test-endpoint'
    test_settings.LLM_SYSTEM_PROMPT = None
    monkeypatch.setattr(config_module, 'get_settings', lambda: test_settings)

    def _chat(level, product_id, tool='delete_data_product'):
        group = f'tool-level-{uuid.uuid4().hex[:6]}'
        _add_role(db_session, group, level)
        user = UserInfo(email=f'{group}@example.com', username=group, user=group,
                        ip='127.0.0.1', groups=[group])

        async def _user():
            return user

        app.dependency_overrides[get_user_details_from_sdk] = _user
        call = SimpleNamespace(id='call-1', function=SimpleNamespace(
            name=tool, arguments=json.dumps({'product_id': product_id})))
        llm = _ScriptedLLM([_response(tool_calls=[call]), _response(content='Done.')])
        monkeypatch.setattr(LLMSearchManager, '_get_openai_client',
                            lambda self, user_token=None: llm)
        resp = client.post('/api/llm-search/chat',
                           json={'content': f'Delete the data product {product_id}'})
        assert resp.status_code == 200, resp.text
        return resp.json()

    return _chat


@pytest.fixture
def product_id(client):
    manager = app.state.data_products_manager
    manager._update_search_index = lambda *a, **k: None
    created = manager.create_product({
        'apiVersion': 'v1.0.0', 'kind': 'DataProduct', 'id': str(uuid.uuid4()),
        'name': 'Chat level product', 'version': '1.0.0', 'status': 'draft',
    })
    return created.id


def _source(body, tool='delete_data_product'):
    sources = [s for s in body['sources'] if s['tool'] == tool]
    assert len(sources) == 1, body['sources']
    return sources[0]


def test_a_consumer_cannot_delete_a_product_through_the_chat(chat_as, product_id):
    body = chat_as('Read-only', product_id)
    source = _source(body)
    assert source['success'] is False
    assert source['error_code'] == TOOL_NOT_PERMITTED_CODE
    assert app.state.data_products_manager.get_product(product_id) is not None


def test_read_write_is_not_enough_to_delete_a_product(chat_as, product_id):
    source = _source(chat_as('Read/Write', product_id))
    assert source['success'] is False and source['error_code'] == TOOL_NOT_PERMITTED_CODE
    assert app.state.data_products_manager.get_product(product_id) is not None


def test_an_admin_deletes_a_product_through_the_chat(chat_as, product_id):
    source = _source(chat_as('Admin', product_id))
    assert source['success'] is True
    assert app.state.data_products_manager.get_product(product_id) is None


def test_a_consumer_reads_a_draft_product_as_not_found(chat_as, product_id):
    source = _source(chat_as('Read-only', product_id, 'get_data_product'), 'get_data_product')
    assert source['success'] is False
    assert source['error'] == f"Data product '{product_id}' not found"


def test_an_admin_reads_a_draft_product(chat_as, product_id):
    source = _source(chat_as('Admin', product_id, 'get_data_product'), 'get_data_product')
    assert source['success'] is True
