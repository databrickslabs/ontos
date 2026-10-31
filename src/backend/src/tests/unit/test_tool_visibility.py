"""The ``visibility`` of the search and list tools (published vs readable).

``published`` (the MCP default) is the marketplace rule: active with a
publication scope other than none. ``readable`` (the Ask Ontos default) is the
read rule. Neither goes beyond the read rule; get-by-id uses only the read rule.
All of it applies before pagination, counts and facets, and rows echo their
status, publication scope and certification level.
"""
import asyncio
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.features import FeatureAccessLevel
from src.common.search_interfaces import SearchIndexItem
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.llm_search_manager import LLMSearchManager
from src.controller.search_manager import SearchManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.routes.mcp_routes import MCPHandler
from src.tools.base import ToolCaller, ToolContext
from src.tools.registry import create_default_registry
from src.tools.visibility import INVALID_VISIBILITY_CODE, VISIBILITY_DESCRIPTION

IRI = 'http://example.com/onto#Order'
_RO = FeatureAccessLevel.READ_ONLY
READ = {'data-products': _RO, 'data-contracts': _RO}
SUE = ToolCaller(email='sue@example.com', auth_path='test', permissions=READ)
CONSUMER = ToolCaller(email='carl@example.com', auth_path='test', permissions=READ)
ADMIN = ToolCaller(email='ann@example.com', auth_path='test',
                   products_admin=True, contracts_admin=True,
                   permissions={'semantic-models': _RO})
NOW = datetime(2026, 10, 1)


def _run(coro):
    return asyncio.run(coro)


class _Index:
    def __init__(self, items):
        self._items = items

    def get_search_index_items(self):
        return self._items


@pytest.fixture
def world(db_session):
    family = str(uuid.uuid4())

    def _product(key, status, scope='none', **kw):
        row = DataProductDb(id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
                            name=f'P {key}', version='1.0.0', status=status,
                            publication_scope=scope, **kw)
        db_session.add(row)
        return row

    def _contract(key, status, scope='none', **kw):
        row = DataContractDb(id=str(uuid.uuid4()), name=f'C {key}', version='1.0.0',
                             status=status, kind='DataContract', api_version='v3.0.2',
                             publication_scope=scope, **kw)
        db_session.add(row)
        return row

    p = {
        'published': _product('published', 'active', 'organization'),
        'certified': _product('certified', 'active', 'organization', certification_level=3),
        'unscoped': _product('unscoped', 'active'),
        'own_draft': _product('own_draft', 'draft', draft_owner_id='sue@example.com'),
        'other_draft': _product('other_draft', 'draft', draft_owner_id='olga@example.com'),
        'v1': _product('v1', 'active', 'organization', version_family_id=family,
                       created_at=NOW - timedelta(days=30)),
        'v2': _product('v2', 'active', 'organization', version_family_id=family,
                       created_at=NOW),
    }
    c = {
        'published': _contract('published', 'active', 'organization'),
        'unscoped': _contract('unscoped', 'active'),
        'own_draft': _contract('own_draft', 'draft', draft_owner_id='sue@example.com'),
    }
    db_session.commit()

    items = [
        SearchIndexItem(id=f'product::{r.id}', type='data-product', feature_id='data-products',
                        title=r.name, description='orders', link='/x', tags=[],
                        extra_data={'status': r.status})
        for r in p.values()
    ] + [
        SearchIndexItem(id=f'contract::{r.id}', type='data-contract',
                        feature_id='data-contracts', title=r.name, description='orders',
                        link='/x', tags=[], extra_data={'status': r.status})
        for r in c.values()
    ] + [
        SearchIndexItem(id='term::1', type='glossary-term', feature_id='semantic-models',
                        title='Order term', description='orders', link='/x', tags=[],
                        extra_data={}),
    ]
    return SimpleNamespace(
        db=db_session, p=p, c=c,
        search=SearchManager(searchable_managers=[_Index(items)]),
        products=DataProductsManager(db=db_session, ws_client=MagicMock(),
                                     notifications_manager=MagicMock(),
                                     tags_manager=MagicMock()),
        contracts=DataContractsManager(data_dir=Path('/tmp')),
    )


def _call(world, caller, tool, default='published', **args):
    ctx = ToolContext(db=world.db, settings=MagicMock(), caller=caller,
                      data_products_manager=world.products,
                      data_contracts_manager=world.contracts,
                      search_manager=world.search, default_visibility=default)
    return _run(create_default_registry().execute(tool, ctx, args))


def _ids(rows, keys):
    return {r['id'] for r in rows}, {k for k in keys}


def _product_ids(world, *keys):
    return {world.p[k].id for k in keys}


class TestSearchProducts:
    def test_mcp_default_is_published_only(self, world):
        res = _call(world, ADMIN, 'search_data_products', query='*')
        assert res.data['visibility'] == 'published'
        got = {r['id'] for r in res.data['products']}
        assert got == _product_ids(world, 'published', 'certified', 'v2')
        assert res.data['total_found'] == 3
        assert res.data['facets']['status'] == {'active': 3}
        for row in res.data['products']:
            assert row['status'] == 'active' and row['publication_scope'] == 'organization'
            assert 'certification_level' in row

    def test_ask_ontos_default_is_readable(self, world):
        res = _call(world, SUE, 'search_data_products', default='readable', query='*')
        assert res.data['visibility'] == 'readable'
        got = {r['id'] for r in res.data['products']}
        assert got == _product_ids(world, 'published', 'certified', 'unscoped', 'own_draft', 'v2')

    def test_readable_never_goes_beyond_the_read_rule(self, world):
        res = _call(world, CONSUMER, 'search_data_products', query='*', visibility='readable')
        got = {r['id'] for r in res.data['products']}
        assert got == _product_ids(world, 'published', 'certified', 'unscoped', 'v2')

    def test_published_for_an_admin_too(self, world):
        res = _call(world, ADMIN, 'list_data_products', default='readable',
                    visibility='published')
        assert {r['id'] for r in res.data['products']} == _product_ids(
            world, 'published', 'certified', 'v2')

    def test_min_certification_level(self, world):
        res = _call(world, ADMIN, 'search_data_products', query='*', min_certification_level=2)
        assert {r['id'] for r in res.data['products']} == _product_ids(world, 'certified')
        assert res.data['products'][0]['certification_level'] == 3

    def test_include_history(self, world):
        res = _call(world, ADMIN, 'search_data_products', query='*', include_history=True)
        assert {r['id'] for r in res.data['products']} == _product_ids(
            world, 'published', 'certified', 'v1', 'v2')

    def test_applied_before_pagination(self, world):
        first = _call(world, ADMIN, 'search_data_products', query='*', limit=2)
        assert first.data['total_found'] == 3 and first.data['has_more'] is True
        second = _call(world, ADMIN, 'search_data_products', query='*', limit=2, offset=2)
        assert second.data['has_more'] is False
        both = {r['id'] for r in first.data['products'] + second.data['products']}
        assert both == _product_ids(world, 'published', 'certified', 'v2')

    def test_an_unknown_visibility_is_a_coded_error(self, world):
        res = _call(world, ADMIN, 'search_data_products', query='*', visibility='all')
        assert res.success is False and res.error_code == INVALID_VISIBILITY_CODE


class TestOtherTools:
    def test_contracts(self, world):
        res = _call(world, SUE, 'search_data_contracts', query='*')
        assert {r['id'] for r in res.data['contracts']} == {world.c['published'].id}
        res = _call(world, SUE, 'list_data_contracts', visibility='readable')
        assert {r['id'] for r in res.data['contracts']} == {
            world.c['published'].id, world.c['unscoped'].id, world.c['own_draft'].id}

    def test_global_search_leaves_other_types_alone(self, world):
        res = _call(world, ADMIN, 'global_search', query='*', limit=100)
        assert res.data['visibility'] == 'published'
        by_type = {}
        for r in res.data['results']:
            by_type.setdefault(r['type'], set()).add(r['id'])
        assert by_type['data-product'] == _product_ids(world, 'published', 'certified', 'v2')
        assert by_type['data-contract'] == {world.c['published'].id}
        assert by_type['glossary-term'] == {'1'}
        assert res.data['total_count'] == 5

    def test_get_by_id_uses_only_the_read_rule(self, world):
        res = _call(world, CONSUMER, 'get_data_product', product_id=world.p['unscoped'].id)
        assert res.success is True
        res = _call(world, SUE, 'get_data_product', product_id=world.p['own_draft'].id)
        assert res.success is True

    def test_semantic_tools(self, world):
        for key in ('published', 'unscoped', 'own_draft', 'other_draft'):
            world.db.add(EntitySemanticLinkDb(
                id=uuid.uuid4(), entity_id=world.p[key].id, entity_type='data_product',
                iri=IRI, label='Order', created_by='x'))
        world.db.commit()

        res = _call(world, SUE, 'find_entities_by_concept', concept_iri=IRI)
        assert {e['entity_id'] for e in res.data['entities']} == _product_ids(world, 'published')
        assert res.data['entities'][0]['publication_scope'] == 'organization'
        res = _call(world, SUE, 'find_entities_by_concept', concept_iri=IRI,
                    visibility='readable')
        assert {e['entity_id'] for e in res.data['entities']} == _product_ids(
            world, 'published', 'unscoped', 'own_draft')

        def _links(key, **kw):
            return _call(world, SUE, 'list_semantic_links', entity_type='data_product',
                         entity_id=world.p[key].id, **kw).data['total_found']

        assert (_links('published'), _links('unscoped'), _links('own_draft')) == (1, 0, 0)
        assert _links('own_draft', visibility='readable') == 1
        assert _links('other_draft', visibility='readable') == 0


class TestDefaultsAndDescriptions:
    def test_each_tool_has_the_parameter_and_the_description(self):
        registry = create_default_registry()
        for name in ('search_data_products', 'list_data_products', 'search_data_contracts',
                     'list_data_contracts', 'global_search', 'find_entities_by_concept',
                     'list_semantic_links'):
            tool = registry.get(name)
            assert tool.parameters['visibility']['enum'] == ['published', 'readable'], name
            assert VISIBILITY_DESCRIPTION in tool.description, name
        for name in ('search_data_products', 'list_data_contracts', 'global_search'):
            assert {'min_certification_level', 'include_history'} <= set(
                registry.get(name).parameters), name

    def test_ask_ontos_reads_and_mcp_publishes_by_default(self):
        mgr = LLMSearchManager(db=MagicMock(), settings=MagicMock())
        assert mgr._create_tool_context().default_visibility == 'readable'
        app = SimpleNamespace(state=SimpleNamespace(workspace_client=None))
        request = SimpleNamespace(headers={}, app=app, client=None)
        handler = MCPHandler(db=None, settings=MagicMock(),
                             token_info=SimpleNamespace(name='t', created_by=None, scopes=[]),
                             request=request)
        assert handler._create_tool_context().default_visibility == 'published'


class TestCollapseAfterFilters:
    """One version per family is chosen among the rows that match, as in REST."""

    @pytest.fixture
    def family(self, world):
        fam = str(uuid.uuid4())
        old = DataProductDb(id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
                            name='Ledger classic', version='1.0.0', status='active',
                            publication_scope='organization', version_family_id=fam,
                            created_at=NOW - timedelta(days=60))
        new = DataProductDb(id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
                            name='Ledger next', version='2.0.0', status='draft',
                            draft_owner_id='sue@example.com', version_family_id=fam,
                            created_at=NOW)
        world.db.add_all([old, new])
        world.db.commit()
        for row in (old, new):
            world.search.index.append(SearchIndexItem(
                id=f'product::{row.id}', type='data-product', feature_id='data-products',
                title=row.name, description='ledger', link='/x', tags=[],
                extra_data={'status': row.status}))
        return SimpleNamespace(old=old, new=new)

    @pytest.mark.parametrize('caller', [SUE, ADMIN])
    def test_a_status_filter_keeps_the_matching_version(self, world, family, caller):
        res = _call(world, caller, 'list_data_products', default='readable', status='active')
        assert family.old.id in {r['id'] for r in res.data['products']}
        res = _call(world, caller, 'list_data_products', default='readable')
        ids = {r['id'] for r in res.data['products']}
        assert family.new.id in ids and family.old.id not in ids

    def test_a_query_keeps_the_matching_version(self, world, family):
        res = _call(world, SUE, 'search_data_products', default='readable', query='classic')
        assert [r['id'] for r in res.data['products']] == [family.old.id]
        assert res.data['total_found'] == 1


def test_fields_keep_the_echoed_status_scope_and_certification(world):
    res = _call(world, ADMIN, 'search_data_products', query='*', fields=['title'])
    for row in res.data['products']:
        assert set(row) >= {'id', 'title', 'status', 'publication_scope', 'certification_level'}
    res = _call(world, ADMIN, 'list_data_contracts')
    assert res.data['contracts'][0]['publication_scope'] == 'organization'
