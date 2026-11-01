"""Two routes used to answer 500 on every call because they passed arguments the
manager no longer accepts:

- POST /api/data-products/from-contract (``product_type`` / ``DataProductType``)
- PUT  /api/data-asset-reviews/{id}/status (``status_update=`` vs ``update_data``)
"""
import uuid
from unittest.mock import MagicMock

import pytest

from src.app import app
from src.controller.data_asset_reviews_manager import DataAssetReviewManager
from src.db_models.data_asset_reviews import DataAssetReviewRequestDb
from src.db_models.data_contracts import DataContractDb


def _contract(db_session, status):
    contract = DataContractDb(name="orders-contract", version="1.0.0", status=status)
    db_session.add(contract)
    db_session.flush()
    return contract


def _from_contract(client, contract_id, **extra):
    body = {"contract_id": contract_id, "product_name": "Orders Product", "version": "1.0.0"}
    body.update(extra)
    return client.post("/api/data-products/from-contract", json=body)


class TestCreateProductFromContract:
    def test_creates_a_draft_product_governed_by_the_contract(self, client, db_session):
        contract = _contract(db_session, "active")

        response = _from_contract(client, contract.id)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["name"] == "Orders Product"
        assert body["status"] == "draft"
        assert [p["contract_id"] for p in body["output_ports"]] == [contract.id]

    def test_product_type_from_older_clients_is_accepted_and_ignored(self, client, db_session):
        contract = _contract(db_session, "approved")

        response = _from_contract(client, contract.id, product_type="source-aligned")

        assert response.status_code == 201, response.text
        assert "productType" not in response.json()

    def test_draft_contract_is_refused_with_400(self, client, db_session):
        contract = _contract(db_session, "draft")

        response = _from_contract(client, contract.id)

        assert response.status_code == 400
        assert client.get(f"/api/data-products/by-contract/{contract.id}").json() == []

    def test_unknown_contract_is_refused_with_400(self, client):
        response = _from_contract(client, str(uuid.uuid4()))

        assert response.status_code == 400


@pytest.fixture
def review_manager(db_session, mock_workspace_client):
    manager = DataAssetReviewManager(
        db=db_session, ws_client=mock_workspace_client, notifications_manager=MagicMock(),
    )
    previous = getattr(app.state, "data_asset_review_manager", None)
    app.state.data_asset_review_manager = manager
    yield manager
    if previous is None:
        del app.state.data_asset_review_manager
    else:
        app.state.data_asset_review_manager = previous


class TestUpdateReviewRequestStatus:
    def _review(self, db_session):
        review = DataAssetReviewRequestDb(
            id=str(uuid.uuid4()), requester_email="req@example.com",
            reviewer_email="rev@example.com", title="Review", status="queued",
        )
        db_session.add(review)
        db_session.flush()
        return review

    def test_status_is_updated_with_the_notes(self, client, db_session, review_manager):
        review = self._review(db_session)

        response = client.put(
            f"/api/data-asset-reviews/{review.id}/status",
            json={"status": "in_review", "notes": "looking at it"},
        )

        assert response.status_code == 200, response.text
        assert response.json()["status"] == "in_review"
        assert response.json()["notes"] == "looking at it"

    def test_unknown_review_is_404(self, client, review_manager):
        response = client.put(
            f"/api/data-asset-reviews/{uuid.uuid4()}/status", json={"status": "in_review"},
        )

        assert response.status_code == 404

    def test_a_status_outside_the_enum_is_422(self, client, db_session, review_manager):
        review = self._review(db_session)

        response = client.put(
            f"/api/data-asset-reviews/{review.id}/status", json={"status": "bogus"},
        )

        assert response.status_code == 422
