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


def test_a_pair_with_a_dispatch_site_is_accepted(db_session):
    result = _manager(db_session).validate_workflow(_workflow(WorkflowTrigger(
        type=TriggerType.BEFORE_UPDATE, entity_types=[EntityType.DATA_CONTRACT],
    )))

    assert result.valid, result.errors


def test_a_pair_no_code_fires_is_refused_with_a_code(db_session):
    result = _manager(db_session).validate_workflow(_workflow(WorkflowTrigger(
        type=TriggerType.BEFORE_UPDATE,
        entity_types=[EntityType.DATA_CONTRACT, EntityType.DATA_PRODUCT],
    )))

    assert not result.valid
    assert _issues(result) == [('trigger_entity_type_unsupported',
                                {'triggerType': 'before_update', 'entityType': 'data_product'})]


@pytest.mark.parametrize('trigger_type', [TriggerType.MANUAL, TriggerType.SCHEDULED,
                                          TriggerType.FOR_APPROVAL_RESPONSE])
def test_an_empty_list_in_the_map_allows_any_entity(db_session, trigger_type):
    result = _manager(db_session).validate_workflow(_workflow(WorkflowTrigger(
        type=trigger_type, entity_types=[EntityType.DATA_PRODUCT, EntityType.TABLE],
    )))

    assert result.valid, result.errors


def test_an_unknown_entity_type_has_its_own_code(db_session):
    result = _manager(db_session).validate_workflow(_workflow(WorkflowTrigger(
        type=TriggerType.BEFORE_UPDATE, entity_types=[EntityType.DATA_CONTRACT],
        unknown_entity_types=['dataset'],
    )))

    assert not result.valid
    assert _issues(result) == [('trigger_entity_type_unknown',
                                {'triggerType': 'before_update', 'entityType': 'dataset'})]


def test_maturity_change_fires_for_products_and_contracts_only(db_session):
    manager = _manager(db_session)
    allowed = manager.validate_workflow(_workflow(WorkflowTrigger(
        type=TriggerType.ON_MATURITY_CHANGE,
        entity_types=[EntityType.DATA_PRODUCT, EntityType.DATA_CONTRACT],
    )))
    refused = manager.validate_workflow(_workflow(WorkflowTrigger(
        type=TriggerType.ON_MATURITY_CHANGE, entity_types=[EntityType.DOMAIN],
    )))

    assert allowed.valid, allowed.errors
    assert _issues(refused) == [('trigger_entity_type_unsupported',
                                 {'triggerType': 'on_maturity_change', 'entityType': 'domain'})]


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
        if not result.valid:
            failures[wf.name] = result.errors
    assert failures == {}


# Demo workflows (``process_workflows`` rows of the demo presets) whose trigger the save
# check refuses. They keep loading and are only refused when edited; listed so a new
# preset workflow with a pair no code fires fails here.
def _refused(code, trigger_type, entity_type):
    return [(code, {'triggerType': trigger_type, 'entityType': entity_type})]


_DEMO_PAIRS_REFUSED = {
    ('demo_data_retail.sql', 'Pre-Creation Compliance Validation'):
        _refused('trigger_entity_type_unsupported', 'before_create', 'view'),
    ('demo_data_retail.sql', 'Contract Purpose Gate'):
        _refused('trigger_entity_type_unknown', 'before_update', 'dataset'),
    ('demo_data_retail.sql', 'Full Governance Pre-Check'):
        _refused('trigger_entity_type_unsupported', 'before_create', 'view'),
    ('demo_data_fsi.sql', 'AML Model Validation Gate'):
        _refused('trigger_entity_type_unsupported', 'before_update', 'data_product'),
}
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


def test_demo_workflows_load_and_only_the_known_ones_are_refused(db_session):
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
        result = manager.validate_workflow(_workflow(stored.trigger))
        if not result.valid:
            refused[(file_name, name)] = _issues(result)

    assert refused == _DEMO_PAIRS_REFUSED
