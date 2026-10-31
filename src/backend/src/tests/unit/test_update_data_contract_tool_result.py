"""update_data_contract returns its result after the update was written.

The result read ``updated.domain`` on a ``DataContractDb``, which has no such
attribute since the domain assignment moved to the entity-domain associations.
Every successful update raised after the write and came back as ``tool_failed``,
so the model believed the update had failed. The domain in the result now comes
from the associations (primary domain name), and a ``domain`` argument is applied.
"""
import os
os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import asyncio
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_domains import DataDomain
from src.repositories.entity_domain_association_repository import entity_domain_repo
from src.tools.base import ToolContext
from src.tools.registry import ToolRegistry
from src.tools.data_contracts import UpdateDataContractTool


@pytest.fixture
def manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path('/tmp'))
    mgr._update_search_index = lambda *a, **k: None
    mgr._queue_delivery = lambda *a, **k: None
    return mgr


def _contract(db_session, status='draft') -> str:
    cid = str(uuid.uuid4())
    db_session.add(DataContractDb(
        id=cid, name=f'Contract {cid[:8]}', version='1.0.0', status=status,
    ))
    db_session.commit()
    return cid


def _domain(db_session, name) -> str:
    did = str(uuid.uuid4())
    db_session.add(DataDomain(id=did, name=f'{name}-{did[:6]}', created_by='admin@example.com'))
    db_session.commit()
    return did


def _run(db_session, manager, args):
    registry = ToolRegistry()
    registry.register(UpdateDataContractTool())
    ctx = ToolContext(db=db_session, settings=MagicMock(), data_contracts_manager=manager)
    return asyncio.run(registry.execute('update_data_contract', ctx, args))


def test_a_status_change_returns_the_updated_contract(manager, db_session):
    cid = _contract(db_session, status='draft')
    did = _domain(db_session, 'sales')
    entity_domain_repo.set_domains_for_entity(
        db_session, entity_type='data_contract', entity_id=cid, domain_ids=[did],
    )
    db_session.commit()

    result = _run(db_session, manager, {'contract_id': cid, 'status': 'proposed'})

    assert result.success is True, result.error
    assert result.data['status'] == 'proposed'
    assert result.data['domain'].startswith('sales-')


def test_a_description_update_returns_the_updated_contract(manager, db_session):
    cid = _contract(db_session)

    result = _run(db_session, manager, {'contract_id': cid, 'description': 'New purpose'})

    assert result.success is True, result.error
    assert result.data['contract_id'] == cid
    assert result.data['domain'] is None


def test_a_domain_argument_is_applied_and_returned(manager, db_session):
    cid = _contract(db_session)
    did = _domain(db_session, 'finance')
    name = db_session.get(DataDomain, did).name

    result = _run(db_session, manager, {'contract_id': cid, 'domain': name})

    assert result.success is True, result.error
    assert result.data['domain'] == name
    assigned = entity_domain_repo.get_domains_for_entity(
        db_session, entity_type='data_contract', entity_id=cid,
    )
    assert [d.domain_id for d in assigned] == [did]
