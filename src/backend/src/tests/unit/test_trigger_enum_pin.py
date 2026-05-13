"""Enum-pin test for TriggerType.

The wire format of `trigger.type` in stored workflow definitions is the raw
string value of each TriggerType enum member. Renaming any of these values is
a breaking change for every existing workflow row in customer databases — so
this test pins the exact strings.

If you genuinely need to add a new trigger, append it here. If you think you
need to rename an existing one, write a migration instead.
"""

import pytest

from src.models.process_workflows import TriggerType


# (Enum-member-name, expected wire value) — one tuple per TriggerType member.
# Keep this list in sync with the enum; the test below also asserts no enum
# member is missing from the list.
_EXPECTED_TRIGGER_VALUES = [
    ("ON_CREATE", "on_create"),
    ("ON_UPDATE", "on_update"),
    ("ON_DELETE", "on_delete"),
    ("ON_STATUS_CHANGE", "on_status_change"),
    ("SCHEDULED", "scheduled"),
    ("MANUAL", "manual"),
    ("BEFORE_CREATE", "before_create"),
    ("BEFORE_UPDATE", "before_update"),
    ("BEFORE_STATUS_CHANGE", "before_status_change"),
    ("ON_REQUEST_REVIEW", "on_request_review"),
    ("ON_REQUEST_ACCESS", "on_request_access"),
    ("ON_REQUEST_PUBLISH", "on_request_publish"),
    ("ON_REQUEST_STATUS_CHANGE", "on_request_status_change"),
    ("ON_JOB_SUCCESS", "on_job_success"),
    ("ON_JOB_FAILURE", "on_job_failure"),
    ("ON_SUBSCRIBE", "on_subscribe"),
    ("ON_UNSUBSCRIBE", "on_unsubscribe"),
    ("ON_REQUEST_CERTIFY", "on_request_certify"),
    ("ON_CERTIFY", "on_certify"),
    ("ON_DECERTIFY", "on_decertify"),
    ("ON_PUBLISH", "on_publish"),
    ("ON_UNPUBLISH", "on_unpublish"),
    ("ON_EXPIRING", "on_expiring"),
    ("ON_REVOKE", "on_revoke"),
    ("FOR_APPROVAL_RESPONSE", "for_approval_response"),
    ("FOR_SUBSCRIBE", "for_subscribe"),
    ("FOR_REQUEST_REVIEW", "for_request_review"),
    ("FOR_REQUEST_ACCESS", "for_request_access"),
    ("FOR_REQUEST_PUBLISH", "for_request_publish"),
    ("FOR_REQUEST_CERTIFY", "for_request_certify"),
    ("FOR_REQUEST_STATUS_CHANGE", "for_request_status_change"),
    ("ON_FIRST_ACCESS", "on_first_access"),
]


@pytest.mark.parametrize(("member_name", "wire_value"), _EXPECTED_TRIGGER_VALUES)
def test_trigger_value_is_pinned(member_name: str, wire_value: str) -> None:
    """Each TriggerType member must keep its exact wire-format string."""
    member = getattr(TriggerType, member_name)
    assert member.value == wire_value, (
        f"TriggerType.{member_name}.value changed from '{wire_value}' to "
        f"'{member.value}' — this is a breaking change for stored workflow "
        f"trigger configs. Add a migration instead of renaming the enum value."
    )


def test_all_enum_members_are_pinned() -> None:
    """Every TriggerType member must appear in the pin table.

    Catches the case where a new trigger is added to the enum but its wire
    value is not vetted here.
    """
    enum_names = {m.name for m in TriggerType}
    pinned_names = {name for name, _ in _EXPECTED_TRIGGER_VALUES}
    missing = enum_names - pinned_names
    extra = pinned_names - enum_names
    assert not missing, (
        f"New TriggerType members missing from the pin table: {sorted(missing)}. "
        f"Add them to _EXPECTED_TRIGGER_VALUES in this file."
    )
    assert not extra, (
        f"Pin table references TriggerType members that no longer exist: "
        f"{sorted(extra)}. Did you delete the enum value?"
    )
