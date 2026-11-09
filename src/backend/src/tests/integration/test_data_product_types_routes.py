"""Integration tests for /api/data-product-types (HTTP status and error mapping).

The rules themselves are covered in tests/unit/test_data_product_types_manager.py.
"""

import uuid

import pytest

from src.db_models.data_products import DataProductDb
from src.repositories.data_product_types_repository import data_product_types_repo

BASE = "/api/data-product-types"


@pytest.fixture
def seeded(db_session):
    data_product_types_repo.seed_defaults(db_session)
    db_session.commit()


def _id(db_session, key):
    return str(data_product_types_repo.get_by_key(db_session, key).id)


def test_list_returns_seeded_types_in_order(client, seeded):
    response = client.get(BASE)

    assert response.status_code == 200, response.text
    data = response.json()
    assert [t["key"] for t in data] == [
        "source-aligned",
        "aggregate",
        "consumer-aligned",
        "source",
        "sink",
    ]
    assert all(t["is_seeded"] and t["usage_count"] == 0 for t in data)


def test_list_active_only(client, db_session, seeded):
    client.put(f"{BASE}/{_id(db_session, 'sink')}", json={"is_active": False})

    keys = [t["key"] for t in client.get(BASE, params={"active_only": True}).json()]

    assert "sink" not in keys


def test_get_one_and_unknown_id(client, db_session, seeded):
    assert client.get(f"{BASE}/{_id(db_session, 'aggregate')}").json()["key"] == "aggregate"

    response = client.get(f"{BASE}/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "data_product_type_not_found"


def test_create_returns_201_and_duplicate_returns_409(client, seeded):
    body = {"key": "custom", "label": "Custom"}

    created = client.post(BASE, json=body)
    assert created.status_code == 201, created.text
    assert created.json()["sort_order"] == 6

    duplicate = client.post(BASE, json=body)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "data_product_type_key_exists"


def test_create_rejects_bad_key(client, seeded):
    assert client.post(BASE, json={"key": "Not Kebab", "label": "X"}).status_code == 422


def test_update_renames_and_rejects_key_change(client, db_session, seeded):
    type_id = _id(db_session, "aggregate")

    renamed = client.put(f"{BASE}/{type_id}", json={"label": "Composite"})
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["label"] == "Composite"

    assert client.put(f"{BASE}/{type_id}", json={"key": "composite"}).status_code == 422


def test_update_refuses_to_deactivate_default(client, db_session, seeded):
    response = client.put(f"{BASE}/{_id(db_session, 'source-aligned')}", json={"is_active": False})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "data_product_type_default_inactive"


def test_reorder(client, db_session, seeded):
    response = client.put(
        f"{BASE}/reorder",
        json={"types": [{"id": _id(db_session, "sink"), "sort_order": 0}]},
    )

    assert response.status_code == 200, response.text
    assert response.json()[0]["key"] == "sink"


def test_delete_custom_type(client, seeded):
    type_id = client.post(BASE, json={"key": "custom", "label": "Custom"}).json()["id"]

    assert client.delete(f"{BASE}/{type_id}").status_code == 204
    assert client.get(f"{BASE}/{type_id}").status_code == 404


def test_delete_seeded_type_returns_409(client, db_session, seeded):
    response = client.delete(f"{BASE}/{_id(db_session, 'sink')}")

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "data_product_type_seeded"


def test_delete_type_in_use_returns_409(client, db_session, seeded):
    type_id = client.post(BASE, json={"key": "custom", "label": "Custom"}).json()["id"]
    db_session.add(
        DataProductDb(
            id=str(uuid.uuid4()),
            name="Typed Product",
            version="1.0.0",
            status="draft",
            product_type_id=uuid.UUID(type_id),
        )
    )
    db_session.commit()

    response = client.delete(f"{BASE}/{type_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["params"] == {"key": "custom", "count": 1}
