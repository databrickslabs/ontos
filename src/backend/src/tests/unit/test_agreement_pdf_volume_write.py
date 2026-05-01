"""
Unit tests for the PDF persistence branch in
AgreementWizardManager._complete_session.

Regression target: the wizard previously used raw open()/mkdir() against
/Volumes/... paths, which silently fails inside the Databricks Apps runtime
(EACCES on /Volumes — it's not a real filesystem mount). The fix routes
Volume writes through the Databricks SDK Files API while keeping the local
filesystem path for non-/Volumes/ targets so dev still works.

These tests exercise the routing logic by injecting a generate_pdf
WorkflowStep with the relevant storage config, mocking the SDK upload
surface, and asserting the right code path is taken.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.controller.agreement_wizard_manager import AgreementWizardManager
from src.models.process_workflows import StepType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_session(
    *,
    workflow_id: str = "wf-1",
    workflow_name: str = "Approval WF",
    workflow_snapshot: dict | None = None,
):
    """Build a minimal session-like object that _complete_session reads."""
    snap = workflow_snapshot or {
        "steps": [
            {
                "step_id": "pdf",
                "name": "Generate PDF",
                "step_type": "generate_pdf",
                "config": {},
                "order": 0,
            }
        ]
    }
    return SimpleNamespace(
        id="sess-1",
        workflow_id=workflow_id,
        workflow_name=workflow_name,
        workflow_snapshot=json.dumps(snap),
        entity_type="data_product",
        entity_id="entity-1",
        created_by="signer@example.com",
        created_at="2026-05-01T00:00:00Z",
        completion_action=None,
    )


def _make_workflow(steps_config: list[dict]):
    """Build a minimal workflow object with steps list."""
    steps = []
    for s in steps_config:
        steps.append(
            SimpleNamespace(
                step_id=s["step_id"],
                step_type=StepType(s["step_type"]),
                config=s.get("config", {}),
                order=s.get("order", 0),
                on_pass=s.get("on_pass"),
                on_fail=s.get("on_fail"),
                name=s.get("name"),
            )
        )
    return SimpleNamespace(
        id="wf-1",
        name="Approval WF",
        version=1,
        steps=steps,
        workflow_type="approval",
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestAgreementPdfVolumeWrite:
    """Verify generate_pdf step persistence routes correctly per storage type."""

    @pytest.fixture
    def manager(self):
        # _db is patched inside each test via mocks; constructing with None is
        # fine because we don't reach DB writes.
        mgr = AgreementWizardManager(db=MagicMock(), storage_base_path=None)
        return mgr

    def _patched_complete(self, manager, *, pdf_volume_path, fake_pdf_bytes=b"%PDF-1.4 fake"):
        """
        Run the PDF-persistence branch with everything around it mocked.
        Returns (upload_mock, open_mock, agreement_set_path_mock).

        We patch the small surface area used inside the if has_generate_pdf
        block so the test stays focused on the routing decision.
        """
        # Workflow with a single generate_pdf step carrying the storage config
        wf = _make_workflow([
            {
                "step_id": "pdf",
                "step_type": "generate_pdf",
                "config": {
                    "storage": "volume",
                    "volume_path": pdf_volume_path,
                },
                "order": 0,
            }
        ])
        sess = _make_session(workflow_snapshot={
            "steps": [
                {
                    "step_id": "pdf",
                    "step_type": "generate_pdf",
                    "config": {
                        "storage": "volume",
                        "volume_path": pdf_volume_path,
                    },
                    "order": 0,
                }
            ]
        })

        # The block builds PDF bytes via build_agreement_pdf — short-circuit it.
        # We also patch _HAS_FPDF True, the SDK client, and repo writes.
        mock_ws = MagicMock()
        mock_ws.files.upload = MagicMock()

        agreement = SimpleNamespace(id="agr-1", pdf_storage_path=None)

        with patch(
            "src.utils.agreement_pdf_builder.build_agreement_pdf",
            return_value=bytearray(fake_pdf_bytes),
        ), patch(
            "src.utils.agreement_pdf_builder._HAS_FPDF", True
        ), patch(
            "src.common.workspace_client.get_workspace_client",
            return_value=mock_ws,
        ), patch(
            "src.controller.agreement_wizard_manager.agreements_repo"
        ) as repo_mock, patch(
            "src.controller.agreement_wizard_manager.agreement_wizard_sessions_repo"
        ) as sessions_repo_mock, patch(
            "src.controller.agreement_wizard_manager.ChangeLogManager"
        ), patch(
            "builtins.open", create=True
        ) as mock_open_builtin:
            sessions_repo_mock.get_step_results.return_value = []
            sessions_repo_mock.set_completed = MagicMock()
            repo_mock.create.return_value = agreement
            repo_mock.update_step_results = MagicMock()
            repo_mock.set_pdf_storage_path = MagicMock()

            # Drive the manager through the relevant tail of _complete_session
            # by calling it with the prepared session + workflow. We patch the
            # workflow lookup to avoid DB.
            with patch.object(
                manager._workflows_manager,
                "get_workflow",
                return_value=wf,
            ), patch.object(
                manager,
                "_send_delivery_notifications",
                return_value=None,
            ):
                manager._complete_session(
                    sess,
                    created_by="signer@example.com",
                )

            return mock_ws.files.upload, mock_open_builtin, repo_mock.set_pdf_storage_path

    def test_volume_path_uses_files_api(self, manager):
        """When volume_path starts with /Volumes/, SDK Files API is used."""
        upload_mock, open_mock, set_path_mock = self._patched_complete(
            manager,
            pdf_volume_path="/Volumes/cat/sch/vol/agreements_root",
        )

        assert upload_mock.called, "Expected ws.files.upload to be called for /Volumes/ path"
        args, kwargs = upload_mock.call_args
        # First positional arg = file_path
        called_path = args[0] if args else kwargs.get("file_path")
        assert called_path == "/Volumes/cat/sch/vol/agreements_root/agreements/agr-1.pdf"
        # overwrite must be True so re-runs don't 409
        assert kwargs.get("overwrite") is True
        # And the local filesystem fallback must NOT have been used
        assert not open_mock.called, "Local open() must not be called for /Volumes/ path"
        # Repo must have recorded the Volume path
        set_path_mock.assert_called_once()
        path_arg = set_path_mock.call_args[0][2]
        assert path_arg.startswith("/Volumes/")

    def test_local_path_uses_open_fallback(self, manager, tmp_path):
        """When volume_path is local, raw open() is still used (dev compat)."""
        local_root = str(tmp_path / "agreements_root")
        upload_mock, open_mock, set_path_mock = self._patched_complete(
            manager,
            pdf_volume_path=local_root,
        )

        assert not upload_mock.called, "Files API must not be called for non-/Volumes/ path"
        assert open_mock.called, "Local open() must be used for non-/Volumes/ path"
        # Repo records the local path
        set_path_mock.assert_called_once()
        path_arg = set_path_mock.call_args[0][2]
        assert path_arg.startswith(local_root)
        assert path_arg.endswith("/agr-1.pdf")
