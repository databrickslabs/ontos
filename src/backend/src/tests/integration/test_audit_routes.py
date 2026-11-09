"""
Integration tests for the audit trail (GET /api/audit) and change log (/api/change-log)
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.db_models.audit_log import AuditLogDb


@pytest.fixture
def audit_entries(db_session: Session):
    """Three audit entries with distinct users, features and actions."""
    entries = [
        AuditLogDb(username='alice@example.com', feature='audit-test-products',
                   action='CREATE', success=True, details={'n': 1}),
        AuditLogDb(username='bob@example.com', feature='audit-test-products',
                   action='UPDATE', success=True, details={'n': 2}),
        AuditLogDb(username='alice@example.com', feature='audit-test-contracts',
                   action='DELETE', success=False, details={'n': 3}),
    ]
    db_session.add_all(entries)
    db_session.flush()
    return entries


def _details(items):
    return sorted(item['details']['n'] for item in items if item.get('details'))


class TestAuditRoutes:
    """Integration tests for audit API endpoints."""

    def test_get_audit_logs(self, client: TestClient, audit_entries):
        """Test getting audit logs."""
        response = client.get("/api/audit")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] >= len(audit_entries)
        ours = [item for item in data["items"] if item["feature"].startswith('audit-test-')]
        assert _details(ours) == [1, 2, 3]

    def test_get_audit_logs_pagination(self, client: TestClient, audit_entries):
        """Test audit logs with pagination."""
        first = client.get("/api/audit?feature=audit-test-products&skip=0&limit=1")
        second = client.get("/api/audit?feature=audit-test-products&skip=1&limit=1")
        assert first.status_code == 200
        assert second.status_code == 200
        assert first.json()["total"] == 2
        assert second.json()["total"] == 2
        assert len(first.json()["items"]) == 1
        assert len(second.json()["items"]) == 1
        pages = _details(first.json()["items"] + second.json()["items"])
        assert pages == [1, 2]

    def test_get_audit_logs_by_feature(self, client: TestClient, audit_entries):
        """Test filtering audit logs by feature."""
        response = client.get("/api/audit?feature=audit-test-contracts")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert _details(data["items"]) == [3]

    def test_get_audit_logs_by_username(self, client: TestClient, audit_entries):
        """Test filtering audit logs by username."""
        response = client.get("/api/audit?username=alice@example.com")
        assert response.status_code == 200
        data = response.json()
        assert {item["username"] for item in data["items"]} == {'alice@example.com'}
        assert _details(data["items"]) == [1, 3]

    def test_get_audit_logs_by_action(self, client: TestClient, audit_entries):
        """Test filtering audit logs by action."""
        response = client.get("/api/audit?feature=audit-test-products&action=UPDATE")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1
        assert data["items"][0]["action"] == 'UPDATE'
        assert data["items"][0]["username"] == 'bob@example.com'

    def test_get_change_logs(self, client: TestClient, db_session: Session):
        """Test getting change logs."""
        created = client.post("/api/change-log", json={
            "entity_type": "data_product",
            "entity_id": "change-log-test-id",
            "action": "UPDATE",
            "details_json": '{"field": "name"}',
        })
        assert created.status_code == 200, created.text

        response = client.get("/api/change-log")
        assert response.status_code == 200
        ids = [row["id"] for row in response.json()]
        assert created.json()["id"] in ids

    def test_get_change_logs_by_entity(self, client: TestClient, db_session: Session):
        """Test getting change logs for specific entity."""
        for entity_id in ("change-log-a", "change-log-b"):
            client.post("/api/change-log", json={
                "entity_type": "data_product", "entity_id": entity_id, "action": "CREATE",
            }).raise_for_status()

        response = client.get(
            "/api/change-log?entity_type=data_product&entity_id=change-log-a"
        )
        assert response.status_code == 200
        rows = response.json()
        assert len(rows) == 1
        assert rows[0]["entity_id"] == "change-log-a"
        assert rows[0]["action"] == "CREATE"
