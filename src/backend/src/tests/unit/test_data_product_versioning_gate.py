"""The versioning check of a non-draft product edit lives in the manager.

``update_product`` is the one write path: the REST route, the assistant and the
MCP tools all reach it, so none of them can remove an output port of an active
product without a new version. ``update_product_with_auth`` checks the caller
first, so a caller who may not edit gets a 403, not a 409.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest

from src.common.api_errors import VersioningRequiredError
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_products import DataProductDb, OutputPortDb

OWNER = 'sue@example.com'


@pytest.fixture
def manager(db_session):
    products = DataProductsManager(db=db_session, ws_client=MagicMock(),
                                   notifications_manager=MagicMock(), tags_manager=MagicMock())
    products._update_search_index = lambda *a, **k: None
    with patch('src.common.workflow_triggers.get_trigger_registry', return_value=MagicMock()):
        yield products


def _product(db, status='active', ports=('a', 'b')):
    row = DataProductDb(
        id=str(uuid.uuid4()), api_version='v1.0.0', kind='DataProduct', name='Orders',
        version='1.0.0', status=status, draft_owner_id=OWNER,
    )
    for name in ports:
        row.output_ports.append(OutputPortDb(
            id=f'{name}-{row.id}', name=name, version='1', contract_id=f'c-{name}',
        ))
    db.add(row)
    db.commit()
    return row


def _keep_first(row):
    first = row.output_ports[0]
    return {'outputPorts': [
        {'id': first.id, 'name': first.name, 'version': '1', 'contractId': first.contract_id}
    ]}


def test_update_product_refuses_removing_an_output_port_of_an_active_product(
    manager, db_session
):
    row = _product(db_session)

    with pytest.raises(VersioningRequiredError) as err:
        manager.update_product(row.id, _keep_first(row), db=db_session, user=OWNER)

    assert err.value.user_can_override is False
    assert any('b' in c for c in err.value.change_analysis['breaking_changes'])
    db_session.refresh(row)
    assert len(row.output_ports) == 2


def test_an_admin_is_told_the_edit_can_be_forced(manager, db_session):
    row = _product(db_session)

    with pytest.raises(VersioningRequiredError) as err:
        manager.update_product(
            row.id, _keep_first(row), db=db_session, user=OWNER, user_is_admin=True
        )

    assert err.value.user_can_override is True


def test_force_update_applies_the_edit(manager, db_session):
    row = _product(db_session)

    manager.update_product(row.id, _keep_first(row), db=db_session, user=OWNER, force_update=True)

    db_session.refresh(row)
    assert len(row.output_ports) == 1


def test_a_draft_may_remove_ports(manager, db_session):
    row = _product(db_session, status='draft')

    manager.update_product(row.id, _keep_first(row), db=db_session, user=OWNER)

    db_session.refresh(row)
    assert len(row.output_ports) == 1


def test_a_refused_caller_gets_a_permission_error_not_the_versioning_error(
    manager, db_session
):
    row = _product(db_session)

    with pytest.raises(PermissionError):
        manager.update_product_with_auth(
            row.id, _keep_first(row), 'carl@example.com', [], db=db_session
        )
