"""The assistant's read tools apply the product and contract read rules of the REST API.

Personas: a consumer (no ownership), the draft owner, a member of the owning
team, a feature admin, a context without a caller, and the MCP API-key policy
(consumer-only). An item the caller can't read is answered like a missing one;
search drops it before pagination, counts and facets.
"""
import asyncio
import uuid
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import src.tools.caller as tool_caller
from src.common.features import FeatureAccessLevel
from src.common.search_interfaces import SearchIndexItem
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.search_manager import SearchManager
from src.db_models.costs import CostItemDb
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.db_models.semantic_links import EntitySemanticLinkDb
from src.models.users import UserInfo
from src.tools.base import TOOL_NOT_PERMITTED_CODE, ToolCaller, ToolContext
from src.tools.caller import mcp_api_key_caller, resolve_tool_caller
from src.tools.read_access import NOT_READABLE
from src.tools.registry import create_default_registry

TEAM = 'team-owners'
IRI = 'http://example.com/onto#Customer'

CONSUMER = ToolCaller(email='carl@example.com', auth_path='test')
OWNER = ToolCaller(email='sue@example.com', auth_path='test')
MEMBER = ToolCaller(email='tom@example.com', auth_path='test', team_ids={TEAM})
ADMIN = ToolCaller(email='ann@example.com', auth_path='test',
                   products_admin=True, contracts_admin=True)
POLICY = mcp_api_key_caller(SimpleNamespace(created_by='ann@example.com'))

PERSONAS = {
    'consumer': CONSUMER, 'owner': OWNER, 'member': MEMBER, 'admin': ADMIN,
    'no caller': None, 'api-key policy': POLICY,
}


def _run(coro):
    return asyncio.run(coro)


class _Index:
    """A searchable manager over the seeded rows (the index the app builds)."""

    def __init__(self, items):
        self._items = items

    def get_search_index_items(self):
        return self._items


@pytest.fixture
def world(db_session):
    """Two products and three contracts per readable class, indexed for search."""
    def _product(name, status, **kw):
        row = DataProductDb(id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct',
                            name=name, version='1.0.0', status=status, **kw)
        db_session.add(row)
        return row

    def _contract(name, status, **kw):
        row = DataContractDb(id=str(uuid.uuid4()), name=name, version='1.0.0', status=status,
                             kind='DataContract', api_version='v3.0.2', **kw)
        db_session.add(row)
        return row

    p = {
        'published': _product('Pub product', 'active'),
        'other_draft': _product('Other draft product', 'draft',
                                draft_owner_id='olga@example.com'),
        'own_draft': _product('Own draft product', 'draft', draft_owner_id='sue@example.com'),
        'team_draft': _product('Team draft product', 'draft', owner_team_id=TEAM),
    }
    c = {
        'published': _contract('Pub contract', 'active'),
        'other_draft': _contract('Other draft contract', 'draft'),
        'own_draft': _contract('Own draft contract', 'draft', draft_owner_id='sue@example.com'),
        'team_draft': _contract('Team draft contract', 'draft', owner_team_id=TEAM),
    }
    db_session.commit()

    items = [
        SearchIndexItem(id=f'product::{r.id}', type='data-product', feature_id='data-products',
                        title=r.name, description='customer data', link='/x', tags=[],
                        extra_data={'status': r.status, 'domain': 'Sales', 'domains': ['Sales']})
        for r in p.values()
    ] + [
        SearchIndexItem(id=f'contract::{r.id}', type='data-contract',
                        feature_id='data-contracts', title=r.name,
                        description='customer data', link='/x', tags=[],
                        extra_data={'status': r.status, 'domain': 'Sales'})
        for r in c.values()
    ]
    search = SearchManager(searchable_managers=[_Index(items)])
    products = DataProductsManager(db=db_session, ws_client=MagicMock(),
                                   notifications_manager=MagicMock(), tags_manager=MagicMock())
    contracts = DataContractsManager(data_dir=Path('/tmp'))
    return SimpleNamespace(db=db_session, p=p, c=c, search=search,
                           products=products, contracts=contracts)


def _ctx(world, caller):
    return ToolContext(db=world.db, settings=MagicMock(), caller=caller,
                       data_products_manager=world.products,
                       data_contracts_manager=world.contracts,
                       search_manager=world.search)


# What each persona may read (keys of world.p / world.c).
READABLE = {
    'consumer': {'published'},
    'owner': {'published', 'own_draft'},
    'member': {'published', 'team_draft'},
    'admin': {'published', 'other_draft', 'own_draft', 'team_draft'},
    'no caller': {'published'},
    'api-key policy': {'published'},
}


def _call(world, persona, tool, **args):
    return _run(create_default_registry().execute(tool, _ctx(world, PERSONAS[persona]), args))


@pytest.mark.parametrize('persona', sorted(PERSONAS))
class TestByPersona:
    def test_get_data_product(self, world, persona):
        for key, row in world.p.items():
            res = _call(world, persona, 'get_data_product', product_id=row.id)
            if key in READABLE[persona]:
                assert res.success is True, (key, res.error)
                assert res.denied_reason is None
            else:
                assert res.success is False and res.error.endswith('not found'), key
                assert res.denied_reason == NOT_READABLE
        missing = _call(world, persona, 'get_data_product', product_id=str(uuid.uuid4()))
        assert missing.error.endswith('not found') and missing.denied_reason is None

    def test_get_data_products_bulk(self, world, persona):
        ids = [r.id for r in world.p.values()]
        res = _call(world, persona, 'get_data_products', product_ids=ids)
        got = {r['id'] for r in res.data['products']}
        assert got == {world.p[k].id for k in READABLE[persona]}
        assert set(res.data['not_found']) == set(ids) - got
        assert (res.denied_reason == NOT_READABLE) == (len(got) < len(ids))

    def test_get_data_contract(self, world, persona):
        for key, row in world.c.items():
            res = _call(world, persona, 'get_data_contract', contract_id=row.id)
            if key in READABLE[persona]:
                assert res.success is True, (key, res.error)
            else:
                assert res.success is False and res.error.endswith('not found'), key
                assert res.denied_reason == NOT_READABLE

    def test_get_data_contracts_bulk(self, world, persona):
        ids = [r.id for r in world.c.values()]
        res = _call(world, persona, 'get_data_contracts', contract_ids=ids)
        got = {r['id'] for r in res.data['contracts']}
        assert got == {world.c[k].id for k in READABLE[persona]}
        assert set(res.data['not_found']) == set(ids) - got

    @pytest.mark.parametrize('tool, key, rows', [
        ('search_data_products', 'products', 'p'),
        ('list_data_products', 'products', 'p'),
        ('search_data_contracts', 'contracts', 'c'),
        ('list_data_contracts', 'contracts', 'c'),
    ])
    def test_search_and_list(self, world, persona, tool, key, rows):
        args = {'query': '*'} if tool.startswith('search') else {}
        res = _call(world, persona, tool, **args)
        expected = {getattr(world, rows)[k].id for k in READABLE[persona]}
        assert {r['id'] for r in res.data[key]} == expected
        assert res.data['total_found'] == len(expected)
        if 'facets' in res.data and res.data['facets']:
            assert sum(res.data['facets']['status'].values()) == len(expected)

    def test_global_search(self, world, persona):
        res = _call(world, persona, 'global_search', query='*', limit=100)
        expected = {world.p[k].id for k in READABLE[persona]}
        expected |= {world.c[k].id for k in READABLE[persona]}
        got = {r['id'].split('::')[-1] for r in res.data['results']}
        assert got == expected and res.data['total_count'] == len(expected)
        assert sum(res.data['facets']['type'].values()) == len(expected)

    def test_semantic_links(self, world, persona):
        for rows, etype in ((world.p, 'data_product'), (world.c, 'data_contract')):
            for row in rows.values():
                world.db.add(EntitySemanticLinkDb(
                    id=uuid.uuid4(), entity_id=row.id, entity_type=etype, iri=IRI,
                    label='Customer', created_by='x'))
        world.db.commit()

        found = _call(world, persona, 'find_entities_by_concept', concept_iri=IRI)
        expected = {world.p[k].id for k in READABLE[persona]}
        expected |= {world.c[k].id for k in READABLE[persona]}
        assert {e['entity_id'] for e in found.data['entities']} == expected

        for key, row in world.p.items():
            res = _call(world, persona, 'list_semantic_links',
                        entity_type='data_product', entity_id=row.id)
            assert res.data['total_found'] == (1 if key in READABLE[persona] else 0), key

    def test_entity_tags(self, world, persona):
        from src.controller.tags_manager import TagsManager
        from src.models.tags import TagCreate

        tags = TagsManager()
        tag = tags.create_tag(world.db, tag_in=TagCreate(name=f't{uuid.uuid4().hex[:6]}'),
                              user_email='x')
        for row in world.c.values():
            tags.add_tag_to_entity(world.db, entity_id=row.id, entity_type='data_contract',
                                   tag_id=tag.id, assigned_value=None, user_email='x')
        for key, row in world.c.items():
            res = _call(world, persona, 'list_entity_tags',
                        entity_type='data_contract', entity_id=row.id)
            assert res.data['total_count'] == (1 if key in READABLE[persona] else 0), key

    def test_costs(self, world, persona):
        for row in world.p.values():
            world.db.add(CostItemDb(entity_type='data_product', entity_id=row.id, title='c',
                                    cost_center='INFRASTRUCTURE', amount_cents=100,
                                    start_month=date(2026, 1, 1)))
        world.db.commit()
        res = _call(world, persona, 'get_data_product_costs')
        expected = {world.p[k].id for k in READABLE[persona]}
        assert {p['product_id'] for p in res.data['products']} == expected
        total = _call(world, persona, 'get_data_product_costs', aggregate=True)
        assert total.data['product_count'] == len(expected)
        hidden = world.p['other_draft']
        one = _call(world, persona, 'get_data_product_costs', product_id=hidden.id)
        if 'other_draft' in READABLE[persona]:
            assert one.data['total_usd'] == 1.0
        else:
            assert one.data == {'message': 'No cost data found', 'total_usd': 0}

    def test_sparql_is_for_admins_only(self, world, persona):
        semantic = MagicMock()
        semantic.query.return_value = []
        ctx = _ctx(world, PERSONAS[persona])
        ctx.semantic_models_manager = semantic
        res = _run(create_default_registry().execute(
            'execute_sparql_query', ctx, {'sparql': 'SELECT ?s WHERE { ?s ?p ?o }'}))
        # None of them is a semantic-models admin (product/contract admins included).
        assert res.error_code == TOOL_NOT_PERMITTED_CODE
        assert res.to_dict()['required_level'] == 'Admin'
        semantic.query.assert_not_called()


def test_sparql_runs_for_a_semantic_models_admin(world):
    semantic = MagicMock()
    semantic.query.return_value = [{'s': 'x'}]
    caller = ToolCaller(email='ann@example.com', auth_path='test',
                        permissions={'semantic-models': FeatureAccessLevel.ADMIN})
    ctx = _ctx(world, caller)
    ctx.semantic_models_manager = semantic
    res = _run(create_default_registry().execute(
        'execute_sparql_query', ctx, {'sparql': 'SELECT ?s WHERE { ?s ?p ?o }'}))
    assert res.success is True, res.error
    semantic.query.assert_called_once()


class TestSearchPagination:
    """The read rule applies before pagination: pages, counts and has_more agree."""

    def test_pages_hold_only_readable_rows(self, world):
        res = _call(world, 'consumer', 'search_data_products', query='*', limit=1)
        assert res.data['total_found'] == 1 and res.data['has_more'] is False
        res = _call(world, 'member', 'search_data_contracts', query='*', limit=1)
        assert res.data['total_found'] == 2 and res.data['has_more'] is True
        page2 = _call(world, 'member', 'search_data_contracts', query='*', limit=1, offset=1)
        both = {r['id'] for r in res.data['contracts'] + page2.data['contracts']}
        assert both == {world.c['published'].id, world.c['team_draft'].id}

    def test_facets_count_only_readable_rows(self, world):
        res = _call(world, 'owner', 'search_data_products', query='customer')
        assert res.data['facets']['status'] == {'active': 1, 'draft': 1}
        res = _call(world, 'admin', 'search_data_products', query='customer')
        assert res.data['facets']['status'] == {'active': 1, 'draft': 3}


class TestCallerResolution:
    def test_teams_are_looked_up_once_per_request(self, monkeypatch, db_session):
        calls = []

        def _teams(db, email, groups):
            calls.append(email)
            return {TEAM}

        async def _levels(email, groups, request):
            return {}

        async def _not_admin(**kwargs):
            return False

        monkeypatch.setattr(tool_caller, 'lookup_team_ids', _teams)
        monkeypatch.setattr(tool_caller, 'resolve_effective_permissions', _levels)
        monkeypatch.setattr(tool_caller, 'is_product_read_admin', lambda request, user: False)
        monkeypatch.setattr(tool_caller, 'is_user_feature_admin', _not_admin)
        user = UserInfo(email='tom@example.com', username='tom', user='Tom', ip=None,
                        groups=['g'])
        caller = _run(resolve_tool_caller(user, MagicMock(), 'ask_ontos', db_session))
        assert calls == ['tom@example.com'] and caller.team_ids == {TEAM}
        assert not caller.products_admin and not caller.contracts_admin

    def test_a_feature_admin_skips_the_team_lookup(self, monkeypatch, db_session):
        async def _levels(email, groups, request):
            return {}

        async def _admin(**kwargs):
            return True

        def _no_lookup(*a, **k):
            raise AssertionError('admins need no team lookup')

        monkeypatch.setattr(tool_caller, 'lookup_team_ids', _no_lookup)
        monkeypatch.setattr(tool_caller, 'resolve_effective_permissions', _levels)
        monkeypatch.setattr(tool_caller, 'is_product_read_admin', lambda request, user: True)
        monkeypatch.setattr(tool_caller, 'is_user_feature_admin', _admin)
        user = UserInfo(email='ann@example.com', username='ann', user='Ann', ip=None, groups=[])
        caller = _run(resolve_tool_caller(user, MagicMock(), 'ask_ontos', db_session))
        assert caller.products_admin and caller.contracts_admin and caller.team_ids == set()
