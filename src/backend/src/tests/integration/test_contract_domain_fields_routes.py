"""Domain fields of a contract create / update, through the routes.

A domain field counts as sent when its key is present with a non-null value, so
``[]`` and ``""`` are values, not absence:
- ``primaryDomainId: ""`` and ``domainIds: [""]`` are refused (400, code
  ``invalid_domain_identifier``), they don't clear the domains;
- ``domainIds: []`` clears the domains, also when the legacy ``domainId`` is sent
  (the modern fields win over the legacy one).
"""
import uuid

from src.db_models.data_domains import DataDomain

CODE = "invalid_domain_identifier"


def _domain(db) -> str:
    domain = DataDomain(
        id=str(uuid.uuid4()), name=f"d-{uuid.uuid4().hex[:8]}", created_by="user@example.com",
    )
    db.add(domain)
    db.flush()
    return domain.id


def _create(client, **fields):
    resp = client.post("/api/data-contracts", json={
        "name": f"Orders {uuid.uuid4().hex[:6]}", "version": "1.0.0", **fields,
    })
    assert resp.status_code == 200, resp.text
    return resp.json()


def _assert_refused(resp, field):
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == CODE
    assert detail["params"] == {"field": field}


def test_an_update_with_empty_domain_ids_and_a_legacy_domain_id_clears_the_domains(
    client, db_session
):
    first, second = _domain(db_session), _domain(db_session)
    contract = _create(client, domainIds=[first, second], primaryDomainId=first)
    assert contract["domainIds"] == [first, second]

    resp = client.put(
        f"/api/data-contracts/{contract['id']}", json={"domainIds": [], "domainId": first},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["domainIds"] == []
    assert resp.json()["primaryDomainId"] is None


def test_an_update_with_domain_ids_ignores_the_legacy_domain_id(client, db_session):
    first, second, third = _domain(db_session), _domain(db_session), _domain(db_session)
    contract = _create(client, domainIds=[first])

    resp = client.put(
        f"/api/data-contracts/{contract['id']}", json={"domainIds": [second], "domainId": third},
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["domainIds"] == [second]
    assert resp.json()["primaryDomainId"] == second


def test_an_update_with_an_empty_primary_domain_id_is_refused(client, db_session):
    contract = _create(client, domainIds=[_domain(db_session)])

    resp = client.put(
        f"/api/data-contracts/{contract['id']}", json={"primaryDomainId": ""},
    )

    _assert_refused(resp, "primaryDomainId")


def test_an_update_with_an_empty_domain_id_is_refused(client, db_session):
    contract = _create(client, domainIds=[_domain(db_session)])

    resp = client.put(f"/api/data-contracts/{contract['id']}", json={"domainId": ""})

    _assert_refused(resp, "domainId")


def test_an_update_with_an_empty_entry_in_domain_ids_is_refused(client, db_session):
    contract = _create(client, domainIds=[_domain(db_session)])

    resp = client.put(f"/api/data-contracts/{contract['id']}", json={"domainIds": [""]})

    _assert_refused(resp, "domainIds")


def test_a_create_with_an_empty_primary_domain_id_is_refused(client, db_session):
    resp = client.post("/api/data-contracts", json={
        "name": f"Orders {uuid.uuid4().hex[:6]}", "version": "1.0.0",
        "domainIds": [_domain(db_session)], "primaryDomainId": "",
    })

    _assert_refused(resp, "primaryDomainId")


def test_a_create_with_a_domain_name_in_domain_ids_is_refused(client, db_session):
    """domainIds takes ids: a domain NAME (what a product's `domain` holds) is an unknown
    id, refused with a 400 and nothing is created."""
    domain = DataDomain(
        id=str(uuid.uuid4()), name=f"Sales-{uuid.uuid4().hex[:6]}", created_by="u@example.com",
    )
    db_session.add(domain)
    db_session.flush()

    resp = client.post("/api/data-contracts", json={
        "name": f"Orders {uuid.uuid4().hex[:6]}", "version": "1.0.0",
        "domainIds": [domain.name], "primaryDomainId": domain.name,
    })

    assert resp.status_code == 400, resp.text


def test_a_create_with_the_domain_ids_of_a_product_keeps_them(client, db_session):
    first, second = _domain(db_session), _domain(db_session)

    contract = _create(client, domainIds=[first, second], primaryDomainId=second)

    assert contract["domainIds"] == [second, first] or contract["domainIds"] == [first, second]
    assert contract["primaryDomainId"] == second
