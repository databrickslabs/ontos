"""Deleting document files from the volume is best effort (#1343)."""
from unittest.mock import MagicMock

from src.controller import metadata_manager as metadata_module
from src.controller.metadata_manager import MetadataManager


def test_counts_deleted_and_failed_files_without_raising():
    ws = MagicMock()
    ws.files.delete.side_effect = [None, RuntimeError('gone'), None]

    result = MetadataManager().delete_document_files(ws, ['/a', '/b', '', '/c'])

    assert result == (2, 1)
    assert [c.args[0] for c in ws.files.delete.call_args_list] == ['/a', '/b', '/c']


def test_uses_the_app_client_and_counts_every_file_as_failed_without_one(monkeypatch):
    def no_client():
        raise RuntimeError('workspace unreachable')

    monkeypatch.setattr(metadata_module, 'get_workspace_client', no_client)

    assert MetadataManager().delete_document_files(None, ['/a', '/b']) == (0, 2)


def test_no_files_needs_no_client(monkeypatch):
    monkeypatch.setattr(
        metadata_module, 'get_workspace_client', MagicMock(side_effect=AssertionError),
    )

    assert MetadataManager().delete_document_files(None, []) == (0, 0)
