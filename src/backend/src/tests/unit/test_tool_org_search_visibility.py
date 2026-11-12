"""The org search tools return only the teams and projects the caller sees over REST.

- ``search_teams``: ``GET /api/teams`` needs Read-only on ``teams``.
- ``search_projects``: ``GET /api/projects`` needs Read-only on ``projects``
  and lists only the projects ``ProjectsManager.get_all_projects`` shows the
  caller (admin groups: all; others: the team-domain relationship).
- ``global_search``: ``/api/search`` drops the ``project`` rows the list hides
  (``SearchManager._apply_project_visibility``).

The get tools and the domain and tag read tools need the Read-only level of
their REST GET routes (``teams``, ``projects``, ``data-domains``, ``tags``);
``get_project`` also applies the project list's visibility. Without it, the
answer is the tool's empty or "not found" one, as for a missing item.

The admin sees everything on both paths, so the cases are for non-admins.
"""
import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.features import FeatureAccessLevel
from src.common.search_interfaces import SearchIndexItem
from src.controller.search_manager import SearchManager
from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.projects import ProjectDb
from src.db_models.teams import TeamDb, TeamMemberDb
from src.tools.base import ToolCaller, ToolContext
from src.tools.read_access import NOT_READABLE
from src.tools.caller import mcp_api_key_caller
from src.tools.registry import create_default_registry

RO = FeatureAccessLevel.READ_ONLY
LEVELS = {'teams': RO, 'projects': RO}
# No team: sees the public projects only.
OUTSIDER = ToolCaller(email='carl@example.com', auth_path='test', permissions=LEVELS,
                      groups=['users'])
# Member of the team that owns the private project.
MEMBER = ToolCaller(email='tom@example.com', auth_path='test', permissions=LEVELS,
                    groups=['users'])
# In the configured admin groups (resolve_tool_caller: project_ids None).
ADMIN = ToolCaller(email='ann@example.com', auth_path='test', permissions=LEVELS,
                   groups=['admins'], project_ids=None)
# No level on either feature (e.g. no role).
NO_LEVEL = ToolCaller(email='tom@example.com', auth_path='test')
# Read-only on domains and tags too.
READER = ToolCaller(email='carl@example.com', auth_path='test',
                    permissions={**LEVELS, 'data-domains': RO, 'tags': RO})


def _run(coro):
    return asyncio.run(coro)


class _Index:
    def __init__(self, items):
        self._items = items

    def get_search_index_items(self):
        return self._items


@pytest.fixture
def world(db_session):
    """A team with a domain owning a private project, plus a public project."""
    domain = DataDomain(id=str(uuid.uuid4()), name=f'sales-{uuid.uuid4().hex[:6]}',
                        created_by='x')
    team = TeamDb(id=str(uuid.uuid4()), name=f'owners-{uuid.uuid4().hex[:6]}',
                  description='customer team', created_by='x', updated_by='x')
    db_session.add_all([domain, team])
    db_session.flush()
    db_session.add(EntityDomainAssociationDb(domain_id=domain.id, entity_id=team.id,
                                             entity_type='team', is_primary=True))
    db_session.add(TeamMemberDb(team_id=team.id, member_type='user',
                                member_identifier='tom@example.com', added_by='x'))
    private = ProjectDb(id=str(uuid.uuid4()), name=f'private-{uuid.uuid4().hex[:6]}',
                        description='customer project', owner_team_id=team.id,
                        created_by='x', updated_by='x')
    public = ProjectDb(id=str(uuid.uuid4()), name=f'public-{uuid.uuid4().hex[:6]}',
                       description='customer project', created_by='x', updated_by='x')
    db_session.add_all([private, public])
    db_session.commit()

    items = [
        SearchIndexItem(id=f'project::{p.id}', type='project', feature_id='projects',
                        title=p.name, description='customer project', link='/x', tags=[])
        for p in (private, public)
    ] + [SearchIndexItem(id=f'team::{team.id}', type='team', feature_id='teams',
                         title=team.name, description='customer team', link='/x', tags=[])]
    from src.controller.tags_manager import TagsManager
    from src.models.tags import TagCreate

    tags = TagsManager()
    tag = tags.create_tag(db_session, tag_in=TagCreate(name=f't{uuid.uuid4().hex[:6]}'),
                          user_email='x')
    tags.add_tag_to_entity(db_session, entity_id=team.id, entity_type='team', tag_id=tag.id,
                           assigned_value=None, user_email='x')
    items += [
        SearchIndexItem(id=f'domain::{domain.id}', type='data-domain', feature_id='data-domains',
                        title=domain.name, description='customer domain', link='/x', tags=[]),
        SearchIndexItem(id=f'tag::{tag.id}', type='tag', feature_id='tags', title=tag.name,
                        description='customer tag', link='/x', tags=[], extra_data={}),
    ]
    return SimpleNamespace(db=db_session, team=team, private=private, public=public,
                           domain=domain, tag=tag,
                           search=SearchManager(searchable_managers=[_Index(items)]))


def _call(world, caller, tool, **args):
    ctx = ToolContext(db=world.db, settings=MagicMock(), caller=caller,
                      search_manager=world.search)
    res = _run(create_default_registry().execute(tool, ctx, {'query': '*', **args}))
    assert res.success is True, res.error
    return res.data


def _exec(world, caller, tool, **args):
    ctx = ToolContext(db=world.db, settings=MagicMock(), caller=caller,
                      search_manager=world.search)
    return _run(create_default_registry().execute(tool, ctx, args))


def _assert_not_found(res):
    assert res.success is False and 'not found' in res.error, res.error
    assert res.denied_reason == NOT_READABLE


def _ids(rows):
    return {r['id'].split('::')[-1] for r in rows}


class TestSearchProjects:
    def test_a_non_member_does_not_see_a_project_the_list_hides(self, world):
        data = _call(world, OUTSIDER, 'search_projects')
        assert _ids(data['projects']) == {world.public.id}
        assert data['total_found'] == 1

    def test_a_member_and_an_admin_see_it(self, world):
        both = {world.public.id, world.private.id}
        assert _ids(_call(world, MEMBER, 'search_projects')['projects']) == both
        assert _ids(_call(world, ADMIN, 'search_projects')['projects']) == both

    def test_without_the_level_nothing_is_returned(self, world):
        data = _call(world, NO_LEVEL, 'search_projects')
        assert data['projects'] == [] and data['total_found'] == 0

    def test_without_a_user_nothing_is_returned(self, world):
        # As GET /api/projects without a user, and the API-key (no user) policy.
        caller = mcp_api_key_caller(SimpleNamespace(scopes=['projects:read']))
        assert _call(world, caller, 'search_projects')['projects'] == []
        assert _call(world, None, 'search_projects')['projects'] == []


class TestSearchTeams:
    def test_without_the_level_nothing_is_returned(self, world):
        data = _call(world, NO_LEVEL, 'search_teams')
        assert data['teams'] == [] and data['total_found'] == 0
        assert _call(world, None, 'search_teams')['teams'] == []

    def test_with_the_level_teams_are_listed(self, world):
        assert _ids(_call(world, OUTSIDER, 'search_teams')['teams']) == {world.team.id}
        caller = mcp_api_key_caller(SimpleNamespace(scopes=['teams:read']))
        assert _ids(_call(world, caller, 'search_teams')['teams']) == {world.team.id}


class TestGlobalSearch:
    def _projects(self, data):
        return _ids(r for r in data['results'] if r['type'] == 'project')

    def test_a_non_member_does_not_see_a_project_the_list_hides(self, world):
        data = _call(world, OUTSIDER, 'global_search', limit=100)
        assert self._projects(data) == {world.public.id}
        # Dropped before the counts and facets, as the read rules.
        assert data['total_count'] == 2  # the public project and the team
        assert data['facets']['type'] == {'project': 1, 'team': 1}

    def test_a_member_and_an_admin_see_it(self, world):
        both = {world.public.id, world.private.id}
        assert self._projects(_call(world, MEMBER, 'global_search', limit=100)) == both
        assert self._projects(_call(world, ADMIN, 'global_search', limit=100)) == both

    def test_the_type_filter_keeps_the_rule(self, world):
        data = _call(world, OUTSIDER, 'global_search', type='project', limit=100)
        assert self._projects(data) == {world.public.id}

    def test_it_matches_rest_search_for_the_same_user(self, world, monkeypatch):
        """/api/search (SearchManager.search) returns the same project rows."""
        from src.controller import projects_manager as pm_module

        monkeypatch.setattr(world.search, 'searchable_managers',
                            [*world.search.searchable_managers, pm_module.projects_manager])
        monkeypatch.setattr('src.common.database.get_session_factory',
                            lambda: (lambda: _NoClose(world.db)))
        auth = MagicMock()
        auth.get_user_effective_permissions.return_value = {}
        auth.has_permission.return_value = True
        user = SimpleNamespace(email=OUTSIDER.email, groups=['users'], username='carl')
        rest = {i.id.split('::', 1)[1] for i in world.search.search('customer', auth, user)
                if i.type == 'project'}
        mcp = self._projects(_call(world, OUTSIDER, 'global_search', query='customer',
                                   limit=100))
        assert rest == mcp == {world.public.id}


class TestGlobalSearchWithoutGroups:
    """/api/search returns nothing to a user with no groups (SearchManager.search)."""

    def test_a_user_without_groups_gets_nothing(self, world):
        caller = ToolCaller(email='carl@example.com', auth_path='test', permissions=LEVELS)
        data = _call(world, caller, 'global_search', limit=100)
        assert data['results'] == [] and data['total_count'] == 0

    def test_the_same_user_with_a_group_gets_results(self, world):
        caller = ToolCaller(email='carl@example.com', auth_path='test', permissions=LEVELS,
                            groups=['users'])
        assert _call(world, caller, 'global_search', limit=100)['total_count'] == 2

    def test_the_api_key_policy_is_not_a_user(self, world):
        # No user and no groups: its reads come from the token's scopes.
        caller = mcp_api_key_caller(SimpleNamespace(scopes=['teams:read']))
        data = _call(world, caller, 'global_search', limit=100)
        assert _ids(data['results']) == {world.team.id}


class TestGetTeam:
    def test_without_the_level_it_is_not_found(self, world):
        _assert_not_found(_exec(world, NO_LEVEL, 'get_team', team_id=world.team.id))
        _assert_not_found(_exec(world, None, 'get_team', team_id=world.team.id))

    def test_with_the_level_it_is_returned(self, world):
        res = _exec(world, OUTSIDER, 'get_team', team_id=world.team.id)
        assert res.success is True and res.data['id'] == world.team.id


class TestGetProject:
    def test_a_non_member_does_not_get_a_project_the_list_hides(self, world):
        _assert_not_found(_exec(world, OUTSIDER, 'get_project', project_id=world.private.id))
        res = _exec(world, OUTSIDER, 'get_project', project_id=world.public.id)
        assert res.success is True and res.data['id'] == world.public.id

    def test_a_member_and_an_admin_get_it(self, world):
        for caller in (MEMBER, ADMIN):
            res = _exec(world, caller, 'get_project', project_id=world.private.id)
            assert res.success is True and res.data['id'] == world.private.id

    def test_without_the_level_it_is_not_found(self, world):
        _assert_not_found(_exec(world, NO_LEVEL, 'get_project', project_id=world.public.id))


class TestDomainTools:
    def test_without_the_level_nothing_is_returned(self, world):
        res = _exec(world, OUTSIDER, 'search_domains', query='*')
        assert res.success is True and res.data['domains'] == []
        assert res.data['total_found'] == 0
        _assert_not_found(_exec(world, OUTSIDER, 'get_domain', domain_id=world.domain.id))

    def test_with_the_level_the_domain_is_returned(self, world):
        res = _exec(world, READER, 'search_domains', query='*')
        assert _ids(res.data['domains']) == {world.domain.id}
        res = _exec(world, READER, 'get_domain', domain_id=world.domain.id)
        assert res.success is True and res.data['id'] == world.domain.id


class TestTagTools:
    def test_without_the_level_nothing_is_returned(self, world):
        res = _exec(world, OUTSIDER, 'search_tags', query='*')
        assert res.success is True and res.data['tags'] == []
        assert res.data['total_found'] == 0
        _assert_not_found(_exec(world, OUTSIDER, 'get_tag', tag_id=str(world.tag.id)))
        res = _exec(world, OUTSIDER, 'list_entity_tags', entity_type='team',
                    entity_id=world.team.id)
        assert res.success is True and res.data['tags'] == []
        assert res.denied_reason == NOT_READABLE

    def test_with_the_level_the_tag_is_returned(self, world):
        res = _exec(world, READER, 'search_tags', query='*')
        assert _ids(res.data['tags']) == {str(world.tag.id)}
        res = _exec(world, READER, 'get_tag', tag_id=str(world.tag.id))
        assert res.success is True and res.data['id'] == str(world.tag.id)
        res = _exec(world, READER, 'list_entity_tags', entity_type='team',
                    entity_id=world.team.id)
        assert res.data['total_count'] == 1


class _NoClose:
    """The test session as a context manager that leaves it open."""

    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *exc):
        return False
