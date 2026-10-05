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
