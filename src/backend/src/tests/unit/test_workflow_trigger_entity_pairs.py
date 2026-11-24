"""Saving a trigger/entity pair that no code fires is refused (#1151 item 7a).

``before_update`` fires only for data contracts, yet a workflow saved through
the API with ``before_update`` on ``data_product`` was accepted and never ran.
A save is now checked against the trigger/entity map of the workflow routes
(``_TRIGGER_ENTITY_TYPES``, an empty list = any entity): a pair outside it,
or an entity type the app doesn't know, is an error with a code and params.
Stored workflows are not checked when they load.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import json
import re
import uuid
from datetime import datetime
from pathlib import Path

import pytest

from src.controller.workflows_manager import WorkflowsManager
from src.db_models.process_workflows import ProcessWorkflowDb
from src.models.process_workflows import (
    EntityType,
    ProcessWorkflowCreate,
    StepType,
    TriggerType,
    WorkflowStepCreate,
    WorkflowTrigger,
)
from src.routes.workflows_routes import _TRIGGER_ENTITY_TYPES

DATA_DIR = Path(__file__).resolve().parents[2] / 'data'


def _manager(db_session):
    return WorkflowsManager(db_session, trigger_entity_types=_TRIGGER_ENTITY_TYPES)


def _workflow(trigger: WorkflowTrigger, steps=None) -> ProcessWorkflowCreate:
    return ProcessWorkflowCreate(
        name='Pairs', trigger=trigger,
        steps=steps or [WorkflowStepCreate(step_id='ok', name='OK', step_type=StepType.PASS)],
    )


def _issues(result):
    return [(issue.code, issue.params) for issue in result.issues]


def _codes(errors):
    return [(e.code, e.params) for e in errors]


def _check(db_session, trigger, stored=None):
    """The trigger/entity errors of saving ``trigger`` (a create, or an update of ``stored``)."""
    return _codes(_manager(db_session).trigger_save_errors(trigger, stored))


def _trigger(trigger_type=TriggerType.BEFORE_UPDATE, known=(), unknown=()):
    return WorkflowTrigger(type=trigger_type, entity_types=list(known),
                           unknown_entity_types=list(unknown))


def test_a_pair_with_a_dispatch_site_is_accepted(db_session):
    assert _check(db_session, _trigger(known=[EntityType.DATA_CONTRACT])) == []


def test_a_pair_no_code_fires_is_refused_with_a_code(db_session):
    assert _check(db_session, _trigger(known=[EntityType.DATA_CONTRACT, EntityType.DATA_PRODUCT])) \
        == [('trigger_entity_type_unsupported',
             {'triggerType': 'before_update', 'entityType': 'data_product'})]


@pytest.mark.parametrize('trigger_type', [TriggerType.MANUAL, TriggerType.SCHEDULED,
                                          TriggerType.FOR_APPROVAL_RESPONSE])
def test_an_empty_list_in_the_map_allows_any_entity(db_session, trigger_type):
    trigger = _trigger(trigger_type, known=[EntityType.DATA_PRODUCT, EntityType.TABLE])
    assert _check(db_session, trigger) == []


def test_an_unknown_entity_type_has_its_own_code(db_session):
    assert _check(db_session, _trigger(known=[EntityType.DATA_CONTRACT], unknown=['dataset'])) \
        == [('trigger_entity_type_unknown',
             {'triggerType': 'before_update', 'entityType': 'dataset'})]


def test_maturity_change_fires_for_products_and_contracts_only(db_session):
    maturity = TriggerType.ON_MATURITY_CHANGE
    assert _check(db_session, _trigger(
        maturity, known=[EntityType.DATA_PRODUCT, EntityType.DATA_CONTRACT])) == []
    assert _check(db_session, _trigger(maturity, known=[EntityType.DOMAIN])) == [
        ('trigger_entity_type_unsupported',
         {'triggerType': 'on_maturity_change', 'entityType': 'domain'}),
    ]


def test_the_trigger_check_is_not_part_of_validate_workflow(db_session):
    """Step edits of a stored workflow go through validate_workflow with the stored trigger."""
    result = _manager(db_session).validate_workflow(_workflow(_trigger(
        known=[EntityType.DATA_PRODUCT], unknown=['dataset'],
    )))
    assert result.valid, result.errors


_STORED_DATASET = _trigger(unknown=['dataset'])
_STORED_PRODUCT_GATE = _trigger(known=[EntityType.DATA_PRODUCT])  # a pair no code fires


@pytest.mark.parametrize('new, stored', [
    (None, _STORED_DATASET),  # trigger not sent
    (_trigger(unknown=['dataset']), _STORED_DATASET),  # sent again as stored
    (_trigger(known=[EntityType.DATA_PRODUCT]), _STORED_PRODUCT_GATE),
    # changed, keeping the stored values under the same trigger type
    (_trigger(known=[EntityType.DATA_CONTRACT], unknown=['dataset']), _STORED_DATASET),
    (_trigger(known=[EntityType.DATA_PRODUCT, EntityType.DATA_CONTRACT]), _STORED_PRODUCT_GATE),
])
def test_an_update_may_keep_what_is_stored(db_session, new, stored):
    assert _check(db_session, new, stored) == []


def test_an_update_may_not_add_an_unsupported_pair(db_session):
    new = _trigger(known=[EntityType.DATA_PRODUCT], unknown=['dataset'])
    assert _check(db_session, new, _STORED_DATASET) == [
        ('trigger_entity_type_unsupported',
         {'triggerType': 'before_update', 'entityType': 'data_product'}),
    ]


@pytest.mark.parametrize('new', [
    _trigger(unknown=['dataset', 'data_product']),  # a known type sent as unknown
    _trigger(unknown=['dataset', 'legacy']),  # an unknown value that isn't stored
])
def test_an_update_may_not_add_unknown_values(db_session, new):
    added = [v for v in new.unknown_entity_types if v != 'dataset']
    assert _check(db_session, new, _STORED_DATASET) == [
        ('trigger_entity_type_unknown', {'triggerType': 'before_update', 'entityType': value})
        for value in added
    ]


def test_stored_values_are_not_kept_under_another_trigger_type(db_session):
    new = _trigger(TriggerType.ON_UPDATE, known=[EntityType.DATA_CONTRACT], unknown=['dataset'])
    assert _check(db_session, new, _STORED_DATASET) == [
        ('trigger_entity_type_unknown', {'triggerType': 'on_update', 'entityType': 'dataset'}),
    ]


def test_every_shipped_default_workflow_validates(db_session):
    manager = _manager(db_session)
    manager.load_from_yaml(str(DATA_DIR / 'default_workflows.yaml'))

    workflows = manager.list_workflows()
    assert len(workflows) > 30
    failures = {}
    for wf in workflows:
        result = manager.validate_workflow(ProcessWorkflowCreate(
            name=wf.name, trigger=wf.trigger, scope=wf.scope, workflow_type=wf.workflow_type,
            steps=[
                WorkflowStepCreate(**step.model_dump(include=set(WorkflowStepCreate.model_fields)))
                for step in wf.steps
            ],
        ))
        errors = [*result.errors, *manager.trigger_save_errors(wf.trigger)]
        if errors:
            failures[wf.name] = errors
    assert failures == {}


# Demo workflows (``process_workflows`` rows of the demo presets) whose trigger would be
# refused on a create. Stored, they keep loading, running and being edited (only a trigger
# change is checked); listed so a new preset workflow with a pair no code fires fails here.
def _refused(code, trigger_type, entity_type):
    return [(code, {'triggerType': trigger_type, 'entityType': entity_type})]


_DEMO_PAIRS_REFUSED = {
    # No code fires before_update for data products (only PUT /data-contracts/{id} does), so
    # there is no pair to move this gate to; it stays as shipped until one exists.
    ('demo_data_fsi.sql', 'AML Model Validation Gate'):
        _refused('trigger_entity_type_unsupported', 'before_update', 'data_product'),
}
# Retail workflows that used to list "view" (no before_create site) or the removed "dataset"
_DEMO_FIXED = ('Pre-Creation Compliance Validation', 'Contract Purpose Gate',
               'Full Governance Pre-Check')
_DEMO_ROW = re.compile(
    r"\('(?P<id>[0-9a-f-]{36})',\s*'(?P<name>(?:[^']|'')*)',\s*'(?:[^']|'')*',"
    r"\s*'(?P<trigger>\{(?:[^']|'')*\})'",
    re.S,
)


def _demo_workflows():
    """(file, name, trigger config) of each process_workflows row in the demo presets."""
    rows = []
    for path in sorted(DATA_DIR.glob('demo_data_*.sql')):
        text = path.read_text()
        start = text.find('INSERT INTO process_workflows')
        while start != -1:
            end = text.find(';\n', start)
            rows += [(path.name, m['name'].replace("''", "'"), m['trigger'].replace("''", "'"))
                     for m in _DEMO_ROW.finditer(text[start:end])]
            start = text.find('INSERT INTO process_workflows', end)
    return rows


def test_demo_workflows_load_edit_and_only_the_known_ones_are_refused_as_new(db_session):
    manager = _manager(db_session)
    rows = _demo_workflows()
    assert len(rows) >= 14

    refused = {}
    for file_name, name, trigger_config in rows:
        wf_id = str(uuid.uuid4())
        now = datetime.utcnow()
        db_session.add(ProcessWorkflowDb(
            id=wf_id, name=f'{name} {wf_id[:8]}', trigger_config=trigger_config,
            scope_config=json.dumps({'type': 'all'}), is_active=False, is_default=False,
            version=1, created_at=now, updated_at=now,
        ))
        db_session.commit()
        stored = manager.get_workflow(wf_id)  # loads, unknown types included
        # A step edit (the trigger unchanged) is accepted
        assert manager.validate_workflow(_workflow(stored.trigger)).valid, name
        assert manager.trigger_save_errors(stored.trigger, stored.trigger) == [], name
        as_new = _codes(manager.trigger_save_errors(stored.trigger))
        if as_new:
            refused[(file_name, name)] = as_new

    assert refused == _DEMO_PAIRS_REFUSED


def test_emptying_a_trigger_of_only_unknown_types_is_refused(db_session):
    stored = WorkflowTrigger(type=TriggerType.BEFORE_UPDATE, unknown_entity_types=['dataset'])

    errors = _manager(db_session).trigger_widening_errors(
        stored, WorkflowTrigger(type=TriggerType.BEFORE_UPDATE),
    )

    assert _codes(errors) == [('trigger_entity_type_required', {'triggerType': 'before_update'})]


@pytest.mark.parametrize('known, unknown', [
    ([EntityType.DATA_PRODUCT], ['dataset']),  # the known type never fires either
    ([EntityType.DATA_PRODUCT], []),  # only a pair no code fires
    ([EntityType.DATA_PRODUCT, EntityType.TABLE], []),
])
def test_emptying_a_trigger_whose_types_all_never_fire_is_refused(db_session, known, unknown):
    stored = _trigger(known=known, unknown=unknown)

    errors = _manager(db_session).trigger_widening_errors(
        stored, WorkflowTrigger(type=TriggerType.BEFORE_UPDATE),
    )

    assert _codes(errors) == [('trigger_entity_type_required', {'triggerType': 'before_update'})]
    # The same through the update check of a changed trigger
    assert _check(db_session, WorkflowTrigger(type=TriggerType.BEFORE_UPDATE), stored) \
        == [('trigger_entity_type_required', {'triggerType': 'before_update'})]


def test_emptying_a_trigger_with_a_type_that_fires_is_not_refused(db_session):
    stored = _trigger(known=[EntityType.DATA_CONTRACT, EntityType.DATA_PRODUCT],
                      unknown=['dataset'])

    assert _manager(db_session).trigger_widening_errors(
        stored, WorkflowTrigger(type=TriggerType.BEFORE_UPDATE),
    ) == []


def test_without_the_map_only_a_trigger_of_unknown_types_counts(db_session):
    manager = WorkflowsManager(db_session)
    empty = WorkflowTrigger(type=TriggerType.BEFORE_UPDATE)

    assert manager.trigger_widening_errors(
        _trigger(known=[EntityType.DATA_PRODUCT], unknown=['dataset']), empty,
    ) == []
    assert [e.code for e in manager.trigger_widening_errors(_trigger(unknown=['dataset']), empty)] \
        == ['trigger_entity_type_required']


def test_unknown_types_under_a_trigger_type_for_any_entity_still_match_nothing(db_session):
    # An unknown value never matches; emptying it under a gate type is refused
    stored = _trigger(TriggerType.MANUAL, unknown=['dataset'])

    assert [e.code for e in _manager(db_session).trigger_widening_errors(
        stored, WorkflowTrigger(type=TriggerType.BEFORE_UPDATE),
    )] == ['trigger_entity_type_required']


@pytest.mark.parametrize('stored, new', [
    # a known type picked
    (WorkflowTrigger(type=TriggerType.BEFORE_UPDATE, unknown_entity_types=['dataset']),
     WorkflowTrigger(type=TriggerType.BEFORE_UPDATE, entity_types=[EntityType.DATA_CONTRACT])),
    # the stored trigger had a known type too: other empty lists are not refused
    (WorkflowTrigger(type=TriggerType.BEFORE_UPDATE, entity_types=[EntityType.DATA_CONTRACT],
                     unknown_entity_types=['dataset']),
     WorkflowTrigger(type=TriggerType.BEFORE_UPDATE)),
    (WorkflowTrigger(type=TriggerType.BEFORE_UPDATE),
     WorkflowTrigger(type=TriggerType.BEFORE_UPDATE)),
    # a trigger type that fires for any entity
    (WorkflowTrigger(type=TriggerType.MANUAL, unknown_entity_types=['dataset']),
     WorkflowTrigger(type=TriggerType.MANUAL)),
    # no trigger in the update
    (WorkflowTrigger(type=TriggerType.BEFORE_UPDATE, unknown_entity_types=['dataset']), None),
])
def test_other_updates_are_not_refused(db_session, stored, new):
    assert _manager(db_session).trigger_widening_errors(stored, new) == []


def test_the_fixed_retail_demo_workflows_pass_the_create_check(db_session):
    manager = _manager(db_session)
    rows = {name: trigger for file_name, name, trigger in _demo_workflows()
            if file_name == 'demo_data_retail.sql'}
    for name in _DEMO_FIXED:
        trigger = WorkflowTrigger.model_validate(json.loads(rows[name]))
        assert trigger.unknown_entity_types == [], name
        assert manager.trigger_save_errors(trigger) == [], name
