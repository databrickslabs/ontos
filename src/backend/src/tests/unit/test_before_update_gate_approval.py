"""Approving a paused before_update gate doesn't apply the update.

The update is refused while the gate waits (a paused gate isn't ``succeeded``).
Approving it runs the gate's remaining steps on the payload of the refused
request, but nothing applies the update afterwards, and the tags the remaining
steps assign aren't written either: the user resubmits the update, which
starts a new approval round.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path

from src.common.workflow_executor import WorkflowExecutor
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.tags_manager import TagsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.process_workflows import ProcessWorkflowDb, WorkflowStepDb
from src.db_models.tags import TagDb, TagNamespaceDb


def _gate(db, fqn):
    """A before_update gate on contracts: an approval, then an assign-tag step."""
    now = datetime.utcnow()
    wf_id = str(uuid.uuid4())
    db.add(ProcessWorkflowDb(
        id=wf_id, name=f'gate-{wf_id[:8]}', description='gate',
        trigger_config=json.dumps({'type': 'before_update', 'entity_types': ['data_contract']}),
        scope_config=json.dumps({'type': 'all'}), is_active=True, is_default=False,
        version=1, created_at=now, updated_at=now,
    ))
    steps = [
        ('approve', 'approval', {'approvers': 'reviewer@example.com'}, 'tag'),
        ('tag', 'assign_tag', {'key': fqn, 'value': 'yes'}, None),
    ]
    for order, (step_id, step_type, config, on_pass) in enumerate(steps):
        db.add(WorkflowStepDb(
            id=str(uuid.uuid4()), workflow_id=wf_id, step_id=step_id, name=step_id,
            step_type=step_type, config=json.dumps(config), on_pass=on_pass, order=order,
            created_at=now, updated_at=now,
        ))
    db.commit()


def test_approving_a_paused_gate_does_not_apply_the_update(db_session, monkeypatch):
    writes = []
    monkeypatch.setattr(
        TagsManager, 'add_tag_to_entity', lambda self, db, **kw: writes.append(kw),
    )
    namespace = TagNamespaceDb(name=f'gate-{uuid.uuid4().hex[:6]}')
    db_session.add(namespace)
    db_session.flush()
    db_session.add(TagDb(name='reviewed', namespace_id=namespace.id, status='active'))
    contract = DataContractDb(
        id=str(uuid.uuid4()), name='Gated', version='1.0.0', status='draft',
        created_by='u@example.com',
    )
    db_session.add(contract)
    db_session.commit()
    _gate(db_session, f'{namespace.name}/reviewed')

    passed, executions = DataContractsManager.run_update_gates(
        db_session, contract, {'name': 'Renamed'}, 'pat@example.com',
    )
    resumed = WorkflowExecutor(db_session).resume_workflow(
        execution_id=executions[0].id, step_result=True,
        result_data={'decision': 'approved'}, user_email='reviewer@example.com',
    )

    assert passed is False
    assert executions[0].status.value == 'paused'
    assert resumed.status.value == 'succeeded'
    db_session.expire_all()
    assert db_session.get(DataContractDb, contract.id).name == 'Gated'
    assert writes == []
