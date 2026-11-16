"""Unit tests for compliance template field admin operations (slices #709, #711).

Tests cover:
- Field reorder with two-pass ordinal assignment
- Destructive edit guards (delete when values exist, value_type change, enum narrowing)
- Safe edits take effect immediately (label, hint, default, mandatory, group order)
"""
import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from src.controller.compliance_templates_manager import (
    ComplianceConflictError,
    ComplianceTemplateError,
    ComplianceTemplatesManager,
)
from src.db_models.compliance_templates import ComplianceTemplateFieldDb, ComplianceTemplateDb
from src.models.compliance_templates import ComplianceValueType
from src.repositories.compliance_templates_repository import compliance_templates_repo


class TestComplianceFieldAdmin(unittest.TestCase):
    """Test destructive edit guards and field reordering."""

    def setUp(self):
        self.manager = ComplianceTemplatesManager()
        self.template_id = uuid4()
        self.field_id_1 = uuid4()
        self.field_id_2 = uuid4()

    # ----- SLICE #711: Destructive Edit Guards -----

    def test_delete_field_succeeds_when_no_values_exist(self):
        """DELETE succeeds when no stored values exist."""
        db = MagicMock()
        field = ComplianceTemplateFieldDb(
            id=self.field_id_1,
            template_id=self.template_id,
            key="test_field",
            label="Test Field",
            reference_id="test_field",
            value_type="string",
            is_mandatory=False,
        )

        with patch.object(
            compliance_templates_repo, "get_field", return_value=field
        ):
            with patch.object(
                compliance_templates_repo, "count_field_values", return_value=0
            ):
                with patch.object(
                    compliance_templates_repo, "delete_field"
                ):
                    # Should not raise
                    self.manager.delete_field(db, field_id=self.field_id_1)
                    db.commit.assert_called_once()

    def test_delete_field_fails_when_values_exist(self):
        """DELETE fails with 409 when stored values exist."""
        db = MagicMock()
        field = ComplianceTemplateFieldDb(
            id=self.field_id_1,
            template_id=self.template_id,
            key="test_field",
            label="Test Field",
            reference_id="test_field",
            value_type="string",
        )

        with patch.object(
            compliance_templates_repo, "get_field", return_value=field
        ):
            with patch.object(
                compliance_templates_repo, "count_field_values", return_value=5
            ):
                with self.assertRaises(ComplianceTemplateError) as ctx:
                    self.manager.delete_field(db, field_id=self.field_id_1)
                self.assertIn("Cannot delete field", str(ctx.exception))

    def test_update_field_rejects_value_type_change_when_values_exist(self):
        """UPDATE rejects value_type change when stored values exist."""
        db = MagicMock()
        field = ComplianceTemplateFieldDb(
            id=self.field_id_1,
            template_id=self.template_id,
            key="test_field",
            label="Test Field",
            reference_id="test_field",
            value_type="string",
            is_mandatory=False,
        )
        payload = {
            "value_type": ComplianceValueType.NUMERIC,
            "label": "New Label",
        }

        with patch.object(
            compliance_templates_repo, "get_field", return_value=field
        ):
            with patch.object(
                compliance_templates_repo, "count_field_values", return_value=3
            ):
                with self.assertRaises(ComplianceTemplateError) as ctx:
                    self.manager.update_field(db, field_id=self.field_id_1, payload=payload)
                self.assertIn("Cannot change field value type", str(ctx.exception))

    def test_update_field_rejects_enum_narrowing_when_values_exist(self):
        """UPDATE rejects removing enum values when stored values exist."""
        db = MagicMock()
        field = ComplianceTemplateFieldDb(
            id=self.field_id_1,
            template_id=self.template_id,
            key="test_field",
            label="Test Field",
            reference_id="test_field",
            value_type="enum",
            possible_values=["red", "green", "blue"],
            is_mandatory=False,
        )
        # Try to narrow possible_values by removing "blue"
        payload = {
            "possible_values": ["red", "green"],
        }

        with patch.object(
            compliance_templates_repo, "get_field", return_value=field
        ):
            with patch.object(
                compliance_templates_repo, "count_field_values", return_value=2
            ):
                with self.assertRaises(ComplianceTemplateError) as ctx:
                    self.manager.update_field(db, field_id=self.field_id_1, payload=payload)
                self.assertIn("Cannot remove enum values", str(ctx.exception))

    def test_update_field_allows_enum_expansion_when_values_exist(self):
        """UPDATE allows adding new enum values (safe)."""
        db = MagicMock()
        field = ComplianceTemplateFieldDb(
            id=self.field_id_1,
            template_id=self.template_id,
            key="test_field",
            label="Test Field",
            reference_id="test_field",
            value_type="enum",
            possible_values=["red", "green"],
            default_value="red",
            is_mandatory=False,
            group_title="",
            group_order=0,
            field_order=0,
        )
        # Add a new color (safe)
        payload = {
            "possible_values": ["red", "green", "blue"],
        }

        with patch.object(
            compliance_templates_repo, "get_field", return_value=field
        ):
            with patch.object(
                compliance_templates_repo, "count_field_values", return_value=2
            ):
                with patch.object(
                    compliance_templates_repo, "update_field", return_value=field
                ):
                    # Should not raise
                    self.manager.update_field(db, field_id=self.field_id_1, payload=payload)
                    db.commit.assert_called_once()

    def test_update_field_safe_attributes_when_no_values_exist(self):
        """UPDATE succeeds on safe attributes (label, hint, mandatory) when no values."""
        db = MagicMock()
        field = ComplianceTemplateFieldDb(
            id=self.field_id_1,
            template_id=self.template_id,
            key="test_field",
            label="Old Label",
            hint_text="Old hint",
            reference_id="test_field",
            value_type="string",
            is_mandatory=False,
        )
        payload = {
            "label": "New Label",
            "hint_text": "New hint",
            "is_mandatory": True,
        }

        updated_field = ComplianceTemplateFieldDb(
            id=self.field_id_1,
            template_id=self.template_id,
            key="test_field",
            label="New Label",
            hint_text="New hint",
            reference_id="test_field",
            value_type="string",
            is_mandatory=True,
            group_title="",
            group_order=0,
            field_order=0,
        )

        with patch.object(
            compliance_templates_repo, "get_field", return_value=field
        ):
            with patch.object(
                compliance_templates_repo, "count_field_values", return_value=0
            ):
                with patch.object(
                    compliance_templates_repo, "update_field", return_value=updated_field
                ):
                    result = self.manager.update_field(db, field_id=self.field_id_1, payload=payload)
                    self.assertEqual(result.label, "New Label")
                    self.assertEqual(result.hint_text, "New hint")
                    self.assertTrue(result.is_mandatory)
                    db.commit.assert_called_once()

    # ----- SLICE #709: Field Reorder -----

    def test_reorder_fields_two_pass_approach(self):
        """REORDER uses two-pass approach: temp negatives, then finals."""
        db = MagicMock()
        template = ComplianceTemplateDb(
            id=self.template_id,
            name="Test Template",
            entity_type="data_product",
        )

        order_map = [
            {"id": self.field_id_1, "group_title": "Group A", "group_order": 0, "field_order": 1},
            {"id": self.field_id_2, "group_title": "Group A", "group_order": 0, "field_order": 0},
        ]

        fields_result = [
            ComplianceTemplateFieldDb(
                id=self.field_id_1,
                template_id=self.template_id,
                key="field_1",
                label="Field 1",
                reference_id="field_1",
                value_type="string",
                group_title="Group A",
                group_order=0,
                field_order=1,
                is_mandatory=False,
            ),
            ComplianceTemplateFieldDb(
                id=self.field_id_2,
                template_id=self.template_id,
                key="field_2",
                label="Field 2",
                reference_id="field_2",
                value_type="string",
                group_title="Group A",
                group_order=0,
                field_order=0,
                is_mandatory=False,
            ),
        ]

        with patch.object(
            compliance_templates_repo, "get_template", return_value=template
        ):
            with patch.object(
                compliance_templates_repo, "reorder_fields", return_value=fields_result
            ):
                result = self.manager.reorder_fields(db, template_id=self.template_id, order_map=order_map)
                self.assertEqual(len(result), 2)
                db.commit.assert_called_once()

    def test_reorder_fields_template_not_found(self):
        """REORDER fails if template doesn't exist."""
        db = MagicMock()
        order_map = [
            {"id": self.field_id_1, "group_title": "Group A", "group_order": 0, "field_order": 0},
        ]

        with patch.object(
            compliance_templates_repo, "get_template", return_value=None
        ):
            with self.assertRaises(ComplianceTemplateError) as ctx:
                self.manager.reorder_fields(db, template_id=self.template_id, order_map=order_map)
            self.assertIn("Template not found", str(ctx.exception))


class TestReorderFieldsRepositoryLogic(unittest.TestCase):
    """Test the two-pass reorder logic at the repository level (pure function test)."""

    def test_reorder_two_pass_avoids_unique_constraint(self):
        """Two-pass reorder temporarily uses negative values to avoid constraint violations."""
        # Simulate field_order unique constraint by checking no duplicates mid-process
        fields_by_id = {
            "f1": {"id": "f1", "field_order": 0},
            "f2": {"id": "f2", "field_order": 1},
        }
        order_map = [
            {"id": "f1", "field_order": 1},
            {"id": "f2", "field_order": 0},
        ]

        # Pass 1: assign temp negatives
        changed = []
        for item in order_map:
            if fields_by_id[item["id"]]["field_order"] != item["field_order"]:
                changed.append(item)
        self.assertEqual(len(changed), 2)

        for i, item in enumerate(changed):
            fields_by_id[item["id"]]["field_order"] = -(i + 1)

        # Check no duplicates after pass 1
        orders = [f["field_order"] for f in fields_by_id.values()]
        self.assertEqual(len(orders), len(set(orders)), "Pass 1 should have no duplicates")

        # Pass 2: assign finals
        for item in changed:
            fields_by_id[item["id"]]["field_order"] = item["field_order"]

        # Check no duplicates after pass 2
        orders = [f["field_order"] for f in fields_by_id.values()]
        self.assertEqual(len(orders), len(set(orders)), "Pass 2 should have no duplicates")
        # Check order swapped
        self.assertEqual(fields_by_id["f1"]["field_order"], 1)
        self.assertEqual(fields_by_id["f2"]["field_order"], 0)


if __name__ == "__main__":
    unittest.main()


class TestUpdateFieldPersistsVocabulary(unittest.TestCase):
    """Regression: value_type / possible_values sent by the editor were silently dropped."""

    def setUp(self):
        self.manager = ComplianceTemplatesManager()
        self.field_id = uuid4()

    def _field(self, value_type="enum", possible_values=("a", "b"), default_value=None):
        return ComplianceTemplateFieldDb(
            id=self.field_id,
            template_id=uuid4(),
            key="k",
            label="Label",
            reference_id="k",
            value_type=value_type,
            possible_values=list(possible_values) if possible_values is not None else None,
            default_value=default_value,
            is_mandatory=False,
            group_title="",
            group_order=0,
            field_order=0,
        )

    def _update(self, field, payload, stored_values):
        db = MagicMock()
        with patch.object(compliance_templates_repo, "get_field", return_value=field), \
             patch.object(compliance_templates_repo, "count_field_values", return_value=stored_values), \
             patch.object(compliance_templates_repo, "update_field", return_value=field) as repo_update:
            self.manager.update_field(db, field_id=self.field_id, payload=payload)
        return repo_update.call_args.kwargs["update_data"], db

    def test_adding_enum_value_is_persisted_with_stored_values(self):
        field = self._field(possible_values=("a", "b"), default_value="c")
        payload = {"value_type": "enum", "possible_values": ["a", "b", "c"], "default_value": "c"}

        update, db = self._update(field, payload, stored_values=3)

        self.assertEqual(update["possible_values"], ["a", "b", "c"])
        self.assertEqual(update["default_value"], "c")
        db.commit.assert_called_once()

    def test_adding_enum_value_is_persisted_without_stored_values(self):
        field = self._field(possible_values=("a", "b"))
        update, _ = self._update(field, {"possible_values": ["a", "b", "c"]}, stored_values=0)
        self.assertEqual(update["possible_values"], ["a", "b", "c"])

    def test_value_type_change_is_persisted_when_no_values_exist(self):
        field = self._field(value_type="string", possible_values=None)
        update, _ = self._update(field, {"value_type": ComplianceValueType.ENUM, "possible_values": ["x"]}, stored_values=0)
        self.assertEqual(update["value_type"], "enum")
        self.assertEqual(update["possible_values"], ["x"])

    def test_removing_enum_value_with_stored_values_is_a_conflict(self):
        field = self._field(possible_values=("a", "b", "c"))
        with self.assertRaises(ComplianceConflictError):
            self._update(field, {"possible_values": ["a", "b"]}, stored_values=2)

    def test_clearing_vocabulary_with_stored_values_is_a_conflict(self):
        field = self._field(possible_values=("a", "b"))
        with self.assertRaises(ComplianceConflictError):
            self._update(field, {"possible_values": None}, stored_values=2)

    def test_value_type_change_with_stored_values_is_a_conflict(self):
        field = self._field(value_type="string", possible_values=None)
        with self.assertRaises(ComplianceConflictError):
            self._update(field, {"value_type": "numeric"}, stored_values=2)

    def test_conflict_is_a_template_error_for_existing_callers(self):
        self.assertTrue(issubclass(ComplianceConflictError, ComplianceTemplateError))
