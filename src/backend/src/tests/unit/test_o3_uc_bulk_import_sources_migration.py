"""Migration o3_uc_bulk_import_sources sits on the native migration stack (#1527 review).

The approved PRs that add a migration on s2 stack natively, each revising the previous
one: s2 <- s3_notif_read_requests_handled <- o3_unshare_entity_metadata_rows <- this one.
"""
import importlib.util
from pathlib import Path

_NAME = 'o3_uc_bulk_import_sources'


def _migration():
    path = Path(__file__).resolve().parents[3] / 'alembic' / 'versions' / f'{_NAME}.py'
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_it_revises_the_unshare_migration():
    migration = _migration()
    assert migration.revision == _NAME
    assert migration.down_revision == 'o3_unshare_entity_metadata_rows'
