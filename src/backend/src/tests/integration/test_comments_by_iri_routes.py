"""By-IRI comment/timeline routes.

IRI entity ids (e.g. ontology concepts) contain '/' and '#', which cannot travel
as a path segment, so the comment sidebar uses
``/entities/{entity_type}/by-iri/...?entity_id=<IRI>``.
"""
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from src.app import app

ENTITY_TYPE = "ontology_concept"
IRI = "http://example.org/onto/sub#Customer"


@pytest.fixture(autouse=True)
def _noop_audit_manager():
    """Comment create logs an audit action; the integration client has none wired."""
    class _NoopAudit:
        def log_action(self, **kwargs):
            return None

        def log_action_background(self, **kwargs):
            return None

    previous = getattr(app.state, "audit_manager", None)
    app.state.audit_manager = _NoopAudit()
    try:
        yield
    finally:
        if previous is not None:
            app.state.audit_manager = previous
        elif hasattr(app.state, "audit_manager"):
            delattr(app.state, "audit_manager")


@pytest.fixture(autouse=True)
def _as_admin(monkeypatch):
    """Global (project-less) comments are admin-only in CommentsManager; act as admin."""
    monkeypatch.setattr("src.routes.comments_routes.is_user_admin", lambda *a, **k: True)


def _q(iri: str) -> str:
    return quote(iri, safe="")


def test_by_iri_comment_round_trip_and_timeline_count(client: TestClient):
    base = f"/api/entities/{ENTITY_TYPE}/by-iri"

    count0 = client.get(f"{base}/timeline/count?entity_id={_q(IRI)}&filter_type=comments")
    assert count0.status_code == 200, count0.text
    assert count0.json()["total_count"] == 0

    created = client.post(
        f"{base}/comments?entity_id={_q(IRI)}",
        json={"entity_type": ENTITY_TYPE, "entity_id": IRI, "comment": "Approved: looks good"},
    )
    assert created.status_code == 201, created.text
    assert created.json()["entity_id"] == IRI

    listed = client.get(f"{base}/comments?entity_id={_q(IRI)}")
    assert listed.status_code == 200, listed.text
    comments = listed.json()["comments"]
    assert [c["comment"] for c in comments] == ["Approved: looks good"]
    assert comments[0]["entity_id"] == IRI

    count1 = client.get(f"{base}/timeline/count?entity_id={_q(IRI)}&filter_type=comments")
    assert count1.status_code == 200, count1.text
    assert count1.json()["total_count"] == 1

    timeline = client.get(f"{base}/timeline?entity_id={_q(IRI)}&filter_type=comments")
    assert timeline.status_code == 200, timeline.text
    entries = timeline.json()["timeline"]
    assert len(entries) == 1 and entries[0]["entity_id"] == IRI

    # A different IRI sharing the prefix sees nothing.
    other = client.get(f"{base}/comments?entity_id={_q(IRI + 'X')}")
    assert other.status_code == 200
    assert other.json()["comments"] == []


def test_by_iri_post_rejects_body_mismatch(client: TestClient):
    r = client.post(
        f"/api/entities/{ENTITY_TYPE}/by-iri/comments?entity_id={_q(IRI)}",
        json={"entity_type": ENTITY_TYPE, "entity_id": "http://example.org/other", "comment": "x"},
    )
    assert r.status_code == 400, r.text


def test_by_iri_requires_entity_id(client: TestClient):
    r = client.get(f"/api/entities/{ENTITY_TYPE}/by-iri/comments")
    assert r.status_code == 422


def test_path_param_routes_unchanged(client: TestClient):
    created = client.post(
        "/api/entities/data_product/dp-1/comments",
        json={"entity_type": "data_product", "entity_id": "dp-1", "comment": "hello"},
    )
    assert created.status_code == 201, created.text
    listed = client.get("/api/entities/data_product/dp-1/comments")
    assert listed.status_code == 200
    assert [c["comment"] for c in listed.json()["comments"]] == ["hello"]
    count = client.get("/api/entities/data_product/dp-1/timeline/count?filter_type=comments")
    assert count.json()["total_count"] == 1
