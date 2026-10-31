"""The contract read rule shared by the list and the single-contract routes (PRD #442)."""
import uuid
from pathlib import Path

import pytest

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb

ME = "me@example.com"
OTHER = "someone-else@example.com"


@pytest.fixture
def manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _contract(db_session, *, status, draft_owner=None, family=None, team=None):
    cid = str(uuid.uuid4())
    row = DataContractDb(id=cid, name="orders", version="1.0.0", status=status,
                         version_family_id=family or cid, draft_owner_id=draft_owner,
                         owner_team_id=team)
    db_session.add(row)
    db_session.flush()
    return row


def _readable(manager, db_session, rows, *, admin=False, teams=()):
    return manager.readable_contracts(
        db_session, rows, is_admin=admin, caller_email=ME, caller_team_ids=set(teams)
    )


def _can_read(manager, db_session, row, **kwargs):
    return bool(_readable(manager, db_session, [row], **kwargs))


def test_published_contracts_are_readable(manager, db_session):
    for status in ("active", "deprecated"):
        assert _can_read(manager, db_session, _contract(db_session, status=status)), status


@pytest.mark.parametrize("status", ["draft", "proposed", "under_review", "approved", "retired"])
def test_unpublished_contracts_need_elevation(manager, db_session, status):
    assert not _can_read(manager, db_session, _contract(db_session, status=status))


def test_another_users_personal_draft_is_not_readable_even_for_the_team(manager, db_session):
    row = _contract(db_session, status="draft", draft_owner=OTHER, team="team-1")
    assert not _can_read(manager, db_session, row, teams=["team-1"])


def test_own_personal_draft_is_readable(manager, db_session):
    assert _can_read(manager, db_session, _contract(db_session, status="draft", draft_owner=ME))


def test_owning_team_members_read_the_teams_unpublished_versions(manager, db_session):
    team_row = _contract(db_session, status="proposed", team="team-1")
    other_team_row = _contract(db_session, status="proposed", team="team-2")
    assert _can_read(manager, db_session, team_row, teams=["team-1"])
    assert not _can_read(manager, db_session, other_team_row, teams=["team-1"])


def test_authoring_any_version_elevates_the_family(manager, db_session):
    proposed = _contract(db_session, status="under_review")
    _contract(db_session, status="draft", draft_owner=ME, family=proposed.version_family_id)
    assert _can_read(manager, db_session, proposed)


def test_elevated_callers_read_retired_versions_as_in_the_expanded_list(manager, db_session):
    retired = _contract(db_session, status="retired", team="team-1")
    assert _can_read(manager, db_session, retired, teams=["team-1"])


def test_feature_admins_read_everything(manager, db_session):
    rows = [
        _contract(db_session, status="draft", draft_owner=OTHER),
        _contract(db_session, status="proposed"),
        _contract(db_session, status="retired"),
    ]
    assert _readable(manager, db_session, rows, admin=True) == rows


def test_readable_contracts_keeps_the_order_and_drops_the_rest(manager, db_session):
    active = _contract(db_session, status="active")
    hidden = _contract(db_session, status="proposed")
    deprecated = _contract(db_session, status="deprecated")
    assert _readable(manager, db_session, [deprecated, hidden, active]) == [deprecated, active]


def test_list_uses_the_same_rule(manager, db_session):
    """The list keeps what the rule allows (no personal-draft row from another user here)."""
    rows = [
        _contract(db_session, status="active"),
        _contract(db_session, status="proposed"),
        _contract(db_session, status="proposed", team="team-1"),
        _contract(db_session, status="retired"),
    ]
    listed, _counts = manager._query_contracts(
        db_session, is_admin=False, latest_only=False,
        caller_email=ME, caller_team_ids={"team-1"},
    )
    listed_ids = {c.id for c in listed}
    expected = {c.id for c in _readable(manager, db_session, rows, teams=["team-1"])}
    assert listed_ids & {c.id for c in rows} == expected
