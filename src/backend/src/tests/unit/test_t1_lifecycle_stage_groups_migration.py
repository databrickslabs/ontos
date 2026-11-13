"""Test the t1 migration (Lifecycle Stage Groups) through Alembic, on SQLite.

The upgrade seeds one default group per entity type with the old transition
maps and assigns every product, contract and asset to its type's default; the
downgrade drops the column and the tables. (Also run on Postgres before
merging: ``alembic upgrade head`` / ``downgrade -1``.)
"""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from src.common.lifecycle_defaults import DEFAULT_GROUP_IDS, default_transitions

_NAME = 't1_lifecycle_stage_groups'


@pytest.fixture
def migration():
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{_NAME}.py'
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _apply(conn, step):
    with Operations.context(MigrationContext.configure(conn)):
        step()


def test_upgrade_seeds_and_backfills_and_downgrade_removes_everything(tmp_path, migration):
    assert migration.down_revision == 'r2_canonical_relationship_types'
    engine = create_engine(f"sqlite:///{tmp_path / 't1.db'}")
    with engine.begin() as conn:
        for table in ('data_products', 'data_contracts', 'assets'):
            conn.execute(text(f"CREATE TABLE {table} (id VARCHAR PRIMARY KEY, status VARCHAR)"))
        conn.execute(text("INSERT INTO data_products VALUES ('p1', 'sandbox'), ('p2', 'active')"))
        conn.execute(text("INSERT INTO data_contracts VALUES ('c1', 'under_review')"))
        conn.execute(text("INSERT INTO assets VALUES ('a1', 'deprecated')"))

        _apply(conn, migration.upgrade)

        groups = conn.execute(text(
            "SELECT entity_type, id, is_default_for_type FROM lifecycle_stage_groups"
        )).all()
        assert {(t, i, bool(d)) for t, i, d in groups} == {
            (t, i, True) for t, i in DEFAULT_GROUP_IDS.items()
        }
        for entity_type, group_id in DEFAULT_GROUP_IDS.items():
            stages = conn.execute(text(
                'SELECT id, key, category, is_initial FROM lifecycle_stages '
                'WHERE group_id = :g ORDER BY "order"'
            ), {'g': group_id}).all()
            keys = {sid: key for sid, key, _c, _i in stages}
            assert [k for _s, k, _c, _i in stages] == list(default_transitions(entity_type))
            assert [k for _s, k, _c, initial in stages if initial] == ['draft']
            moves = conn.execute(text(
                'SELECT from_stage_id, to_stage_id FROM lifecycle_stage_transitions '
                'WHERE group_id = :g'
            ), {'g': group_id}).all()
            got = {}
            for src, dst in moves:
                got.setdefault(keys[src], set()).add(keys[dst])
            expected = {k: set(v) for k, v in default_transitions(entity_type).items() if v}
            assert got == expected
        categories = dict(conn.execute(text(
            "SELECT key, category FROM lifecycle_stages WHERE group_id = :g"
        ), {'g': DEFAULT_GROUP_IDS['data_product']}).all())
        assert categories['sandbox'] == 'draft'
        assert {categories[k] for k in ('proposed', 'under_review', 'approved')} == {'review'}

        for table, entity_type in (('data_products', 'data_product'),
                                   ('data_contracts', 'data_contract'), ('assets', 'asset')):
            assigned = {g for (g,) in conn.execute(text(
                f"SELECT lifecycle_stage_group_id FROM {table}"
            )).all()}
            assert assigned == {DEFAULT_GROUP_IDS[entity_type]}
        # Statuses are untouched: they are the stage keys
        assert dict(conn.execute(text("SELECT id, status FROM data_products")).all()) == {
            'p1': 'sandbox', 'p2': 'active',
        }

        _apply(conn, migration.downgrade)

        inspector = sa.inspect(conn)
        tables = set(inspector.get_table_names())
        assert not tables & {
            'lifecycle_stage_groups', 'lifecycle_stages', 'lifecycle_stage_transitions',
        }
        for table in ('data_products', 'data_contracts', 'assets'):
            assert 'lifecycle_stage_group_id' not in {
                c['name'] for c in inspector.get_columns(table)
            }
        assert conn.execute(text("SELECT status FROM data_contracts")).scalar() == 'under_review'
