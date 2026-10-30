"""Lineage read gates (routes/business_lineage_routes.py) — the predicates the
lineage walk applies to every product and contract it adds (PR #973 review)."""

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.controller.model_lineage import LineageAccess
from src.db_models.data_contracts import DataContractDb
from src.models.users import UserInfo
from src.routes import business_lineage_routes as routes

ME = "Me@Example.com"


def _user(email=ME, groups=None):
    return UserInfo(email=email, username=email, user=email, ip=None, groups=groups or [])


def _contract(db_session, *, status="active", draft_owner=None, family=None, team=None):
    c = DataContractDb(
        id=str(uuid4()), name=f"c-{uuid4().hex[:6]}", version="1.0.0",
        version_family_id=family or str(uuid4()), status=status,
        draft_owner_id=draft_owner, owner_team_id=team,
    )
    db_session.add(c)
    db_session.flush()
    return c


@pytest.fixture
def no_teams(monkeypatch):
    from src.controller import teams_manager as tm
    monkeypatch.setattr(tm.teams_manager, "get_teams_for_user", lambda db, email, groups: [])


def _access(db_session, admin=False, user=None):
    return routes.build_lineage_access(SimpleNamespace(), db_session, user or _user(), admin)


def test_published_contract_is_readable(db_session, no_teams):
    assert _access(db_session).can_read_contract(_contract(db_session, status="active"))
    assert _access(db_session).can_read_contract(_contract(db_session, status="deprecated"))


def test_other_users_personal_draft_is_hidden_even_if_active(db_session, no_teams):
    row = _contract(db_session, status="active", draft_owner="someone-else@example.com")
    assert not _access(db_session).can_read_contract(row)


def test_own_personal_draft_matches_case_insensitively(db_session, no_teams):
    row = _contract(db_session, status="draft", draft_owner="me@example.com")
    assert _access(db_session).can_read_contract(row)


def test_unpublished_contract_hidden_from_consumers(db_session, no_teams):
    for status in ("draft", "proposed", "under_review", "approved", "retired"):
        assert not _access(db_session).can_read_contract(_contract(db_session, status=status)), status


def test_elevated_via_family_ownership_or_team(db_session, monkeypatch):
    family = str(uuid4())
    _contract(db_session, status="active", draft_owner=None, family=family)
    owned_elsewhere = _contract(db_session, status="draft", family=str(uuid4()))
    _contract(db_session, status="active", draft_owner="me@example.com", family=owned_elsewhere.version_family_id)

    from src.controller import teams_manager as tm
    monkeypatch.setattr(tm.teams_manager, "get_teams_for_user",
                        lambda db, email, groups: [SimpleNamespace(id="team-1")])
    team_draft = _contract(db_session, status="proposed", team="team-1")
    other_team_draft = _contract(db_session, status="proposed", team="team-2")

    access = _access(db_session)
    assert access.can_read_contract(owned_elsewhere)  # caller authored a version in the family
    assert access.can_read_contract(team_draft)
    assert not access.can_read_contract(other_team_draft)


def test_admin_sees_everything(db_session, no_teams):
    row = _contract(db_session, status="draft", draft_owner="someone-else@example.com")
    assert _access(db_session, admin=True).can_read_contract(row)


def test_product_gate_delegates_to_product_route(db_session, monkeypatch):
    from src.routes import data_product_routes
    seen = []
    monkeypatch.setattr(data_product_routes, "_caller_can_read_product",
                        lambda request, db, user, manager, row: seen.append(row) or False)
    row = SimpleNamespace(id="p1")
    assert _access(db_session).can_read_product(row) is False
    assert seen == [row]


@pytest.mark.asyncio
async def test_feature_admin_check_fails_closed(monkeypatch):
    import src.common.authorization as authz

    async def boom(**kwargs):
        raise RuntimeError("auth down")

    monkeypatch.setattr(authz, "is_user_feature_admin", boom)
    assert await routes.contracts_feature_admin(SimpleNamespace(), _user()) is False


@pytest.mark.parametrize("route", ["get_business_lineage", "get_impact_analysis"])
def test_routes_always_pass_access(db_session, route):
    manager = MagicMock()
    fn = getattr(routes, route)
    kwargs = dict(entity_type="DataProduct", entity_id="p1", request=SimpleNamespace(), db=db_session,
                  current_user=_user(), contracts_admin=False, max_depth=2, manager=manager)
    if route == "get_business_lineage":
        kwargs["direction"] = None
    fn(**kwargs)
    access = manager.get_business_lineage.call_args.kwargs["access"]
    assert isinstance(access, LineageAccess)
