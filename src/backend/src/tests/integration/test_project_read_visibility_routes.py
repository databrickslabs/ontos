"""The project read routes follow the visibility of the project list.

``GET /api/projects`` lists, for a non-admin, only the projects related to the
caller's teams (``ProjectsManager.visible_project_ids``). The routes that return
one project's content answer 404, with the body of a missing project, for a
project the caller can't see, and ``GET /api/projects/summary`` leaves it out.

``GET /api/user/projects`` treats as admin only the configured admin groups
(``APP_ADMIN_DEFAULT_GROUPS``), not any group whose name contains "admin".
"""
import uuid

import pytest

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.common.config import get_settings
from src.db_models.data_domains import DataDomain
from src.db_models.domain_associations import EntityDomainAssociationDb
from src.db_models.notifications import NotificationDb
from src.db_models.projects import ProjectDb, project_team_association
from src.db_models.teams import TeamDb, TeamMemberDb
from src.models.users import UserInfo

MEMBER = "member@example.com"
OUTSIDER = "outsider@example.com"
ADMIN = "admin@example.com"

# email, groups. "data-consumers" maps to the Data Consumer role (Read-only on
# Projects), "data-producers" to Data Producer (Read/Write on Projects);
# "test_admins" is APP_ADMIN_DEFAULT_GROUPS in the test settings.
PERSONAS = {
    "member": (MEMBER, ["data-consumers"]),
    "outsider": (OUTSIDER, ["data-consumers"]),
    "admin_named_group": (OUTSIDER, ["data-consumers", "billing-admin-viewers"]),
    "admin": (ADMIN, ["test_admins"]),
    "outsider_producer": (OUTSIDER, ["data-producers"]),
    "member_producer": (MEMBER, ["data-producers"]),
}


@pytest.fixture
def as_persona(client, test_settings):
    """Switch the caller of ``client`` to one of ``PERSONAS``.

    The routes read the admin groups from ``get_settings``, which the shared client
    doesn't override; the test settings make ``test_admins`` the admin group.
    """
    prev_settings = app.dependency_overrides.get(get_settings)
    app.dependency_overrides[get_settings] = lambda: test_settings

    def _switch(persona):
        email, groups = PERSONAS[persona]

        async def _override():
            return UserInfo(username=email, email=email, user=email, ip="127.0.0.1", groups=groups)

        app.dependency_overrides[get_user_details_from_sdk] = _override
        return client

    yield _switch
    if prev_settings is not None:
        app.dependency_overrides[get_settings] = prev_settings
    else:
        app.dependency_overrides.pop(get_settings, None)


@pytest.fixture
def hidden_project(db_session):
    """A project owned by a team that has a domain, with only ``MEMBER`` on it.

    The owner team's domain makes the project non-public, so ``OUTSIDER`` (in no
    team) doesn't see it on the list. Opens a SAVEPOINT first, as a request that
    rolls its session back must not undo the test's data.
    """
    db_session.connection().begin_nested()
    domain = DataDomain(id=str(uuid.uuid4()), name=f"domain-{uuid.uuid4().hex[:8]}",
                        created_by=ADMIN)
    team = TeamDb(id=str(uuid.uuid4()), name=f"team-{uuid.uuid4().hex[:8]}",
                  created_by=ADMIN, updated_by=ADMIN)
    db_session.add_all([domain, team])
    db_session.flush()
    db_session.add(EntityDomainAssociationDb(domain_id=domain.id, entity_type="team",
                                             entity_id=team.id, is_primary=True))
    db_session.add(TeamMemberDb(team_id=team.id, member_type="user",
                                member_identifier=MEMBER, added_by=ADMIN))
    project = ProjectDb(id=str(uuid.uuid4()), name=f"secret-{uuid.uuid4().hex[:8]}",
                        project_type="TEAM", owner_team_id=team.id,
                        created_by=ADMIN, updated_by=ADMIN)
    db_session.add(project)
    db_session.flush()
    db_session.execute(project_team_association.insert().values(
        project_id=project.id, team_id=team.id, assigned_by=ADMIN))
    db_session.flush()
    return project


def _missing_bodies(client):
    """The 404 bodies of the read routes for a project that doesn't exist."""
    missing = "no-such-project"
    return {
        "detail": client.get(f"/api/projects/{missing}").json(),
        "teams": client.get(f"/api/projects/{missing}/teams").json(),
    }, missing


def test_outsider_gets_404_on_a_hidden_project(as_persona, hidden_project):
    client = as_persona("outsider")
    bodies, missing = _missing_bodies(client)

    detail = client.get(f"/api/projects/{hidden_project.id}")
    assert detail.status_code == 404
    missing_detail = bodies["detail"]["detail"]
    assert detail.json() == {"detail": missing_detail.replace(missing, hidden_project.id)}

    teams = client.get(f"/api/projects/{hidden_project.id}/teams")
    assert teams.status_code == 404
    assert teams.json() == bodies["teams"]

    summary_ids = {p["id"] for p in client.get("/api/projects/summary").json()}
    assert hidden_project.id not in summary_ids
    # The same project the list hides.
    assert hidden_project.id not in {p["id"] for p in client.get("/api/projects").json()}


@pytest.mark.parametrize("persona", ["member", "admin"])
def test_member_and_admin_read_the_project(as_persona, hidden_project, persona):
    client = as_persona(persona)

    detail = client.get(f"/api/projects/{hidden_project.id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == hidden_project.id

    teams = client.get(f"/api/projects/{hidden_project.id}/teams")
    assert teams.status_code == 200
    assert [t["id"] for t in teams.json()] == [hidden_project.owner_team_id]

    assert hidden_project.id in {p["id"] for p in client.get("/api/projects/summary").json()}


def test_group_named_admin_is_not_admin_on_user_projects(as_persona, hidden_project):
    response = as_persona("admin_named_group").get("/api/user/projects")
    assert response.status_code == 200
    assert hidden_project.id not in {p["id"] for p in response.json()["projects"]}


def test_configured_admin_group_sees_every_project_on_user_projects(as_persona, hidden_project):
    response = as_persona("admin").get("/api/user/projects")
    assert response.status_code == 200
    assert hidden_project.id in {p["id"] for p in response.json()["projects"]}


ACCESS_REQUEST = "/api/user/request-project-access"


def _access_request_notifications(db_session):
    return db_session.query(NotificationDb).filter(
        NotificationDb.recipient == MEMBER,
        NotificationDb.action_type == "project_access_request",
    ).count()


def test_request_access_error_answers(as_persona, hidden_project):
    missing = as_persona("outsider").post(ACCESS_REQUEST, json={"project_id": "no-such-project"})
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Project not found"}

    already_member = as_persona("member").post(
        ACCESS_REQUEST, json={"project_id": hidden_project.id})
    assert already_member.status_code == 409


def test_request_access_to_a_hidden_project_is_404_and_notifies_nobody(
    as_persona, hidden_project, db_session
):
    response = as_persona("outsider").post(ACCESS_REQUEST, json={"project_id": hidden_project.id})
    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}
    assert _access_request_notifications(db_session) == 0


def _write_calls(project_id, team_id):
    """(method, path, json) of the project write routes."""
    return [
        ("PUT", f"/api/projects/{project_id}", {"description": "edited"}),
        ("POST", f"/api/projects/{project_id}/teams", {"team_id": team_id}),
        ("DELETE", f"/api/projects/{project_id}/teams/{team_id}", None),
        ("DELETE", f"/api/projects/{project_id}", None),
    ]


@pytest.mark.parametrize("persona", ["outsider", "outsider_producer"])
def test_write_routes_answer_404_on_a_hidden_project(as_persona, hidden_project, persona):
    """Before the feature-level check: 404 with the body of a missing project, also
    for a caller without the write level, and the project is unchanged."""
    client = as_persona(persona)
    team_id = hidden_project.owner_team_id
    missing = {path: client.request(method, path.replace(hidden_project.id, "no-such-project"),
                                    json=body)
               for method, path, body in _write_calls(hidden_project.id, team_id)}
    for method, path, body in _write_calls(hidden_project.id, team_id):
        response = client.request(method, path, json=body)
        assert response.status_code == 404, (method, path, response.status_code)
        want = missing[path]
        assert want.status_code == 404, (method, path, want.status_code)
        assert response.json() == {
            "detail": want.json()["detail"].replace("no-such-project", hidden_project.id)
        }, (method, path)

    detail = as_persona("admin").get(f"/api/projects/{hidden_project.id}")
    assert detail.status_code == 200
    assert detail.json()["description"] is None
    assert [t["id"] for t in detail.json()["teams"]] == [team_id]


def test_member_writes_a_project_it_sees(as_persona, hidden_project):
    response = as_persona("member_producer").put(
        f"/api/projects/{hidden_project.id}", json={"description": "edited"})
    assert response.status_code == 200
    assert response.json()["description"] == "edited"


def test_admin_keeps_every_write_route(as_persona, hidden_project):
    client = as_persona("admin")
    team_id = hidden_project.owner_team_id
    calls = _write_calls(hidden_project.id, team_id)
    # Remove the team before assigning it again, then delete the project.
    calls = [calls[0], calls[2], calls[1], calls[3]]
    for method, path, body in calls:
        response = client.request(method, path, json=body)
        assert response.status_code < 300, (method, path, response.status_code, response.text)
    assert client.get(f"/api/projects/{hidden_project.id}").status_code == 404


@pytest.fixture
def public_project(db_session):
    """A project without an owning team, so everyone sees it; ``MEMBER`` is on
    its assigned team."""
    db_session.connection().begin_nested()
    team = TeamDb(id=str(uuid.uuid4()), name=f"team-{uuid.uuid4().hex[:8]}",
                  created_by=ADMIN, updated_by=ADMIN)
    db_session.add(team)
    db_session.flush()
    db_session.add(TeamMemberDb(team_id=team.id, member_type="user",
                                member_identifier=MEMBER, added_by=ADMIN))
    project = ProjectDb(id=str(uuid.uuid4()), name=f"open-{uuid.uuid4().hex[:8]}",
                        project_type="TEAM", created_by=ADMIN, updated_by=ADMIN)
    db_session.add(project)
    db_session.flush()
    db_session.execute(project_team_association.insert().values(
        project_id=project.id, team_id=team.id, assigned_by=ADMIN))
    db_session.flush()
    return project


def test_request_access_to_a_visible_project_notifies_its_team(
    as_persona, public_project, db_session
):
    response = as_persona("outsider").post(ACCESS_REQUEST, json={"project_id": public_project.id})
    assert response.status_code == 201, response.text
    assert response.json()["project_name"] == public_project.name
    assert _access_request_notifications(db_session) >= 1
