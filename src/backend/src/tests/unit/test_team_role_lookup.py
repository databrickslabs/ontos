"""Team role overrides are stored by role id (#1453) and looked up with one indexed query.

- The lookup reads only the member entries that can apply to the user (their own
  entry, or a group entry for one of their groups), never whole teams.
- Renaming a role keeps every override that points at it.
"""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import event

from src.common import authorization
from src.common.authorization import lookup_user_team_roles
from src.controller.teams_manager import TeamsManager
from src.db_models.settings import AppRoleDb
from src.db_models.teams import TeamDb, TeamMemberDb
from src.models.teams import TeamMemberCreate
from src.controller.teams_manager import InvalidMemberSetError


def _role(db, name):
    role = AppRoleDb(id=str(uuid.uuid4()), name=name)
    db.add(role)
    db.flush()
    return role


def _team(db, name):
    team = TeamDb(id=str(uuid.uuid4()), name=name, created_by="system", updated_by="system")
    db.add(team)
    db.flush()
    return team


def _member(db, team, identifier, member_type, role=None):
    db.add(TeamMemberDb(
        id=str(uuid.uuid4()), team_id=team.id, member_type=member_type, member_identifier=identifier,
        app_role_override_id=role.id if role else None, added_by="system",
    ))
    db.flush()


@pytest.fixture
def roles(db_session):
    return SimpleNamespace(admin=_role(db_session, "Admin"), steward=_role(db_session, "Data Steward"))


def test_lookup_is_one_query_and_skips_teams_the_user_is_not_in(db_session, roles):
    # 200 teams with 10 members each, none of them the user's.
    for i in range(200):
        team = _team(db_session, f"team-{i}")
        for j in range(10):
            _member(db_session, team, f"user{i}-{j}@example.com", "user", roles.steward)
    mine = _team(db_session, "mine")
    _member(db_session, mine, "alice@example.com", "user", roles.steward)
    _member(db_session, mine, "bob@example.com", "user", roles.admin)
    eng = _team(db_session, "eng")
    _member(db_session, eng, "data-consumers", "group", roles.admin)
    _member(db_session, eng, "other-group", "group", roles.admin)  # not the user's group
    _member(db_session, eng, "data-consumers", "user", roles.steward)  # a user entry named like a group
    _member(db_session, eng, "alice@example.com", "group", roles.admin)  # a group entry named like the user
    db_session.commit()

    statements = []

    def count(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    connection = db_session.get_bind()
    event.listen(connection, "before_cursor_execute", count)
    try:
        members = TeamsManager().get_role_override_members_for_user(
            db_session, "alice@example.com", ["data-consumers"],
        )
    finally:
        event.remove(connection, "before_cursor_execute", count)

    assert len(statements) == 1
    assert "team_members" in statements[0] and "teams" not in statements[0].replace("team_members", "")
    assert {(m.member_identifier, m.app_role_override_id) for m in members} == {
        ("alice@example.com", roles.steward.id),
        ("data-consumers", roles.admin.id),
        ("data-consumers", roles.steward.id),
        ("alice@example.com", roles.admin.id),
    }


def test_the_request_lookup_resolves_role_ids_once_per_request(db_session, roles):
    team = _team(db_session, "eng")
    _member(db_session, team, "alice@example.com", "user", roles.steward)
    db_session.commit()
    request = SimpleNamespace(
        app=SimpleNamespace(state=SimpleNamespace(teams_manager=TeamsManager())),
        state=SimpleNamespace(),
    )

    def fake_get_db():
        yield db_session

    with patch.object(authorization, "get_db", fake_get_db):
        first = lookup_user_team_roles(request, "alice@example.com", ["data-consumers"])
        second = lookup_user_team_roles(request, "alice@example.com", ["data-consumers"])

    assert first == [roles.steward.id]
    assert first is second


def test_renaming_a_role_keeps_its_overrides(db_session, roles):
    team = _team(db_session, "eng")
    _member(db_session, team, "alice@example.com", "user", roles.admin)
    db_session.commit()

    roles.admin.name = "Administrators"
    db_session.flush()

    members = TeamsManager().get_role_override_members_for_user(db_session, "alice@example.com", [])
    assert [m.app_role_override_id for m in members] == [roles.admin.id]
    assert [m.app_role_override for m in members] == ["Administrators"]


def test_adding_a_member_stores_the_role_id_for_the_named_role(db_session, roles):
    team = _team(db_session, "eng")
    db_session.commit()

    created = TeamsManager().add_team_member(
        db_session, team.id,
        TeamMemberCreate(member_type="user", member_identifier="alice@example.com", app_role_override="Data Steward"),
        current_user_id="admin@example.com",
    )

    stored = db_session.query(TeamMemberDb).filter_by(team_id=team.id).one()
    assert stored.app_role_override_id == roles.steward.id
    assert created.app_role_override == "Data Steward"
    assert created.app_role_override_id == roles.steward.id


def test_a_role_name_that_matches_no_role_is_refused(db_session, roles):
    team = _team(db_session, "eng")
    db_session.commit()

    with pytest.raises(InvalidMemberSetError):
        TeamsManager().add_team_member(
            db_session, team.id,
            TeamMemberCreate(member_type="user", member_identifier="alice@example.com", app_role_override="Retired"),
            current_user_id="admin@example.com",
        )


def test_updating_an_override_by_name_stores_the_role_id(db_session, roles):
    from src.models.teams import TeamMemberUpdate

    team = _team(db_session, "eng")
    _member(db_session, team, "alice@example.com", "user", None)
    db_session.commit()
    member = db_session.query(TeamMemberDb).filter_by(team_id=team.id).one()

    TeamsManager().update_team_member(
        db_session, team.id, member.id, TeamMemberUpdate(app_role_override="Admin"), current_user_id="admin@example.com",
    )

    assert member.app_role_override_id == roles.admin.id
    assert member.app_role_override == "Admin"


class TestViewerRoleIds:
    """Comment audiences: role ids of the viewer include team roles, unless an applied override pins one role."""

    def _auth(self):
        from src.controller.authorization_manager import AuthorizationManager
        from src.models.settings import AppRole

        group_role = AppRole(id=uuid.uuid4(), name="Consumer", description="", assigned_groups=["data-consumers"],
                             feature_permissions={}, home_sections=[], approval_privileges={})
        team_role = AppRole(id=uuid.uuid4(), name="Steward", description="", assigned_groups=[],
                            feature_permissions={}, home_sections=[], approval_privileges={})
        settings = MagicMock()
        settings.list_app_roles.return_value = [group_role, team_role]
        return AuthorizationManager(settings_manager=settings), group_role, team_role

    def test_team_roles_join_the_group_roles(self):
        auth, group_role, team_role = self._auth()

        ids = auth.get_user_effective_role_ids(["data-consumers"], team_role_ids=[str(team_role.id)])

        assert ids == {str(group_role.id), str(team_role.id)}

    def test_an_applied_override_pins_the_viewer_to_its_role(self):
        auth, group_role, team_role = self._auth()

        ids = auth.get_user_effective_role_ids(
            ["data-consumers"], applied_role_override_id=str(group_role.id), team_role_ids=[str(team_role.id)],
        )

        assert ids == {str(group_role.id)}


def test_updating_to_a_role_name_that_matches_no_role_is_refused(db_session, roles):
    from src.models.teams import TeamMemberUpdate

    team = _team(db_session, "eng")
    _member(db_session, team, "alice@example.com", "user", roles.steward)
    db_session.commit()
    member = db_session.query(TeamMemberDb).filter_by(team_id=team.id).one()

    with pytest.raises(InvalidMemberSetError):
        TeamsManager().update_team_member(
            db_session, team.id, member.id,
            TeamMemberUpdate(app_role_override="  Retired  "),
            current_user_id="admin@example.com",
        )
