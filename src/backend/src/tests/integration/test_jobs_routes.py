"""
Integration tests for jobs API endpoints
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session


class TestJobsRoutes:
    """Integration tests for jobs API endpoints."""

    def test_get_workflow_installations(self, client: TestClient, db_session: Session):
        """Test getting workflow installations (GET /api/jobs/workflows/statuses)."""
        from src.db_models.workflow_installations import WorkflowInstallationDb

        db_session.add_all([
            WorkflowInstallationDb(workflow_id="compliance_checks", name="Compliance", job_id=101),
            WorkflowInstallationDb(workflow_id="uninstalled_wf", name="Gone", job_id=102,
                                   status="failed"),
        ])
        db_session.flush()

        response = client.get("/api/jobs/workflows/statuses")
        assert response.status_code == 200
        data = response.json()
        assert set(data) == {"compliance_checks"}
        assert data["compliance_checks"]["installed"] is True
        assert data["compliance_checks"]["job_id"] == 101
        assert data["compliance_checks"]["is_running"] is False

    def test_get_workflow_runs(self, client: TestClient, db_session: Session):
        """Test getting workflow runs."""
        response = client.get("/api/jobs/runs")
        assert response.status_code == 200

    def test_trigger_workflow(self, client: TestClient, db_session: Session):
        """Test triggering a workflow."""
        trigger_data = {
            "workflow_id": "test-workflow",
            "parameters": {},
        }
        response = client.post("/api/jobs/trigger", json=trigger_data)
        assert response.status_code in [200, 201, 404, 503]

    def test_get_job_status(self, client: TestClient, db_session: Session):
        """Test getting job status."""
        response = client.get("/api/jobs/status/12345")
        assert response.status_code in [200, 404]

    def test_get_job_logs(self, client: TestClient, db_session: Session):
        """Test getting job logs."""
        response = client.get("/api/jobs/logs/12345")
        assert response.status_code in [200, 404]

    def test_cancel_job(self, client: TestClient, db_session: Session):
        """Test canceling a job."""
        response = client.post("/api/jobs/cancel/12345")
        assert response.status_code in [200, 404]

    def test_get_workflow_installation_by_id(self, client: TestClient, db_session: Session):
        """Test getting specific workflow installation."""
        response = client.get("/api/jobs/installation/test-installation-id")
        assert response.status_code in [200, 404]



class TestTagSyncConfigurationUpgrade:
    """A uc_tag_sync configuration saved before the lifecycle mapping existed (#998)."""

    NAME_ENTRY = {"entity_type": "data_product", "enabled": True,
                  "tag_key_format": "ontos_product_name", "tag_value_format": "{PRODUCT.NAME}"}
    URL = "/api/jobs/workflows/uc_tag_sync/configuration"

    @staticmethod
    def _lifecycle(configs):
        return [(c["entity_type"], c["enabled"], c["tag_value_format"])
                for c in configs if c.get("mapping") == "lifecycle_status"]

    def test_get_adds_the_lifecycle_mapping_to_an_old_saved_list(
        self, client: TestClient, db_session: Session
    ):
        from src.repositories.workflow_configurations_repository import (
            workflow_configuration_repo,
        )
        workflow_configuration_repo.upsert(
            db_session, workflow_id="uc_tag_sync",
            configuration={"tag_sync_configs": [self.NAME_ENTRY]},
        )
        db_session.flush()

        response = client.get(self.URL)

        assert response.status_code == 200
        configs = response.json()["configuration"]["tag_sync_configs"]
        assert configs[0] == self.NAME_ENTRY
        assert self._lifecycle(configs) == [
            ("data_contract", False, "{CONTRACT.STATUS}"),
            ("data_product", True, "{PRODUCT.STATUS}"),
        ]

    def test_a_disabled_lifecycle_mapping_stays_disabled(
        self, client: TestClient, db_session: Session
    ):
        configs = [self.NAME_ENTRY] + [
            {"entity_type": entity_type, "mapping": "lifecycle_status", "enabled": False,
             "tag_key_format": "ontos_lifecycle_status", "tag_value_format": value_format}
            for entity_type, value_format in (("data_contract", "{CONTRACT.STATUS}"),
                                              ("data_product", "{PRODUCT.STATUS}"))
        ]

        put = client.put(self.URL, json={"configuration": {"tag_sync_configs": configs}})
        response = client.get(self.URL)

        assert put.status_code == 200
        assert response.json()["configuration"]["tag_sync_configs"] == configs
