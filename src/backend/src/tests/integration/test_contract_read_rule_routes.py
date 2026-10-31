"""The single-contract read routes use the same read rule as the contract list.

Every ``GET /api/data-contracts/{id}/...`` route that returns a contract's
content (or content derived from it) answers 404, with the body of a missing
contract, when the caller can't read the contract; it answers 200 otherwise.
Each persona runs through every route in one test, and a failure lists the
routes that answered differently.
"""
import uuid

import pytest

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.db_models.data_contracts import (
    DataContractDb,
    DataProfilingRunDb,
    SchemaObjectDb,
    SchemaPropertyDb,
)
from src.db_models.data_products import DataProductDb
from src.db_models.teams import TeamDb, TeamMemberDb
from src.models.users import UserInfo

OWNER = "owner@example.com"
TEAMMATE = "teammate@example.com"
CONSUMER = "consumer@example.com"
GOVERNANCE = "governance@example.com"

# email, groups (the default roles map these groups to the role in the comment)
PERSONAS = {
    "owner": (OWNER, ["data-producers"]),  # Data Producer
    "teammate": (TEAMMATE, ["data-producers"]),  # Data Producer, owning-team member
    "consumer": (CONSUMER, ["data-consumers"]),  # Data Consumer (data-contracts read)
    "feature_admin": (GOVERNANCE, ["data-governance-officers"]),  # data-contracts admin
}

ROUTES = [
    "/api/data-contracts/{cid}",
    "/api/data-contracts/{cid}/schemas",
    "/api/data-contracts/{cid}/schemas/{schema_name}/properties",
    "/api/data-contracts/{cid}/odcs/export",
    "/api/data-contracts/{cid}/entity-relationships",
    "/api/data-contracts/{cid}/comments",
    "/api/data-contracts/{cid}/profile-runs",
    "/api/data-contracts/{cid}/profile-runs/{run_id}/suggestions",
    "/api/data-contracts/{cid}/custom-properties",
    "/api/data-contracts/{cid}/support",
    "/api/data-contracts/{cid}/pricing",
    "/api/data-contracts/{cid}/roles",
    "/api/data-contracts/{cid}/authoritative-definitions",
    "/api/data-contracts/{cid}/schemas/{schema_id}/authoritative-definitions",
    "/api/data-contracts/{cid}/schemas/{schema_id}/properties/{prop_id}/authoritative-definitions",
    "/api/data-contracts/{cid}/tags",
    "/api/data-contracts/{cid}/versions",
    "/api/data-contracts/{cid}/version-history",
    "/api/data-contracts/{cid}/diff-from-parent",
    "/api/data-contracts/{cid}/schemas/{schema_id}/relationships",
    "/api/data-contracts/{cid}/schemas/{schema_id}/properties/{prop_id}/relationships",
    "/api/data-contracts/{cid}/team-metadata",
    "/api/data-contracts/{cid}/maturity",
    "/api/data-contracts/{cid}/maturity/history",
]

NOT_FOUND = {"detail": "Contract not found"}


@pytest.fixture
def as_persona(client):
    """Switch the caller of ``client`` to one of ``PERSONAS``."""
    def _switch(persona):
        email, groups = PERSONAS[persona]

        async def _override():
            return UserInfo(username=email, email=email, user=email, ip="127.0.0.1", groups=groups)

        app.dependency_overrides[get_user_details_from_sdk] = _override
        return client

    return _switch


@pytest.fixture
def team(db_session):
    """A team with the owner and the teammate as members.

    Opens a SAVEPOINT first: a request that answers 404 rolls its session back,
    and inside a savepoint that undoes only the request, not the test's data.
    """
    db_session.connection().begin_nested()
    row = TeamDb(id=str(uuid.uuid4()), name=f"team-{uuid.uuid4().hex[:8]}",
                 created_by=OWNER, updated_by=OWNER)
    db_session.add(row)
    db_session.flush()
    for email in (OWNER, TEAMMATE):
        db_session.add(TeamMemberDb(team_id=row.id, member_type="user",
                                    member_identifier=email, added_by=OWNER))
    db_session.flush()
    return row


def _contract(db_session, *, status, draft_owner=None, team_id=None):
    """A v1.0.0 (active) parent and the v1.1.0 contract under test, in one family.

    The contract has a schema object, a property and a profiling run, so the
    sub-resource routes have something to return.
    """
    family = str(uuid.uuid4())
    parent = DataContractDb(id=family, name="orders", version="1.0.0", status="active",
                            version_family_id=family, owner_team_id=team_id)
    db_session.add(parent)
    db_session.flush()
    row = DataContractDb(id=str(uuid.uuid4()), name="orders", version="1.1.0", status=status,
                         version_family_id=family, parent_contract_id=parent.id,
                         draft_owner_id=draft_owner, owner_team_id=team_id)
    db_session.add(row)
    db_session.flush()
    schema = SchemaObjectDb(id=str(uuid.uuid4()), contract_id=row.id, name="orders_tbl",
                            physical_name="cat.sch.orders")
    db_session.add(schema)
    db_session.flush()
    prop = SchemaPropertyDb(id=str(uuid.uuid4()), object_id=schema.id, name="order_id",
                            logical_type="string")
    run = DataProfilingRunDb(id=str(uuid.uuid4()), contract_id=row.id, source="manual",
                             status="completed")
    db_session.add_all([prop, run])
    db_session.commit()
    return {"cid": row.id, "schema_id": schema.id, "schema_name": schema.name,
            "prop_id": prop.id, "run_id": run.id}


def _statuses(client, ids):
    return {route: client.get(route.format(**ids)) for route in ROUTES}


def _mismatches(responses, expected):
    """Routes whose status isn't ``expected``; a 404 must have the missing-contract body."""
    wrong = {r: resp.status_code for r, resp in responses.items() if resp.status_code != expected}
    if expected == 404:
        wrong.update({r: resp.json() for r, resp in responses.items()
                      if resp.status_code == 404 and resp.json() != NOT_FOUND})
    return wrong


CASES = [
    # (contract kind, persona, expected status)
    ("personal_draft", "consumer", 404),
    ("personal_draft", "teammate", 404),  # another user's personal draft, same team
    ("personal_draft", "owner", 200),
    ("personal_draft", "feature_admin", 200),
    ("team_draft", "consumer", 404),
    ("team_draft", "teammate", 200),
    ("team_draft", "feature_admin", 200),
    ("proposed", "consumer", 404),
    ("proposed", "teammate", 200),
    ("under_review", "consumer", 404),
    ("under_review", "teammate", 200),
    ("under_review", "feature_admin", 200),
    ("active", "consumer", 200),
    ("deprecated", "consumer", 200),
]


def _make(db_session, team, kind):
    if kind == "personal_draft":
        return _contract(db_session, status="draft", draft_owner=OWNER, team_id=team.id)
    if kind == "team_draft":
        return _contract(db_session, status="draft", team_id=team.id)
    return _contract(db_session, status=kind, team_id=team.id)


@pytest.mark.parametrize("kind,persona,expected", CASES, ids=[f"{k}-{p}" for k, p, _ in CASES])
def test_read_routes_follow_the_list_rule(as_persona, db_session, team, kind, persona, expected):
    ids = _make(db_session, team, kind)
    responses = _statuses(as_persona(persona), ids)
    assert _mismatches(responses, expected) == {}


def test_missing_contract_answers_the_same_404(as_persona, db_session, team):
    ids = _make(db_session, team, "active")
    ids["cid"] = str(uuid.uuid4())
    responses = _statuses(as_persona("consumer"), ids)
    assert _mismatches(responses, 404) == {}


def test_versions_list_only_the_readable_versions(as_persona, db_session, team):
    ids = _make(db_session, team, "proposed")
    parent_id = db_session.get(DataContractDb, ids["cid"]).parent_contract_id

    consumer = as_persona("consumer").get(f"/api/data-contracts/{parent_id}/versions")
    assert consumer.status_code == 200
    assert [v["id"] for v in consumer.json()] == [parent_id]

    teammate = as_persona("teammate").get(f"/api/data-contracts/{parent_id}/versions")
    assert {v["id"] for v in teammate.json()} == {parent_id, ids["cid"]}


def test_version_history_leaves_out_unreadable_children(as_persona, db_session, team):
    ids = _make(db_session, team, "proposed")
    parent_id = db_session.get(DataContractDb, ids["cid"]).parent_contract_id

    consumer = as_persona("consumer").get(f"/api/data-contracts/{parent_id}/version-history")
    assert consumer.status_code == 200
    assert consumer.json()["children"] == []

    teammate = as_persona("teammate").get(f"/api/data-contracts/{parent_id}/version-history")
    assert [c["id"] for c in teammate.json()["children"]] == [ids["cid"]]


def test_sub_resources_of_another_contract_are_not_found(as_persona, db_session, team):
    """A readable contract id doesn't open the schema or property of another contract."""
    readable = _make(db_session, team, "active")
    hidden = _make(db_session, team, "proposed")
    client = as_persona("consumer")
    cid = readable["cid"]
    paths = [
        f"/api/data-contracts/{cid}/schemas/{hidden['schema_id']}/authoritative-definitions",
        f"/api/data-contracts/{cid}/schemas/{hidden['schema_id']}/properties/"
        f"{hidden['prop_id']}/authoritative-definitions",
        f"/api/data-contracts/{cid}/schemas/{hidden['schema_id']}/properties/"
        f"{hidden['prop_id']}/relationships",
        f"/api/data-contracts/{cid}/profile-runs/{hidden['run_id']}/suggestions",
    ]
    assert {p: client.get(p).status_code for p in paths} == {p: 404 for p in paths}


@pytest.mark.parametrize("persona,expected", [("consumer", 404), ("teammate", 200)])
def test_maturity_evaluation_follows_the_rule(as_persona, db_session, team, persona, expected):
    ids = _make(db_session, team, "proposed")
    response = as_persona(persona).post(f"/api/data-contracts/{ids['cid']}/maturity/evaluate")
    assert response.status_code == expected
    if expected == 404:
        assert response.json() == NOT_FOUND


PRODUCT_ROUTES = [
    ("get", "/api/data-products/{pid}/maturity"),
    ("get", "/api/data-products/{pid}/maturity/history"),
    ("post", "/api/data-products/{pid}/maturity/evaluate"),
]
PRODUCT_NOT_FOUND = {"detail": "Data product not found"}

PRODUCT_CASES = [
    # (status, owned through, persona, expected status)
    ("draft", "draft_owner", "consumer", 404),
    ("draft", "draft_owner", "owner", 200),
    ("draft", "draft_owner", "feature_admin", 200),
    ("draft", "team", "consumer", 404),
    ("draft", "team", "teammate", 200),
    ("proposed", "team", "consumer", 404),
    ("proposed", "team", "teammate", 200),
    ("proposed", "team", "feature_admin", 200),
    ("active", "team", "consumer", 200),
    ("deprecated", "team", "consumer", 200),
]


def _product(db_session, team, status, owned_through):
    row = DataProductDb(
        id=str(uuid.uuid4()), name="orders-product", version="1.0.0", status=status,
        draft_owner_id=OWNER if owned_through == "draft_owner" else None,
        owner_team_id=team.id if owned_through == "team" else None,
    )
    db_session.add(row)
    db_session.commit()
    return row.id


def _product_responses(client, pid):
    return {f"{m} {r}": getattr(client, m)(r.format(pid=pid)) for m, r in PRODUCT_ROUTES}


@pytest.mark.parametrize("status,owned_through,persona,expected", PRODUCT_CASES,
                         ids=[f"{s}-{o}-{p}" for s, o, p, _ in PRODUCT_CASES])
def test_product_maturity_routes_follow_the_product_read_rule(
        as_persona, db_session, team, status, owned_through, persona, expected):
    pid = _product(db_session, team, status, owned_through)
    responses = _product_responses(as_persona(persona), pid)
    assert {r: x.status_code for r, x in responses.items() if x.status_code != expected} == {}
    if expected == 404:
        assert all(x.json() == PRODUCT_NOT_FOUND for x in responses.values())


def test_missing_product_answers_the_same_404_on_the_maturity_routes(as_persona):
    responses = _product_responses(as_persona("consumer"), str(uuid.uuid4()))
    assert {r: x.status_code for r, x in responses.items() if x.status_code != 404} == {}
    assert all(x.json() == PRODUCT_NOT_FOUND for x in responses.values())
