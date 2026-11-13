"""Ask Ontos changes a data contract with the workflows and audit of the REST routes.

The same Read/Write user, through ``POST`` / ``PUT /api/data-contracts`` and
through ``POST /api/llm-search/chat`` with a scripted LLM calling the contract
tools:
- a create and an update fire the same on_create / on_update workflows for the
  user, and write the same data-contracts CREATE / UPDATE audit entries;
- a failing before_update gate refuses the update both ways (PUT answers 400,
  the tool ``update_blocked``) and the contract is unchanged.
"""
import json
import uuid
from datetime import datetime
from types import SimpleNamespace

import pytest

from src.app import app
from src.common import config as config_module
from src.common.authorization import get_user_details_from_sdk
from src.controller.llm_search_manager import LLMSearchManager
from src.db_models.audit_log import AuditLogDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.process_workflows import (
    ProcessWorkflowDb, WorkflowExecutionDb, WorkflowStepDb,
)
from src.db_models.settings import AppRoleDb
from src.models.users import UserInfo

# Spelled out so the tests run (and fail) on a tree without the constant.
UPDATE_BLOCKED_CODE = 'update_blocked'


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
    """A user whose only role gives Read/Write on data-contracts, signed in."""
    test_settings.LLM_ENABLED = True
    test_settings.LLM_ENDPOINT = 'test-endpoint'
    test_settings.LLM_SYSTEM_PROMPT = None
    monkeypatch.setattr(config_module, 'get_settings', lambda: test_settings)
    group = f'contract-writer-{uuid.uuid4().hex[:6]}'
    db_session.add(AppRoleDb(
        id=str(uuid.uuid4()), name=f'Contract writer {group}', description='test role',
        feature_permissions=json.dumps({'data-contracts': 'Read/Write'}),
        assigned_groups=json.dumps([group]), home_sections='[]',
        approval_privileges='{}', is_admin=False,
    ))
    db_session.commit()
    user = UserInfo(email=f'{group}@example.com', username=f'{group}@example.com',
                    user=group, ip='127.0.0.1', groups=[group])

    async def _user():
        return user

    app.dependency_overrides[get_user_details_from_sdk] = _user
    manager = app.state.data_contracts_manager
    monkeypatch.setattr(manager, '_update_search_index', lambda *a, **k: None)
    monkeypatch.setattr(manager, '_queue_delivery', lambda *a, **k: None)
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


def _workflow(db, trigger, step_type='pass'):
    """An active one-step workflow on ``trigger`` for data contracts."""
    now = datetime.utcnow()
    wf_id = str(uuid.uuid4())
    db.add(ProcessWorkflowDb(
        id=wf_id, name=f'{trigger} {wf_id[:6]}', description='test',
        trigger_config=json.dumps({'type': trigger, 'entity_types': ['data_contract']}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        workflow_type='process', created_at=now, updated_at=now,
    ))
    db.flush()
    db.add(WorkflowStepDb(
        id=str(uuid.uuid4()), workflow_id=wf_id, step_id='only', name='Only step',
        step_type=step_type, config='{}', on_pass=None, on_fail=None, order=0,
        created_at=now, updated_at=now,
    ))
    db.commit()
    return wf_id


def _runs(db, wf_id):
    """(entity_id, triggered_by) of each execution of the workflow, sorted."""
    db.expire_all()
    rows = db.query(WorkflowExecutionDb).filter_by(workflow_id=wf_id).all()
    return sorted((json.loads(r.trigger_context)['entity_id'], r.triggered_by) for r in rows)


def _audit(db, user, action):
    """(contract id, success) of the user's data-contracts audit entries for ``action``."""
    db.expire_all()
    rows = db.query(AuditLogDb).filter_by(
        username=user.username, feature='data-contracts', action=action).all()
    out = []
    for r in rows:
        details = r.details or {}
        cid = (details.get('created_resource_id') or details.get('updated_resource_id')
               or details.get('params', {}).get('contract_id'))
        out.append((cid, r.success))
    return sorted(out)


def _chat_create(client, db_session, monkeypatch, name):
    source = _chat(client, monkeypatch, 'create_draft_data_contract',
                   {'name': name, 'description': 'made in the chat', 'domain': 'Sales'})
    assert source['success'] is True, source
    return db_session.query(DataContractDb).filter_by(name=name).one().id


def test_the_chat_and_the_routes_fire_and_audit_the_same(
    client, db_session, writer, monkeypatch
):
    on_create = _workflow(db_session, 'on_create')
    on_update = _workflow(db_session, 'on_update')

    chat_id = _chat_create(client, db_session, monkeypatch, f'Chat {uuid.uuid4().hex[:6]}')
    source = _chat(client, monkeypatch, 'update_data_contract',
                   {'contract_id': chat_id, 'description': 'edited in the chat'})
    assert source['success'] is True, source

    resp = client.post('/api/data-contracts', json={
        'name': f'REST {uuid.uuid4().hex[:6]}', 'version': '0.1.0', 'status': 'draft',
    })
    assert resp.status_code == 200, resp.text
    rest_id = resp.json()['id']
    resp = client.put(f'/api/data-contracts/{rest_id}',
                      json={'description': {'purpose': 'edited with PUT'}})
    assert resp.status_code == 200, resp.text

    expected = sorted([(chat_id, writer.email), (rest_id, writer.email)])
    assert _runs(db_session, on_create) == expected
    assert _runs(db_session, on_update) == expected
    both = sorted([(chat_id, True), (rest_id, True)])
    assert _audit(db_session, writer, 'CREATE') == both
    assert _audit(db_session, writer, 'UPDATE') == both


def test_a_failing_before_update_gate_refuses_both_ways(
    client, db_session, writer, monkeypatch
):
    chat_id = _chat_create(client, db_session, monkeypatch, f'Chat {uuid.uuid4().hex[:6]}')
    _workflow(db_session, 'before_update', step_type='fail')

    source = _chat(client, monkeypatch, 'update_data_contract',
                   {'contract_id': chat_id, 'description': 'edited in the chat'})
    assert source['success'] is False
    assert source['error_code'] == UPDATE_BLOCKED_CODE
    db_session.expire_all()
    assert db_session.get(DataContractDb, chat_id).description_purpose == 'made in the chat'

    # Last: the refused request rolls back the test's shared session.
    resp = client.put(f'/api/data-contracts/{chat_id}',
                      json={'description': {'purpose': 'edited with PUT'}})
    assert resp.status_code == 400, resp.text
    assert resp.json()['detail']['message'] == 'Pre-update validation failed'
