"""A field update is checked as a whole before anything is written.

Regression: the route takes a raw body and only value_type was checked, so
``{"possible_values": "abc"}`` was committed and then failed the read model, which
answered 500 on every template and entity read after that.
"""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from src.controller.compliance_templates_manager import ComplianceTemplateError, ComplianceTemplatesManager
from src.db_models.compliance_templates import ComplianceTemplateFieldDb
from src.models.compliance_templates import ComplianceFieldRead
from src.repositories.compliance_templates_repository import compliance_templates_repo


def _string_field(**overrides):
    values = dict(
        id=uuid4(), template_id=uuid4(), key="k", label="Label", reference_id="k",
        value_type="string", possible_values=None, default_value=None, is_mandatory=False,
        group_title="", group_order=0, field_order=0,
    )
    values.update(overrides)
    return ComplianceTemplateFieldDb(**values)


def _run(field, payload, *, stored_values=0):
    manager = ComplianceTemplatesManager()
    db = MagicMock()
    with patch.object(compliance_templates_repo, "get_field", return_value=field), \
         patch.object(compliance_templates_repo, "count_field_values", return_value=stored_values), \
         patch.object(compliance_templates_repo, "update_field") as repo_update:
        repo_update.return_value = field
        result = manager.update_field(db, field_id=field.id, payload=payload)
    return result, repo_update, db


BAD_PAYLOADS = [
    {"possible_values": "abc"},
    {"possible_values": [1, 2]},
    {"possible_values": ["a", ""]},
    {"possible_values": ["a", "   "]},
    {"possible_values": ["a", " a "]},
    {"possible_values": {"a": 1}},
    {"value_type": "enum"},  # enum without an allowed value
    {"value_type": "bogus"},
    {"value_type": None},
    {"value_type": ["string"]},
    {"is_mandatory": "yes"},
    {"is_mandatory": 1},
    {"is_mandatory": None},
    {"label": "   "},
    {"label": None},
    {"label": 42},
    {"group_order": -1},
    {"group_order": "3"},
    {"field_order": 1.5},
    {"hint_text": ["x"]},
    {"group_title": None},
    {"possible_values": ["a"]},  # a string field takes no vocabulary
    {"value_type": "numeric", "default_value": "not a number"},
    {"bogus": 1},  # unknown key
    {"id": "00000000-0000-0000-0000-000000000001"},  # not a writable attribute
]


@pytest.mark.parametrize("payload", BAD_PAYLOADS, ids=[repr(p)[:60] for p in BAD_PAYLOADS])
def test_bad_update_is_a_template_error_and_nothing_is_written(payload):
    field = _string_field()
    with pytest.raises(ComplianceTemplateError):
        _run(field, payload)
    _, repo_update, db = _run_refusal(field, payload)
    repo_update.assert_not_called()
    db.commit.assert_not_called()


def _run_refusal(field, payload):
    """Run the refused update and return the mocks, so the write can be asserted absent."""
    manager = ComplianceTemplatesManager()
    db = MagicMock()
    with patch.object(compliance_templates_repo, "get_field", return_value=field), \
         patch.object(compliance_templates_repo, "count_field_values", return_value=0), \
         patch.object(compliance_templates_repo, "update_field") as repo_update:
        with pytest.raises(ComplianceTemplateError):
            manager.update_field(db, field_id=field.id, payload=payload)
    return None, repo_update, db


@pytest.mark.parametrize("payload", [
    {"possible_values": "abc"},
    {"possible_values": [1, 2]},
    {"possible_values": ["a", ""]},
])
def test_bad_vocabulary_on_a_field_with_stored_values_is_refused_before_the_write(payload):
    """The same refusal holds when values exist, so the stored values can't be left inconsistent."""
    field = _string_field(value_type="enum", possible_values=["a", "b"])
    manager = ComplianceTemplatesManager()
    db = MagicMock()
    with patch.object(compliance_templates_repo, "get_field", return_value=field), \
         patch.object(compliance_templates_repo, "count_field_values", return_value=2), \
         patch.object(compliance_templates_repo, "update_field") as repo_update:
        with pytest.raises(ComplianceTemplateError):
            manager.update_field(db, field_id=field.id, payload=payload)
    repo_update.assert_not_called()
    db.commit.assert_not_called()


def test_a_value_the_read_model_would_reject_is_never_committed():
    """Validation happens before the commit: a read-model failure leaves nothing behind."""
    field = _string_field()
    manager = ComplianceTemplatesManager()
    db = MagicMock()
    with patch.object(compliance_templates_repo, "get_field", return_value=field), \
         patch.object(compliance_templates_repo, "count_field_values", return_value=0), \
         patch.object(compliance_templates_repo, "update_field", return_value=field), \
         patch.object(ComplianceFieldRead, "model_validate", side_effect=ValueError("bad row")):
        with pytest.raises(ValueError):
            manager.update_field(db, field_id=field.id, payload={"label": "Fine"})
    db.commit.assert_not_called()


def test_key_and_reference_id_are_accepted_but_never_written():
    """The editor sends the whole field on every save, identity fields included."""
    field = _string_field()
    _, repo_update, db = _run(field, {
        "label": "Renamed", "is_mandatory": True, "key": "renamed-key", "reference_id": "renamed-ref",
    })
    assert repo_update.call_args.kwargs["update_data"] == {"label": "Renamed", "is_mandatory": True}
    db.commit.assert_called_once()


def test_the_editor_payload_for_a_vocabulary_field_is_written_as_sent():
    field = _string_field(value_type="string")
    _, repo_update, db = _run(field, {
        "group_title": "", "group_order": 0, "key": "tier", "label": "Tier", "reference_id": "tier",
        "value_type": "enum", "possible_values": ["gold", "silver"], "default_value": "gold",
        "hint_text": None, "is_mandatory": False, "field_order": 2,
    })
    data = repo_update.call_args.kwargs["update_data"]
    assert data == {
        "group_title": "", "group_order": 0, "label": "Tier", "value_type": "enum",
        "possible_values": ["gold", "silver"], "default_value": "gold", "hint_text": None,
        "is_mandatory": False, "field_order": 2,
    }
    db.commit.assert_called_once()


def test_vocabulary_entries_are_stripped_before_they_are_stored():
    field = _string_field(value_type="multi_enum", possible_values=["a"])
    _, repo_update, _ = _run(field, {"possible_values": [" a ", "b"]})
    assert repo_update.call_args.kwargs["update_data"]["possible_values"] == ["a", "b"]
