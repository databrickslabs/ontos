"""Connector sync routes: CRUD, the scheduled job is installed once and started on demand."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from src.db_models.connections import ConnectionDb
from src.routes import connector_sync_routes as routes


class FakeJobs:
    def __init__(self, fail=False):
        self.fail = fail
        self.installed, self.resumed, self.runs = [], [], []

    def install_workflow(self, workflow_id, job_cluster_id=None):
        if self.fail:
            raise RuntimeError("no permission to create jobs")
        self.installed.append(workflow_id)
        return 42

    def resume_job(self, job_id):
        self.resumed.append(job_id)

    def run_job(self, job_id, job_name=None, job_parameters=None, workflow_id=None):
        self.runs.append((job_id, job_parameters, workflow_id))
        return 7


@pytest.fixture
def jobs(monkeypatch):
    fake = FakeJobs()
    monkeypatch.setattr(routes, "get_jobs_manager", lambda request: fake)
    return fake


@pytest.fixture
def connection(db_session):
    conn = ConnectionDb(id=uuid4(), name=f"tableau-{uuid4().hex[:6]}", connector_type="tableau", config={})
    db_session.add(conn)
    db_session.flush()
    return conn


def _create(client, connection, **overrides):
    body = {"name": "Finance", "connection_id": str(connection.id), "selected_paths": ["p~p1"],
            "interval_minutes": 1440, **overrides}
    return client.post("/api/connector-syncs", json=body)


def test_create_installs_and_unpauses_the_job(client: TestClient, connection, jobs):
    response = _create(client, connection)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["selected_paths"] == ["p~p1"] and body["depth"] == "full_recursive"
    assert body["enabled"] is True and body["next_due_at"] and body["job_warning"] is None
    assert jobs.installed == ["connector_sync"] and jobs.resumed == [42]

    listed = client.get("/api/connector-syncs", params={"connection_id": str(connection.id)}).json()
    assert [s["id"] for s in listed] == [body["id"]]


def test_a_job_that_cannot_be_installed_is_a_warning(client: TestClient, connection, monkeypatch):
    monkeypatch.setattr(routes, "get_jobs_manager", lambda request: FakeJobs(fail=True))
    response = _create(client, connection)
    assert response.status_code == 201
    assert "Settings → Jobs" in response.json()["job_warning"]


def test_validation(client: TestClient, connection, jobs):
    assert _create(client, connection, interval_minutes=5).status_code == 422
    assert _create(client, connection, selected_paths=[]).status_code == 422
    assert client.post("/api/connector-syncs", json={
        "name": "x", "connection_id": str(uuid4()), "selected_paths": ["p~p1"],
    }).status_code == 404


def test_update_disable_and_delete(client: TestClient, connection, jobs):
    sync_id = _create(client, connection).json()["id"]

    response = client.put(f"/api/connector-syncs/{sync_id}", json={"enabled": False, "excluded_paths": ["p~p1.p~p2"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["enabled"] is False and body["next_due_at"] is None
    assert body["excluded_paths"] == ["p~p1.p~p2"] and body["selected_paths"] == ["p~p1"]

    assert client.delete(f"/api/connector-syncs/{sync_id}").status_code == 204
    assert client.get(f"/api/connector-syncs/{sync_id}").status_code == 404


def test_run_now_starts_the_job_for_this_sync(client: TestClient, connection, jobs):
    sync_id = _create(client, connection).json()["id"]
    response = client.post(f"/api/connector-syncs/{sync_id}/run")
    assert response.status_code == 202, response.text
    assert response.json() == {"job_run_id": 7}
    assert jobs.runs == [(42, {"sync_id": sync_id}, "connector_sync")]
    assert client.get(f"/api/connector-syncs/{sync_id}/runs").json() == []


def test_unknown_sync_is_404(client: TestClient, jobs):
    assert client.post(f"/api/connector-syncs/{uuid4()}/run").status_code == 404
