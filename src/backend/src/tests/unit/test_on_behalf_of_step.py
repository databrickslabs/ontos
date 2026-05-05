"""Unit tests for the in-wizard ``on_behalf_of`` approval step ().

The step lets the workflow author capture self/group/SP intent at the start
of the wizard rather than via the pre-wizard SubscribeDialog. Validated
payloads land in two places:

  1. ``step_results`` (kept by the workflow snapshot + agreement PDF for audit)
  2. ``agreement_wizard_sessions.on_behalf_of_type`` /
     ``on_behalf_of_value`` columns (read by ``_complete_session`` to thread
     OBO into the auto-subscribe path).

Tests cover:

  * Validator gates (allow_self / allow_user_groups / allow_free_text /
    require_justification)
  * Required ``type`` ∈ {user, group, service_principal} and non-empty value
  * SCIM mocking for group / service_principal happy + unhappy paths
  * ``submit_step`` for an ``on_behalf_of`` step writes the OBO onto the
    session row via ``update_on_behalf_of`` *and* appends the full payload
    (including justification) to ``step_results``.
"""

# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.controller.agreement_wizard_manager import AgreementWizardManager
from src.models.process_workflows import StepType, WorkflowStep


def _make_step(config: dict) -> WorkflowStep:
    """Build a WorkflowStep with the given on_behalf_of config."""
    return WorkflowStep(
        id="step-obo",
        step_id="who",
        name="Who",
        step_type=StepType.ON_BEHALF_OF,
        config=config,
        on_pass=None,
        on_fail=None,
        order=0,
        workflow_id="wf-1",
    )


@pytest.fixture
def manager():
    """AgreementWizardManager with a MagicMock DB — enough for the validator
    to exercise the SCIM lookup helper through ``DataProductsManager``."""
    return AgreementWizardManager(db=MagicMock(), storage_base_path=None)


# =========================================================================
# Validator
# =========================================================================

class TestValidateOnBehalfOfPayload:
    def test_missing_type_raises(self, manager):
        step = _make_step({})
        with pytest.raises(ValueError, match="type must be"):
            manager._validate_on_behalf_of_payload(step, {"value": "users"})

    def test_unknown_type_raises(self, manager):
        step = _make_step({})
        with pytest.raises(ValueError, match="type must be"):
            manager._validate_on_behalf_of_payload(
                step, {"type": "team", "value": "users"},
            )

    def test_missing_value_raises(self, manager):
        step = _make_step({})
        with pytest.raises(ValueError, match="non-empty"):
            manager._validate_on_behalf_of_payload(step, {"type": "user", "value": ""})

    def test_user_type_accepts_any_email(self, manager):
        """``type=user`` skips SCIM (matches PR A pattern for new hires)."""
        step = _make_step({})
        manager._validate_on_behalf_of_payload(
            step, {"type": "user", "value": "alice@example.com"},
        )

    def test_self_disallowed_when_value_matches_requester(self, manager):
        step = _make_step({"allow_self": False})
        with pytest.raises(ValueError, match="Self-requests"):
            manager._validate_on_behalf_of_payload(
                step,
                {"type": "user", "value": "alice@example.com"},
                requester_email="alice@example.com",
            )

    def test_self_disallowed_case_insensitive(self, manager):
        step = _make_step({"allow_self": False})
        with pytest.raises(ValueError, match="Self-requests"):
            manager._validate_on_behalf_of_payload(
                step,
                {"type": "user", "value": "ALICE@example.com"},
                requester_email="alice@example.com",
            )

    def test_group_disallowed_when_user_groups_off(self, manager):
        step = _make_step({"allow_user_groups": False, "allow_free_text": True})
        with pytest.raises(ValueError, match="Group requests"):
            manager._validate_on_behalf_of_payload(
                step, {"type": "group", "value": "users"},
            )

    def test_service_principal_disallowed_when_free_text_off(self, manager):
        step = _make_step({"allow_free_text": False})
        # Skip SCIM by making workspace_client unavailable; the gate runs first.
        with patch(
            'src.common.workspace_client.get_workspace_client',
            side_effect=Exception("no creds"),
        ):
            with pytest.raises(ValueError, match="Service principal"):
                manager._validate_on_behalf_of_payload(
                    step, {"type": "service_principal", "value": "my-sp"},
                )

    def test_require_justification_rejects_empty(self, manager):
        step = _make_step({"require_justification": True})
        with pytest.raises(ValueError, match="justification"):
            manager._validate_on_behalf_of_payload(
                step, {"type": "user", "value": "alice@example.com"},
            )

    def test_require_justification_accepts_value(self, manager):
        step = _make_step({"require_justification": True})
        manager._validate_on_behalf_of_payload(
            step,
            {
                "type": "user",
                "value": "alice@example.com",
                "justification": "On-call rotation",
            },
        )

    def test_group_calls_scim_validator(self, manager):
        """``type=group`` defers to DataProductsManager._validate_on_behalf_of_principal."""
        step = _make_step({})
        fake_ws = MagicMock()
        fake_ws.groups.list.return_value = iter([MagicMock(display_name="users")])
        with patch(
            'src.common.workspace_client.get_workspace_client',
            return_value=fake_ws,
        ):
            manager._validate_on_behalf_of_payload(
                step, {"type": "group", "value": "users"},
            )

    def test_unknown_group_raises(self, manager):
        step = _make_step({})
        fake_ws = MagicMock()
        fake_ws.groups.list.return_value = iter([])
        with patch(
            'src.common.workspace_client.get_workspace_client',
            return_value=fake_ws,
        ):
            with pytest.raises(ValueError, match="not found"):
                manager._validate_on_behalf_of_payload(
                    step, {"type": "group", "value": "ghost-not-real"},
                )

    def test_workspace_unavailable_falls_through(self, manager):
        """SCIM unavailable → log + accept (dev/test parity)."""
        step = _make_step({})
        with patch(
            'src.common.workspace_client.get_workspace_client',
            side_effect=Exception("no creds"),
        ):
            manager._validate_on_behalf_of_payload(
                step, {"type": "group", "value": "anything"},
            )


# =========================================================================
# submit_step → update_on_behalf_of
# =========================================================================

def _session(*, current_index=0, status="in_progress"):
    return SimpleNamespace(
        id="sess-1",
        workflow_id="wf-1",
        workflow_name="Subscribe Approval",
        workflow_snapshot=None,
        entity_type="data_product",
        entity_id="prod-1",
        created_by="alice@example.com",
        completion_action="subscribe",
        on_behalf_of_type=None,
        on_behalf_of_value=None,
        current_step_index=current_index,
        status=status,
        step_results="[]",
    )


class TestSubmitStepWritesOnBehalfOf:
    def test_submit_persists_obo_on_session(self, manager):
        """A successful submit_step on an on_behalf_of step calls
        ``update_on_behalf_of`` with the captured type/value AND appends the
        full payload (including display + justification) to step_results."""
        step = _make_step({"allow_self": True, "allow_user_groups": True, "allow_free_text": True})
        snapshot_steps = [step]

        with patch(
            'src.controller.agreement_wizard_manager.agreement_wizard_sessions_repo'
        ) as repo_mock, patch.object(
            manager, '_get_steps_from_snapshot', return_value=snapshot_steps,
        ), patch.object(
            manager, '_get_workflow_steps', return_value=snapshot_steps,
        ):
            session = _session()
            # repo.get must return our session twice (pre-submit, post-append)
            repo_mock.get.return_value = session
            repo_mock.append_step_result.return_value = session
            repo_mock.get_step_results.return_value = []
            repo_mock.update_on_behalf_of = MagicMock()
            # Drive the path that finishes the wizard (no on_pass → completes)
            with patch.object(manager, '_complete_session', return_value={"complete": True}):
                manager.submit_step(
                    "sess-1",
                    "who",
                    {
                        "type": "group",
                        "value": "users",
                        "display": "users",
                        "justification": "rotation handoff",
                    },
                    created_by="alice@example.com",
                )

        # Assertions: repo.update_on_behalf_of called with type+value
        repo_mock.update_on_behalf_of.assert_called_once_with(
            manager._db, "sess-1", "group", "users",
        )
        # And step_results received the FULL payload (display + justification kept)
        appended = repo_mock.append_step_result.call_args
        assert appended.args[1] == "sess-1"
        assert appended.args[2] == "who"
        appended_payload = appended.args[3]
        assert appended_payload["type"] == "group"
        assert appended_payload["value"] == "users"
        assert appended_payload.get("display") == "users"
        assert appended_payload.get("justification") == "rotation handoff"

    def test_submit_does_not_write_when_value_blank(self, manager):
        """Defensive: if validator passed but value resolves to empty (shouldn't
        happen) the repo update is skipped to avoid clobbering a previously
        captured OBO. Validator catches this; this just locks the contract."""
        step = _make_step({"require_justification": False})
        snapshot_steps = [step]

        with patch(
            'src.controller.agreement_wizard_manager.agreement_wizard_sessions_repo'
        ) as repo_mock, patch.object(
            manager, '_get_steps_from_snapshot', return_value=snapshot_steps,
        ), patch.object(
            manager, '_get_workflow_steps', return_value=snapshot_steps,
        ), patch.object(
            manager, '_validate_on_behalf_of_payload', return_value=None,
        ):
            session = _session()
            repo_mock.get.return_value = session
            repo_mock.append_step_result.return_value = session
            repo_mock.get_step_results.return_value = []
            repo_mock.update_on_behalf_of = MagicMock()
            with patch.object(manager, '_complete_session', return_value={"complete": True}):
                manager.submit_step(
                    "sess-1",
                    "who",
                    {"type": "user", "value": ""},
                    created_by="alice@example.com",
                )
        repo_mock.update_on_behalf_of.assert_not_called()
