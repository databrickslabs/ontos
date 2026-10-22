"""An imported status Ontos doesn't have is imported as draft, with a note.

ODCS v3.x and ODPS v1.0.0 define ``status`` as free text, so a valid document
from another tool may say ``production``. Refusing it made the whole entity
fail; it is now imported as ``draft`` and its item in the import result says
so (code ``imported_status_mapped``). Older Ontos status names are mapped as
migration b5 maps them: ``archived`` to ``retired``, ``certified`` to
``active`` (certification, ``certification_level``, isn't imported).
"""
import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml
from sqlalchemy.orm import Session

from src.common.lifecycle_status import (
    CONTRACT_STATUSES,
    PRODUCT_STATUSES,
    import_status,
)
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb


@pytest.fixture
def product_manager(db_session: Session) -> DataProductsManager:
    return DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )


@pytest.fixture
def contract_manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path('/tmp'))
    mgr._update_search_index = lambda *a, **k: None
    return mgr


def _odps(name, status):
    return {
        'apiVersion': 'v1.0.0', 'kind': 'DataProduct', 'id': str(uuid.uuid4()),
        'name': name, 'version': '1.0.0', 'status': status,
        'productType': 'sourceAligned', 'owner': 'test@example.com',
    }


def _odcs(name, status):
    return {
        'apiVersion': 'v3.1.0', 'kind': 'DataContract', 'id': str(uuid.uuid4()),
        'name': name, 'version': '1.0.0', 'status': status,
    }


def test_import_status_keeps_lifecycle_statuses_and_maps_the_others():
    assert import_status('Proposed', CONTRACT_STATUSES) == ('proposed', None)
    assert import_status(None, CONTRACT_STATUSES) == ('draft', None)
    status, note = import_status('Production', CONTRACT_STATUSES)
    assert status == 'draft'
    assert note['code'] == 'imported_status_mapped'
    assert note['params'] == {'status': 'Production', 'mappedTo': 'draft'}
    assert "'Production' is not a lifecycle status" in note['message']


@pytest.mark.parametrize('statuses', [CONTRACT_STATUSES, PRODUCT_STATUSES])
def test_older_status_names_map_like_migration_b5(statuses):
    status, note = import_status('Archived', statuses)
    assert status == 'retired'
    assert note['code'] == 'imported_legacy_status'
    assert note['params'] == {'status': 'Archived', 'mappedTo': 'retired'}

    status, note = import_status('certified', statuses)
    assert status == 'active'
    assert note['code'] == 'imported_certified_as_active'
    assert note['params'] == {'status': 'certified', 'mappedTo': 'active'}
    assert "Certification isn't imported" in note['message']


def test_an_odps_product_with_an_unknown_status_imports_as_draft(product_manager, db_session):
    result = product_manager.create_products_from_files(
        files=[('p.json', json.dumps(_odps('Prod Status', 'production')).encode())],
        user='alice@example.com',
    )

    assert (result.created, result.failed) == (1, 0)
    item = result.items[0]
    assert item.code == 'imported_status_mapped'
    assert item.params == {'status': 'production', 'mappedTo': 'draft'}
    assert db_session.get(DataProductDb, result.created_ids[0]).status == 'draft'


def test_an_odcs_contract_with_an_unknown_status_imports_as_draft(contract_manager, db_session):
    result = contract_manager.create_contracts_from_files(
        db=db_session,
        files=[('c.yaml', yaml.safe_dump(_odcs('Prod Contract', 'in development')), 'application/x-yaml')],
        current_user='alice@example.com',
    )

    assert (result.created, result.failed) == (1, 0)
    item = result.items[0]
    assert item.code == 'imported_status_mapped'
    assert item.params == {'status': 'in development', 'mappedTo': 'draft'}
    assert db_session.get(DataContractDb, result.created_ids[0]).status == 'draft'


def test_a_lifecycle_status_imports_without_a_note(contract_manager, db_session):
    result = contract_manager.create_contracts_from_files(
        db=db_session,
        files=[('c.yaml', yaml.safe_dump(_odcs('Active Contract', 'active')), 'application/x-yaml')],
        current_user='alice@example.com',
    )

    assert result.items[0].code is None
    assert db_session.get(DataContractDb, result.created_ids[0]).status == 'active'


@pytest.mark.parametrize('kind', ['product', 'contract'])
@pytest.mark.parametrize('file_status, stored, code', [
    ('certified', 'active', 'imported_certified_as_active'),
    ('archived', 'retired', 'imported_legacy_status'),
])
def test_older_status_names_import_like_migration_b5(
    kind, file_status, stored, code, product_manager, contract_manager, db_session,
):
    if kind == 'product':
        result = product_manager.create_products_from_files(
            files=[('p.json', json.dumps(_odps(f'Legacy {file_status}', file_status)).encode())],
        )
        model = DataProductDb
    else:
        result = contract_manager.create_contracts_from_files(
            db=db_session,
            files=[('c.yaml', yaml.safe_dump(_odcs(f'Legacy {file_status}', file_status)), 'application/x-yaml')],
        )
        model = DataContractDb

    assert (result.created, result.failed) == (1, 0)
    item = result.items[0]
    assert item.code == code
    entity = db_session.get(model, result.created_ids[0])
    assert entity.status == stored
    # An import never certifies
    assert getattr(entity, 'certification_level', None) is None
