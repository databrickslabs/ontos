"""The o4 migration (delivery_outbox, #1688) through Alembic: retry-safe, reversible."""
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine

from src.common.database import Base
from src.db_models.delivery_outbox import DeliveryOutboxDb

_NAME = 't2_delivery_outbox'
_INDEXES = {'ix_delivery_outbox_status_next_attempt', 'ix_delivery_outbox_entity'}


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


def _state(conn):
    inspector = sa.inspect(conn)
    if 'delivery_outbox' not in inspector.get_table_names():
        return None
    columns = {c['name'] for c in inspector.get_columns('delivery_outbox')}
    indexes = {i['name'] for i in inspector.get_indexes('delivery_outbox')}
    return columns, indexes


def test_it_revises_the_development_head(migration):
    assert migration.revision == _NAME
    assert migration.down_revision == 't1_contract_tag_backfill'


def test_upgrade_twice_downgrade_and_upgrade_again(tmp_path, migration):
    engine = create_engine(f"sqlite:///{tmp_path / 'o4.db'}")
    model_columns = {c.name for c in DeliveryOutboxDb.__table__.columns}
    with engine.begin() as conn:
        _apply(conn, migration.upgrade)
        columns, indexes = _state(conn)
        assert columns == model_columns
        assert indexes == _INDEXES

        _apply(conn, migration.upgrade)  # a retried upgrade
        assert _state(conn) == (columns, indexes)

        _apply(conn, migration.downgrade)
        assert _state(conn) is None
        _apply(conn, migration.downgrade)  # nothing left to drop

        _apply(conn, migration.upgrade)
        assert _state(conn) == (columns, indexes)
    engine.dispose()


def test_upgrade_keeps_a_table_create_all_made(tmp_path, migration):
    engine = create_engine(f"sqlite:///{tmp_path / 'o4.db'}")
    Base.metadata.create_all(engine, tables=[DeliveryOutboxDb.__table__])
    with engine.begin() as conn:
        before = _state(conn)
        _apply(conn, migration.upgrade)
        assert _state(conn) == before
        assert before[1] == _INDEXES
    engine.dispose()
