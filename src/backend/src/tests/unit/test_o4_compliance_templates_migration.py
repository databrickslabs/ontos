"""o4_compliance_templates is idempotent: tables and indexes that already exist are left alone.

A schema made by create_all, or a re-run after a partial failure, must upgrade cleanly.
"""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_NAME = "o4_compliance_templates"
_TABLES = ("compliance_templates", "compliance_template_fields", "compliance_template_values")
_INDEXES = {
    "compliance_templates": ["ix_compliance_templates_entity_type", "ix_compliance_templates_is_active",
                             "uq_compliance_template_active_scope"],
    "compliance_template_fields": ["ix_compliance_template_fields_template_id"],
    "compliance_template_values": ["ix_compliance_template_values_field_id",
                                   "ix_compliance_template_values_entity_type",
                                   "ix_compliance_template_values_entity_id"],
}


def _migration():
    path = Path(__file__).resolve().parents[3] / "alembic" / "versions" / f"{_NAME}.py"
    spec = importlib.util.spec_from_file_location(_NAME, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run_upgrade(existing_tables=(), existing_indexes=()):
    """Run upgrade() against a fake schema; return the mocked op for the calls it made."""
    migration = _migration()
    inspector = MagicMock()
    inspector.get_table_names.return_value = list(existing_tables)
    inspector.get_indexes.side_effect = lambda table: [
        {"name": name} for name in existing_indexes if name in _INDEXES.get(table, [])
    ]
    fake_op = MagicMock()
    with patch.object(migration, "op", fake_op), patch("sqlalchemy.inspect", return_value=inspector):
        migration.upgrade()
    return fake_op


def _created_tables(fake_op):
    return [c.args[0] for c in fake_op.create_table.call_args_list]


def _created_indexes(fake_op):
    return [c.args[0] for c in fake_op.create_index.call_args_list]


def test_a_fresh_schema_gets_every_table_and_index():
    fake_op = _run_upgrade()
    assert _created_tables(fake_op) == list(_TABLES)
    assert sorted(_created_indexes(fake_op)) == sorted(i for names in _INDEXES.values() for i in names)


def test_a_schema_that_already_has_everything_is_left_alone():
    everything_indexes = [i for names in _INDEXES.values() for i in names]
    fake_op = _run_upgrade(existing_tables=_TABLES, existing_indexes=everything_indexes)
    fake_op.create_table.assert_not_called()
    fake_op.create_index.assert_not_called()


def test_a_missing_index_on_an_existing_table_is_created_alone():
    existing = [i for names in _INDEXES.values() for i in names if i != "ix_compliance_template_values_entity_id"]
    fake_op = _run_upgrade(existing_tables=_TABLES, existing_indexes=existing)
    fake_op.create_table.assert_not_called()
    assert _created_indexes(fake_op) == ["ix_compliance_template_values_entity_id"]


def test_a_missing_table_is_created_and_present_ones_are_skipped():
    fake_op = _run_upgrade(existing_tables=["compliance_templates"],
                           existing_indexes=_INDEXES["compliance_templates"])
    assert _created_tables(fake_op) == ["compliance_template_fields", "compliance_template_values"]
    assert "ix_compliance_templates_entity_type" not in _created_indexes(fake_op)


def test_the_unique_active_scope_index_stays_partial_and_unique():
    fake_op = _run_upgrade()
    [call] = [c for c in fake_op.create_index.call_args_list if c.args[0] == "uq_compliance_template_active_scope"]
    assert call.kwargs["unique"] is True
    assert "postgresql_where" in call.kwargs


def test_downgrade_is_unchanged():
    migration = _migration()
    fake_op = MagicMock()
    with patch.object(migration, "op", fake_op):
        migration.downgrade()
    assert [c.args[0] for c in fake_op.drop_table.call_args_list] == [
        "compliance_template_values", "compliance_template_fields", "compliance_templates",
    ]
