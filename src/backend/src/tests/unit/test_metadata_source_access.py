"""Read gate for merged-metadata inheritance sources (routes/metadata_routes.py):
a source is used only when the caller could open it through its own read route."""

from types import SimpleNamespace
from uuid import uuid4

import pytest

from src.db_models.data_contracts import DataContractDb
from src.models.users import UserInfo
from src.routes import assets_routes
from src.routes import metadata_routes as routes

ME = "me@example.com"


def _user():
    return UserInfo(email=ME, username=ME, user=ME, ip=None, groups=[])


def _contract(db_session, *, status="active", draft_owner=None, team=None):
    c = DataContractDb(
        id=str(uuid4()), name=f"c-{uuid4().hex[:6]}", version="1.0.0",
        version_family_id=str(uuid4()), status=status,
        draft_owner_id=draft_owner, owner_team_id=team,
    )
    db_session.add(c)
    db_session.flush()
    return c


class _AssetsManager:
    def __init__(self, ids):
        self.ids = ids
        self.calls = 0

    def resolve_accessible_asset_ids(self, db, *, data_products_manager, is_admin):
        self.calls += 1
        return self.ids


def _request(assets_manager=None, dpm=None):
    state = SimpleNamespace(assets_manager=assets_manager, data_products_manager=dpm)
    return SimpleNamespace(app=SimpleNamespace(state=state))


@pytest.fixture
def no_teams(monkeypatch):
    from src.controller import teams_manager as tm
    monkeypatch.setattr(tm.teams_manager, "get_teams_for_user", lambda db, email, groups: [])


@pytest.fixture
def scoped(monkeypatch):
    """Caller without assets READ_WRITE."""
    monkeypatch.setattr(
        assets_routes, "_user_has_assets_feature", lambda request, user, level: False,
    )


def _asset(asset_id=None):
    return SimpleNamespace(id=asset_id or uuid4())


def test_contract_source_follows_contract_read_rule(db_session, no_teams, scoped):
    can_read = routes.build_inheritance_source_access(_request(), db_session, _user(), False)

    assert can_read("data_contract", _contract(db_session, status="active"))
    assert not can_read("data_contract", _contract(db_session, status="draft"))
    other_team = _contract(db_session, status="proposed", team="other-team")
    assert not can_read("data_contract", other_team)
    assert not can_read(
        "data_contract", _contract(db_session, status="active", draft_owner="someone@example.com"),
    )
    assert can_read("data_contract", _contract(db_session, status="draft", draft_owner=ME))


def test_contracts_admin_reads_every_contract_source(db_session, no_teams, scoped):
    can_read = routes.build_inheritance_source_access(_request(), db_session, _user(), True)

    someone_elses = _contract(db_session, status="draft", draft_owner="x@example.com")
    assert can_read("data_contract", someone_elses)


def test_asset_source_follows_asset_read_rule(db_session, scoped):
    linked = _asset()
    mgr = _AssetsManager([linked.id])
    can_read = routes.build_inheritance_source_access(
        _request(mgr, dpm=object()), db_session, _user(), False,
    )

    assert can_read("asset", linked)
    assert not can_read("asset", _asset())
    assert mgr.calls == 1  # resolved once per request


def test_assets_read_write_reads_every_asset_source(db_session, monkeypatch):
    monkeypatch.setattr(
        assets_routes, "_user_has_assets_feature", lambda request, user, level: True,
    )
    can_read = routes.build_inheritance_source_access(_request(), db_session, _user(), False)

    assert can_read("asset", _asset())


def test_asset_source_fails_closed_without_product_context(db_session, scoped):
    can_read = routes.build_inheritance_source_access(
        _request(_AssetsManager(None), dpm=None), db_session, _user(), False,
    )

    assert not can_read("asset", _asset())


def test_unknown_source_kind_is_rejected(db_session, scoped):
    can_read = routes.build_inheritance_source_access(_request(), db_session, _user(), True)

    assert not can_read("data_product", SimpleNamespace(id="p-1"))
