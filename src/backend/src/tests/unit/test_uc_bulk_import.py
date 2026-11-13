"""UC Bulk Import creates Data Products and Contracts the app can read (#931, #932).

The job writes products and output ports with raw SQL, so the ORM defaults
don't apply. On a fresh database (tables from the ORM, no server defaults)
the product insert failed on the NOT NULL columns it left out
(max_level_inheritance, version_family_id, published, publication_scope), the
port insert targeted the pre-rename ``output_ports`` table, and ports were
written without the contains_pii / auto_approve booleans the API model needs.
The contract insert left out published, version_family_id and
publication_scope the same way.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from src.common.database import Base
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.models.data_products import OutputPort
from src.repositories.data_contracts_repository import data_contract_repo

# pyspark only exists on the job cluster; the functions under test don't use it.
_pyspark_sql = ModuleType('pyspark.sql')
_pyspark_sql.SparkSession = MagicMock()
with patch.dict(sys.modules, {'pyspark': ModuleType('pyspark'), 'pyspark.sql': _pyspark_sql}):
    import src.workflows.uc_bulk_import.uc_bulk_import as job

_TABLES = ['main.sales.orders', 'main.sales.customers']


@pytest.fixture
def engine(tmp_path):
    # A fresh install builds its tables with create_all(): no server defaults.
    engine = create_engine(f"sqlite:///{tmp_path / 'bulk_import.db'}")
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


def _discovered(name='sales', tables=_TABLES):
    return {name: [job.DiscoveredObject('TABLE', t, {f'data_product_{name}': ''}) for t in tables]}


def _import(engine, strategy='skip', tables=_TABLES):
    return job.create_products(engine, _discovered(tables=tables), strategy, None, None)


def _count(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()


def test_an_imported_product_is_readable_through_the_manager(engine):
    assert _import(engine) == {'created': 1, 'updated': 0, 'skipped': 0, 'errors': 0}

    with Session(engine) as db:
        products = DataProductsManager(db=db).list_products(is_admin=True)
        assert [p.name for p in products] == ['sales']
        product = DataProductsManager(db=db).get_product(products[0].id)

    assert product.status == 'draft'
    assert product.max_level_inheritance == 99
    assert product.version_family_id == product.id
    assert product.publication_scope == 'none'
    assert sorted(p.assetIdentifier for p in product.outputPorts) == sorted(_TABLES)
    assert all(p.containsPii is False and p.autoApprove is False for p in product.outputPorts)


def test_a_rerun_skips_the_product(engine):
    _import(engine)

    assert _import(engine) == {'created': 0, 'updated': 0, 'skipped': 1, 'errors': 0}
    assert _count(engine, 'data_products') == 1
    assert _count(engine, 'data_product_output_ports') == len(_TABLES)


def test_a_failed_port_insert_leaves_no_half_imported_product(engine):
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE data_product_output_ports'))

    assert _import(engine) == {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 1}
    # A product without its ports would be skipped by every later run
    assert _count(engine, 'data_products') == 0


def _import_contract(engine, name='orders', tables=_TABLES[:1], strategy='skip'):
    tag = {f'data_contract_{name}': ''}
    objects = {name: [job.DiscoveredObject('TABLE', t, tag) for t in tables]}
    return job.create_contracts(engine, objects, strategy, None, None), objects


def _contract_ids(engine, name='orders'):
    with engine.connect() as conn:
        sql = text('SELECT id FROM data_contracts WHERE name = :n')
        return conn.execute(sql, {'n': name}).scalars().all()


def test_an_imported_contract_is_readable_through_the_manager(engine):
    stats, _ = _import_contract(engine)
    assert stats == {'created': 1, 'updated': 0, 'skipped': 0, 'errors': 0}

    [contract_id] = _contract_ids(engine)
    with Session(engine) as db:
        contract = DataContractsManager(data_dir=Path('/tmp'))._build_contract_api_model(
            db, data_contract_repo.get_with_all(db, id=contract_id))

    assert contract.status == 'draft'
    assert [(s.name, s.physicalName) for s in contract.contract_schema] == [('orders', _TABLES[0])]
    with engine.connect() as conn:
        row = conn.execute(text(
            'SELECT version_family_id, published, publication_scope FROM data_contracts'
        )).one()
    assert tuple(row) == (contract_id, False, 'none')


def test_a_failed_schema_insert_leaves_no_half_imported_contract(engine):
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE data_contract_schema_objects'))

    stats, _ = _import_contract(engine)
    assert stats == {'created': 0, 'updated': 0, 'skipped': 0, 'errors': 1}
    assert _contract_ids(engine) == []


def test_ports_are_linked_to_the_contract_tagged_on_the_same_table(engine):
    _, contracts = _import_contract(engine)
    _import(engine)
    discovered = {'product': _discovered(), 'contract': contracts}

    assert job.link_products_to_contracts(engine, discovered) == 1
    with Session(engine) as db:
        [product] = DataProductsManager(db=db).list_products(is_admin=True)
        product = DataProductsManager(db=db).get_product(product.id)
    [contract_id] = _contract_ids(engine)
    linked = {p.assetIdentifier: p.contractId for p in product.outputPorts}
    assert linked == {_TABLES[0]: contract_id, _TABLES[1]: None}


def _port_assets(engine):
    with engine.connect() as conn:
        return sorted(conn.execute(text(
            'SELECT asset_identifier FROM data_product_output_ports')).scalars())


def test_update_adds_the_new_ports_to_the_existing_product(engine):
    _import(engine, tables=_TABLES[:1])
    with engine.connect() as conn:
        [product_id] = conn.execute(text('SELECT id FROM data_products')).scalars().all()

    # Run twice: the second run has nothing new to add
    for _ in range(2):
        assert _import(engine, 'update') == {'created': 0, 'updated': 1, 'skipped': 0, 'errors': 0}

    with engine.connect() as conn:
        assert conn.execute(text('SELECT id FROM data_products')).scalars().all() == [product_id]
    assert _port_assets(engine) == sorted(_TABLES)


def test_update_adds_the_new_schema_objects_to_the_existing_contract(engine):
    _import_contract(engine, tables=_TABLES[:1])
    [contract_id] = _contract_ids(engine)

    for _ in range(2):
        stats, _ = _import_contract(engine, tables=_TABLES, strategy='update')
        assert stats == {'created': 0, 'updated': 1, 'skipped': 0, 'errors': 0}

    assert _contract_ids(engine) == [contract_id]
    with engine.connect() as conn:
        names = conn.execute(text(
            'SELECT physical_name FROM data_contract_schema_objects WHERE contract_id = :c'
        ), {'c': contract_id}).scalars().all()
    assert sorted(names) == sorted(_TABLES)


def test_update_keeps_the_existing_domain(engine):
    tag = {'data_domain_finance': ''}
    domains = {'finance': [job.DiscoveredObject('SCHEMA', 'main.finance', tag)]}
    assert job.create_domains(engine, domains, 'skip', created_by='job') == \
        {'created': 1, 'updated': 0, 'skipped': 0, 'errors': 0}
    with engine.connect() as conn:
        [domain_id] = conn.execute(text('SELECT id FROM data_domains')).scalars().all()

    # Inserting again failed on the unique domain name
    assert job.create_domains(engine, domains, 'update', created_by='job') == \
        {'created': 0, 'updated': 1, 'skipped': 0, 'errors': 0}
    with engine.connect() as conn:
        assert conn.execute(text('SELECT id FROM data_domains')).scalars().all() == [domain_id]


def test_a_stored_port_with_null_booleans_still_reads():
    # Rows written before the fix carry NULL in both columns
    port = OutputPort.model_validate({'name': 'orders', 'version': '1.0.0',
                                      'contains_pii': None, 'auto_approve': None})

    assert port.containsPii is False
    assert port.autoApprove is False
