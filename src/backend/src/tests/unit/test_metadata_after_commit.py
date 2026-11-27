"""Document files and search entries are only released when the outer transaction commits.

``after_commit`` also fires when a savepoint is released: a rollback of the
outer transaction afterwards must still keep the files and the index entries
of rows that come back.
"""
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from src.controller.metadata_manager import MetadataManager


@pytest.fixture
def committing_session(db_session):
    session = Session(bind=db_session.connection(), join_transaction_mode="create_savepoint")
    yield session
    session.close()


@pytest.fixture
def manager(monkeypatch):
    manager = MetadataManager()
    monkeypatch.setattr(manager, "remove_document_from_index", MagicMock())
    return manager


def _queue_in_released_savepoint(manager, session, ws):
    session.execute(text("SELECT 1"))
    with session.begin_nested():
        manager.delete_document_files_after_commit(session, ["/Volumes/c/s/v/f"], ws)
        manager.remove_documents_from_index_after_commit(session, ["doc-1"])


def test_a_released_savepoint_then_a_rollback_keeps_files_and_index_entries(
    manager, committing_session,
):
    ws = MagicMock()
    _queue_in_released_savepoint(manager, committing_session, ws)

    committing_session.rollback()
    committing_session.commit()

    ws.files.delete.assert_not_called()
    manager.remove_document_from_index.assert_not_called()


def test_a_released_savepoint_then_a_commit_releases_them_once(manager, committing_session):
    ws = MagicMock()
    _queue_in_released_savepoint(manager, committing_session, ws)
    ws.files.delete.assert_not_called()

    committing_session.commit()

    ws.files.delete.assert_called_once_with("/Volumes/c/s/v/f")
    manager.remove_document_from_index.assert_called_once_with("doc-1")


def test_a_rolled_back_savepoint_keeps_only_its_own(manager, committing_session):
    ws = MagicMock()
    committing_session.execute(text("SELECT 1"))
    manager.delete_document_files_after_commit(committing_session, ["/Volumes/c/s/v/outer"], ws)
    savepoint = committing_session.begin_nested()
    manager.delete_document_files_after_commit(committing_session, ["/Volumes/c/s/v/inner"], ws)
    manager.remove_documents_from_index_after_commit(committing_session, ["doc-inner"])
    savepoint.rollback()

    committing_session.commit()

    assert [c.args[0] for c in ws.files.delete.call_args_list] == ["/Volumes/c/s/v/outer"]
    manager.remove_document_from_index.assert_not_called()
