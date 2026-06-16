"""Tests for the workflow template-variable descriptor registry.

Two layers:

1. **Shape tests** — call ``WorkflowsManager.get_template_vars`` for each
   supported (trigger × entity_type) combination, assert the response
   shape is well-formed (every descriptor has ``path`` / ``type`` /
   ``description`` / ``sample``).

2. **Drift detector** — for each supported combo, build a realistic
   ``StepContext`` whose ``entity`` mirrors what the corresponding
   enrichment block actually produces (e.g.
   ``enrich_entity_data_with_data_product`` for DP triggers), then walk
   every descriptor's ``${<path>}`` through ``substitute_template`` and
   assert it resolves (i.e. the literal placeholder isn't returned).

   When someone adds a new field to entity_data without updating the
   registry — or vice versa — this test fires and surfaces the drift in
   CI. That's the static-descriptor mitigation per the PR brief.
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

from src.common.workflow_executor import StepContext, substitute_template
from src.common.workflow_triggers import enrich_entity_data_with_data_product
from src.controller.workflows_manager import WorkflowsManager
from src.models.process_workflows import (
    EntityType,
    TemplateVarDescriptor,
    TemplateVarsResponse,
    TriggerType,
)


# Supported (trigger × entity_type) combinations the registry currently
# describes. Update this list AND the registry together — the drift
# detector below uses this list as the canonical scope.
SUPPORTED_COMBOS = [
    (TriggerType.ON_REQUEST_ACCESS, EntityType.ACCESS_GRANT),
    (TriggerType.ON_SUBSCRIBE, EntityType.DATA_PRODUCT),
]


def _make_port(name: str, asset_identifier: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, asset_identifier=asset_identifier)


def _build_dp_entity_data_for_access_grant() -> Dict[str, Any]:
    """Mirror the entity_data shape ``AccessGrantsManager`` produces for
    ``on_request_access`` × ``data_product``.

    Keep this aligned with the live enrichment block — if a new field
    lands there, mirror it here AND register a descriptor.
    """
    fake_dp = SimpleNamespace(
        id="prd-123",
        name="customer_360",
        output_ports=[
            _make_port("orders", "prod.sales.orders"),
            _make_port("customers", "main.marts.customers"),
        ],
    )
    entity_data: Dict[str, Any] = {
        "request_id": "agr-1",
        "entity_type": "data_product",
        "entity_id": "prd-123",
        "entity_name": "customer_360",
        "requested_duration_days": 30,
        "permission_level": "READ",
        "reason": "Need to validate Q3 churn metrics.",
        "consumer_principals": [
            {"type": "group", "value": "data_product_consumers"},
        ],
    }
    enrich_entity_data_with_data_product(entity_data, fake_dp)
    entity_data["data_product_name"] = fake_dp.name
    return entity_data


def _build_dp_entity_data_for_subscribe() -> Dict[str, Any]:
    """Mirror the entity_data shape ``DataProductsManager.subscribe``
    produces for ``on_subscribe`` × ``data_product``."""
    fake_dp = SimpleNamespace(
        id="prd-123",
        name="customer_360",
        output_ports=[
            _make_port("orders", "prod.sales.orders"),
            _make_port("customers", "main.marts.customers"),
        ],
    )
    entity_data: Dict[str, Any] = {
        "product_id": "prd-123",
        "subscriber_email": "alice@example.com",
        "reason": "Onboarding analytics dashboard.",
        "consumer_principals": [
            {"type": "group", "value": "data_product_consumers"},
        ],
        "on_behalf_of": {
            "type": "group",
            "value": "data_product_consumers",
            "display": "Group: data_product_consumers",
        },
    }
    enrich_entity_data_with_data_product(entity_data, fake_dp)
    entity_data["data_product_name"] = fake_dp.name
    return entity_data


ENTITY_DATA_BUILDERS = {
    (TriggerType.ON_REQUEST_ACCESS, EntityType.ACCESS_GRANT): _build_dp_entity_data_for_access_grant,
    (TriggerType.ON_SUBSCRIBE, EntityType.DATA_PRODUCT): _build_dp_entity_data_for_subscribe,
}


def _make_context(entity_data: Dict[str, Any]) -> StepContext:
    """Build a StepContext that matches what the executor would build at runtime."""
    return StepContext(
        entity=entity_data,
        entity_type=entity_data.get("entity_type") or "data_product",
        entity_id=entity_data.get("entity_id") or entity_data.get("product_id") or "prd-123",
        entity_name=entity_data.get("entity_name") or entity_data.get("data_product_name") or "customer_360",
        user_email="alice@example.com",
        trigger_context=None,
        execution_id="exe-001",
        workflow_id="wf-001",
        workflow_name="Test Workflow",
        step_results={},
        # The executor hoists entity_data["on_behalf_of"] onto the
        # context when present (workflow_executor.py ~2064); mirror that
        # so ${context.on_behalf_of.*} resolves like it does at runtime.
        on_behalf_of=entity_data.get("on_behalf_of") or {
            "type": "user",
            "value": "alice@example.com",
            "display": "alice@example.com",
        },
    )


class TestTemplateVarsRegistryShape:
    """Verify every supported combo returns a well-formed response."""

    @pytest.fixture
    def manager(self, db_session):
        return WorkflowsManager(db_session)

    @pytest.mark.parametrize("trigger,entity", SUPPORTED_COMBOS)
    def test_supported_combo_returns_non_empty_groups(self, manager, trigger, entity):
        response = manager.get_template_vars(trigger, entity)
        assert isinstance(response, TemplateVarsResponse)
        assert response.trigger == trigger
        assert response.entity_type == entity
        assert len(response.groups) > 0, (
            f"Expected curated descriptors for ({trigger.value}, {entity.value})"
        )

    @pytest.mark.parametrize("trigger,entity", SUPPORTED_COMBOS)
    def test_every_descriptor_has_required_fields(self, manager, trigger, entity):
        response = manager.get_template_vars(trigger, entity)
        for group in response.groups:
            assert group.namespace, "Group namespace must be non-empty"
            assert group.description, "Group description must be non-empty"
            assert isinstance(group.variables, list)
            assert len(group.variables) > 0, (
                f"Group '{group.namespace}' must have at least one descriptor"
            )
            for descriptor in group.variables:
                assert isinstance(descriptor, TemplateVarDescriptor)
                assert descriptor.path, "Descriptor.path must be non-empty"
                assert descriptor.type in {
                    "string",
                    "number",
                    "boolean",
                    "array",
                    "object",
                    "enum",
                }, f"Unknown type '{descriptor.type}' on '{descriptor.path}'"
                assert descriptor.description, (
                    f"Descriptor '{descriptor.path}' must have a description"
                )
                # ``sample`` is allowed to be None for enum-only or
                # explicitly opaque descriptors, but we keep all
                # current entries populated.
                assert descriptor.sample is not None, (
                    f"Descriptor '{descriptor.path}' should have a sample value"
                )
                if descriptor.type == "enum":
                    assert descriptor.enum_values, (
                        f"Enum descriptor '{descriptor.path}' must list enum_values"
                    )

    def test_unsupported_combo_returns_empty_groups(self, manager):
        """Combinations not in the registry return a valid response with
        an empty ``groups`` list — never raise. The UI surfaces this as
        a friendly "no descriptors yet" state.
        """
        response = manager.get_template_vars(
            TriggerType.ON_CREATE,
            EntityType.CATALOG,
        )
        assert response.groups == []


class TestTemplateVarsRegistryDrift:
    """Walk every descriptor through ``substitute_template`` against a
    realistic ``StepContext``. If a path doesn't resolve, the registry
    has drifted from the live enrichment — fail and ask the developer
    to reconcile.
    """

    @pytest.fixture
    def manager(self, db_session):
        return WorkflowsManager(db_session)

    @pytest.mark.parametrize("trigger,entity", SUPPORTED_COMBOS)
    def test_every_descriptor_resolves_against_live_context(
        self, manager, trigger, entity
    ):
        builder = ENTITY_DATA_BUILDERS[(trigger, entity)]
        entity_data = builder()
        context = _make_context(entity_data)
        response = manager.get_template_vars(trigger, entity)

        unresolved = []
        for group in response.groups:
            for descriptor in group.variables:
                placeholder = f"${{{descriptor.path}}}"
                rendered = substitute_template(placeholder, context)
                # Drift signal: substitute_template returns the literal
                # placeholder when the path is unknown. Empty string is
                # OK — it means the path resolved to a value that
                # happens to be empty/None.
                if rendered == placeholder:
                    unresolved.append(
                        f"  - '{descriptor.path}' in group '{group.namespace}'"
                    )

        assert not unresolved, (
            f"Template-var registry has drifted from the live entity_data "
            f"for ({trigger.value}, {entity.value}). The following descriptor "
            f"paths do not resolve against a realistic StepContext — either "
            f"add the missing field to the enrichment block or remove the "
            f"stale descriptor:\n" + "\n".join(unresolved)
        )
