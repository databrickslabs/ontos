"""The org search tools return only the teams and projects the caller sees over REST.

- ``search_teams``: ``GET /api/teams`` needs Read-only on ``teams``.
- ``search_projects``: ``GET /api/projects`` needs Read-only on ``projects``
  and lists only the projects ``ProjectsManager.get_all_projects`` shows the
  caller (admin groups: all; others: the team-domain relationship).
- ``global_search``: ``/api/search`` drops the ``project`` rows the list hides
  (``SearchManager._apply_project_visibility``).

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
from src.tools.caller import mcp_api_key_caller
from src.tools.registry import create_default_registry

RO = FeatureAccessLevel.READ_ONLY
LEVELS = {'teams': RO, 'projects': RO}
# No team: sees the public projects only.
OUTSIDER = ToolCaller(email='carl@example.com', auth_path='test', permissions=LEVELS)
# Member of the team that owns the private project.
MEMBER = ToolCaller(email='tom@example.com', auth_path='test', permissions=LEVELS)
# In the configured admin groups (resolve_tool_caller: project_ids None).
ADMIN = ToolCaller(email='ann@example.com', auth_path='test', permissions=LEVELS,
                   project_ids=None)
# No level on either feature (e.g. no role).
NO_LEVEL = ToolCaller(email='tom@example.com', auth_path='test')


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
    return SimpleNamespace(db=db_session, team=team, private=private, public=public,
                           search=SearchManager(searchable_managers=[_Index(items)]))


def _call(world, caller, tool, **args):
    ctx = ToolContext(db=world.db, settings=MagicMock(), caller=caller,
                      search_manager=world.search)
    res = _run(create_default_registry().execute(tool, ctx, {'query': '*', **args}))
    assert res.success is True, res.error
    return res.data


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


class _NoClose:
    """The test session as a context manager that leaves it open."""

    def __init__(self, db):
        self._db = db

    def __enter__(self):
        return self._db

    def __exit__(self, *exc):
        return False
