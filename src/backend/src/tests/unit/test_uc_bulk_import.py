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

import asyncio
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from src.common.database import Base
from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.models.data_products import OutputPort
from src.routes.data_contracts_routes import get_contract

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


def _stats(**counts):
    return {'created': 0, 'updated': 0, 'unchanged': 0, 'skipped': 0, 'errors': 0, **counts}


def _count(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()


def test_an_imported_product_is_readable_through_the_manager(engine):
    assert _import(engine) == _stats(created=1)

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

    assert _import(engine) == _stats(skipped=1)
    assert _count(engine, 'data_products') == 1
    assert _count(engine, 'data_product_output_ports') == len(_TABLES)


def test_a_failed_port_insert_leaves_no_half_imported_product(engine):
    with engine.begin() as conn:
        conn.execute(text('DROP TABLE data_product_output_ports'))

    assert _import(engine) == _stats(errors=1)
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
    assert stats == _stats(created=1)

    [contract_id] = _contract_ids(engine)
    with Session(engine) as db:
        # The handler of GET /api/data-contracts/{id}, called without the HTTP layer
        contract = asyncio.run(get_contract(
            contract_id, db, DataContractsManager(data_dir=Path('/tmp')), True, None))

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
    assert stats == _stats(errors=1)
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


def _port_contracts(engine):
    with engine.connect() as conn:
        return dict(conn.execute(text(
            'SELECT asset_identifier, contract_id FROM data_product_output_ports')).all())


def test_linking_keeps_a_contract_the_user_linked_to_the_port(engine):
    _, contracts = _import_contract(engine)
    _import(engine)
    with engine.begin() as conn:
        conn.execute(text("UPDATE data_product_output_ports SET contract_id = 'chosen-by-user'"))

    discovered = {'product': _discovered(), 'contract': contracts}
    assert job.link_products_to_contracts(engine, discovered) == 0
    assert set(_port_contracts(engine).values()) == {'chosen-by-user'}


def test_linking_uses_the_newest_version_of_the_contract(engine):
    _, contracts = _import_contract(engine)
    _import(engine)
    _add_newer_draft(engine, 'data_contracts', 'orders')

    discovered = {'product': _discovered(), 'contract': contracts}
    assert job.link_products_to_contracts(engine, discovered) == 1
    assert _port_contracts(engine) == {_TABLES[0]: 'newer', _TABLES[1]: None}


def _port_assets(engine):
    with engine.connect() as conn:
        return sorted(conn.execute(text(
            'SELECT asset_identifier FROM data_product_output_ports')).scalars())


def test_update_adds_the_new_ports_to_the_existing_product(engine):
    _import(engine, tables=_TABLES[:1])
    with engine.connect() as conn:
        [product_id] = conn.execute(text('SELECT id FROM data_products')).scalars().all()

    assert _import(engine, 'update') == _stats(updated=1)
    # The second run has nothing new to add
    assert _import(engine, 'update') == _stats(unchanged=1)

    with engine.connect() as conn:
        assert conn.execute(text('SELECT id FROM data_products')).scalars().all() == [product_id]
    assert _port_assets(engine) == sorted(_TABLES)


def _updated_at(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(f'SELECT updated_at FROM {table}')).scalar()


def test_update_changes_updated_at_only_when_it_adds_a_port(engine):
    _import(engine, tables=_TABLES[:1])
    created = _updated_at(engine, 'data_products')

    assert _import(engine, 'update', tables=_TABLES[:1]) == _stats(unchanged=1)
    assert _updated_at(engine, 'data_products') == created

    assert _import(engine, 'update') == _stats(updated=1)
    assert _updated_at(engine, 'data_products') > created


def test_update_changes_a_contracts_updated_at_only_when_it_adds_a_schema_object(engine):
    _import_contract(engine, tables=_TABLES[:1])
    created = _updated_at(engine, 'data_contracts')

    stats, _ = _import_contract(engine, tables=_TABLES[:1], strategy='update')
    assert stats == _stats(unchanged=1)
    assert _updated_at(engine, 'data_contracts') == created


def _delete(engine, sql):
    with engine.begin() as conn:
        conn.execute(text(sql), {'t': _TABLES[0]})


def test_a_port_deleted_in_the_app_is_not_added_back(engine):
    _import(engine)
    _delete(engine, 'DELETE FROM data_product_output_ports WHERE asset_identifier = :t')

    assert _import(engine, 'update') == _stats(unchanged=1)
    assert _port_assets(engine) == [_TABLES[1]]


def test_a_schema_object_deleted_in_the_app_is_not_added_back(engine):
    _import_contract(engine, tables=_TABLES)
    _delete(engine, 'DELETE FROM data_contract_schema_objects WHERE physical_name = :t')

    stats, _ = _import_contract(engine, tables=_TABLES, strategy='update')
    assert stats == _stats(unchanged=1)
    with engine.connect() as conn:
        assert conn.execute(text(
            'SELECT physical_name FROM data_contract_schema_objects')).scalars().all() == \
            [_TABLES[1]]


def test_a_product_imported_before_the_job_recorded_its_tables(engine):
    # Imported by an earlier job version: ports exist, nothing is recorded
    _import(engine)
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM uc_bulk_import_sources'))

    # The first update run records the ports it finds instead of adding them twice
    assert _import(engine, 'update') == _stats(unchanged=1)
    assert _port_assets(engine) == sorted(_TABLES)

    # From then on a deleted port stays deleted
    _delete(engine, 'DELETE FROM data_product_output_ports WHERE asset_identifier = :t')
    assert _import(engine, 'update') == _stats(unchanged=1)
    assert _port_assets(engine) == [_TABLES[1]]


def test_a_new_version_shares_what_was_imported_into_its_family(engine):
    _import(engine)
    with engine.begin() as conn:
        old_id, family = conn.execute(text(
            'SELECT id, version_family_id FROM data_products')).one()
        # A new draft version of the product: copied without the first table's port
        conn.execute(text(
            "INSERT INTO data_products (id, api_version, kind, status, name, version, "
            "max_level_inheritance, version_family_id, published, publication_scope, "
            "created_at, updated_at) SELECT 'v2', api_version, kind, 'draft', name, '2.0.0', "
            "max_level_inheritance, version_family_id, published, publication_scope, "
            ":later, :later FROM data_products WHERE id = :id"
        ), {'id': old_id, 'later': datetime(2999, 1, 1)})
        conn.execute(text(
            "INSERT INTO data_product_output_ports (id, product_id, name, version, asset_type, "
            "asset_identifier, contains_pii, auto_approve) VALUES "
            "('p2', 'v2', 'customers', '1.0.0', 'table', :t, 0, 0)"
        ), {'t': _TABLES[1]})

    assert _import(engine, 'update') == _stats(unchanged=1)
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT asset_identifier FROM data_product_output_ports WHERE product_id = 'v2'"
        )).scalars().all() == [_TABLES[1]]
    assert family == old_id


def test_a_product_deleted_in_the_app_is_imported_again_in_full(engine):
    _import(engine)
    with engine.begin() as conn:
        conn.execute(text('DELETE FROM data_product_output_ports'))
        conn.execute(text('DELETE FROM data_products'))

    # A new product is a new version family: nothing recorded for it yet
    assert _import(engine, 'update') == _stats(created=1)
    assert _port_assets(engine) == sorted(_TABLES)


def _add_newer_draft(engine, table, name, owner=None):
    """A newer row with the same name, as a new version of the entity has (a
    personal draft of ``owner``, when given)."""
    columns = {
        'data_products': "id, api_version, kind, status, name, version, max_level_inheritance, "
                         "version_family_id, published, publication_scope, created_at, "
                         "updated_at, draft_owner_id",
        'data_contracts': "id, kind, api_version, status, name, version, version_family_id, "
                          "published, publication_scope, created_at, updated_at, "
                          "draft_owner_id",
    }[table]
    values = {
        'data_products': "'newer', 'v1.0.0', 'DataProduct', 'draft', :n, '2.0.0', 99, "
                         "'newer', 0, 'none', :t, :t, :o",
        'data_contracts': "'newer', 'DataContract', 'v3.1.0', 'draft', :n, '2.0.0', 'newer', "
                          "0, 'none', :t, :t, :o",
    }[table]
    with engine.begin() as conn:
        conn.execute(text(f'INSERT INTO {table} ({columns}) VALUES ({values})'),
                     {'n': name, 't': datetime(2999, 1, 1), 'o': owner})


def test_update_adds_ports_to_the_newest_version_of_the_product(engine):
    _import(engine, tables=_TABLES[:1])
    _add_newer_draft(engine, 'data_products', 'sales')

    assert _import(engine, 'update') == _stats(updated=1)
    with engine.connect() as conn:
        rows = conn.execute(text(
            'SELECT product_id, asset_identifier FROM data_product_output_ports '
            'ORDER BY asset_identifier')).all()
    newer = [a for p, a in rows if p == 'newer']
    assert newer == sorted(_TABLES)
    assert len(rows) == 3  # the older version keeps its one port


def test_update_adds_schema_objects_to_the_newest_version_of_the_contract(engine):
    _import_contract(engine, tables=_TABLES[:1])
    _add_newer_draft(engine, 'data_contracts', 'orders')

    stats, _ = _import_contract(engine, tables=_TABLES, strategy='update')
    assert stats == _stats(updated=1)
    with engine.connect() as conn:
        assert sorted(conn.execute(text(
            "SELECT physical_name FROM data_contract_schema_objects "
            "WHERE contract_id = 'newer'")).scalars()) == sorted(_TABLES)


def _set_status(engine, table, status):
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE {table} SET status = :s"), {'s': status})


@pytest.mark.parametrize('status', ['active', 'deprecated', 'retired'])
def test_update_leaves_a_product_past_draft_alone(engine, status):
    _import(engine, tables=_TABLES[:1])
    _set_status(engine, 'data_products', status)
    with engine.connect() as conn:
        before = conn.execute(text('SELECT updated_at FROM data_products')).scalar()

    # Ports a user deleted in the app must not come back, new ones must not appear
    assert _import(engine, 'update') == _stats(skipped=1)

    assert _port_assets(engine) == _TABLES[:1]
    with engine.connect() as conn:
        assert conn.execute(text('SELECT updated_at FROM data_products')).scalar() == before


@pytest.mark.parametrize('status', ['active', 'deprecated', 'retired'])
def test_update_leaves_a_contract_past_draft_alone(engine, status):
    _import_contract(engine, tables=_TABLES[:1])
    _set_status(engine, 'data_contracts', status)

    stats, _ = _import_contract(engine, tables=_TABLES, strategy='update')

    assert stats == _stats(skipped=1)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM data_contract_schema_objects')).scalar() == 1


def test_linking_leaves_the_ports_of_a_product_past_draft_alone(engine):
    _, contracts = _import_contract(engine)
    _import(engine)
    _set_status(engine, 'data_products', 'active')

    discovered = {'product': _discovered(), 'contract': contracts}
    assert job.link_products_to_contracts(engine, discovered) == 0
    with engine.connect() as conn:
        linked = conn.execute(text(
            'SELECT COUNT(*) FROM data_product_output_ports WHERE contract_id IS NOT NULL'
        )).scalar()
    assert linked == 0


def test_update_adds_the_new_schema_objects_to_the_existing_contract(engine):
    _import_contract(engine, tables=_TABLES[:1])
    [contract_id] = _contract_ids(engine)

    for expected in (_stats(updated=1), _stats(unchanged=1)):
        stats, _ = _import_contract(engine, tables=_TABLES, strategy='update')
        assert stats == expected

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
        _stats(created=1)
    with engine.connect() as conn:
        [(domain_id, before)] = conn.execute(text('SELECT id, updated_at FROM data_domains')).all()

    # Inserting again failed on the unique domain name. The job sets nothing on
    # a domain beyond its name, so there is nothing to change (not even updated_at)
    assert job.create_domains(engine, domains, 'update', created_by='job') == \
        _stats(unchanged=1)
    with engine.connect() as conn:
        assert conn.execute(text('SELECT id, updated_at FROM data_domains')).all() == \
            [(domain_id, before)]


def test_a_stored_port_with_null_booleans_still_reads(engine):
    # Both columns are nullable, so a row written by any raw-SQL writer can hold NULL
    _import(engine, tables=_TABLES[:1])
    with engine.begin() as conn:
        conn.execute(text('UPDATE data_product_output_ports SET contains_pii = NULL, '
                          'auto_approve = NULL'))
        stored = conn.execute(text('SELECT contains_pii, auto_approve '
                                   'FROM data_product_output_ports')).one()
    assert tuple(stored) == (None, None)

    with Session(engine) as db:
        manager = DataProductsManager(db=db)
        product = manager.get_product(manager.list_products(is_admin=True)[0].id)

    [port] = product.outputPorts
    assert (port.containsPii, port.autoApprove) == (False, False)


def test_an_imported_product_is_visible_to_admins_only(engine):
    # The job sets no draft_owner_id, owner_team_id or project_id (documented)
    _import(engine)

    with Session(engine) as db:
        manager = DataProductsManager(db=db)
        assert len(manager.list_products(is_admin=True)) == 1
        assert manager.list_products(
            is_admin=False, caller_email='analyst@example.com',
            caller_team_ids=[], caller_project_ids=[]) == []


def test_an_imported_contract_is_visible_to_admins_only(engine):
    # Like products: no owner team, project or draft owner is set
    _import_contract(engine)
    manager = DataContractsManager(data_dir=Path('/tmp'))

    with Session(engine) as db:
        assert [c.name for c in manager.list_contracts_from_db(db, is_admin=True)] == ['orders']
        assert manager.list_contracts_from_db(
            db, is_admin=False, caller_email='analyst@example.com', caller_team_ids=set()) == []


def _inserted_columns(engine, run):
    """Columns of each table the job inserts into while ``run`` executes."""
    columns = {}

    def capture(conn, cursor, statement, parameters, context, executemany):
        match = re.match(r'\s*INSERT INTO (\w+) \(([^)]*)\)', statement)
        if match:
            columns.setdefault(match.group(1), set()).update(
                c.strip() for c in match.group(2).split(','))

    event.listen(engine, 'before_cursor_execute', capture)
    run()
    event.remove(engine, 'before_cursor_execute', capture)
    return columns


def test_the_job_sets_every_not_null_column_the_models_require(engine):
    def run():
        _import(engine)
        _import_contract(engine)
        job.create_domains(engine, {'finance': [job.DiscoveredObject(
            'SCHEMA', 'main.finance', {'data_domain_finance': ''})]}, 'skip', created_by='job')

    inserted = _inserted_columns(engine, run)

    for table in ('data_products', 'data_product_output_ports',
                  'data_contracts', 'data_contract_schema_objects',
                  'data_domains', 'uc_bulk_import_sources'):
        required = {c.name for c in Base.metadata.tables[table].columns
                    if not c.nullable and c.server_default is None and not c.primary_key}
        assert required - inserted[table] == set(), table


def test_the_job_writes_timezone_aware_timestamps(engine):
    seen = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        values = parameters.values() if isinstance(parameters, dict) else parameters
        seen.extend(v for v in values if isinstance(v, datetime))

    event.listen(engine, 'before_cursor_execute', capture)
    _import(engine)
    _import_contract(engine)
    job.create_domains(engine, {'finance': [job.DiscoveredObject(
        'SCHEMA', 'main.finance', {'data_domain_finance': ''})]}, 'skip', created_by='job')
    event.remove(engine, 'before_cursor_execute', capture)

    assert seen and all(v.tzinfo is not None for v in seen)


def _postgres_engine(lock_free):
    conn = MagicMock()
    conn.execute.return_value.scalar.return_value = lock_free
    engine = MagicMock()
    engine.dialect.name = 'postgresql'
    engine.connect.return_value.execution_options.return_value = conn
    return engine, conn


def _statements(conn):
    return [str(call.args[0]) for call in conn.execute.call_args_list]


def test_a_run_holds_the_advisory_lock_and_releases_it():
    engine, conn = _postgres_engine(lock_free=True)

    with job.single_flight(engine) as acquired:
        assert acquired is True
        assert [s for s in _statements(conn) if 'unlock' in s] == []

    assert 'pg_try_advisory_lock' in _statements(conn)[0]
    assert 'pg_advisory_unlock' in _statements(conn)[-1]
    conn.close.assert_called_once()
    # Autocommit: the lock connection is not left idle in a transaction
    engine.connect.return_value.execution_options.assert_called_once_with(
        isolation_level='AUTOCOMMIT')


def test_an_overlapping_run_does_not_get_the_lock():
    engine, conn = _postgres_engine(lock_free=False)

    with job.single_flight(engine) as acquired:
        assert acquired is False

    assert all('unlock' not in s for s in _statements(conn))
    conn.close.assert_called_once()


def test_databases_without_advisory_locks_always_run(engine):
    with job.single_flight(engine) as acquired:
        assert acquired is True


def test_a_run_refused_by_the_lock_fails_with_its_own_exit_code():
    @contextmanager
    def lock_held(_engine):
        yield False

    argv = ['uc_bulk_import.py', '--entity_patterns', '[]', '--lakebase_instance_name', 'x',
            '--postgres_host', 'h', '--postgres_db', 'd']
    with patch.object(sys, 'argv', argv), patch.object(job, 'WorkspaceClient'), \
            patch.object(job, 'create_engine_from_params'), \
            patch.object(job, 'single_flight', lock_held), \
            patch.object(job, 'run_import') as run_import:
        with pytest.raises(SystemExit) as exited:
            job.main()

    # Not 0 (a scheduler would show the skipped run green), not 1 (errors)
    assert exited.value.code == job.LOCK_HELD_EXIT_CODE == 3
    run_import.assert_not_called()


def _personal_draft_state(engine, table):
    with engine.connect() as conn:
        return conn.execute(text(
            f"SELECT id, status, draft_owner_id FROM {table} WHERE draft_owner_id = 'alice'"
        )).all()


def test_update_leaves_a_users_personal_draft_of_a_product_alone(engine):
    _import(engine, tables=_TABLES[:1])
    _set_status(engine, 'data_products', 'active')
    _add_newer_draft(engine, 'data_products', 'sales', owner='alice')

    # The shared row is active (skipped); alice's newer draft is not the match
    assert _import(engine, 'update') == _stats(skipped=1)

    assert _port_assets(engine) == _TABLES[:1]
    assert _personal_draft_state(engine, 'data_products') == [('newer', 'draft', 'alice')]


def test_update_leaves_a_users_personal_draft_of_a_contract_alone(engine):
    _import_contract(engine, tables=_TABLES[:1])
    _set_status(engine, 'data_contracts', 'active')
    _add_newer_draft(engine, 'data_contracts', 'orders', owner='alice')

    stats, _ = _import_contract(engine, tables=_TABLES, strategy='update')

    assert stats == _stats(skipped=1)
    assert _personal_draft_state(engine, 'data_contracts') == [('newer', 'draft', 'alice')]
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM data_contract_schema_objects WHERE contract_id = 'newer'"
        )).scalar() == 0


def test_linking_leaves_the_ports_of_a_personal_draft_alone(engine):
    _, contracts = _import_contract(engine)
    _import(engine, tables=_TABLES[:1])
    _set_status(engine, 'data_products', 'active')
    _add_newer_draft(engine, 'data_products', 'sales', owner='alice')
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO data_product_output_ports "
            "(id, product_id, name, version, asset_identifier) "
            "VALUES ('p1', 'newer', 'orders', '1.0.0', :a)"), {'a': _TABLES[0]})

    discovered = {'product': _discovered(tables=_TABLES[:1]), 'contract': contracts}
    assert job.link_products_to_contracts(engine, discovered) == 0
    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT contract_id FROM data_product_output_ports WHERE id = 'p1'")).scalar() is None


def test_update_adds_nothing_to_a_personal_draft_when_it_is_the_only_row_with_the_name(engine):
    # The ports live on the shared row only; the personal draft stays at its own ports
    _import(engine, tables=_TABLES[:1])
    _add_newer_draft(engine, 'data_products', 'sales', owner='alice')

    assert _import(engine, 'update') == _stats(updated=1)

    with engine.connect() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM data_product_output_ports WHERE product_id = 'newer'"
        )).scalar() == 0


def _dead_connection(engine, conn):
    from sqlalchemy.exc import OperationalError

    def execute(statement, *_args, **_kwargs):
        if 'pg_advisory_unlock' in str(statement):
            raise OperationalError('SELECT pg_advisory_unlock', {}, Exception('server closed'))
        return MagicMock(scalar=MagicMock(return_value=True))

    conn.execute.side_effect = execute


def test_a_lock_connection_that_died_does_not_mask_a_successful_run(capsys):
    engine, conn = _postgres_engine(lock_free=True)
    _dead_connection(engine, conn)

    with job.single_flight(engine) as acquired:
        assert acquired is True

    assert 'lock was lost' in capsys.readouterr().out
    conn.close.assert_called_once()


@pytest.mark.parametrize('code', [1, 3])
def test_a_lock_connection_that_died_keeps_the_exit_code_of_the_run(code, capsys):
    engine, conn = _postgres_engine(lock_free=True)
    _dead_connection(engine, conn)

    with pytest.raises(SystemExit) as exited:
        with job.single_flight(engine):
            sys.exit(code)

    assert exited.value.code == code
    assert 'lock was lost' in capsys.readouterr().out
