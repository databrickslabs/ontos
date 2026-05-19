"""Tests for access-grant ``entity_data`` enrichment with underlying-DP fields.

When an access-grant request is fired against a data product, the workflow's
trigger context carries ``entity_type=access_grant`` + ``entity_id=<request_id>``
(the AGR is a proxy for the actual data product). Webhook ``body_template``
authors often need fields from the *underlying* DP — most importantly
``consumer_principals``, the AD/UC access group(s) that a downstream
provisioner adds the requester into to grant catalog access.

Before this enrichment, ``${entity.consumer_principals}`` resolved to nothing,
forcing customers to either (a) hard-code the group name in the webhook
template, (b) modify the FE to inject ``consumer_principals`` into the AGR
POST body, or (c) wait for a "fetch underlying entity" step type that
doesn't exist. All of those were brittle or required customer-side changes
that Ontos can't ship for them.

This module asserts:
- ``consumer_principals`` is enriched onto entity_data from the underlying DP
- The enrichment deserializes the DP's JSON-string column into an array
- Caller-supplied ``consumer_principals`` (via ``wizard_data`` or
  ``extra='allow'``) is NOT overwritten — caller wins
- Non-``data_product`` entity types are not enriched (no DP fetch)
- A DP-fetch failure does not break the access-grant submission
- The DP's name is also exposed under ``data_product_name`` for
  log-friendly webhook templates
"""
import json
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


def _make_dp(*, id_: str, name: str = "Test DP",
             consumer_principals_raw=None):
    """Mock a ``DataProductDb`` with the fields the enrichment reads."""
    dp = MagicMock()
    dp.id = id_
    dp.name = name
    dp.consumer_principals = consumer_principals_raw
    return dp


def _drive_create_request(payload, captured, *, dp_mock=None,
                          dp_fetch_raises=False):
    """Drive ``create_request`` with mocks; capture trigger kwargs."""
    manager = AccessGrantsManager()
    manager._request_repo = MagicMock()
    manager._request_repo.check_existing_pending.return_value = None
    manager._request_repo.create.return_value = _make_db_request(uuid4())
    manager._grant_repo = MagicMock()
    manager._grant_repo.check_active_grant.return_value = None
    manager._config_repo = MagicMock()
    manager._config_repo.get_by_entity_type.return_value = None

    db = MagicMock()
    db.commit = MagicMock()

    fake_registry = MagicMock()
    fake_registry.on_request_access = MagicMock(return_value=[])

    # Patch the DP repo: either return our mock DP, or raise to test
    # the fail-safe wrapper around the enrichment.
    fake_dp_repo = MagicMock()
    if dp_fetch_raises:
        fake_dp_repo.get.side_effect = RuntimeError("simulated DB failure")
    else:
        fake_dp_repo.get.return_value = dp_mock

    with patch(
        "src.common.workflow_triggers.get_trigger_registry",
        return_value=fake_registry,
    ), patch(
        "src.controller.access_grants_manager.AccessGrantRequestResponse"
    ) as resp_cls, patch(
        "src.repositories.data_products_repository.data_product_repo",
        fake_dp_repo,
    ):
        resp_cls.model_validate.return_value = MagicMock()
        data = AccessGrantRequestCreate(**payload)
        manager.create_request(db, requester_email="alice@example.com", data=data)

    assert fake_registry.on_request_access.call_count == 1
    captured.update(fake_registry.on_request_access.call_args.kwargs)


class TestConsumerPrincipalsEnrichment:
    def test_consumer_principals_is_enriched_from_dp(self):
        """Happy path: DP carries consumer_principals; they appear on entity_data."""
        dp_id = "dp-1"
        cp_value = [
            {"type": "group", "value": "099_Treasure_DataProducer_R"}
        ]
        dp = _make_dp(
            id_=dp_id,
            consumer_principals_raw=json.dumps(cp_value),
        )

        captured = {}
        _drive_create_request(
            payload={
                "entity_type": "data_product",
                "entity_id": dp_id,
                "requested_duration_days": 7,
                "permission_level": PermissionLevel.READ,
            },
            captured=captured,
            dp_mock=dp,
        )

        ed = captured["entity_data"]
        assert ed["consumer_principals"] == cp_value
        assert ed.get("data_product_name") == "Test DP"

    def test_dp_with_no_consumer_principals_yields_empty_array(self):
        """A DP that has no consumers set should expose an empty array (not None).

        Downstream provisioners can then fail-fast on empty rather than
        getting null. (Also keeps the JSON shape stable for runbook
        authors.)
        """
        dp = _make_dp(id_="dp-empty", consumer_principals_raw=None)
        captured = {}
        _drive_create_request(
            payload={
                "entity_type": "data_product",
                "entity_id": "dp-empty",
                "requested_duration_days": 7,
                "permission_level": PermissionLevel.READ,
            },
            captured=captured,
            dp_mock=dp,
        )
        assert captured["entity_data"]["consumer_principals"] == []

    def test_caller_supplied_consumer_principals_overrides_enrichment(self):
        """Wizard / extra= callers may want to inject their own group list;
        their value must win over the DP's value."""
        caller_cp = [
            {"type": "group", "value": "caller-specified-group"}
        ]
        dp_cp = [
            {"type": "group", "value": "dp-default-group"}
        ]
        dp = _make_dp(
            id_="dp-2",
            consumer_principals_raw=json.dumps(dp_cp),
        )
        captured = {}
        _drive_create_request(
            payload={
                "entity_type": "data_product",
                "entity_id": "dp-2",
                "requested_duration_days": 7,
                "permission_level": PermissionLevel.READ,
                "consumer_principals": caller_cp,  # extra='allow' field
            },
            captured=captured,
            dp_mock=dp,
        )
        assert captured["entity_data"]["consumer_principals"] == caller_cp

    def test_non_data_product_entity_type_is_not_enriched(self):
        """Workflow types like ``access_grant`` against a contract should
        NOT trigger a DP fetch."""
        fake_dp_repo = MagicMock()
        manager = AccessGrantsManager()
        manager._request_repo = MagicMock()
        manager._request_repo.check_existing_pending.return_value = None
        manager._request_repo.create.return_value = _make_db_request(uuid4())
        manager._grant_repo = MagicMock()
        manager._grant_repo.check_active_grant.return_value = None
        manager._config_repo = MagicMock()
        manager._config_repo.get_by_entity_type.return_value = None

        fake_registry = MagicMock()
        fake_registry.on_request_access = MagicMock(return_value=[])

        with patch(
            "src.common.workflow_triggers.get_trigger_registry",
            return_value=fake_registry,
        ), patch(
            "src.controller.access_grants_manager.AccessGrantRequestResponse"
        ) as resp_cls, patch(
            "src.repositories.data_products_repository.data_product_repo",
            fake_dp_repo,
        ):
            resp_cls.model_validate.return_value = MagicMock()
            data = AccessGrantRequestCreate(
                entity_type="data_contract",
                entity_id="dc-1",
                requested_duration_days=7,
                permission_level=PermissionLevel.READ,
            )
            manager.create_request(
                MagicMock(), requester_email="alice@example.com", data=data
            )

        # The DP repo must NOT have been consulted.
        fake_dp_repo.get.assert_not_called()
        ed = fake_registry.on_request_access.call_args.kwargs["entity_data"]
        assert "consumer_principals" not in ed

    def test_dp_fetch_failure_is_fail_safe(self):
        """If the DP fetch raises, the access-grant submission must still
        succeed — the enrichment is a nice-to-have, not a critical path.
        The exception is logged but never propagates."""
        captured = {}
        _drive_create_request(
            payload={
                "entity_type": "data_product",
                "entity_id": "dp-missing",
                "requested_duration_days": 7,
                "permission_level": PermissionLevel.READ,
            },
            captured=captured,
            dp_fetch_raises=True,
        )
        # entity_data must still be intact (request_id, entity_type, etc.)
        ed = captured["entity_data"]
        assert ed["entity_type"] == "data_product"
        assert ed["entity_id"] == "dp-missing"
        # consumer_principals MUST NOT be set when fetch fails
        assert "consumer_principals" not in ed

    def test_malformed_json_in_consumer_principals_yields_empty_array(self):
        """A DP whose consumer_principals column has invalid JSON must not
        crash submission — the field becomes an empty array and a warning
        is logged."""
        dp = _make_dp(
            id_="dp-bad-json",
            consumer_principals_raw="this is not json",
        )
        captured = {}
        _drive_create_request(
            payload={
                "entity_type": "data_product",
                "entity_id": "dp-bad-json",
                "requested_duration_days": 7,
                "permission_level": PermissionLevel.READ,
            },
            captured=captured,
            dp_mock=dp,
        )
        assert captured["entity_data"]["consumer_principals"] == []
