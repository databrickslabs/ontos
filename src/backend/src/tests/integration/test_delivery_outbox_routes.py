"""Settings > Delivery Modes lists what wasn't delivered and delivers it again (#1688).

An imported product whose delivery failed is kept in the delivery outbox: the
list shows it, and ``redeliver`` delivers it once the cause is fixed.
"""
from types import SimpleNamespace

import pytest
import yaml

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.controller import delivery_service as delivery_module
from src.controller.delivery_service import DeliveryService
from src.models.users import UserInfo


class _Git:
    """A Git working copy that keeps the files written to it."""

    def __init__(self, cloned: bool):
        self.is_cloned = cloned
        self.files = {}

    def save_yaml(self, filename, data, subdir=None):
        self.files[f"{subdir}/{filename}"] = data
        return True


@pytest.fixture
def git(monkeypatch):
    """Indirect (Git) delivery on, with a working copy that isn't cloned yet."""
    git = _Git(cloned=False)
    settings = SimpleNamespace(
        DELIVERY_MODE_DIRECT=False, DELIVERY_MODE_INDIRECT=True, DELIVERY_MODE_MANUAL=False,
        DELIVERY_DIRECT_DRY_RUN=False,
    )
    monkeypatch.setattr(delivery_module, "get_settings", lambda: settings)
    monkeypatch.setattr(delivery_module, "_delivery_service",
                        DeliveryService(settings=settings, git_service=git))
    return git


def _upload(client, name):
    content = yaml.safe_dump([{
        "apiVersion": "v1.0.0", "kind": "DataProduct", "name": name, "version": "1.0.0",
        "status": "draft", "productType": "sourceAligned",
    }]).encode()
    resp = client.post(
        "/api/data-products/upload",
        files={"files": ("products.yaml", content, "application/x-yaml")},
        data={"adopt_ids": "false"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_an_undelivered_import_is_listed_and_delivered_again(client, git):
    body = _upload(client, "Undelivered Product")
    product_id = body["created_ids"][0]
    assert body["items"][0]["delivery"]["status"] == "failed"

    listed = client.get("/api/delivery/outbox")

    assert listed.status_code == 200, listed.text
    [row] = listed.json()["rows"]
    assert (row["entity_type"], row["entity_id"], row["entity_name"]) == (
        "DataProduct", product_id, "Undelivered Product")
    assert (row["status"], row["code"], row["mode"], row["attempts"]) == (
        "pending", "delivery_git_unavailable", "indirect", 1)
    assert listed.json()["counts"] == {"pending": 1}

    git.is_cloned = True
    resp = client.post(f"/api/delivery/DataProduct/{product_id}/redeliver")

    assert resp.status_code == 200, resp.text
    assert resp.json()["delivery"] == {
        "status": "delivered", "code": None, "params": {"modes": ["indirect"]}}
    assert [r["status"] for r in resp.json()["rows"]] == ["delivered"]
    assert git.files["products/undelivered-product-v1-0-0.yaml"]["id"] == product_id
    assert client.get("/api/delivery/outbox").json()["rows"] == []
    delivered = client.get("/api/delivery/outbox", params={"status": "delivered"}).json()
    assert [r["entity_id"] for r in delivered["rows"]] == [product_id]


# One refusal per test: a refused request rolls back the shared test session
def test_redeliver_of_a_missing_entity_is_a_coded_404(client, git):
    missing = client.post("/api/delivery/DataProduct/no-such-product/redeliver")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "delivery_entity_not_found"


def test_redeliver_of_an_unsupported_type_is_a_coded_400(client, git):
    unsupported = client.post("/api/delivery/Nothing/x/redeliver")
    assert unsupported.status_code == 400
    assert unsupported.json()["detail"]["code"] == "delivery_entity_type_unsupported"


def test_a_user_without_the_delivery_settings_cant_list_or_redeliver(client, git):
    product_id = _upload(client, "Someone Elses")["created_ids"][0]

    async def not_admin():
        return UserInfo(username="reader", email="reader@example.com", user="reader",
                        ip="127.0.0.1", groups=["no_such_group"])

    admin = app.dependency_overrides[get_user_details_from_sdk]
    app.dependency_overrides[get_user_details_from_sdk] = not_admin
    try:
        assert client.get("/api/delivery/outbox").status_code == 403
        git.is_cloned = True
        resp = client.post(f"/api/delivery/DataProduct/{product_id}/redeliver")
        assert resp.status_code == 403
    finally:
        app.dependency_overrides[get_user_details_from_sdk] = admin
    assert git.files == {}
