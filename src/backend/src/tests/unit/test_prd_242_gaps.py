"""Unit tests for PRD #242 follow-up gap fixes.

Two narrow regressions:

1. ``AcknowledgementChecklistStepConfig.items`` documented a max-10 cap but
   had no Pydantic enforcement — designers could persist unlimited items.
   ``test_acknowledgement_checklist_cap`` locks the validator behaviour.

2. ``DeliverStepConfig.recipients`` documented ``co_signers`` as a token but
   ``_send_delivery_notifications`` only handled ``signer`` / ``entity_owner``
   / literal email — workflows configured with ``recipients: ['co_signers']``
   silently dropped them. ``test_deliver_resolves_co_signers_recipients`` and
   ``test_deliver_skips_non_user_co_signers`` lock the new branch.
"""
# Set test environment variables BEFORE any app imports
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.models.process_workflows import (
    AcknowledgementChecklistStepConfig,
    StepType,
    WorkflowStep,
)


# =========================================================================
# Gap 1 — AcknowledgementChecklistStepConfig hard cap of 10 items
# =========================================================================

class TestAcknowledgementChecklistCap:
    """AC: items field rejects payloads with >10 entries; <=10 succeeds."""

    def test_acknowledgement_checklist_cap(self):
        """11 items must raise; 10 items must succeed (boundary)."""
        # Boundary: exactly 10 is allowed
        ten_items = [{"id": f"i{n}", "label": f"Item {n}", "required": True} for n in range(10)]
        cfg_ok = AcknowledgementChecklistStepConfig(items=ten_items)
        assert len(cfg_ok.items) == 10

        # 11 items must raise with the documented cap message
        eleven_items = ten_items + [{"id": "i10", "label": "Eleventh", "required": False}]
        with pytest.raises(ValueError) as excinfo:
            AcknowledgementChecklistStepConfig(items=eleven_items)
        assert "hard cap of 10" in str(excinfo.value)

    def test_empty_items_allowed(self):
        """Default (empty list) must still work — zero is below the cap."""
        cfg = AcknowledgementChecklistStepConfig()
        assert cfg.items == []


# =========================================================================
# Gap 2 — _send_delivery_notifications resolves 'co_signers' token
# =========================================================================

def _make_session_with_co_signers(co_signers_payload):
    """Build a SimpleNamespace mimicking the wizard session row.

    ``step_results`` is the JSON-encoded list-of-dicts the repo deserialises.
    The deliver step is appended after a co_signers step so the wizard
    runtime sees both step_ids when walking ``step_source``.
    """
    return SimpleNamespace(
        id="sess-cs-1",
        workflow_id="wf-cs",
        workflow_name="Co-signer Approval",
        # Snapshot includes both a co_signers step and a deliver step so
        # _send_delivery_notifications finds them via step_source.
        workflow_snapshot=json.dumps({
            "steps": [
                {
                    "step_id": "step_co_signers_1",
                    "name": "Co-signers",
                    "step_type": StepType.CO_SIGNERS.value,
                    "config": {"min_count": 1, "max_count": 5, "principal_type": "user"},
                },
                {
                    "step_id": "step_deliver_1",
                    "name": "Deliver",
                    "step_type": StepType.DELIVER.value,
                    "config": {
                        "channels": ["in_app"],
                        "recipients": ["co_signers"],
                    },
                },
            ],
        }),
        entity_type="data_product",
        entity_id="prod-cs-9",
        created_by="signer@example.com",
        created_at="2026-05-01T00:00:00Z",
        completion_action=None,
        on_behalf_of_type=None,
        on_behalf_of_value=None,
        step_results=json.dumps([
            {"step_id": "step_co_signers_1", "payload": {"co_signers": co_signers_payload}},
        ]),
    )


def _run_delivery(session) -> MagicMock:
    """Drive ``_send_delivery_notifications`` and return the mocked
    NotificationsManager so tests can inspect ``create_notification`` calls.
    """
    from src.controller.agreement_wizard_manager import AgreementWizardManager

    manager = AgreementWizardManager(db=MagicMock(), storage_base_path=None)
    notifications_manager = MagicMock()
    manager._notifications_manager = notifications_manager

    # Build a stub workflow object with a `.name` and `.steps` attr (the
    # snapshot path is preferred, but the function reads workflow.name as a
    # display-name fallback). Returning None for steps is fine because
    # snapshot_steps wins.
    workflow = SimpleNamespace(name="Co-signer Approval", steps=None)

    with patch.object(manager, "_get_entity_name", return_value="My Product"), \
         patch.object(manager, "_resolve_entity_owner", return_value="owner@example.com"):
        manager._send_delivery_notifications(
            session=session,
            workflow=workflow,
            workflow_name="Co-signer Approval",
            agreement_id="agr-cs-1",
            created_by="signer@example.com",
        )

    return notifications_manager


class TestDeliverCoSignersRecipientResolution:
    """AC: deliver step's 'co_signers' token resolves to user emails from the
       co_signers step result."""

    def test_deliver_resolves_co_signers_recipients(self):
        """Two user-type co_signers -> two in_app notifications dispatched."""
        co_signers = [
            {"type": "user", "value": "alice@x.com", "display": "Alice"},
            {"type": "user", "value": "bob@x.com", "display": "Bob"},
        ]
        session = _make_session_with_co_signers(co_signers)

        notif_mgr = _run_delivery(session)

        assert notif_mgr.create_notification.call_count == 2
        recipients = {
            call.kwargs["notification"].recipient
            for call in notif_mgr.create_notification.call_args_list
        }
        assert recipients == {"alice@x.com", "bob@x.com"}

    def test_deliver_skips_non_user_co_signers(self):
        """Group / SP co_signers are skipped (logged) — no notification crash."""
        co_signers = [
            {"type": "group", "value": "finance", "display": "Finance Team"},
            {"type": "service_principal", "value": "sp-id-123", "display": "Audit SP"},
        ]
        session = _make_session_with_co_signers(co_signers)

        notif_mgr = _run_delivery(session)

        # No notifications because there are no resolvable user emails and
        # 'signer' is NOT in the recipients list (only 'co_signers' was).
        assert notif_mgr.create_notification.call_count == 0

    def test_deliver_mixed_user_and_group(self):
        """Only user-type entries are dispatched; group entries are skipped."""
        co_signers = [
            {"type": "user", "value": "carol@x.com", "display": "Carol"},
            {"type": "group", "value": "ops-team", "display": "Ops"},
        ]
        session = _make_session_with_co_signers(co_signers)

        notif_mgr = _run_delivery(session)

        assert notif_mgr.create_notification.call_count == 1
        recipient = notif_mgr.create_notification.call_args_list[0].kwargs["notification"].recipient
        assert recipient == "carol@x.com"
