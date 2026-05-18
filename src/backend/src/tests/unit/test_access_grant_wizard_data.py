"""Path-B portable wizard launch — backend pass-through tests.

When a ``for_request_access`` approval workflow is configured, the FE captures
the wizard's ``user_action`` fields and posts them in ``wizard_data`` on the
``AccessGrantRequestCreate`` body. The ``AccessGrantsManager`` must:
  1. Accept the request (model has ``extra='allow'``).
  2. Forward each wizard field into the ``on_request_access`` trigger's
     ``entity_data`` so Process workflow steps can reference them via
     ``${entity.<field_id>}``.

These tests mock the trigger registry to capture the entity_data dict reaching
``trigger_registry.on_request_access`` and assert the merge contract holds.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.controller.access_grants_manager import AccessGrantsManager
from src.models.access_grants import AccessGrantRequestCreate, PermissionLevel


def _make_db_request(request_id):
    db_req = MagicMock()
    db_req.id = request_id
    return db_req


def _run_create_request(payload_kwargs, captured):
    """Drive ``create_request`` with mocks, capturing the trigger entity_data."""
    manager = AccessGrantsManager()

    # Mocked repos: no existing pending / no active grant / no duration config.
    manager._request_repo = MagicMock()
    manager._request_repo.check_existing_pending.return_value = None
    request_id = uuid4()
    manager._request_repo.create.return_value = _make_db_request(request_id)

    manager._grant_repo = MagicMock()
    manager._grant_repo.check_active_grant.return_value = None

    manager._config_repo = MagicMock()
    manager._config_repo.get_by_entity_type.return_value = None

    db = MagicMock()
    db.commit = MagicMock()

    fake_registry = MagicMock()
    fake_registry.on_request_access = MagicMock(return_value=[])

    fake_response = MagicMock()

    with patch(
        "src.common.workflow_triggers.get_trigger_registry",
        return_value=fake_registry,
    ), patch(
        "src.controller.access_grants_manager.AccessGrantRequestResponse"
    ) as resp_cls:
        resp_cls.model_validate.return_value = fake_response
        data = AccessGrantRequestCreate(**payload_kwargs)
        manager.create_request(db, requester_email="alice@example.com", data=data)

    # Capture the kwargs reaching the trigger.
    assert fake_registry.on_request_access.call_count == 1
    captured.update(fake_registry.on_request_access.call_args.kwargs)


class TestAccessGrantRequestCreateWithWizardData:
    def test_model_accepts_wizard_data(self):
        """``AccessGrantRequestCreate`` must accept ``wizard_data`` natively."""
        data = AccessGrantRequestCreate(
            entity_type="data_product",
            entity_id="prod-1",
            requested_duration_days=30,
            permission_level=PermissionLevel.READ,
            reason="Need access for the Q3 analytics rollup.",
            wizard_data={"urgency": "high", "ticket_ref": "INC-123"},
        )
        assert data.wizard_data == {"urgency": "high", "ticket_ref": "INC-123"}

    def test_model_accepts_arbitrary_extra_fields(self):
        """``extra='allow'`` keeps the surface flexible for ad-hoc fields."""
        data = AccessGrantRequestCreate(
            entity_type="data_product",
            entity_id="prod-1",
            requested_duration_days=30,
            reason="Need access for the Q3 analytics rollup.",
            custom_top_level_field="hello",
        )
        # Pydantic v2 exposes extras via model_extra
        assert (data.model_extra or {}).get("custom_top_level_field") == "hello"


class TestAccessGrantsManagerEntityData:
    def test_wizard_data_is_splatted_into_entity_data(self):
        """Each wizard field must land at ``entity_data.<field_id>`` so
        Process workflow steps can reference it via ``${entity.<field_id>}``.
        """
        captured = {}
        _run_create_request(
            {
                "entity_type": "data_product",
                "entity_id": "prod-1",
                "requested_duration_days": 30,
                "reason": "Need access for the Q3 analytics rollup.",
                "wizard_data": {"urgency": "high", "ticket_ref": "INC-123"},
            },
            captured,
        )
        entity_data = captured["entity_data"]
        # Splatted form — the workflow author can use ${entity.urgency}.
        assert entity_data["urgency"] == "high"
        assert entity_data["ticket_ref"] == "INC-123"
        # Namespaced bag is also preserved for authors who prefer
        # ${entity.wizard_data.urgency}.
        assert entity_data["wizard_data"] == {"urgency": "high", "ticket_ref": "INC-123"}
        # First-class fields still present.
        assert entity_data["entity_type"] == "data_product"
        assert entity_data["entity_id"] == "prod-1"

    def test_wizard_data_does_not_clobber_first_class_fields(self):
        """A wizard field with the same id as a first-class field (e.g. ``reason``)
        must not overwrite the first-class value.
        """
        captured = {}
        _run_create_request(
            {
                "entity_type": "data_product",
                "entity_id": "prod-1",
                "requested_duration_days": 30,
                "reason": "Need access for the Q3 analytics rollup.",
                # Adversarial: same key as first-class.
                "wizard_data": {"reason": "OVERWRITE", "urgency": "high"},
            },
            captured,
        )
        entity_data = captured["entity_data"]
        # First-class wins.
        assert entity_data["reason"] == "Need access for the Q3 analytics rollup."
        # Other wizard fields still pass through.
        assert entity_data["urgency"] == "high"
        # The full wizard_data bag is still there for explicit lookups.
        assert entity_data["wizard_data"]["reason"] == "OVERWRITE"

    def test_no_wizard_data_keeps_legacy_entity_data_shape(self):
        """Regression: requests without ``wizard_data`` must keep the original
        entity_data shape so existing workflows don't break.
        """
        captured = {}
        _run_create_request(
            {
                "entity_type": "data_product",
                "entity_id": "prod-1",
                "requested_duration_days": 30,
                "reason": "Need access for the Q3 analytics rollup.",
            },
            captured,
        )
        entity_data = captured["entity_data"]
        assert "wizard_data" not in entity_data  # No wrapper bag injected.
        assert entity_data["entity_type"] == "data_product"
        assert entity_data["reason"] == "Need access for the Q3 analytics rollup."

    def test_extra_top_level_fields_also_forward(self):
        """Pydantic ``extra='allow'`` means callers can drop ad-hoc fields at
        the top level (not nested under ``wizard_data``). These should also
        forward into entity_data.
        """
        captured = {}
        _run_create_request(
            {
                "entity_type": "data_product",
                "entity_id": "prod-1",
                "requested_duration_days": 30,
                "reason": "Need access for the Q3 analytics rollup.",
                "deployment_specific_flag": "true",
            },
            captured,
        )
        entity_data = captured["entity_data"]
        assert entity_data["deployment_specific_flag"] == "true"
