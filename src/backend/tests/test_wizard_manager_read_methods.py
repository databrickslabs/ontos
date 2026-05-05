"""Unit tests for AgreementWizardManager read-side methods.

Covers the methods extracted from approvals_routes.py during the route ->
controller refactor (PR #315 Lars review):

* list_sessions
* list_agreements
* get_agreement
* get_pending_first_access_workflows
* get_completed_session_step_results

`get_agreement_pdf` is covered separately in test_pdf_download_volume.py.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.controller.agreement_wizard_manager import AgreementWizardManager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def manager():
    """A manager with a mock DB session — methods we test only delegate to repos."""
    return AgreementWizardManager(db=MagicMock())


def _agreement(
    *,
    id_: str = "agr-1",
    workflow_id: str = "wf-1",
    workflow_name: str = "Test Workflow",
    workflow_version: int | None = 1,
    workflow_snapshot: str | None = '{"steps": [{"step_type": "generate_pdf"}]}',
    step_results: str | None = '[{"step_id": "legal", "payload": {"acknowledged": true}}]',
    pdf_storage_path: str | None = None,
    created_by: str = "alice@example.com",
    created_at=None,
):
    """Stand-in for an AgreementDb row."""
    return SimpleNamespace(
        id=id_,
        entity_type="data_product",
        entity_id="entity-1",
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        workflow_version=workflow_version,
        workflow_snapshot=workflow_snapshot,
        wizard_session_id="sess-1",
        step_results=step_results,
        pdf_storage_path=pdf_storage_path,
        created_by=created_by,
        created_at=created_at,
    )


# ---------------------------------------------------------------------------
# list_sessions
# ---------------------------------------------------------------------------

class TestListSessions:
    def test_returns_payload_with_sessions_and_total(self, manager):
        rows = [{"id": "s1"}, {"id": "s2"}]
        with patch(
            "src.controller.agreement_wizard_manager.agreement_wizard_sessions_repo.list_recent",
            return_value=rows,
        ) as repo_call:
            out = manager.list_sessions(limit=10)
        repo_call.assert_called_once()
        assert out == {"sessions": rows, "total": 2}

    def test_default_limit_50(self, manager):
        with patch(
            "src.controller.agreement_wizard_manager.agreement_wizard_sessions_repo.list_recent",
            return_value=[],
        ) as repo_call:
            manager.list_sessions()
        # Limit 50 is documented default; assert via call kwargs
        _, kwargs = repo_call.call_args
        assert kwargs.get("limit") == 50


# ---------------------------------------------------------------------------
# list_agreements
# ---------------------------------------------------------------------------

class TestListAgreements:
    def test_filters_propagate(self, manager):
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.list_recent",
            return_value=[],
        ) as repo_call:
            manager.list_agreements(entity_type="data_product", entity_id="abc", limit=5)
        _, kwargs = repo_call.call_args
        assert kwargs == {"entity_type": "data_product", "entity_id": "abc", "limit": 5}

    def test_returns_total_alongside_rows(self, manager):
        rows = [{"id": "a1"}, {"id": "a2"}, {"id": "a3"}]
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.list_recent",
            return_value=rows,
        ):
            out = manager.list_agreements()
        assert out["agreements"] == rows
        assert out["total"] == 3


# ---------------------------------------------------------------------------
# get_agreement
# ---------------------------------------------------------------------------

class TestGetAgreement:
    def test_none_when_missing(self, manager):
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.get",
            return_value=None,
        ):
            assert manager.get_agreement("does-not-exist") is None

    def test_parses_step_results_json_string(self, manager):
        ag = _agreement(
            step_results='[{"step_id": "x", "payload": {"k": 1}}]',
        )
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.get",
            return_value=ag,
        ):
            out = manager.get_agreement("agr-1")
        assert out is not None
        assert out["step_results"] == [{"step_id": "x", "payload": {"k": 1}}]
        assert out["id"] == "agr-1"
        assert out["workflow_name"] == "Test Workflow"

    def test_invalid_step_results_json_falls_back_to_empty(self, manager):
        ag = _agreement(step_results="not-json{{{")
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.get",
            return_value=ag,
        ):
            out = manager.get_agreement("agr-1")
        assert out["step_results"] == []

    def test_pdf_url_present_when_snapshot_has_generate_pdf(self, manager):
        ag = _agreement(
            workflow_snapshot='{"steps": [{"step_type": "generate_pdf"}]}',
        )
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.get",
            return_value=ag,
        ):
            out = manager.get_agreement("agr-1")
        assert out["pdf_url"] == "/api/approvals/agreements/agr-1/pdf"

    def test_pdf_url_absent_without_generate_pdf_step(self, manager):
        ag = _agreement(
            workflow_snapshot='{"steps": [{"step_type": "legal_document"}]}',
        )
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.get",
            return_value=ag,
        ):
            out = manager.get_agreement("agr-1")
        assert out["pdf_url"] is None


# ---------------------------------------------------------------------------
# _agreement_has_pdf_step (private helper)
# ---------------------------------------------------------------------------

class TestAgreementHasPdfStep:
    def test_true_when_snapshot_includes_generate_pdf(self):
        ag = _agreement(workflow_snapshot='{"steps":[{"step_type":"generate_pdf"}]}')
        assert AgreementWizardManager._agreement_has_pdf_step(ag) is True

    def test_false_when_no_snapshot(self):
        ag = _agreement(workflow_snapshot=None)
        assert AgreementWizardManager._agreement_has_pdf_step(ag) is False

    def test_false_when_snapshot_malformed_json(self):
        ag = _agreement(workflow_snapshot="not valid json")
        assert AgreementWizardManager._agreement_has_pdf_step(ag) is False

    def test_false_when_snapshot_lacks_pdf_step(self):
        ag = _agreement(workflow_snapshot='{"steps":[{"step_type":"legal_document"}]}')
        assert AgreementWizardManager._agreement_has_pdf_step(ag) is False


# ---------------------------------------------------------------------------
# get_pending_first_access_workflows
# ---------------------------------------------------------------------------

class TestGetPendingFirstAccessWorkflows:
    def _wf(self, id_, name="WF", version=1):
        return SimpleNamespace(id=id_, name=name, version=version)

    def test_returns_empty_when_no_active_workflows(self, manager):
        manager._workflows_manager = MagicMock()
        manager._workflows_manager.get_workflows_for_trigger.return_value = []
        out = manager.get_pending_first_access_workflows("alice@example.com")
        assert out == []

    def test_returns_workflows_user_hasnt_signed(self, manager):
        manager._workflows_manager = MagicMock()
        manager._workflows_manager.get_workflows_for_trigger.return_value = [
            self._wf("wf1", "Welcome", 2),
        ]
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.has_user_signed_workflow_at_version",
            return_value=False,
        ):
            out = manager.get_pending_first_access_workflows("alice@example.com")
        assert out == [
            {"workflow_id": "wf1", "workflow_name": "Welcome", "workflow_version": 2}
        ]

    def test_excludes_workflows_user_already_signed(self, manager):
        manager._workflows_manager = MagicMock()
        manager._workflows_manager.get_workflows_for_trigger.return_value = [
            self._wf("wf1", "Welcome", 2),
        ]
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.has_user_signed_workflow_at_version",
            return_value=True,
        ):
            out = manager.get_pending_first_access_workflows("alice@example.com")
        assert out == []

    def test_default_version_when_none(self, manager):
        manager._workflows_manager = MagicMock()
        wf_no_version = SimpleNamespace(id="wf1", name="Welcome", version=None)
        manager._workflows_manager.get_workflows_for_trigger.return_value = [wf_no_version]
        with patch(
            "src.controller.agreement_wizard_manager.agreements_repo.has_user_signed_workflow_at_version",
            return_value=False,
        ) as repo_call:
            out = manager.get_pending_first_access_workflows("alice@example.com")
        # version defaulted to 1 when workflow has no version
        _, kwargs = repo_call.call_args
        assert kwargs["workflow_version"] == 1
        assert out[0]["workflow_version"] == 1


# ---------------------------------------------------------------------------
# get_completed_session_step_results
# ---------------------------------------------------------------------------

class TestGetCompletedSessionStepResults:
    def test_empty_when_entity_type_missing(self, manager):
        assert manager.get_completed_session_step_results(None, "id-1") == []

    def test_empty_when_entity_id_missing(self, manager):
        assert manager.get_completed_session_step_results("data_product", None) == []

    def test_empty_when_no_session_found(self, manager):
        with patch(
            "src.controller.agreement_wizard_manager.agreement_wizard_sessions_repo.get_latest_completed_by_entity",
            return_value=None,
        ):
            out = manager.get_completed_session_step_results("data_product", "abc")
        assert out == []

    def test_returns_step_results_when_session_exists(self, manager):
        fake_session = SimpleNamespace(id="sess-1")
        results = [{"step_id": "legal", "payload": {"ok": True}}]
        with patch(
            "src.controller.agreement_wizard_manager.agreement_wizard_sessions_repo.get_latest_completed_by_entity",
            return_value=fake_session,
        ), patch(
            "src.controller.agreement_wizard_manager.agreement_wizard_sessions_repo.get_step_results",
            return_value=results,
        ):
            out = manager.get_completed_session_step_results("data_product", "abc")
        assert out == results
