"""Teams and projects are indexed into global search (#919).

They were absent from the search index because their managers did not implement
SearchableAsset. These tests assert the managers now produce SearchIndexItems and that
the shared search path (UI global search + MCP) matches them by name/title.
"""
import uuid

from sqlalchemy.orm import Session

from src.common.search_interfaces import SearchableAsset
from src.controller.search_manager import SearchManager
from src.controller.teams_manager import TeamsManager
from src.controller.projects_manager import ProjectsManager
from src.db_models.teams import TeamDb
from src.db_models.projects import ProjectDb


def _ids(results):
    return {r.get("id") for r in results}


def test_managers_are_searchable_assets():
    # Startup auto-registration keys off isinstance(SearchableAsset); guard that contract.
    assert isinstance(TeamsManager(), SearchableAsset)
    assert isinstance(ProjectsManager(), SearchableAsset)


def test_team_indexed_and_searchable(db_session: Session):
    tid = str(uuid.uuid4())
    db_session.add(TeamDb(id=tid, name="Platform Guild", description="Owns the platform", created_by="t@e.com", updated_by="t@e.com"))
    db_session.commit()

    item = TeamsManager()._build_search_index_item(db_session.get(TeamDb, tid))
    assert item.type == "team" and item.feature_id == "teams"
    assert item.title == "Platform Guild"
    assert item.link == f"/teams/{tid}"

    sm = SearchManager([])
    sm.index = [item]
    res = sm.query_index("Platform Guild", type_filter="team")
    assert tid in _ids(res["results"])


def test_project_indexed_and_searchable(db_session: Session):
    pid = str(uuid.uuid4())
    db_session.add(ProjectDb(id=pid, name="atlas-migration", title="Atlas Migration",
                             description="Cross-team data migration", created_by="t@e.com", updated_by="t@e.com"))
    db_session.commit()

    item = ProjectsManager()._build_search_index_item(db_session.get(ProjectDb, pid))
    assert item.type == "project" and item.feature_id == "projects"
    assert item.title == "Atlas Migration"  # title preferred over name
    assert item.link == f"/projects/{pid}"

    sm = SearchManager([])
    sm.index = [item]
    # Findable by the display title and by the slug-ish name.
    assert pid in _ids(sm.query_index("Atlas Migration", type_filter="project")["results"])
    assert pid in _ids(sm.query_index("atlas-migration", type_filter="project")["results"])


def test_get_search_index_items_returns_list(db_session: Session):
    # Exercises the repo/session wiring; returns a list (contents depend on the live DB).
    assert isinstance(TeamsManager().get_search_index_items(), list)
    assert isinstance(ProjectsManager().get_search_index_items(), list)


# =====================================================================
# Route dependency wiring — regression tests for #919 re-review
# =====================================================================
#
# Index-upsert/remove hooks only fire on the manager instance that got
# `set_search_manager(...)` wired to it at startup. That instance is on
# ``app.state``; the module-level singleton (``teams_manager`` /
# ``projects_manager``) is a *different* instance and never gets its
# ``_search_manager`` set — so a route reaching the singleton would silently
# skip the index update. The route getters must prefer ``request.app.state``
# when a request context is present.


def test_get_teams_manager_prefers_app_state_instance():
    from fastapi import FastAPI
    from starlette.requests import Request

    from src.routes.teams_routes import get_teams_manager
    from src.controller.teams_manager import TeamsManager

    app = FastAPI()
    state_mgr = TeamsManager()  # intentionally a fresh instance, not the singleton
    app.state.teams_manager = state_mgr

    scope = {"type": "http", "app": app, "headers": []}
    assert get_teams_manager(request=Request(scope)) is state_mgr


def test_get_teams_manager_falls_back_to_singleton_without_request():
    from src.routes.teams_routes import get_teams_manager
    from src.controller.teams_manager import teams_manager as singleton

    assert get_teams_manager() is singleton


def test_get_projects_manager_prefers_app_state_instance():
    from fastapi import FastAPI
    from starlette.requests import Request

    from src.routes.projects_routes import get_projects_manager
    from src.controller.projects_manager import ProjectsManager

    app = FastAPI()
    state_mgr = ProjectsManager()
    app.state.projects_manager = state_mgr

    scope = {"type": "http", "app": app, "headers": []}
    assert get_projects_manager(request=Request(scope)) is state_mgr


def test_get_projects_manager_falls_back_to_singleton_without_request():
    from src.routes.projects_routes import get_projects_manager
    from src.controller.projects_manager import projects_manager as singleton

    assert get_projects_manager() is singleton


# =====================================================================
# Project visibility admin check — regression test for #919 re-review
# =====================================================================
#
# `_apply_project_visibility` previously used `'admin' in g.lower()`, which
# matched any group whose name happened to contain "admin" as a substring
# (e.g. `billing-admin-viewers`) and skipped the visibility filter entirely.
# It must now use `is_user_admin(user_groups, settings)` to mirror the list
# route exactly.


def test_apply_project_visibility_admin_check_uses_exact_group_match(monkeypatch):
    from src.controller.search_manager import SearchManager
    from src.controller.projects_manager import ProjectsManager
    from src.common.search_interfaces import SearchIndexItem
    from src.common.config import Settings
    from src.models.users import UserInfo

    captured_is_admin = []

    # The resolver in _apply_project_visibility matches by `__class__.__name__ == 'ProjectsManager'`,
    # so the fake must keep that class name while overriding only visible_project_ids.
    fake_projects = ProjectsManager()

    def _fake_visible(db, project_ids, *, user_identifier, user_groups, is_admin):
        captured_is_admin.append(is_admin)
        return set()

    monkeypatch.setattr(fake_projects, "visible_project_ids", _fake_visible)
    # Settings whose configured admin groups do NOT include anything the test user has.
    # Both symbols are imported inside the method, so patch them at their source modules.
    monkeypatch.setattr(
        "src.common.config.get_settings",
        lambda: Settings(APP_ADMIN_DEFAULT_GROUPS='["admins"]'),
    )
    # Session factory must return something truthy; the actual DB query is handled
    # by our fake visible_project_ids above.
    monkeypatch.setattr(
        "src.common.database.get_session_factory",
        lambda: (lambda: __import__("contextlib").nullcontext(None)),
    )

    sm = SearchManager(searchable_managers=[fake_projects])
    item = SearchIndexItem(
        id="project::p1", title="Platform Atlas", description="",
        feature_id="projects", link="/projects/p1", type="project",
    )
    # A group that contains the substring "admin" but is NOT in APP_ADMIN_DEFAULT_GROUPS.
    user = UserInfo(username="u", email="u@e.com", user="u", ip="127.0.0.1",
                    groups=["billing-admin-viewers"])

    out = sm._apply_project_visibility([item], user)

    assert captured_is_admin == [False], (
        "Substring 'admin' in a non-admin group should NOT grant the admin shortcut."
    )
    assert out == [], "With no visibility and non-admin user, the project must be hidden."
