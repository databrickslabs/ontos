"""Every assistant tool declares who may run it, and an undeclared tool is refused.

Ask Ontos and MCP run the same tools. ``required_permission`` is the
``(feature, level)`` of the matching REST route, or ``ANY_CALLER`` for a tool that
needs no feature level. A tool that declares nothing is refused (coded
``tool_not_permitted``), so a new tool cannot be added without a decision.
"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.features import APP_FEATURES, FeatureAccessLevel
from src.db_models.data_products import DataProductDb
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.routes.mcp_routes import MCPHandler
from src.tools.base import (
    ANY_CALLER,
    TOOL_NOT_PERMITTED_CODE,
    BaseTool,
    ToolCaller,
    ToolContext,
    ToolResult,
    check_tool_permission,
)
from src.tools.registry import ToolRegistry, create_default_registry

RO = FeatureAccessLevel.READ_ONLY
NONE = FeatureAccessLevel.NONE

# Tools that need no feature level, on purpose. Adding a name here is a decision:
# the matching REST route has no PermissionChecker (or the tool is not tied to a
# feature); a tool whose route has one declares that level instead.
ANY_CALLER_TOOLS = {
    # Product and contract reads: the read rules (src.tools.read_access) apply.
    'search_data_products', 'get_data_product', 'get_data_products', 'list_data_products',
    'search_data_contracts', 'get_data_contract', 'get_data_contracts', 'list_data_contracts',
    'get_data_product_costs',
    # Organisation and tag reads.
    'search_domains', 'get_domain', 'search_teams', 'get_team', 'search_projects',
    'get_project', 'search_tags', 'get_tag', 'list_entity_tags',
    # GET /semantic-links/entity/... and /semantic-links/by-iri have no PermissionChecker.
    'list_semantic_links', 'find_entities_by_concept',
    # Cross-cutting.
    'global_search', 'search_ontos_handbook', 'get_app_state', 'get_current_user',
    # Unity Catalog and analytics reads.
    'get_table_schema', 'execute_analytics_query', 'explore_catalog_schema',
    'list_catalogs', 'get_catalog_details', 'list_schemas',
}
# The semantic reads whose REST routes require Read-only on 'semantic-models':
# GET /semantic-models/search, /concepts/hierarchy, /neighbors.
SEMANTIC_READS = {
    'search_glossary_terms': {'term': 'Customer'},
    'get_concept_hierarchy': {'concept_iri': 'http://example.com/onto#Customer'},
    'get_concept_neighbors': {'concept_iri': 'http://example.com/onto#Customer'},
}


def _run(coro):
    return asyncio.run(coro)


def _caller(levels, email='sue@example.com'):
    return ToolCaller(email=email, auth_path='test', permissions=dict(levels))


def _ctx(db=None, caller=None, **managers):
    return ToolContext(db=db if db is not None else MagicMock(), settings=MagicMock(),
                       caller=caller, **managers)


class _Undeclared(BaseTool):
    """A tool whose author forgot ``required_permission``."""
    name = 'undeclared_tool'
    description = 'x'
    required_scope = '*'

    def __init__(self):
        self.ran = 0

    async def execute(self, ctx, **kwargs):
        self.ran += 1
        return ToolResult(success=True, data={'ran': True})


class TestEveryToolDeclaresAPermission:
    def test_each_registered_tool_declares_a_level_or_any_caller(self):
        for tool in create_default_registry().list_tools():
            perm = tool.required_permission
            assert perm, f'{tool.name} declares no required_permission'
            if perm == ANY_CALLER:
                continue
            feature_id, level = perm
            assert feature_id in APP_FEATURES, f'{tool.name}: unknown feature {feature_id}'
            assert isinstance(level, FeatureAccessLevel) and level != NONE, tool.name

    def test_the_tools_that_need_no_feature_level_are_the_listed_ones(self):
        any_caller = {
            t.name for t in create_default_registry().list_tools()
            if t.required_permission == ANY_CALLER
        }
        assert any_caller == ANY_CALLER_TOOLS

    @pytest.mark.parametrize('name', sorted(SEMANTIC_READS))
    def test_a_semantic_read_declares_the_level_of_its_rest_route(self, name):
        tool = create_default_registry().get(name)
        assert tool.required_permission == ('semantic-models', RO)


class TestAnUndeclaredToolIsRefused:
    def test_the_registry_refuses_it_and_does_not_run_it(self):
        registry, tool = ToolRegistry(), _Undeclared()
        registry.register(tool)
        for ctx in (_ctx(), _ctx(caller=_caller({'tags': FeatureAccessLevel.ADMIN})),
                    _ctx(caller=ToolCaller(email=None, auth_path='test', full_access=True))):
            res = _run(registry.execute('undeclared_tool', ctx, {}))
            assert res.success is False
            assert res.error_code == TOOL_NOT_PERMITTED_CODE
            assert 'error id' not in res.error and 'Traceback' not in res.error
        assert tool.ran == 0

    def test_the_check_the_mcp_handler_calls_refuses_it(self):
        refusal = check_tool_permission(_Undeclared(), _ctx())
        assert refusal is not None and refusal.error_code == TOOL_NOT_PERMITTED_CODE

    def test_an_mcp_tool_call_is_refused_and_audited(self):
        audit = MagicMock()
        app = SimpleNamespace(state=SimpleNamespace(workspace_client=object(),
                                                    users_manager=MagicMock()))
        request = SimpleNamespace(headers={}, app=app, state=SimpleNamespace(),
                                  client=SimpleNamespace(host='127.0.0.1'))
        handler = MCPHandler(
            db=None, settings=MagicMock(),
            token_info=SimpleNamespace(id='t1', name='tok', created_by='admin@example.com',
                                       scopes=['*']),
            request=request, audit_manager=audit, session_id='s1',
        )
        tool = _Undeclared()
        handler._tool_registry.register(tool)

        out = _run(handler._handle_tools_call({'name': 'undeclared_tool', 'arguments': {}}))

        assert out['isError'] is True and tool.ran == 0
        assert out['structuredContent']['error_code'] == TOOL_NOT_PERMITTED_CODE
        entry = [c.kwargs for c in audit.log_action.call_args_list
                 if c.kwargs['action'] == 'TOOL_CALL'][0]
        assert entry['details']['error_code'] == TOOL_NOT_PERMITTED_CODE

    def test_any_caller_runs_with_or_without_an_identity(self):
        class _Open(_Undeclared):
            name = 'open_tool'
            required_permission = ANY_CALLER

        registry, tool = ToolRegistry(), _Open()
        registry.register(tool)
        assert _run(registry.execute('open_tool', _ctx(), {})).success is True
        assert _run(registry.execute('open_tool', _ctx(caller=_caller({})), {})).success is True
        assert tool.ran == 2


class TestSemanticReadsNeedReadOnlyOnSemanticModels:
    """Through the registry with the real tool body."""

    @pytest.mark.parametrize('name', sorted(SEMANTIC_READS))
    def test_without_the_level_it_is_refused(self, name):
        registry = create_default_registry()
        manager = MagicMock()
        for caller in (None, _caller({}), _caller({'semantic-models': NONE}),
                       # A level on another feature does not count.
                       _caller({'data-products': FeatureAccessLevel.ADMIN, 'tags': RO})):
            ctx = _ctx(caller=caller, semantic_models_manager=manager)
            res = _run(registry.execute(name, ctx, SEMANTIC_READS[name]))
            assert res.success is False
            assert res.error_code == TOOL_NOT_PERMITTED_CODE
            assert res.to_dict()['feature_id'] == 'semantic-models'
            assert res.to_dict()['required_level'] == RO.value
        assert manager.mock_calls == []

    def test_search_glossary_terms_runs_at_read_only(self):
        manager = MagicMock()
        manager.search_ontology_concepts.return_value = []
        ctx = _ctx(caller=_caller({'semantic-models': RO}), semantic_models_manager=manager)
        res = _run(create_default_registry().execute(
            'search_glossary_terms', ctx, SEMANTIC_READS['search_glossary_terms']))
        assert res.success is True and res.data['terms'] == []
        manager.search_ontology_concepts.assert_called_once()

    def test_get_concept_hierarchy_runs_at_read_only(self):
        manager = MagicMock()
        manager.get_concept_hierarchy.return_value = None
        ctx = _ctx(caller=_caller({'semantic-models': RO}), semantic_models_manager=manager)
        res = _run(create_default_registry().execute(
            'get_concept_hierarchy', ctx, SEMANTIC_READS['get_concept_hierarchy']))
        # Reached the manager: a missing concept, not a refusal.
        assert res.error_code != TOOL_NOT_PERMITTED_CODE
        assert res.error == 'Concept not found: http://example.com/onto#Customer'
        manager.get_concept_hierarchy.assert_called_once()

    def test_get_concept_neighbors_runs_at_read_only(self):
        manager = MagicMock()
        manager.neighbors.return_value = []
        ctx = _ctx(caller=_caller({'semantic-models': RO}), semantic_models_manager=manager)
        res = _run(create_default_registry().execute(
            'get_concept_neighbors', ctx, SEMANTIC_READS['get_concept_neighbors']))
        assert res.success is True
        manager.neighbors.assert_called_once()

    @pytest.mark.parametrize('level', [FeatureAccessLevel.READ_WRITE, FeatureAccessLevel.ADMIN])
    def test_a_higher_level_runs_too(self, level):
        manager = MagicMock()
        manager.search_ontology_concepts.return_value = []
        ctx = _ctx(caller=_caller({'semantic-models': level}), semantic_models_manager=manager)
        res = _run(create_default_registry().execute(
            'search_glossary_terms', ctx, SEMANTIC_READS['search_glossary_terms']))
        assert res.success is True


class TestLinkReadsKeepTheirReadRulesOnly:
    """list_semantic_links / find_entities_by_concept: their REST routes have no
    PermissionChecker, so the tools keep only the product and contract read rules."""

    def _published_product_with_link(self, db_session):
        entity_id = str(uuid.uuid4())
        iri = f'http://example.com/onto#C{uuid.uuid4().hex[:6]}'
        db_session.add(DataProductDb(id=entity_id, api_version='v1.0.0', kind='DataProduct',
                                     name='Linked', version='1.0.0', status='active'))
        db_session.add(EntitySemanticLinkDb(entity_type='data_product', entity_id=entity_id,
                                            iri=iri, label='Customer'))
        db_session.commit()
        return entity_id, iri

    def test_list_semantic_links_runs_without_a_level_on_semantic_models(self, db_session):
        entity_id, iri = self._published_product_with_link(db_session)
        ctx = _ctx(db_session, _caller({'data-products': RO}),
                   semantic_models_manager=MagicMock())
        res = _run(create_default_registry().execute(
            'list_semantic_links', ctx, {'entity_type': 'data_product', 'entity_id': entity_id,
                          'visibility': 'readable'}))
        assert res.success is True
        assert [link['iri'] for link in res.data['links']] == [iri]

    def test_find_entities_by_concept_runs_without_a_level_on_semantic_models(
        self, db_session
    ):
        entity_id, iri = self._published_product_with_link(db_session)
        ctx = _ctx(db_session, _caller({'data-products': RO}),
                   semantic_models_manager=MagicMock())
        res = _run(create_default_registry().execute(
            'find_entities_by_concept', ctx, {'concept_iri': iri, 'visibility': 'readable'}))
        assert res.success is True
        assert [e['entity_id'] for e in res.data['entities']] == [entity_id]
