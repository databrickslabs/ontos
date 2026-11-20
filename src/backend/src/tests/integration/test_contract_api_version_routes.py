"""``POST /api/data-contracts`` reads ``apiVersion`` by its documented camelCase name.

Before, only ``api_version`` was read: a camelCase ``apiVersion`` was ignored and the
contract silently got the ``v3.1.0`` default.
"""
import uuid

import pytest


def _create(client, **fields):
    resp = client.post("/api/data-contracts", json={
        "name": f"Orders {uuid.uuid4().hex[:6]}", "version": "1.0.0", **fields,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize("key", ["apiVersion", "api_version"])
def test_a_create_stores_the_api_version_sent_under_either_spelling(client, db_session, key):
    assert _create(client, **{key: "3.0.2"})["apiVersion"] == "v3.0.2"


def test_a_create_without_api_version_gets_the_default(client, db_session):
    assert _create(client)["apiVersion"] == "v3.1.0"


def test_a_create_with_both_spellings_takes_the_name(client, db_session):
    assert _create(client, apiVersion="v3.0.2", api_version="v3.1.0")["apiVersion"] == "v3.0.2"


def test_a_create_stores_the_fields_the_wizard_sends_by_name(client, db_session):
    """The contract wizard POSTs camelCase field names (``dataProduct``, ``domainIds``,
    ``primaryDomainId``, ``tenant``, ``description``): each is stored, none is dropped."""
    from src.db_models.data_contracts import DataContractDb
    from src.db_models.data_domains import DataDomain

    domain = DataDomain(
        id=str(uuid.uuid4()), name=f"d-{uuid.uuid4().hex[:8]}", created_by="u@example.com",
    )
    db_session.add(domain)
    db_session.flush()

    created = _create(
        client,
        owner="alice@example.com",
        status="draft",
        domainIds=[domain.id],
        primaryDomainId=domain.id,
        tenant="acme",
        dataProduct="orders-dp",
        description={"usage": "u", "purpose": "p", "limitations": "l"},
        consumers=[], subjectMatterExperts=[],
        accessControl={"readGroups": [], "writeGroups": []},
        support={"primaryEmail": "team@example.com"},
        authoritativeDefinitions=[],
        schema=[],
    )

    row = db_session.get(DataContractDb, created["id"])
    assert (row.tenant, row.data_product) == ("acme", "orders-dp")
    assert (row.description_usage, row.description_purpose, row.description_limitations) == (
        "u", "p", "l",
    )
    assert created["domainIds"] == [domain.id]
    assert created["primaryDomainId"] == domain.id


@pytest.mark.parametrize("fields", [
    {"dataProduct": "orders-dp"}, {"data_product": "orders-dp"},
])
def test_a_create_stores_the_data_product_under_either_spelling(client, db_session, fields):
    from src.db_models.data_contracts import DataContractDb

    created = _create(client, **fields)

    assert db_session.get(DataContractDb, created["id"]).data_product == "orders-dp"
