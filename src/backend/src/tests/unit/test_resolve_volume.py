"""DATABRICKS_VOLUME has one meaning everywhere (#950).

Databricks Apps injects the volume path (/Volumes/c/s/v), the bundle passes a
volume name, and metadata storage built "<catalog>.<schema>.<DATABRICKS_VOLUME>"
from it, i.e. "app_ontos.app_ontos./Volumes/c/s/v" on a default deployment.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.config import resolve_volume
from src.controller.metadata_manager import MetadataManager


def _settings(volume, catalog='app_ontos', schema='app_ontos'):
    return SimpleNamespace(
        DATABRICKS_VOLUME=volume, DATABRICKS_CATALOG=catalog, DATABRICKS_SCHEMA=schema,
    )


@pytest.mark.parametrize('volume, expected', [
    ('/Volumes/banco/files/app_files', ('banco', 'files', 'app_files')),
    ('/Volumes/banco/files/app_files/', ('banco', 'files', 'app_files')),
    ('  app_files ', ('app_ontos', 'app_ontos', 'app_files')),
    ('banco.files.app_files', ('banco', 'files', 'app_files')),
    ('app_files', ('app_ontos', 'app_ontos', 'app_files')),
])
def test_the_three_forms_resolve_to_the_same_parts(volume, expected):
    assert resolve_volume(_settings(volume)) == expected


@pytest.mark.parametrize('volume', [None, '', '  '])
def test_no_volume_configured(volume):
    assert resolve_volume(_settings(volume)) is None


@pytest.mark.parametrize('volume', [
    '/tmp/files', '/Volumes/c/s/v/subdir', 'a.b', 'a..c', 'c. s.v', 'Volumes/c/s/v', 'app files',
])
def test_other_values_are_rejected(volume):
    with pytest.raises(ValueError, match='DATABRICKS_VOLUME must be'):
        resolve_volume(_settings(volume))


def test_metadata_storage_uses_the_injected_volume_path():
    ws = MagicMock()
    ws.volumes.read.side_effect = Exception('not found')

    path = MetadataManager().ensure_volume_path(
        ws, _settings('/Volumes/banco/files/app_files'), 'documents'
    )

    assert path == '/Volumes/banco/files/app_files'
    ws.volumes.read.assert_called_once_with('banco.files.app_files')
    kwargs = ws.volumes.create.call_args.kwargs
    assert (kwargs['catalog_name'], kwargs['schema_name'], kwargs['name']) == (
        'banco', 'files', 'app_files'
    )


def test_metadata_storage_without_volume_fails_clearly():
    with pytest.raises(ValueError, match='not configured'):
        MetadataManager().ensure_volume_path(MagicMock(), _settings(None), 'documents')

