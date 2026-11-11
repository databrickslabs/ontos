"""Atomic team member replacement, team role override resolution, and the self-lockout guard."""
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.errors import NotFoundError
from src.common.features import ACCESS_LEVEL_ORDER, FeatureAccessLevel
from src.common.team_role_override import pick_team_role_override
from src.controller.teams_manager import InvalidMemberSetError, TeamsManager
from src.db_models.teams import TeamDb, TeamMemberDb
from src.models.teams import TeamMemberCreate
from src.models.users import UserInfo
from src.routes.teams_routes import _would_lose_team_write_access


def _team(db_session, name="Admin Team") -> TeamDb:
    team = TeamDb(
        id=str(uuid.uuid4()), name=name, created_by="t", updated_by="t", extra_metadata="{}"
    )
    db_session.add(team)
    db_session.commit()
    return team


def _member(db_session, team, identifier, member_type="user", override=None) -> TeamMemberDb:
    member = TeamMemberDb(
        team_id=team.id,
        member_type=member_type,
        member_identifier=identifier,
        app_role_override=override,
        added_by="seed",
    )
    db_session.add(member)
    db_session.commit()
    return member


def _create(identifier, member_type="user", override=None) -> TeamMemberCreate:
    return TeamMemberCreate(
        member_type=member_type, member_identifier=identifier, app_role_override=override
    )


@pytest.fixture
def manager():
    return TeamsManager()


class TestReplaceTeamMembers:
    def test_adding_a_member_keeps_existing_rows(self, manager, db_session):
        team = _team(db_session)
        alice = _member(db_session, team, "alice@example.com", override="Admin")
        admins = _member(db_session, team, "admins", member_type="group", override="Admin")

        result = manager.replace_team_members(
            db_session,
            team.id,
            [
                _create("alice@example.com", override="Admin"),
                _create("admins", member_type="group", override="Admin"),
                _create("bob@example.com"),
            ],
            current_user_id="alice@example.com",
        )
        db_session.commit()

        assert sorted(m.member_identifier for m in result) == [
            "admins", "alice@example.com", "bob@example.com",
        ]
        by_id = {m.member_identifier: m for m in result}
        # Unchanged members keep their row, so their id and added_by survive the save.
        assert by_id["alice@example.com"].id == alice.id
        assert by_id["admins"].id == admins.id
        bob = db_session.query(TeamMemberDb).filter_by(member_identifier="bob@example.com").one()
        assert bob.added_by == "alice@example.com"

    def test_removes_and_updates_only_what_changed(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")
        _member(db_session, team, "bob@example.com")
        carol = _member(db_session, team, "carol@example.com")

        result = manager.replace_team_members(
            db_session,
            team.id,
            [_create("alice@example.com", override="Admin"), _create("carol@example.com", override="Data Steward")],
            current_user_id="alice@example.com",
        )
        db_session.commit()

        by_id = {m.member_identifier: m for m in result}
        assert set(by_id) == {"alice@example.com", "carol@example.com"}
        assert by_id["carol@example.com"].id == carol.id
        assert by_id["carol@example.com"].app_role_override == "Data Steward"

    def test_case_change_keeps_the_row(self, manager, db_session):
        team = _team(db_session)
        alice = _member(db_session, team, "Alice@Example.com", override="Admin")

        result = manager.replace_team_members(
            db_session, team.id, [_create("alice@example.com", override="Admin")], current_user_id="x"
        )

        assert [(m.id, m.member_identifier) for m in result] == [(alice.id, "alice@example.com")]

    def test_duplicate_rows_are_collapsed(self, manager, db_session):
        """A twin row must not keep a stale override after the set is replaced."""
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")
        _member(db_session, team, "alice@example.com")

        result = manager.replace_team_members(
            db_session, team.id, [_create("alice@example.com")], current_user_id="x"
        )
        db_session.commit()

        assert len(result) == 1
        assert result[0].app_role_override is None
        assert db_session.query(TeamMemberDb).filter_by(team_id=team.id).count() == 1

    def test_blank_override_is_stored_as_none(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        result = manager.replace_team_members(
            db_session, team.id, [_create("alice@example.com", override="  ")], current_user_id="x"
        )

        assert result[0].app_role_override is None

    def test_empty_set_clears_the_team(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com")

        assert manager.replace_team_members(db_session, team.id, [], current_user_id="x") == []

    def test_case_insensitive_duplicates_are_rejected(self, manager, db_session):
        team = _team(db_session)
        with pytest.raises(InvalidMemberSetError, match="more than once"):
            manager.replace_team_members(
                db_session,
                team.id,
                [_create("alice@example.com"), _create(" Alice@example.com ")],
                current_user_id="x",
            )

    def test_unknown_team_raises_not_found(self, manager, db_session):
        with pytest.raises(NotFoundError):
            manager.replace_team_members(db_session, "missing", [], current_user_id="x")


class TestPickTeamRoleOverride:
    def _teams(self, *members):
        return [SimpleNamespace(members=[
            SimpleNamespace(member_identifier=i, app_role_override=o) for i, o in members
        ])]

    def test_group_entry_in_users_team_grants_override(self):
        teams = self._teams(("alice@example.com", None), ("Admins", "Admin"))
        assert pick_team_role_override(teams, "alice@example.com", ["admins"]) == "Admin"

    def test_direct_entry_wins_over_group(self):
        teams = self._teams(("admins", "Data Steward"), ("alice@example.com", "Admin"))
        assert pick_team_role_override(teams, "alice@example.com", ["admins"]) == "Admin"

    def test_members_without_override_are_ignored(self):
        teams = self._teams(("alice@example.com", None))
        assert pick_team_role_override(teams, "alice@example.com", []) is None


class TestTeamRoleOverrideWithMembers:
    def test_group_only_membership_does_not_count(self, manager, db_session):
        """Unchanged semantics: group entries only apply in teams the user directly belongs to."""
        team = _team(db_session)
        _member(db_session, team, "admins", member_type="group", override="Admin")

        override = manager.team_role_override_with_members(
            db_session, team.id, [_create("admins", member_type="group", override="Admin")],
            user_identifier="alice@example.com", user_groups=["admins"],
        )

        assert override is None

    def test_removing_own_entry_drops_override(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        override = manager.team_role_override_with_members(
            db_session, team.id, [_create("bob@example.com")],
            user_identifier="alice@example.com", user_groups=[],
        )

        assert override is None

    def test_joining_a_team_picks_up_its_override(self, manager, db_session):
        team = _team(db_session)

        override = manager.team_role_override_with_members(
            db_session, team.id, [_create("Alice@example.com", override="Admin")],
            user_identifier="alice@example.com", user_groups=[],
        )

        # The direct entry is matched exactly, like request authorization does.
        assert override is None
        override = manager.team_role_override_with_members(
            db_session, team.id, [_create("alice@example.com", override="Admin")],
            user_identifier="alice@example.com", user_groups=[],
        )
        assert override == "Admin"

    def test_override_from_another_team_is_kept(self, manager, db_session):
        team = _team(db_session)
        other = _team(db_session, name="Other Team")
        _member(db_session, team, "alice@example.com", override="Admin")
        _member(db_session, other, "alice@example.com", override="Admin")

        override = manager.team_role_override_with_members(
            db_session, team.id, [],
            user_identifier="alice@example.com", user_groups=[],
        )

        assert override == "Admin"


class TestSelfLockoutGuard:
    def _request(self, applied_role=None):
        auth_manager = MagicMock()
        auth_manager.get_user_effective_permissions.side_effect = (
            lambda groups, team_override, user_email=None: {
                "teams": FeatureAccessLevel.ADMIN if team_override == "Admin" else FeatureAccessLevel.READ_ONLY
            }
        )
        auth_manager.has_permission.side_effect = (
            lambda perms, feature, level:
            ACCESS_LEVEL_ORDER[perms.get(feature, FeatureAccessLevel.NONE)] >= ACCESS_LEVEL_ORDER[level]
        )
        settings_manager = MagicMock()
        settings_manager.get_applied_role_override_for_user.return_value = applied_role
        state = SimpleNamespace(authorization_manager=auth_manager, settings_manager=settings_manager)
        return SimpleNamespace(app=SimpleNamespace(state=state))

    def _user(self):
        return UserInfo(email="alice@example.com", username="alice", user="Alice", ip="127.0.0.1", groups=[])

    def test_refuses_removing_own_admin_entry(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        assert _would_lose_team_write_access(
            self._request(), db_session, manager, team.id, [_create("bob@example.com")], self._user(),
        ) is True

    def test_refuses_deleting_the_team_that_grants_access(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        assert _would_lose_team_write_access(
            self._request(), db_session, manager, team.id, [], self._user(),
        ) is True

    def test_allows_adding_members_while_keeping_own_entry(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        assert _would_lose_team_write_access(
            self._request(), db_session, manager, team.id,
            [_create("alice@example.com", override="Admin"), _create("bob@example.com")], self._user(),
        ) is False

    def test_applied_role_override_skips_the_guard(self, manager, db_session):
        team = _team(db_session)
        _member(db_session, team, "alice@example.com", override="Admin")

        assert _would_lose_team_write_access(
            self._request(applied_role="role-1"), db_session, manager, team.id, [], self._user(),
        ) is False
