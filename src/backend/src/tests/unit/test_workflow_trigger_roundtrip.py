"""Round-trip test for workflow trigger values.

Creates a workflow with a representative trigger, fetches it, updates it
unchanged, fetches again — and asserts the raw `trigger.type` string is
byte-identical at every hop. Guards against silent enum coercion or
case-normalisation that could break stored customer workflows.
"""

import pytest

from src.controller.workflows_manager import WorkflowsManager
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    ProcessWorkflowUpdate,
    ScopeType,
    TriggerType,
    WorkflowScope,
    WorkflowTrigger,
    WorkflowType,
)


# Every for_* trigger (the new approval picker uses these) plus one
# representative from each process category (on_*, before_*, scheduled).
_TRIGGER_FIXTURES = [
    # (TriggerType, entity_types, workflow_type, schedule)
    (TriggerType.FOR_SUBSCRIBE, [EntityType.DATA_PRODUCT], WorkflowType.APPROVAL, None),
    (TriggerType.FOR_REQUEST_ACCESS, [EntityType.ACCESS_GRANT], WorkflowType.APPROVAL, None),
    (TriggerType.FOR_REQUEST_REVIEW, [EntityType.DATA_PRODUCT], WorkflowType.APPROVAL, None),
    (TriggerType.FOR_REQUEST_PUBLISH, [EntityType.DATA_CONTRACT], WorkflowType.APPROVAL, None),
    (TriggerType.FOR_REQUEST_CERTIFY, [EntityType.DATA_PRODUCT], WorkflowType.APPROVAL, None),
    (TriggerType.FOR_REQUEST_STATUS_CHANGE, [EntityType.DATA_PRODUCT], WorkflowType.APPROVAL, None),
    (TriggerType.FOR_APPROVAL_RESPONSE, [], WorkflowType.APPROVAL, None),
    (TriggerType.ON_CREATE, [EntityType.TABLE], WorkflowType.PROCESS, None),
    (TriggerType.BEFORE_CREATE, [EntityType.TABLE], WorkflowType.PROCESS, None),
    (TriggerType.SCHEDULED, [], WorkflowType.PROCESS, "0 9 * * *"),
]


@pytest.mark.parametrize(
    ("trigger_type", "entity_types", "workflow_type", "schedule"),
    _TRIGGER_FIXTURES,
    ids=lambda v: v.value if hasattr(v, "value") else str(v),
)
def test_trigger_value_survives_create_get_update_get(
    db_session,
    trigger_type: TriggerType,
    entity_types,
    workflow_type: WorkflowType,
    schedule,
) -> None:
    manager = WorkflowsManager(db_session)

    trigger = WorkflowTrigger(
        type=trigger_type,
        entity_types=entity_types,
        schedule=schedule,
    )
    create_payload = ProcessWorkflowCreate(
        name=f"roundtrip-{trigger_type.value}",
        description="roundtrip test",
        trigger=trigger,
        scope=WorkflowScope(type=ScopeType.ALL),
        workflow_type=workflow_type,
        is_active=True,
        steps=[],
    )

    # Create
    created = manager.create_workflow(create_payload, created_by="test_user")
    wf_id = created.id
    assert created.trigger.type.value == trigger_type.value, (
        f"create dropped value: expected '{trigger_type.value}', got "
        f"'{created.trigger.type.value}'"
    )

    # Get
    fetched = manager.get_workflow(wf_id)
    assert fetched is not None
    assert fetched.trigger.type.value == trigger_type.value
    assert [et.value for et in fetched.trigger.entity_types] == [
        et.value for et in entity_types
    ]

    # Update (unchanged trigger)
    update_payload = ProcessWorkflowUpdate(
        trigger=fetched.trigger,
    )
    updated = manager.update_workflow(wf_id, update_payload, updated_by="test_user")
    assert updated is not None
    assert updated.trigger.type.value == trigger_type.value

    # Get again
    refetched = manager.get_workflow(wf_id)
    assert refetched is not None
    assert refetched.trigger.type.value == trigger_type.value, (
        f"refetched value drifted: expected '{trigger_type.value}', got "
        f"'{refetched.trigger.type.value}'"
    )
