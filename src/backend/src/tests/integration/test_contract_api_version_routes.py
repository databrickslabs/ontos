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
