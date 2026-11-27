"""Tableau connections are administrator-only: create, update and test (#1328 review 1)."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.routes import connection_routes


@pytest.fixture
def as_role(monkeypatch):
    """Stand in for the settings-connectors level of the caller; records the request it was given."""
    calls = []

    def set_admin(is_admin: bool):
        def fake(auth_manager, user, feature_id, required_level, request=None):
            calls.append((feature_id, required_level, request))
            return is_admin
        monkeypatch.setattr(connection_routes, "user_has_feature_level", fake)
        return calls

    return set_admin


def _tableau_payload(name: str = "Tableau test site") -> dict:
    return {
        "name": name,
        "connector_type": "tableau",
        "config": {"server_url": "https://tableau.example.com", "site_content_url": "", "auth_mode": "pat",
                   "pat_name": "ontos", "secret_name": "main.ops.tableau_pat"},
    }


def test_admin_creates_tableau_connection(client: TestClient, as_role):
    calls = as_role(True)
    response = client.post("/api/connections", json=_tableau_payload())
    assert response.status_code == 201, response.text
    assert calls and calls[0][0] == "settings-connectors"
    assert calls[0][2] is not None, "the gate must receive the request"


def test_non_admin_cannot_create_tableau_connection(client: TestClient, as_role):
    as_role(False)
    response = client.post("/api/connections", json=_tableau_payload())
    assert response.status_code == 403, response.text


def test_non_admin_can_still_create_other_connection_types(client: TestClient, as_role):
    as_role(False)
    payload = {"name": "BigQuery", "connector_type": "bigquery", "config": {}}
    response = client.post("/api/connections", json=payload)
    assert response.status_code == 201, response.text


def test_admin_updates_tableau_connection(client: TestClient, as_role):
    as_role(True)
    created = client.post("/api/connections", json=_tableau_payload()).json()
    response = client.put(f"/api/connections/{created['id']}", json={"name": "Renamed"})
    assert response.status_code == 200, response.text


def test_non_admin_cannot_update_tableau_connection(client: TestClient, as_role):
    as_role(True)
    created = client.post("/api/connections", json=_tableau_payload()).json()
    as_role(False)
    response = client.put(
        f"/api/connections/{created['id']}",
        json={"config": {"server_url": "https://attacker.example.com", "secret_name": "main.ops.tableau_pat"}},
    )
    assert response.status_code == 403, response.text


def test_non_admin_cannot_test_tableau_connection(client: TestClient, as_role):
    as_role(True)
    created = client.post("/api/connections", json=_tableau_payload()).json()
    as_role(False)
    response = client.post(f"/api/connections/{created['id']}/test")
    assert response.status_code == 403, response.text


def test_update_of_unknown_connection_is_404_for_admin(client: TestClient, as_role):
    as_role(True)
    assert client.put(f"/api/connections/{uuid4()}", json={"name": "x"}).status_code == 404
