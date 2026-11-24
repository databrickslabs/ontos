"""``TagsManager.add_tag_to_entity`` / ``remove_tag_from_entity`` with ``commit=False``.

A workflow tag step calls them inside a savepoint with ``commit=False``: the change
(and its change-log row) is only flushed, so it is visible in the session but a
rollback of the outer transaction removes it. With ``commit=True`` (the default) it
is committed. Runs the real manager and repositories on a file SQLite database, read
back from a second connection, so committed and uncommitted rows differ.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from src.common.database import Base
from src.controller.tags_manager import TagsManager
from src.db_models.change_log import ChangeLogDb
from src.db_models.tags import EntityTagAssociationDb
from src.repositories.tags_repository import seed_default_tags

ENTITY = dict(entity_id='t-1', entity_type='table')


@pytest.fixture
def sessions(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tags.db'}")

    # As in conftest: let SQLAlchemy emit BEGIN, so savepoints nest in it
    @event.listens_for(engine, 'connect')
    def _no_implicit_begin(dbapi_connection, _record):
        dbapi_connection.isolation_level = None

    @event.listens_for(engine, 'begin')
    def _begin(connection):
        connection.exec_driver_sql('BEGIN')

    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    db, other = factory(), factory()
    try:
        tag = seed_default_tags(db)[0]
        db.commit()
        yield db, other, tag.id
    finally:
        db.close()
        other.close()
        engine.dispose()


def _state(session, action, end_read=False):
    """(assignments of t-1, change-log rows of ``action``) as ``session`` sees them.

    ``end_read`` ends the reader's transaction (the second connection), so the writer
    can commit later; never on the writer, whose open transaction is under test."""
    session.expire_all()
    assigned = session.query(EntityTagAssociationDb).filter_by(**ENTITY).count()
    logged = session.query(ChangeLogDb).filter_by(entity_id='t-1', action=action).count()
    if end_read:
        session.rollback()
    return assigned, logged


def _add(db, tag_id, commit):
    TagsManager().add_tag_to_entity(
        db, **ENTITY, tag_id=tag_id, assigned_value=None, user_email='pat@example.com',
        commit=commit,
    )


def _remove(db, tag_id, commit):
    return TagsManager().remove_tag_from_entity(
        db, **ENTITY, tag_id=tag_id, user_email='pat@example.com', commit=commit,
    )


def test_add_without_commit_is_flushed_and_rolled_back_with_the_transaction(sessions):
    db, other, tag_id = sessions
    with db.begin_nested():
        _add(db, tag_id, commit=False)

    assert _state(db, 'TAG_ASSIGN') == (1, 1)  # flushed: the session sees it
    assert _state(other, 'TAG_ASSIGN', end_read=True) == (0, 0)  # not committed
    db.rollback()
    assert _state(db, 'TAG_ASSIGN') == (0, 0)  # gone, change-log row included


def test_add_with_commit_is_committed(sessions):
    db, other, tag_id = sessions
    _add(db, tag_id, commit=True)

    db.rollback()
    assert _state(other, 'TAG_ASSIGN', end_read=True) == (1, 1)


def test_remove_without_commit_is_flushed_and_rolled_back_with_the_transaction(sessions):
    db, other, tag_id = sessions
    _add(db, tag_id, commit=True)
    with db.begin_nested():
        assert _remove(db, tag_id, commit=False) is True

    assert _state(db, 'TAG_REMOVE') == (0, 1)  # flushed: removed in the session
    assert _state(other, 'TAG_REMOVE', end_read=True) == (1, 0)  # not committed
    db.rollback()
    assert _state(db, 'TAG_REMOVE') == (1, 0)  # assignment back, no change-log row


def test_remove_with_commit_is_committed(sessions):
    db, other, tag_id = sessions
    _add(db, tag_id, commit=True)
    assert _remove(db, tag_id, commit=True) is True

    db.rollback()
    assert _state(other, 'TAG_REMOVE', end_read=True) == (0, 1)
