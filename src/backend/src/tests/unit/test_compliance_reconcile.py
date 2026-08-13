"""Unit tests for the pure compliance reconciler (materialization & freezing)."""
import pytest
from uuid import uuid4

from src.common.compliance_reconcile import FieldDesc, ReconcileAction, reconcile


class TestReconcileBasics:
    """Basic reconciler semantics: propose defaults for fields lacking rows."""

    def test_no_fields(self):
        """Empty template yields no actions."""
        actions = reconcile([], set())
        assert actions == []

    def test_no_existing_rows(self):
        """All fields without stored rows and with defaults get proposed."""
        f1 = uuid4()
        f2 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="string", default_value="default1"),
            FieldDesc(field_id=f2, value_type="string", default_value="default2"),
        ]
        actions = reconcile(fields, set())
        assert len(actions) == 2
        assert {a.field_id for a in actions} == {f1, f2}

    def test_fields_with_existing_rows_skipped(self):
        """Fields in existing_field_ids are never touched."""
        f1 = uuid4()
        f2 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="string", default_value="default1"),
            FieldDesc(field_id=f2, value_type="string", default_value="default2"),
        ]
        # f1 already has a row
        actions = reconcile(fields, {f1})
        assert len(actions) == 1
        assert actions[0].field_id == f2

    def test_frozen_rows_never_in_action_set(self):
        """Existing rows are NEVER modified — they're skipped entirely."""
        f1 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="string", default_value="newdefault"),
        ]
        # f1 already has a stored row (maybe with an old value)
        actions = reconcile(fields, {f1})
        # Should propose NO actions because the row already exists
        assert actions == []


class TestEmptyDefaults:
    """Fields with empty/None defaults yield no row proposal."""

    def test_string_empty_string_no_proposal(self):
        """Empty string default is unset."""
        f1 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="string", default_value=""),
        ]
        actions = reconcile(fields, set())
        assert actions == []

    def test_string_none_no_proposal(self):
        """None default is unset."""
        f1 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="string", default_value=None),
        ]
        actions = reconcile(fields, set())
        assert actions == []

    def test_multi_enum_empty_list_no_proposal(self):
        """Empty list is unset for multi_enum."""
        f1 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="multi_enum", default_value=[]),
        ]
        actions = reconcile(fields, set())
        assert actions == []

    def test_range_missing_bounds_no_proposal(self):
        """Range with missing bound is unset."""
        f1 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="range", default_value={"low": 1}),
        ]
        actions = reconcile(fields, set())
        assert actions == []

    def test_boolean_explicit_false_is_set(self):
        """Explicit false is considered SET for booleans."""
        f1 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="boolean", default_value=False),
        ]
        actions = reconcile(fields, set())
        assert len(actions) == 1
        assert actions[0].value is False


class TestValuePreservation:
    """Reconciler preserves the exact default value in the action."""

    def test_string_value_preserved(self):
        """String default is copied as-is."""
        f1 = uuid4()
        default = "my-default-text"
        fields = [
            FieldDesc(field_id=f1, value_type="string", default_value=default),
        ]
        actions = reconcile(fields, set())
        assert len(actions) == 1
        assert actions[0].value == default

    def test_numeric_value_preserved(self):
        """Numeric default is copied as-is."""
        f1 = uuid4()
        default = 42
        fields = [
            FieldDesc(field_id=f1, value_type="numeric", default_value=default),
        ]
        actions = reconcile(fields, set())
        assert len(actions) == 1
        assert actions[0].value == default

    def test_enum_value_preserved(self):
        """Enum default is copied as-is."""
        f1 = uuid4()
        default = "choice1"
        fields = [
            FieldDesc(field_id=f1, value_type="enum", default_value=default),
        ]
        actions = reconcile(fields, set())
        assert len(actions) == 1
        assert actions[0].value == default

    def test_multi_enum_value_preserved(self):
        """MultiEnum default list is copied as-is."""
        f1 = uuid4()
        default = ["a", "b"]
        fields = [
            FieldDesc(field_id=f1, value_type="multi_enum", default_value=default),
        ]
        actions = reconcile(fields, set())
        assert len(actions) == 1
        assert actions[0].value == default

    def test_range_value_preserved(self):
        """Range default dict is copied as-is."""
        f1 = uuid4()
        default = {"low": 10, "high": 20}
        fields = [
            FieldDesc(field_id=f1, value_type="range", default_value=default),
        ]
        actions = reconcile(fields, set())
        assert len(actions) == 1
        assert actions[0].value == default


class TestIdempotence:
    """Reconciler is idempotent: running twice yields same result."""

    def test_second_run_no_new_actions(self):
        """Running reconcile a second time over the same post-reconcile state yields no actions."""
        f1 = uuid4()
        f2 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="string", default_value="d1"),
            FieldDesc(field_id=f2, value_type="string", default_value="d2"),
        ]
        # First run
        actions1 = reconcile(fields, set())
        assert len(actions1) == 2

        # Simulate that rows have now been written for f1 and f2
        existing_after_first_run = {f1, f2}

        # Second run: no new actions should be proposed
        actions2 = reconcile(fields, existing_after_first_run)
        assert actions2 == []


class TestMandatoryWithoutDefault:
    """Mandatory fields without defaults are left pending."""

    def test_mandatory_no_default_no_action(self):
        """Mandatory field with no default yields no proposal (left pending)."""
        f1 = uuid4()
        fields = [
            FieldDesc(field_id=f1, value_type="string", default_value=None),
        ]
        actions = reconcile(fields, set())
        assert actions == []


class TestMixedScenario:
    """Table-driven test combining all semantics."""

    @pytest.mark.parametrize(
        "field_id,value_type,default_value,in_existing,expect_action",
        [
            # (id, type, default, in_existing_set, should_propose)
            (None, "string", "default", False, True),  # Propose: has default, no row
            (None, "string", "", False, False),  # Skip: empty default
            (None, "string", None, False, False),  # Skip: None default
            (None, "string", "default", True, False),  # Skip: row exists (frozen)
            (None, "numeric", 0, False, True),  # Propose: 0 is a set number
            (None, "numeric", None, False, False),  # Skip: None
            (None, "boolean", False, False, True),  # Propose: False is set
            (None, "boolean", None, False, False),  # Skip: None
            (None, "multi_enum", ["a"], False, True),  # Propose: non-empty list
            (None, "multi_enum", [], False, False),  # Skip: empty list
            (None, "range", {"low": 1, "high": 2}, False, True),  # Propose: both bounds
            (None, "range", {"low": 1}, False, False),  # Skip: missing high
        ],
    )
    def test_table_driven(self, field_id, value_type, default_value, in_existing, expect_action):
        """Table-driven test of reconcile semantics."""
        if field_id is None:
            field_id = uuid4()
        existing_set = {field_id} if in_existing else set()
        fields = [
            FieldDesc(field_id=field_id, value_type=value_type, default_value=default_value),
        ]
        actions = reconcile(fields, existing_set)
        if expect_action:
            assert len(actions) == 1
            assert actions[0].field_id == field_id
            assert actions[0].value == default_value
        else:
            assert actions == []
