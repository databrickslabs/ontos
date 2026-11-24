"""The ODPS upload's response tells how each imported product was delivered (#1385 review).

An imported product is delivered (Git, Unity Catalog) once committed, inside the
import's per-product commit: before the route builds its response. A failed
delivery doesn't undo the import, and the response says so.
"""
from types import SimpleNamespace

import pytest
import yaml

from src.controller import delivery_service as delivery_module
from src.controller.delivery_service import DeliveryService


def _odps(name: str) -> dict:
    return {
        "apiVersion": "v1.0.0", "kind": "DataProduct", "name": name, "version": "1.0.0",
        "status": "draft", "productType": "sourceAligned",
        "outputPorts": [{"name": "out", "version": "1.0.0", "containsPii": True}],
    }


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
    """Indirect (Git) delivery on; the working copy is cloned unless a test says not."""
    git = _Git(cloned=True)
    settings = SimpleNamespace(
        DELIVERY_MODE_DIRECT=False, DELIVERY_MODE_INDIRECT=True, DELIVERY_MODE_MANUAL=False,
        DELIVERY_DIRECT_DRY_RUN=False,
    )
    monkeypatch.setattr(delivery_module, "get_settings", lambda: settings)
    monkeypatch.setattr(delivery_module, "_delivery_service",
                        DeliveryService(settings=settings, git_service=git))
    return git


def _upload(client, *names):
    content = yaml.safe_dump([_odps(name) for name in names]).encode()
    resp = client.post(
        "/api/data-products/upload",
        files={"files": ("products.yaml", content, "application/x-yaml")},
        data={"adopt_ids": "false"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_response_says_each_product_was_delivered(client, git):
    body = _upload(client, "Delivered A", "Delivered B")

    assert (body["created"], body["delivery_failed"]) == (2, 0)
    assert [item["delivery"] for item in body["items"]] == [
        {"status": "delivered", "code": None, "params": {"modes": ["indirect"]}},
    ] * 2
    # The file written is the product's ODPS document
    document = git.files["products/delivered-a-v1-0-0.yaml"]
    assert (document["kind"], document["id"]) == ("DataProduct", body["created_ids"][0])


def test_the_response_says_a_product_was_imported_but_not_delivered(client, git):
    git.is_cloned = False

    body = _upload(client, "Undelivered")

    assert (body["created"], body["failed"], body["delivery_failed"]) == (1, 0, 1)
    assert body["items"][0]["delivery"] == {
        "status": "failed", "code": "delivery_git_unavailable", "params": {"mode": "indirect"},
    }
    assert git.files == {}
