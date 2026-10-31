"""Assistant tools that change data need the feature level of their REST route.

Ask Ontos and MCP run the same tools as the REST API. A tool that changes data
declares the ``(feature, level)`` of the matching route's ``PermissionChecker``
and both runners (``ToolRegistry.execute`` and the MCP handler) check it against
the caller resolved for the request. A refusal is a coded tool result
(``tool_not_permitted``) and the tool does not run.
"""
import asyncio
import logging
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import src.routes.mcp_routes as mcp_routes
import src.tools.caller as tool_caller
from src.common.features import FeatureAccessLevel
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.llm_search_manager import LLMSearchManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.db_models.projects import ProjectDb
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.db_models.tags import TagDb, TagNamespaceDb
from src.db_models.teams import TeamDb
from src.models.users import UserInfo
from src.routes.mcp_routes import MCP_AUTH_FAILED, MCPError, MCPHandler
from src.tools.base import (
    TOOL_NOT_PERMITTED_CODE,
    ToolCaller,
    ToolContext,
    ToolResult,
)
from src.tools.caller import mcp_api_key_caller, resolve_tool_caller
from src.tools.registry import create_default_registry

RO = FeatureAccessLevel.READ_ONLY
RW = FeatureAccessLevel.READ_WRITE
ADMIN = FeatureAccessLevel.ADMIN

# Tool -> the PermissionChecker of the REST route doing the same change.
EXPECTED = {
    # POST /data-products, PUT /data-products/{id} (+ change-status), DELETE
    'create_draft_data_product': ('data-products', RW),
    'update_data_product': ('data-products', RW),
    'delete_data_product': ('data-products', ADMIN),
    # POST /data-contracts, PUT and DELETE /data-contracts/{id}
    'create_draft_data_contract': ('data-contracts', RW),
    'update_data_contract': ('data-contracts', RW),
    'delete_data_contract': ('data-contracts', RW),
    'create_domain': ('data-domains', RW),
    'update_domain': ('data-domains', RW),
    'delete_domain': ('data-domains', ADMIN),
    'create_team': ('teams', RW),
    'update_team': ('teams', RW),
    'delete_team': ('teams', ADMIN),
    'create_project': ('projects', RW),
    'update_project': ('projects', RW),
    'delete_project': ('projects', ADMIN),
    'create_tag': ('tags', RW),
    'update_tag': ('tags', RW),
    'delete_tag': ('tags', ADMIN),
    # POST /entities/{type}/{id}/tags:add, DELETE .../tags:remove
    'assign_tag_to_entity': ('tags', RW),
    'remove_tag_from_entity': ('tags', RW),
    # POST /semantic-links/, DELETE /semantic-links/{id}
    'add_semantic_link': ('semantic-models', RW),
    'remove_semantic_link': ('semantic-models', RW),
    # Reads, but admins only: POST /semantic-models/query (Read/Write), one level up
    'execute_sparql_query': ('semantic-models', ADMIN),
}
WRITE_PREFIXES = ('create_', 'update_', 'delete_', 'add_', 'remove_', 'assign_', 'set_')
BELOW = {RW: RO, ADMIN: RW}


def _run(coro):
    return asyncio.run(coro)


def _caller(levels, email='sue@example.com'):
    return ToolCaller(email=email, auth_path='test', permissions=dict(levels))


def _ctx(db=None, caller=None, **managers):
    return ToolContext(db=db if db is not None else MagicMock(), settings=MagicMock(),
                       caller=caller, **managers)


def _assert_refused(res, feature, level):
    assert res.success is False
    assert res.error_code == TOOL_NOT_PERMITTED_CODE
    out = res.to_dict()
    assert out['feature_id'] == feature and out['required_level'] == level.value
    # A refusal, not a crash: no error id, no exception text.
    assert 'error id' not in res.error and 'Traceback' not in res.error


class TestDeclaredLevels:
    def test_each_write_tool_declares_the_level_of_its_rest_route(self):
        registry = create_default_registry()
        declared = {
            t.name: t.required_permission for t in registry.list_tools() if t.required_permission
        }
        assert declared == EXPECTED

    def test_no_write_tool_is_left_without_a_level(self):
        for tool in create_default_registry().list_tools():
            if tool.name.startswith(WRITE_PREFIXES):
                assert tool.required_permission, tool.name


@pytest.fixture
def fake_registry(monkeypatch):
    """The default registry with each write tool's body replaced by a recorder."""
    registry = create_default_registry()
    calls = []
    for name in EXPECTED:
        tool = registry.get(name)

        async def _fake(ctx, _name=name, **kwargs):
            calls.append(_name)
            return ToolResult(success=True, data={'ran': _name})

        monkeypatch.setattr(tool, 'execute', _fake)
    return registry, calls


class TestRegistryChecksTheLevel:
    @pytest.mark.parametrize('name', sorted(EXPECTED))
    def test_below_the_level_is_refused_and_at_the_level_runs(self, name, fake_registry):
        registry, calls = fake_registry
        feature, level = EXPECTED[name]

        refused = _run(registry.execute(name, _ctx(caller=_caller({feature: BELOW[level]})), {}))
        _assert_refused(refused, feature, level)
        assert calls == []

        allowed = _run(registry.execute(name, _ctx(caller=_caller({feature: level})), {}))
        assert allowed.success is True and calls == [name]

    @pytest.mark.parametrize('name', sorted(EXPECTED))
    def test_without_a_caller_it_is_refused(self, name, fake_registry):
        registry, calls = fake_registry
        feature, level = EXPECTED[name]
        _assert_refused(_run(registry.execute(name, _ctx(), {})), feature, level)
        assert calls == []

    def test_a_level_on_another_feature_does_not_count(self, fake_registry):
        registry, calls = fake_registry
        caller = _caller({'tags': ADMIN, 'data-contracts': ADMIN})
        res = _run(registry.execute('delete_data_product', _ctx(caller=caller), {}))
        _assert_refused(res, 'data-products', ADMIN)
        assert calls == []

    def test_the_api_key_policy_caller_is_refused_every_write_tool(self, fake_registry):
        registry, calls = fake_registry
        caller = mcp_api_key_caller(SimpleNamespace(created_by='admin@example.com'))
        # Consumer-only: no identity (not the token's creator), no levels.
        assert caller.email is None and caller.auth_path == 'mcp_api_key'
        for name, (feature, level) in EXPECTED.items():
            _assert_refused(_run(registry.execute(name, _ctx(caller=caller), {})), feature, level)
        assert calls == []

    def test_a_full_access_caller_runs_every_write_tool(self, fake_registry):
        registry, calls = fake_registry
        caller = ToolCaller(email=None, auth_path='test', full_access=True)
        for name in EXPECTED:
            assert _run(registry.execute(name, _ctx(caller=caller), {})).success is True
        assert sorted(calls) == sorted(EXPECTED)

    def test_read_tools_need_no_caller(self, monkeypatch):
        registry = create_default_registry()
        tool = registry.get('get_domain')
        assert tool.required_permission is None

        async def _fake(ctx, **kwargs):
            return ToolResult(success=True, data={'ok': True})

        monkeypatch.setattr(tool, 'execute', _fake)
        assert _run(registry.execute('get_domain', _ctx(), {})).success is True

    def test_a_refusal_is_logged_with_the_tool_and_the_auth_path(self, fake_registry, caplog):
        registry, _ = fake_registry
        with caplog.at_level(logging.WARNING):
            _run(registry.execute('delete_team', _ctx(caller=_caller({'teams': RW})), {}))
        text = caplog.text
        assert 'delete_team' in text and 'sue@example.com' in text and 'auth_path=test' in text


# --- Each family with the real tool body ------------------------------------

def _product_manager(db_session):
    mgr = DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )
    mgr._update_search_index = lambda *a, **k: None
    return mgr


class TestFamilies:
    """One change per family, through the registry with the real tool."""

    def test_products_delete_needs_admin(self, db_session):
        registry = create_default_registry()
        mgr = _product_manager(db_session)
        created = mgr.create_product(
            {'apiVersion': 'v1.0.0', 'kind': 'DataProduct', 'id': str(uuid.uuid4()),
             'name': 'Level Product', 'version': '1.0.0', 'status': 'draft'},
            db=db_session, user='a@b.com',
        )
        args = {'product_id': created.id}
        for level in (RO, RW):
            ctx = _ctx(db_session, _caller({'data-products': level}), data_products_manager=mgr)
            _assert_refused(_run(registry.execute('delete_data_product', ctx, args)),
                            'data-products', ADMIN)
            assert mgr.get_product(created.id) is not None

        ctx = _ctx(db_session, _caller({'data-products': ADMIN}), data_products_manager=mgr)
        assert _run(registry.execute('delete_data_product', ctx, args)).success is True
        assert mgr.get_product(created.id) is None

    def test_contracts_delete_needs_read_write(self, db_session):
        registry = create_default_registry()
        mgr = DataContractsManager(data_dir=Path('/tmp'))
        mgr._update_search_index = lambda *a, **k: None
        created = mgr.create_from_upload(
            db=db_session, current_user='a@b.com',
            parsed_odcs={'apiVersion': 'v3.1.0', 'kind': 'DataContract',
                         'name': 'Level Contract', 'version': '1.0.0', 'status': 'draft'},
        )
        args = {'contract_id': created.id}
        ctx = _ctx(db_session, _caller({'data-contracts': RO}), data_contracts_manager=mgr)
        _assert_refused(_run(registry.execute('delete_data_contract', ctx, args)),
                        'data-contracts', RW)
        assert db_session.get(DataContractDb, created.id) is not None

        ctx = _ctx(db_session, _caller({'data-contracts': RW}), data_contracts_manager=mgr)
        assert _run(registry.execute('delete_data_contract', ctx, args)).success is True
        assert db_session.get(DataContractDb, created.id) is None

    def _create_needs_read_write(self, db_session, tool, feature, args, model, name_col):
        registry = create_default_registry()
        name = args['name']

        def _count():
            return db_session.query(model).filter(name_col == name).count()

        res = _run(registry.execute(tool, _ctx(db_session, _caller({feature: RO})), args))
        _assert_refused(res, feature, RW)
        assert _count() == 0

        res = _run(registry.execute(tool, _ctx(db_session, _caller({feature: RW})), args))
        assert res.success is True, res.error
        assert _count() == 1

    def test_domains_create_needs_read_write(self, db_session):
        name = f'level-domain-{uuid.uuid4().hex[:6]}'
        self._create_needs_read_write(
            db_session, 'create_domain', 'data-domains', {'name': name},
            DataDomain, DataDomain.name,
        )

    def test_teams_create_needs_read_write(self, db_session):
        name = f'level-team-{uuid.uuid4().hex[:6]}'
        self._create_needs_read_write(
            db_session, 'create_team', 'teams', {'name': name, 'title': 'Level team'},
            TeamDb, TeamDb.name,
        )

    def test_projects_create_needs_read_write(self, db_session):
        name = f'level-project-{uuid.uuid4().hex[:6]}'
        self._create_needs_read_write(
            db_session, 'create_project', 'projects', {'name': name, 'title': 'Level project'},
            ProjectDb, ProjectDb.name,
        )

    def test_tags_create_needs_admin_for_a_new_namespace(self, db_session):
        registry = create_default_registry()
        ns = f'levelns{uuid.uuid4().hex[:6]}'
        args = {'name': f'{ns}/gdpr'}

        def _ns_count():
            return db_session.query(TagNamespaceDb).filter(TagNamespaceDb.name == ns).count()

        _assert_refused(
            _run(registry.execute('create_tag', _ctx(db_session, _caller({'tags': RO})), args)),
            'tags', RW,
        )
        # Read/write may create tags but not namespaces (POST /tags/namespaces is admin).
        _assert_refused(
            _run(registry.execute('create_tag', _ctx(db_session, _caller({'tags': RW})), args)),
            'tags', ADMIN,
        )
        assert _ns_count() == 0

        res = _run(registry.execute('create_tag', _ctx(db_session, _caller({'tags': ADMIN})), args))
        assert res.success is True, res.error
        assert _ns_count() == 1
        assert db_session.query(TagDb).filter(TagDb.name == 'gdpr').count() == 1

    def test_semantic_links_add_needs_read_write(self, db_session):
        registry = create_default_registry()
        entity_id = str(uuid.uuid4())
        args = {'entity_type': 'data_product', 'entity_id': entity_id,
                'concept_iri': 'http://example.com/onto#Customer', 'concept_label': 'Customer'}

        def _count():
            return db_session.query(EntitySemanticLinkDb).filter(
                EntitySemanticLinkDb.entity_id == entity_id).count()

        ctx = _ctx(db_session, _caller({'semantic-models': RO}),
                   semantic_models_manager=MagicMock())
        _assert_refused(_run(registry.execute('add_semantic_link', ctx, args)),
                        'semantic-models', RW)
        assert _count() == 0

        ctx.caller = _caller({'semantic-models': RW})
        res = _run(registry.execute('add_semantic_link', ctx, args))
        assert res.success is True, res.error
        assert _count() == 1


# --- Caller resolution --------------------------------------------------------

class TestResolveToolCaller:
    def test_levels_come_from_the_shared_resolver(self, monkeypatch):
        seen = {}

        async def _resolve(email, groups, request):
            seen.update(email=email, groups=groups)
            return {'teams': RW}

        monkeypatch.setattr(tool_caller, 'resolve_effective_permissions', _resolve)
        user = UserInfo(email='sue@example.com', username='sue', user='Sue', ip=None, groups=['g1'])
        caller = _run(resolve_tool_caller(user, MagicMock(), 'ask_ontos'))
        assert seen == {'email': 'sue@example.com', 'groups': ['g1']}
        assert caller.email == 'sue@example.com' and caller.auth_path == 'ask_ontos'
        assert caller.has_level('teams', RW) and not caller.has_level('teams', ADMIN)
        assert not caller.full_access

    def test_a_resolution_failure_gives_no_levels(self, monkeypatch, caplog):
        async def _boom(*a, **k):
            raise RuntimeError('db down')

        monkeypatch.setattr(tool_caller, 'resolve_effective_permissions', _boom)
        user = UserInfo(email='sue@example.com', username='sue', user='Sue', ip=None, groups=['g1'])
        with caplog.at_level(logging.ERROR):
            caller = _run(resolve_tool_caller(user, MagicMock(), 'ask_ontos'))
        assert caller.permissions == {} and not caller.has_level('teams', RO)
        assert 'sue@example.com' in caplog.text and 'ask_ontos' in caplog.text


class TestAskOntosPassesTheCaller:
    def test_the_tool_context_carries_the_chat_caller_only_during_the_chat(self):
        mgr = LLMSearchManager(db=MagicMock(), settings=MagicMock())
        caller = _caller({'teams': RW})
        seen = []

        async def _inner(**kwargs):
            seen.append(mgr._create_tool_context().caller)
            return 'response'

        mgr._chat_inner = _inner
        assert _run(mgr.chat(user_message='hi', user_id='sue', caller=caller)) == 'response'
        assert seen == [caller]
        assert mgr._create_tool_context().caller is None


# --- MCP ----------------------------------------------------------------------

def _mcp_handler(headers, audit_manager=None, user=None, me_error=None):
    users_manager = MagicMock()
    if me_error is not None:
        users_manager.get_current_user.side_effect = me_error
    else:
        users_manager.get_current_user.return_value = user
    app = SimpleNamespace(state=SimpleNamespace(workspace_client=object(),
                                                users_manager=users_manager))
    request = SimpleNamespace(headers=headers, app=app, state=SimpleNamespace(),
                              client=SimpleNamespace(host='127.0.0.1'))
    return MCPHandler(
        db=None, settings=MagicMock(),
        token_info=SimpleNamespace(id='t1', name='tok', created_by='admin@example.com',
                                   scopes=['*']),
        request=request, audit_manager=audit_manager, session_id='s1',
    )


def _recording_tool(handler, name):
    calls = []

    async def _fake(ctx, **kwargs):
        calls.append(ctx.caller)
        return ToolResult(success=True, data={'ran': name})

    handler._tool_registry.get(name).execute = _fake
    return calls


def _audits(audit_manager, action):
    return [c.kwargs for c in audit_manager.log_action.call_args_list
            if c.kwargs['action'] == action]


SUE = UserInfo(email='sue@example.com', username='sue@example.com', user='Sue', ip=None,
               groups=['g'])
TOKEN = {'x-forwarded-access-token': 'user-token'}


@pytest.fixture
def obo(monkeypatch):
    monkeypatch.setattr(mcp_routes, 'get_obo_workspace_client', lambda *a, **k: object())

    async def _levels(email, groups, request):
        return {'data-domains': RW}

    monkeypatch.setattr(tool_caller, 'resolve_effective_permissions', _levels)


class TestMcpChecksTheLevel:
    def test_an_api_key_without_a_forwarded_token_is_consumer_only(self, obo):
        audit = MagicMock()
        # The forwarded email header alone never names the caller.
        h = _mcp_handler({'X-Forwarded-Email': 'sue@example.com'}, audit)
        calls = _recording_tool(h, 'delete_domain')
        out = _run(h._handle_tools_call({'name': 'delete_domain', 'arguments': {}}))
        assert out['isError'] is True and calls == []
        details = _audits(audit, 'TOOL_CALL')[0]['details']
        assert details['auth_path'] == 'mcp_api_key'
        assert details['error_code'] == TOOL_NOT_PERMITTED_CODE
        read_calls = _recording_tool(h, 'get_domain')
        out = _run(h._handle_tools_call({'name': 'get_domain', 'arguments': {}}))
        assert out['isError'] is False and read_calls[0].email is None

    def test_the_verified_user_is_the_caller_and_the_audit_username(self, obo):
        audit = MagicMock()
        h = _mcp_handler(TOKEN, audit, user=SUE)
        calls = _recording_tool(h, 'delete_domain')

        out = _run(h._handle_tools_call({'name': 'delete_domain', 'arguments': {}}))
        assert out['isError'] is True and calls == []
        assert 'Not allowed' in out['content'][0]['text']
        entry = _audits(audit, 'TOOL_CALL')[0]
        assert entry['username'] == 'sue@example.com'
        assert entry['details']['error_code'] == TOOL_NOT_PERMITTED_CODE
        assert entry['details']['auth_path'] == 'mcp_forwarded_token'
        assert entry['details']['token_name'] == 'tok' and entry['details']['token_id'] == 't1'
        # The code and its params reach the client, not only the audit.
        assert out['structuredContent']['error_code'] == TOOL_NOT_PERMITTED_CODE
        assert out['structuredContent']['feature_id'] == 'data-domains'
        assert out['structuredContent']['required_level'] == 'Admin'

        create_calls = _recording_tool(h, 'create_domain')
        out = _run(h._handle_tools_call({'name': 'create_domain', 'arguments': {}}))
        assert out['isError'] is False and create_calls[0].email == 'sue@example.com'
        # me() once per request.
        assert h._request.app.state.users_manager.get_current_user.call_count == 1

    def test_the_x_real_ip_is_recorded(self, obo):
        audit = MagicMock()
        h = _mcp_handler({**TOKEN, 'X-Real-Ip': '10.1.2.3'}, audit, user=SUE)
        _recording_tool(h, 'create_domain')
        _run(h._handle_tools_call({'name': 'create_domain', 'arguments': {}}))
        assert _audits(audit, 'TOOL_CALL')[0]['ip_address'] == '10.1.2.3'

    @pytest.mark.parametrize('headers, kwargs, reason', [
        (TOKEN, {'me_error': RuntimeError('token rejected')}, 'caller_unresolved'),
        ({**TOKEN, 'X-Forwarded-Email': 'mallory@example.com'}, {'user': SUE},
         'forwarded_identity_mismatch'),
    ])
    def test_an_unverifiable_forwarded_user_fails_and_is_recorded(
        self, obo, caplog, headers, kwargs, reason
    ):
        audit = MagicMock()
        h = _mcp_handler(headers, audit, **kwargs)
        calls = _recording_tool(h, 'get_domain')

        with caplog.at_level(logging.WARNING), pytest.raises(MCPError) as exc_info:
            _run(h._handle_tools_call({'name': 'get_domain', 'arguments': {}}))
        assert exc_info.value.code == MCP_AUTH_FAILED
        assert exc_info.value.message == mcp_routes.IDENTITY_REJECTED_MESSAGE
        assert calls == []
        rejected = _audits(audit, 'IDENTITY_REJECTED')
        assert len(rejected) == 1 and rejected[0]['success'] is False
        assert rejected[0]['details']['reason'] == reason
        assert rejected[0]['details']['tool_name'] == 'get_domain'
        assert rejected[0]['details']['auth_path'] == 'mcp_forwarded_token'
        assert 'get_domain' in caplog.text and 'mcp_forwarded_token' in caplog.text

    def test_any_method_resolves_the_verified_user_first(self, obo):
        h = _mcp_handler(TOKEN, MagicMock(), me_error=RuntimeError('expired'))
        from src.models.mcp import JSONRPCRequest

        resp = _run(h.handle(JSONRPCRequest(jsonrpc='2.0', id=1, method='tools/list')))
        assert resp.error is not None and resp.error.code == MCP_AUTH_FAILED

    def test_a_rejected_tool_call_is_audited_with_the_tool_name(self, obo):
        audit = MagicMock()
        h = _mcp_handler(TOKEN, audit, me_error=RuntimeError('expired'))
        from src.models.mcp import JSONRPCRequest

        rpc = JSONRPCRequest(jsonrpc='2.0', id=1, method='tools/call',
                             params={'name': 'get_domain', 'arguments': {}})
        resp = _run(h.handle(rpc))
        assert resp.error.code == MCP_AUTH_FAILED
        assert resp.error.message == mcp_routes.IDENTITY_REJECTED_MESSAGE
        rejected = _audits(audit, 'IDENTITY_REJECTED')[0]['details']
        assert rejected['tool_name'] == 'get_domain' and rejected['reason'] == 'caller_unresolved'

    def test_an_unexpected_failure_is_coded_too(self):
        h = _mcp_handler({})

        async def _boom(ctx, **kwargs):
            raise RuntimeError('secret detail')

        h._tool_registry.get('get_domain').execute = _boom
        out = _run(h._handle_tools_call({'name': 'get_domain', 'arguments': {}}))
        assert out['isError'] is True
        assert out['structuredContent']['error_code'] == 'tool_failed'
        assert out['structuredContent']['error_id'] in out['content'][0]['text']
        assert 'secret detail' not in str(out)

    def test_the_test_user_header_does_not_name_the_caller(self, obo):
        # Only the verified forwarded token names an MCP caller.
        h = _mcp_handler({'X-Test-Token': 'tok'}, MagicMock())
        h._settings.TEST_USER_TOKEN = 'tok'
        calls = _recording_tool(h, 'get_domain')
        _run(h._handle_tools_call({'name': 'get_domain', 'arguments': {}}))
        assert calls[0].auth_path == 'mcp_api_key' and calls[0].email is None

    def test_an_unexpected_method_error_has_no_exception_text(self, obo):
        h = _mcp_handler({}, MagicMock())
        from src.models.mcp import JSONRPCRequest

        async def _boom(params):
            raise RuntimeError('db password=hunter2')

        h._handle_tools_list = _boom
        resp = _run(h.handle(JSONRPCRequest(jsonrpc='2.0', id=1, method='tools/list')))
        assert 'hunter2' not in resp.error.message
        assert resp.error.message.startswith('The request failed with an unexpected error')
        assert 'error id' in resp.error.message
