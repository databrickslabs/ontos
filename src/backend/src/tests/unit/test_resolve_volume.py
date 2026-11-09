"""resolve_volume: a bare volume name needs a usable catalog and schema to fall back to."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.common.api_errors import CodedValueError
from src.common.config import VolumeInvalidError, resolve_volume
from src.common.git import GitVolumeInvalidError, resolve_git_paths


def _settings(volume, catalog='main', schema='gov'):
    return SimpleNamespace(
        DATABRICKS_VOLUME=volume, DATABRICKS_CATALOG=catalog, DATABRICKS_SCHEMA=schema,
        GIT_WORK_DIR=None,
    )


def test_forms_that_name_the_whole_volume_ignore_the_fallback():
    for volume in ('/Volumes/c/s/v', 'c.s.v'):
        assert resolve_volume(_settings(volume, catalog='bad/catalog', schema=None)) == ('c', 's', 'v')


def test_a_bare_name_uses_the_catalog_and_schema_settings():
    assert resolve_volume(_settings('app_files')) == ('main', 'gov', 'app_files')


def test_no_volume_setting_resolves_to_none():
    assert resolve_volume(_settings('  ', catalog='bad/catalog')) is None


@pytest.mark.parametrize('catalog, schema', [
    ('bad/catalog', 'gov'),
    ('main', 'gov schema'),
    ('main.x', 'gov'),
    ('', 'gov'),
    (None, 'gov'),
    ('main', None),
])
def test_a_bare_name_with_an_unusable_catalog_or_schema_fails_with_a_code(catalog, schema):
    with pytest.raises(VolumeInvalidError) as raised:
        resolve_volume(_settings('app_files', catalog=catalog, schema=schema))

    assert isinstance(raised.value, CodedValueError)
    assert isinstance(raised.value, ValueError)
    assert raised.value.code == 'volume_invalid'
    assert raised.value.params == {
        'value': 'app_files', 'catalog': catalog or '', 'schema': schema or '',
    }
    assert 'DATABRICKS_CATALOG' in str(raised.value)


def test_a_malformed_value_fails_with_the_same_code():
    with pytest.raises(VolumeInvalidError) as raised:
        resolve_volume(_settings('/Volumes/main/gov'))
    assert raised.value.code == 'volume_invalid'
    assert raised.value.params['value'] == '/Volumes/main/gov'


def test_the_git_export_reports_a_bad_fallback_with_its_own_code():
    with pytest.raises(GitVolumeInvalidError) as raised:
        resolve_git_paths(_settings('app_files', catalog='bad/catalog'))
    assert raised.value.code == 'git_volume_invalid'


def test_uploads_do_not_build_a_malformed_volumes_path():
    from src.controller.metadata_manager import MetadataManager

    manager = MetadataManager.__new__(MetadataManager)
    ws = MagicMock()
    with pytest.raises(VolumeInvalidError):
        manager.ensure_volume_path(ws, _settings('app_files', catalog='bad/catalog'), 'x')
    ws.volumes.read.assert_not_called()
    ws.volumes.create.assert_not_called()
