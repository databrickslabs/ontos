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

# Read-only on both features, as the default Data Consumer role.
READ = {'data-products': FeatureAccessLevel.READ_ONLY,
        'data-contracts': FeatureAccessLevel.READ_ONLY}
CONSUMER = ToolCaller(email='carl@example.com', auth_path='test', permissions=READ)
OWNER = ToolCaller(email='sue@example.com', auth_path='test', permissions=READ)
MEMBER = ToolCaller(email='tom@example.com', auth_path='test', team_ids={TEAM},
                    permissions=READ)
ADMIN = ToolCaller(email='ann@example.com', auth_path='test',
                   products_admin=True, contracts_admin=True)
# No level on either feature, as the default Security Officer role or no role:
# owning a draft doesn't help.
NO_LEVEL = ToolCaller(email='sue@example.com', auth_path='test')
POLICY = mcp_api_key_caller(SimpleNamespace(
    created_by='ann@example.com', scopes=['data-products:read', 'contracts:read']))

PERSONAS = {
    'consumer': CONSUMER, 'owner': OWNER, 'member': MEMBER, 'admin': ADMIN,
    'no caller': None, 'api-key policy': POLICY, 'no level': NO_LEVEL,
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
    # visibility 'readable' (the Ask Ontos default) is the read rule itself.
    return ToolContext(db=world.db, settings=MagicMock(), caller=caller,
                       data_products_manager=world.products,
                       data_contracts_manager=world.contracts,
                       search_manager=world.search, default_visibility='readable')


# What each persona may read (keys of world.p / world.c).
READABLE = {
    'consumer': {'published'},
    'owner': {'published', 'own_draft'},
    'member': {'published', 'team_draft'},
    'admin': {'published', 'other_draft', 'own_draft', 'team_draft'},
    'no caller': set(),
    'api-key policy': {'published'},
    'no level': set(),
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
        assert sum(res.data['facets'].get('type', {}).values()) == len(expected)

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
        assert {p['product_id'] for p in res.data.get('products', [])} == expected
        total = _call(world, persona, 'get_data_product_costs', aggregate=True)
        assert total.data.get('product_count', 0) == len(expected)
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


# --- Review follow-ups ---------------------------------------------------------

def _graph_iri(entity_type, entity_id):
    return f'urn:ontos:{entity_type}:{entity_id}'


class _Graph:
    """A semantic models manager over a fixed set of neighbor rows and concepts."""

    def __init__(self, neighbors, concepts=()):
        self._neighbors = neighbors
        self._concepts = list(concepts)
        self.asked = []

    def neighbors(self, iri, limit=200):
        self.asked.append(iri)
        return list(self._neighbors)

    def get_concept_hierarchy(self, iri):
        self.asked.append(iri)
        c = SimpleNamespace(iri=iri, label='x', comment=None, concept_type='class',
                            source_context='urn:app-entities')
        nodes = [SimpleNamespace(iri=i, label=i, concept_type='individual')
                 for i in self._concepts]
        return SimpleNamespace(concept=c, ancestors=[], descendants=nodes, siblings=nodes)

    def search_ontology_concepts(self, term, limit=20):
        return [SimpleNamespace(concept=SimpleNamespace(iri=i, label=i, comment=None,
                                                        source_context='urn:app-entities'),
                                relevance_score=1.0, match_type='label')
                for i in self._concepts]


def _graph_ctx(world, caller, graph):
    ctx = _ctx(world, caller)
    ctx.semantic_models_manager = graph
    return ctx


class TestGraphNodes:
    """get_concept_neighbors / get_concept_hierarchy / search_glossary_terms."""

    def _nodes(self, world):
        return {key: _graph_iri('data_product', row.id) for key, row in world.p.items()}

    def test_neighbors_of_the_entity_type_hide_unreadable_products(self, world):
        nodes = self._nodes(world)
        rows = [{'direction': 'incoming', 'predicate': 'rdf:type', 'display': iri,
                 'stepIri': iri, 'stepIsResource': True} for iri in nodes.values()]
        for persona, readable in READABLE.items():
            ctx = _graph_ctx(world, PERSONAS[persona], _Graph(rows))
            res = _run(create_default_registry().execute(
                'get_concept_neighbors', ctx,
                {'concept_iri': 'urn:ontos:entity-type:data_product'}))
            got = {n['step_iri'] for n in res.data['incoming']}
            assert got == {nodes[k] for k in readable}, persona

    def test_an_unreadable_product_node_is_answered_like_an_unknown_iri(self, world):
        iri = self._nodes(world)['other_draft']
        rows = [{'direction': 'outgoing', 'predicate': 'rdfs:label',
                 'display': 'Other draft product', 'stepIri': None}]
        graph = _Graph(rows)
        res = _run(create_default_registry().execute(
            'get_concept_neighbors', _graph_ctx(world, CONSUMER, graph), {'concept_iri': iri}))
        assert res.success is True and res.data['outgoing'] == [] and graph.asked == []
        assert res.denied_reason == NOT_READABLE
        res = _run(create_default_registry().execute(
            'get_concept_neighbors', _graph_ctx(world, ADMIN, graph), {'concept_iri': iri}))
        assert res.data['outgoing'][0]['display'] == 'Other draft product'

    def test_schema_and_property_nodes_follow_their_contract(self, world):
        draft = world.c['other_draft'].id
        rows = [{'direction': 'incoming', 'predicate': 'ontos:semanticAssignment',
                 'display': iri, 'stepIri': iri, 'stepIsResource': True}
                for iri in (_graph_iri('data_contract_schema', f'{draft}#secret'),
                            _graph_iri('data_contract_property', f'{draft}#secret#col'),
                            _graph_iri('data_contract_schema',
                                       f"{world.c['published'].id}#public"))]
        res = _run(create_default_registry().execute(
            'get_concept_neighbors', _graph_ctx(world, CONSUMER, _Graph(rows)),
            {'concept_iri': IRI}))
        assert [n['step_iri'] for n in res.data['incoming']] == [rows[2]['stepIri']]

    def test_hierarchy_and_glossary_search(self, world):
        nodes = self._nodes(world)
        graph = _Graph([], concepts=list(nodes.values()))
        res = _run(create_default_registry().execute(
            'get_concept_hierarchy', _graph_ctx(world, CONSUMER, graph),
            {'concept_iri': 'urn:ontos:entity-type:data_product'}))
        assert {d['iri'] for d in res.data['descendants']} == {nodes['published']}
        assert {d['iri'] for d in res.data['siblings']} == {nodes['published']}
        res = _run(create_default_registry().execute(
            'get_concept_hierarchy', _graph_ctx(world, CONSUMER, graph),
            {'concept_iri': nodes['own_draft']}))
        assert res.success is False and res.error.startswith('Concept not found')
        res = _run(create_default_registry().execute(
            'search_glossary_terms', _graph_ctx(world, OWNER, graph), {'term': 'p'}))
        assert {t['iri'] for t in res.data['terms']} == {nodes['published'], nodes['own_draft']}


class TestDerivedEntities:
    def test_schema_and_property_links_follow_their_contract(self, world):
        draft, pub = world.c['other_draft'].id, world.c['published'].id
        for etype, eid in (('data_contract_schema', f'{draft}#secret_schema'),
                           ('data_contract_property', f'{draft}#secret_schema#col'),
                           ('data_contract_schema', f'{pub}#public')):
            world.db.add(EntitySemanticLinkDb(id=uuid.uuid4(), entity_id=eid, entity_type=etype,
                                              iri=IRI, label='Customer', created_by='x'))
        world.db.commit()
        found = _call(world, 'consumer', 'find_entities_by_concept', concept_iri=IRI)
        assert {e['entity_id'] for e in found.data['entities']} == {f'{pub}#public'}
        admin = _call(world, 'admin', 'find_entities_by_concept', concept_iri=IRI)
        assert len(admin.data['entities']) == 3
        res = _call(world, 'consumer', 'list_semantic_links',
                    entity_type='data_contract_schema', entity_id=f'{draft}#secret_schema')
        assert res.data['total_found'] == 0


class TestAllowList:
    def test_an_index_entry_without_a_readable_row_is_left_out(self, world):
        # E.g. another session's draft, indexed before its transaction commits.
        ghost = SearchIndexItem(id='product::not-committed', type='data-product',
                                feature_id='data-products', title='Ghost', description='x',
                                link='/x', tags=[], extra_data={'status': 'draft'})
        world.search.index.append(ghost)
        res = _call(world, 'consumer', 'search_data_products', query='*')
        assert 'not-committed' not in {r['id'] for r in res.data['products']}
        assert res.data['total_found'] == 1
        # A feature admin reading every version keeps the no-filter path. (The
        # default, one version per family, needs the rows, so it lists rows only.)
        res = _call(world, 'admin', 'search_data_products', query='*', include_history=True)
        assert 'not-committed' in {r['id'] for r in res.data['products']}


class TestAppState:
    def test_totals_count_only_readable_items(self, world):
        for persona, readable in READABLE.items():
            res = _call(world, persona, 'get_app_state')
            assert res.data['counts']['data_products_total'] == len(readable), persona
            assert res.data['counts']['data_contracts_total'] == len(readable), persona


class TestOneQueryPerRequest:
    def test_project_membership_is_resolved_once(self, world, monkeypatch):
        from src.controller.projects_manager import projects_manager
        from src.db_models.projects import ProjectDb, project_team_association
        from src.db_models.teams import TeamDb, TeamMemberDb

        team = TeamDb(id=str(uuid.uuid4()), name=f't{uuid.uuid4().hex[:6]}',
                      created_by='x', updated_by='x')
        proj = ProjectDb(id=str(uuid.uuid4()), name=f'p{uuid.uuid4().hex[:6]}',
                         created_by='x', updated_by='x')
        world.db.add_all([team, proj])
        world.db.flush()
        world.db.add(TeamMemberDb(team_id=team.id, member_type='user',
                                  member_identifier='pat@example.com', added_by='x'))
        world.db.execute(project_team_association.insert().values(
            project_id=proj.id, team_id=team.id, assigned_by='x'))
        in_project = DataProductDb(id=str(uuid.uuid4()), api_version='v1.0.0',
                                   kind='DataProduct', name='Project draft', version='1.0.0',
                                   status='draft', project_id=proj.id)
        world.db.add(in_project)
        world.db.commit()

        def _no_per_product_query(**kwargs):
            raise AssertionError('membership is resolved once per request')

        monkeypatch.setattr(projects_manager, 'is_user_project_member', _no_per_product_query)

        async def _levels(email, groups, request):
            return dict(READ)

        async def _not_admin(**kwargs):
            return False

        monkeypatch.setattr(tool_caller, 'resolve_effective_permissions', _levels)
        monkeypatch.setattr(tool_caller, 'is_product_read_admin', lambda request, user: False)
        monkeypatch.setattr(tool_caller, 'is_user_feature_admin', _not_admin)
        user = UserInfo(email='pat@example.com', username='pat', user='Pat', ip=None, groups=[])
        pat = _run(resolve_tool_caller(user, MagicMock(), 'ask_ontos', world.db))
        assert pat.project_ids == {proj.id}

        ctx = _ctx(world, pat)
        res = _run(create_default_registry().execute(
            'get_data_products', ctx, {'product_ids': [in_project.id, world.p['own_draft'].id]}))
        assert {p['id'] for p in res.data['products']} == {in_project.id}

    def test_readable_sets_are_computed_once_per_context(self, world, monkeypatch):
        from src.tools import read_access

        calls = []
        real = read_access.can_read_product

        def _counting(ctx, product):
            calls.append(product.id)
            return real(ctx, product)

        monkeypatch.setattr(read_access, 'can_read_product', _counting)
        ctx = _ctx(world, CONSUMER)
        read_access.readable_ids(ctx, read_access.PRODUCT_TYPE)
        first = len(calls)
        read_access.readable_ids(ctx, read_access.PRODUCT_TYPE)
        assert first == len(world.p) and len(calls) == first


# --- Re-review follow-ups -------------------------------------------------------

L = FeatureAccessLevel
# Feature levels to change things, but no ownership and not a feature admin.
WRITER = ToolCaller(email='carl@example.com', auth_path='test', permissions={
    'data-products': L.ADMIN, 'data-contracts': L.READ_WRITE,
    'semantic-models': L.READ_WRITE, 'tags': L.READ_WRITE,
})


def _write(world, tool, caller=WRITER, **args):
    return _run(create_default_registry().execute(tool, _ctx(world, caller), args))


class TestWritesApplyTheReadRule:
    """Changing or linking an unreadable item answers exactly like a missing id."""

    def _same_as_missing(self, world, tool, id_key, real_id, **args):
        missing = str(uuid.uuid4())
        got = _write(world, tool, **{id_key: real_id}, **args)
        ref = _write(world, tool, **{id_key: missing}, **args)
        assert got.success is False and ref.success is False
        assert got.error == ref.error.replace(missing, real_id)
        assert got.data == ref.data and got.error_code == ref.error_code
        return got

    def test_update_and_delete_products(self, world):
        row = world.p['other_draft']
        res = self._same_as_missing(world, 'update_data_product', 'product_id', row.id,
                                    status='draft')
        assert 'Other draft' not in str(res.to_dict())
        self._same_as_missing(world, 'delete_data_product', 'product_id', row.id)
        world.db.expire_all()
        assert world.db.get(DataProductDb, row.id) is not None

    def test_update_and_delete_contracts(self, world):
        row = world.c['other_draft']
        self._same_as_missing(world, 'update_data_contract', 'contract_id', row.id,
                              status='retired')
        self._same_as_missing(world, 'delete_data_contract', 'contract_id', row.id)
        world.db.expire_all()
        assert world.db.get(DataContractDb, row.id) is not None

    def test_a_readable_contract_is_still_deleted(self, world):
        row = world.c['published']
        assert _write(world, 'delete_data_contract', contract_id=row.id).success is True

    def test_links_and_tags(self, world):
        draft = world.c['other_draft'].id
        world.db.add(EntitySemanticLinkDb(id=uuid.uuid4(), entity_id=draft,
                                          entity_type='data_contract', iri=IRI, label='C',
                                          created_by='x'))
        world.db.commit()
        link_args = {'entity_type': 'data_contract', 'concept_iri': IRI, 'concept_label': 'C'}
        self._same_as_missing(world, 'add_semantic_link', 'entity_id', draft, **link_args)
        self._same_as_missing(world, 'add_semantic_link', 'entity_id', f'{draft}#schema',
                              entity_type='data_contract_schema', concept_iri=IRI,
                              concept_label='C')
        link = world.db.query(EntitySemanticLinkDb).filter_by(entity_id=draft).one()
        self._same_as_missing(world, 'remove_semantic_link', 'link_id', str(link.id))
        assert world.db.query(EntitySemanticLinkDb).filter_by(entity_id=draft).count() == 1
        tag_args = {'entity_type': 'data_contract', 'tag_id': str(uuid.uuid4())}
        for tool in ('assign_tag_to_entity', 'remove_tag_from_entity'):
            res = _write(world, tool, entity_id=draft, **tag_args)
            assert res.error == f"data_contract '{draft}' not found"

    def test_a_draft_product_cannot_point_at_an_unreadable_contract(self, world):
        res = self._same_as_missing(world, 'create_draft_data_product', 'contract_id',
                                    world.c['other_draft'].id, name='x', description='y',
                                    domain='z', output_tables=['a.b.c'])
        assert res.error.startswith('Data contract')

    def test_a_contract_in_a_project_needs_a_member(self, world):
        row = world.c['published']
        row.project_id = 'proj-1'
        world.db.commit()
        res = _write(world, 'update_data_contract', contract_id=row.id, description='new')
        assert res.error_code == 'project_membership_required'
        member = ToolCaller(email='carl@example.com', auth_path='test',
                            permissions=WRITER.permissions, project_ids={'proj-1'})
        res = _write(world, 'update_data_contract', member, contract_id=row.id,
                     description='new')
        assert res.error_code != 'project_membership_required'


def test_readable_ids_read_only_the_rule_columns(world):
    from sqlalchemy import event

    from src.tools import read_access

    statements = []
    engine = world.db.get_bind()

    def _count(conn, cursor, statement, *args):
        statements.append(statement)

    event.listen(engine, 'before_cursor_execute', _count)
    try:
        ids = read_access.readable_ids(_ctx(world, CONSUMER), read_access.PRODUCT_TYPE)
    finally:
        event.remove(engine, 'before_cursor_execute', _count)
    assert ids == {world.p['published'].id}
    assert len(statements) == 1, statements
    assert 'data_products.name' not in statements[0]


def test_app_state_published_count_follows_the_read_rule(world):
    world.p['other_draft'].publication_scope = 'organization'
    world.p['published'].publication_scope = 'organization'
    world.db.commit()
    res = _call(world, 'consumer', 'get_app_state')
    counts = res.data['counts']
    assert counts['data_products_published'] == 1 <= counts['data_products_total']
    assert _call(world, 'admin', 'get_app_state').data['counts']['data_products_published'] == 2


# --- The feature's Read-only level (option A, 2026-10-31) ------------------------

class TestReadLevel:
    def test_global_search_drops_rows_of_features_without_the_level(self, world):
        term = SearchIndexItem(id='term::1', type='glossary-term', feature_id='semantic-models',
                               title='Customer term', description='customer data',
                               link='/x', tags=[], extra_data={})
        world.search.index.append(term)
        res = _call(world, 'consumer', 'global_search', query='*', limit=100)
        assert 'glossary-term' not in res.data['facets'].get('type', {})
        assert res.data['total_count'] == 2  # the published product and contract
        reader = ToolCaller(email='carl@example.com', auth_path='test',
                            permissions={**READ, 'semantic-models': FeatureAccessLevel.READ_ONLY})
        res = _run(create_default_registry().execute(
            'global_search', _ctx(world, reader), {'query': '*', 'limit': 100}))
        assert res.data['facets']['type']['glossary-term'] == 1
        assert res.data['total_count'] == 3

    def test_api_key_scopes_grant_read_levels(self):
        from src.tools.caller import scope_read_levels

        ro = FeatureAccessLevel.READ_ONLY
        assert scope_read_levels(['data-products:read', 'contracts:write', 'search:read']) == {
            'data-products': ro, 'data-contracts': ro}
        assert set(scope_read_levels(['*'])) == {
            'data-products', 'data-contracts', 'data-domains', 'teams', 'projects',
            'semantic-models', 'tags'}
        assert scope_read_levels(['search:read', 'analytics:read']) == {}

    def test_an_api_key_without_product_scopes_reads_no_products(self, world):
        caller = mcp_api_key_caller(SimpleNamespace(scopes=['search:read']))
        res = _run(create_default_registry().execute(
            'global_search', _ctx(world, caller), {'query': '*'}))
        assert res.data['total_count'] == 0


class TestReadLevelThroughMcp:
    """A forwarded user without the level gets no products or contracts over MCP."""

    def _handler(self, world, monkeypatch, levels, headers=None):
        import src.routes.mcp_routes as mcp_routes
        from src.routes.mcp_routes import MCPHandler

        async def _levels(email, groups, request):
            return dict(levels)

        async def _not_admin(**kwargs):
            return False

        monkeypatch.setattr(mcp_routes, 'get_obo_workspace_client', lambda *a, **k: object())
        monkeypatch.setattr(tool_caller, 'resolve_effective_permissions', _levels)
        monkeypatch.setattr(tool_caller, 'is_product_read_admin', lambda request, user: False)
        monkeypatch.setattr(tool_caller, 'is_user_feature_admin', _not_admin)
        users = MagicMock()
        users.get_current_user.return_value = UserInfo(
            email='sec@example.com', username='sec@example.com', user='Sec', ip=None,
            groups=['security'])
        state = SimpleNamespace(workspace_client=object(), users_manager=users,
                                data_products_manager=world.products,
                                data_contracts_manager=world.contracts,
                                search_manager=world.search, semantic_models_manager=None)
        request = SimpleNamespace(headers=headers or {'x-forwarded-access-token': 't'},
                                  app=SimpleNamespace(state=state), state=SimpleNamespace(),
                                  client=SimpleNamespace(host='127.0.0.1'))
        return MCPHandler(db=world.db, settings=MagicMock(),
                          token_info=SimpleNamespace(id='t1', name='tok', created_by=None,
                                                     scopes=['*']),
                          request=request, audit_manager=MagicMock(), session_id='s')

    def _call(self, handler, tool, **args):
        import json

        out = _run(handler._handle_tools_call({'name': tool, 'arguments': args}))
        return out['isError'], (json.loads(out['content'][0]['text'])
                                if not out['isError'] else out['content'][0]['text'])

    def test_security_officer_reads_nothing_and_a_consumer_reads_published(
        self, world, monkeypatch
    ):
        pub = world.p['published'].id
        officer = self._handler(world, monkeypatch, {'settings': FeatureAccessLevel.ADMIN})
        err, data = self._call(officer, 'search_data_products', query='*')
        assert not err and data['total_found'] == 0 and data['products'] == []
        err, text = self._call(officer, 'get_data_product', product_id=pub)
        assert err and text == f"Data product '{pub}' not found"
        err, data = self._call(officer, 'list_data_contracts')
        assert data['total_found'] == 0

        consumer = self._handler(world, monkeypatch, READ)
        err, data = self._call(consumer, 'search_data_products', query='*',
                               visibility='readable')
        assert {p['id'] for p in data['products']} == {pub}
        assert self._call(consumer, 'get_data_product', product_id=pub)[0] is False
