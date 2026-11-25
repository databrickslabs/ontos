"""Who may call the product access and linked-assets routes (#1613, review).

- ``GET /api/data-products/{id}/my-access``: without data-products the answer
  is 403 for an existing id and a missing one alike (no existence probe); a
  product the caller can't read answers 404 like the product page; otherwise
  ``can_write`` follows the PUT ownership rule.
- ``GET /api/data-products/{id}/assets``: the product page's read rule. A
  consumer reads the linked assets of a published product (it answered 403:
  the route used the owned-products listing) and gets 404 on a draft they
  can't read.
"""
import uuid

import pytest

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.db_models.data_products import DataProductDb
from src.models.users import UserInfo

OWNER = "owner@example.com"
PERSONAS = {
    "owner": (OWNER, ["data-producers"]),  # Data Producer, the draft owner
    "producer": ("other@example.com", ["data-producers"]),  # writer, not an owner
    "consumer": ("consumer@example.com", ["data-consumers"]),
    "nobody": ("nobody@example.com", []),  # no data-products permission
}


@pytest.fixture
def as_persona(client):
    def _switch(persona):
        email, groups = PERSONAS[persona]

        async def _override():
            return UserInfo(username=email, email=email, user=email, ip="127.0.0.1", groups=groups)

        app.dependency_overrides[get_user_details_from_sdk] = _override
        return client

    yield _switch
    app.dependency_overrides.pop(get_user_details_from_sdk, None)


@pytest.fixture
def products(db_session):
    # Savepoint: a 404 rolls the request's session back, not the test's data
    db_session.connection().begin_nested()
    rows = {
        "published": DataProductDb(id=str(uuid.uuid4()), name="pub", version="1.0.0",
                                   status="active", publication_scope="organization"),
        "draft": DataProductDb(id=str(uuid.uuid4()), name="draft", version="0.1.0",
                               status="draft", draft_owner_id=OWNER),
    }
    db_session.add_all(rows.values())
    db_session.flush()
    return {k: v.id for k, v in rows.items()}


def _get(client, path):
    response = client.get(path)
    return response.status_code, (response.json() if response.content else None)


def test_my_access_without_the_feature_is_403_for_existing_and_missing(as_persona, products):
    client = as_persona("nobody")
    existing, _ = _get(client, f"/api/data-products/{products['draft']}/my-access")
    missing, _ = _get(client, f"/api/data-products/{uuid.uuid4()}/my-access")
    assert (existing, missing) == (403, 403)


def test_my_access_follows_the_read_and_write_rules(as_persona, products):
    draft = f"/api/data-products/{products['draft']}/my-access"
    published = f"/api/data-products/{products['published']}/my-access"
    assert _get(as_persona("owner"), draft) == (200, {"can_write": True})
    assert _get(as_persona("consumer"), draft)[0] == 404
    assert _get(as_persona("consumer"), published) == (200, {"can_write": False})
    assert _get(as_persona("producer"), published) == (200, {"can_write": False})


def test_linked_assets_follow_the_product_read_rule(as_persona, products):
    consumer = as_persona("consumer")
    status, body = _get(consumer, f"/api/data-products/{products['published']}/assets")
    assert status == 200, body
    assert _get(consumer, f"/api/data-products/{products['draft']}/assets")[0] == 404
    assert _get(as_persona("owner"), f"/api/data-products/{products['draft']}/assets")[0] == 200
