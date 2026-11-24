"""What GET /api/search returns to a Data Consumer, asserted on the HTTP response.

The marketplace asks for ``types=data-product``. An unpublished product or contract
must never be in the JSON the browser receives, with or without ``types``: hiding it
in the UI is not enough (the response can be inspected). A published one stays.
"""
import uuid

import pytest

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.common.search_interfaces import SearchIndexItem
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb
from src.models.users import UserInfo

OWNER = "owner@example.com"
TERM = "visibilityzebra"


def _item(kind, row, feature_id, type_):
    return SearchIndexItem(
        id=f"{kind}::{row.id}", type=type_, feature_id=feature_id,
        title=f"{TERM} {row.name}", description=TERM, link=f"/{feature_id}/{row.id}",
        tags=[], extra_data={},
    )


@pytest.fixture
def consumer(client):
    async def _override():
        email = "consumer@example.com"
        return UserInfo(username=email, email=email, user=email, ip="127.0.0.1",
                        groups=["data-consumers"])

    app.dependency_overrides[get_user_details_from_sdk] = _override
    yield client
    app.dependency_overrides.pop(get_user_details_from_sdk, None)


@pytest.fixture
def indexed(db_session):
    # Savepoint: a failed request rolls the request's session back, not the test's data
    db_session.connection().begin_nested()
    rows = {
        "published_product": DataProductDb(
            id=str(uuid.uuid4()), name="published-product", version="1.0.0",
            status="active", publication_scope="organization"),
        "draft_product": DataProductDb(
            id=str(uuid.uuid4()), name="draft-product", version="0.1.0",
            status="draft", draft_owner_id=OWNER),
        "published_contract": DataContractDb(
            id=str(uuid.uuid4()), name="published-contract", version="1.0.0", status="active"),
        "draft_contract": DataContractDb(
            id=str(uuid.uuid4()), name="draft-contract", version="0.1.0",
            status="draft", draft_owner_id=OWNER),
    }
    db_session.add_all(rows.values())
    db_session.flush()
    search = app.state.search_manager
    for key, row in rows.items():
        if "product" in key:
            search.upsert_item(_item("product", row, "data-products", "data-product"))
        else:
            search.upsert_item(_item("contract", row, "data-contracts", "data-contract"))
    yield {key: row.id for key, row in rows.items()}
    for row in rows.values():
        search.remove_item(
            f"{'product' if isinstance(row, DataProductDb) else 'contract'}::{row.id}")


def _ids(response):
    assert response.status_code == 200
    return {hit["id"] for hit in response.json()}


def test_search_response_has_no_unpublished_product_or_contract(consumer, indexed):
    ids = _ids(consumer.get(f"/api/search?search_term={TERM}"))
    assert f"product::{indexed['published_product']}" in ids
    assert f"contract::{indexed['published_contract']}" in ids
    assert f"product::{indexed['draft_product']}" not in ids
    assert f"contract::{indexed['draft_contract']}" not in ids


def test_search_response_with_types_has_no_unpublished_product(consumer, indexed):
    """The marketplace call: the ``types`` filter must not bypass the read rule."""
    response = consumer.get(f"/api/search?search_term={TERM}&types=data-product")
    ids = _ids(response)
    assert ids == {f"product::{indexed['published_product']}"}
    # Nothing of the draft in the raw body either (id, title, link)
    assert indexed["draft_product"] not in response.text
    assert "draft-product" not in response.text


def test_search_response_with_contract_type_has_no_unpublished_contract(consumer, indexed):
    response = consumer.get(f"/api/search?search_term={TERM}&types=data-contract")
    assert _ids(response) == {f"contract::{indexed['published_contract']}"}
    assert indexed["draft_contract"] not in response.text
