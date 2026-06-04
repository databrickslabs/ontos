"""Contract test for GET /api/workflows/trigger-types.

Asserts the response shape and that every TriggerType enum member is
represented exactly once. The endpoint is the canonical catalog consumed by
the frontend workflow-authoring picker — drift here breaks the UX without
breaking type checks.
"""

import asyncio
from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from src.models.process_workflows import TriggerType
from src.routes.workflows_routes import get_trigger_types


def _call_endpoint() -> List[Dict[str, Any]]:
    """Invoke the async route handler directly, bypassing FastAPI auth."""
    # PermissionChecker is a Depends() — bypassed by calling the underlying
    # coroutine directly with positional args. request is unused by the
    # handler body, so a MagicMock is sufficient.
    #
    # asyncio.run() creates and tears down a fresh event loop per call.
    # asyncio.get_event_loop() is unreliable here: on Python 3.10+ it raises
    # "There is no current event loop in thread 'MainThread'" when no loop has
    # been set, which is the case under pytest's default (non-async) runner.
    return asyncio.run(get_trigger_types(request=MagicMock(), _=True))


def test_every_trigger_type_represented_exactly_once() -> None:
    payload = _call_endpoint()
    values = [entry["value"] for entry in payload]
    expected = {tt.value for tt in TriggerType}
    assert set(values) == expected, (
        f"Trigger-types catalog drift: missing={expected - set(values)}, "
        f"extra={set(values) - expected}"
    )
    # No duplicates
    assert len(values) == len(set(values)), (
        f"Duplicate entries in trigger-types catalog: {values}"
    )
    assert len(values) == len(expected)


def test_response_shape() -> None:
    payload = _call_endpoint()
    required_keys = {"value", "label", "workflow_type", "entity_types", "group"}
    for entry in payload:
        assert required_keys.issubset(entry.keys()), (
            f"Trigger-types entry missing keys: {required_keys - entry.keys()} "
            f"(entry={entry})"
        )
        assert isinstance(entry["value"], str)
        assert isinstance(entry["label"], str) and entry["label"]
        assert entry["workflow_type"] in {"process", "approval"}
        assert isinstance(entry["entity_types"], list)
        for et in entry["entity_types"]:
            assert isinstance(et, str)
        assert entry["group"] in {
            "lifecycle", "request_flow", "validation_gates", "system_scheduled",
        }


def test_is_advanced_not_in_response() -> None:
    """The is_advanced field was removed when the "Show advanced triggers"
    toggle was dropped from the picker — for_approval_response is now shown
    inline alongside the other approval triggers. Guard against it sneaking
    back in.
    """
    payload = _call_endpoint()
    for entry in payload:
        assert "is_advanced" not in entry, (
            f"is_advanced should not be returned anymore (entry={entry})"
        )


def test_for_triggers_are_approval_workflow_type() -> None:
    """Every for_* trigger must be classified as approval, everything else as process."""
    payload = _call_endpoint()
    for entry in payload:
        if entry["value"].startswith("for_"):
            assert entry["workflow_type"] == "approval", entry
        else:
            assert entry["workflow_type"] == "process", entry


def test_approval_triggers_are_in_request_flow_group() -> None:
    """All for_* approval triggers should live under request_flow in the UI."""
    payload = _call_endpoint()
    for entry in payload:
        if entry["workflow_type"] == "approval":
            assert entry["group"] == "request_flow", entry
