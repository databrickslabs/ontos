"""Unit test for the Daimler #486363 gap-fill: thread on_behalf_of through
the agreement wizard's auto-subscribe path.

When ``completion_action='subscribe'``, ``_complete_session`` calls
``data_products_manager.subscribe()``. PR A added ``on_behalf_of`` to
``subscribe()`` but the wizard wasn't passing it — so wizard-completed
subscriptions ended up with ``on_behalf_of_type=null`` even when the user
selected a group up front.

The fix:
  1. Persist ``on_behalf_of_type`` / ``on_behalf_of_value`` on the wizard
     session row at create time (route → manager → repo).
  2. Read them back in ``_complete_session`` and forward to
     ``dp_manager.subscribe(on_behalf_of=...)``.

These tests assert the kwargs reaching ``DataProductsManager.subscribe`` so
the regression cannot reappear.
"""
# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.controller.agreement_wizard_manager import AgreementWizardManager


def _make_session(*, on_behalf_of_type=None, on_behalf_of_value=None):
    """Minimal session-like object that ``_complete_session`` reads."""
    return SimpleNamespace(
        id="sess-obo-1",
        workflow_id="wf-obo",
        workflow_name="Subscribe Approval",
        workflow_snapshot=None,
        entity_type="data_product",
        entity_id="prod-123",
        created_by="consumer@example.com",
        created_at="2026-05-01T00:00:00Z",
        completion_action="subscribe",
        on_behalf_of_type=on_behalf_of_type,
        on_behalf_of_value=on_behalf_of_value,
    )


def _run_complete(session) -> MagicMock:
    """Drive ``_complete_session`` with mocks and return the captured
    ``DataProductsManager`` instance so the test can inspect its
    ``subscribe`` kwargs.
    """
    manager = AgreementWizardManager(db=MagicMock(), storage_base_path=None)

    fake_dp_manager_cls = MagicMock()
    fake_dp_manager_instance = MagicMock()
    fake_dp_manager_cls.return_value = fake_dp_manager_instance

    with patch(
        "src.controller.data_products_manager.DataProductsManager",
        fake_dp_manager_cls,
    ), patch(
        "src.controller.agreement_wizard_manager.agreements_repo"
    ) as repo_mock, patch(
        "src.controller.agreement_wizard_manager.agreement_wizard_sessions_repo"
    ) as sessions_repo_mock, patch(
        "src.controller.agreement_wizard_manager.ChangeLogManager"
    ), patch.object(
        manager._workflows_manager, "get_workflow", return_value=None
    ), patch.object(
        manager, "_send_delivery_notifications", return_value=None
    ):
        sessions_repo_mock.get_step_results.return_value = []
        sessions_repo_mock.set_completed = MagicMock()
        agreement = SimpleNamespace(id="agr-obo-1", pdf_storage_path=None)
        repo_mock.create.return_value = agreement
        repo_mock.update_step_results = MagicMock()

        manager._complete_session(session, created_by="consumer@example.com")

    return fake_dp_manager_instance


class TestWizardAutoSubscribeOnBehalfOf:
    def test_subscribe_forwards_on_behalf_of_group(self):
        """Wizard completion with persisted OBO must forward it to subscribe()."""
        session = _make_session(
            on_behalf_of_type="group",
            on_behalf_of_value="users",
        )
        dp_instance = _run_complete(session)

        assert dp_instance.subscribe.call_count == 1
        kwargs = dp_instance.subscribe.call_args.kwargs
        assert kwargs["product_id"] == "prod-123"
        assert kwargs["subscriber_email"] == "consumer@example.com"
        # Critical assertion — pre-fix this was missing entirely.
        obo = kwargs.get("on_behalf_of")
        assert obo is not None, "on_behalf_of was not threaded through to dp.subscribe()"
        assert obo.type == "group"
        assert obo.value == "users"

    def test_subscribe_forwards_on_behalf_of_service_principal(self):
        """Same path also handles SP principals."""
        session = _make_session(
            on_behalf_of_type="service_principal",
            on_behalf_of_value="treasure-runbook-sp",
        )
        dp_instance = _run_complete(session)

        kwargs = dp_instance.subscribe.call_args.kwargs
        obo = kwargs.get("on_behalf_of")
        assert obo is not None
        assert obo.type == "service_principal"
        assert obo.value == "treasure-runbook-sp"

    def test_subscribe_self_when_no_on_behalf_of(self):
        """When the session has no OBO, subscribe() receives None — regression
        check so wizard auto-subscribe still works for plain self-subscribes."""
        session = _make_session(
            on_behalf_of_type=None,
            on_behalf_of_value=None,
        )
        dp_instance = _run_complete(session)

        kwargs = dp_instance.subscribe.call_args.kwargs
        assert kwargs.get("on_behalf_of") is None

    def test_subscribe_self_when_partial_on_behalf_of(self):
        """A partially-populated OBO (defensive: only one of type/value) must
        be treated as None rather than triggering a Pydantic validation error
        inside _complete_session."""
        session = _make_session(
            on_behalf_of_type="group",
            on_behalf_of_value=None,
        )
        dp_instance = _run_complete(session)

        kwargs = dp_instance.subscribe.call_args.kwargs
        assert kwargs.get("on_behalf_of") is None
