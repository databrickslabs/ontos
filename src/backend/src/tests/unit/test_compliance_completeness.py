"""Unit tests for the Compliance Templates completeness validator.

Pure-function, table-driven coverage of the mandatory-satisfaction logic and
effective-value fallback (mirrors the compliance-DSL evaluator tests).
"""
import pytest

from src.common.compliance_completeness import (
    FieldSpec,
    check_completeness,
)


def _field(fid, *, mandatory, value_type="string", default=None, label=None):
    return FieldSpec(
        field_id=fid,
        label=label or fid,
        value_type=value_type,
        is_mandatory=mandatory,
        default_value=default,
    )


class TestMandatorySatisfaction:
    def test_mandatory_with_value_passes(self):
        fields = [_field("a", mandatory=True)]
        result = check_completeness(fields, {"a": "filled"})
        assert result.passed is True
        assert result.missing == []
        assert result.messages == []

    def test_mandatory_unfilled_no_default_fails(self):
        fields = [_field("a", mandatory=True, label="Purpose")]
        result = check_completeness(fields, {})
        assert result.passed is False
        assert result.missing == ["Purpose"]
        assert result.messages == ["'Purpose' is required but has no value."]

    def test_mandatory_with_default_passes_even_when_unfilled(self):
        fields = [_field("a", mandatory=True, default="90 days")]
        result = check_completeness(fields, {})
        assert result.passed is True

    def test_non_mandatory_unfilled_passes(self):
        fields = [_field("a", mandatory=False)]
        result = check_completeness(fields, {})
        assert result.passed is True

    def test_empty_string_value_does_not_satisfy(self):
        fields = [_field("a", mandatory=True, label="Purpose")]
        result = check_completeness(fields, {"a": "   "})
        assert result.passed is False
        assert "Purpose" in result.missing

    def test_stored_value_overrides_missing_default(self):
        # No default, but a real stored value satisfies.
        fields = [_field("a", mandatory=True, default=None)]
        assert check_completeness(fields, {"a": "x"}).passed is True


class TestEffectiveValueFallback:
    def test_falls_back_to_default_when_unstored(self):
        fields = [_field("a", mandatory=True, value_type="numeric", default=5)]
        assert check_completeness(fields, {}).passed is True

    def test_empty_default_does_not_satisfy(self):
        fields = [_field("a", mandatory=True, value_type="string", default="")]
        assert check_completeness(fields, {}).passed is False


class TestTypeEdgeCases:
    def test_boolean_false_satisfies(self):
        # Boolean false counts as set.
        fields = [_field("a", mandatory=True, value_type="boolean")]
        assert check_completeness(fields, {"a": False}).passed is True

    def test_multi_enum_empty_list_fails(self):
        fields = [_field("a", mandatory=True, value_type="multi_enum", label="Cats")]
        result = check_completeness(fields, {"a": []})
        assert result.passed is False
        assert result.missing == ["Cats"]

    def test_multi_enum_with_selection_passes(self):
        fields = [_field("a", mandatory=True, value_type="multi_enum")]
        assert check_completeness(fields, {"a": ["pii"]}).passed is True

    def test_range_partial_bounds_fails(self):
        fields = [_field("a", mandatory=True, value_type="range", label="Band")]
        result = check_completeness(fields, {"a": {"low": 1, "high": None}})
        assert result.passed is False
        assert result.missing == ["Band"]

    def test_range_both_bounds_passes(self):
        fields = [_field("a", mandatory=True, value_type="range")]
        assert check_completeness(fields, {"a": {"low": 1, "high": 2}}).passed is True

    def test_numeric_zero_satisfies(self):
        fields = [_field("a", mandatory=True, value_type="numeric")]
        assert check_completeness(fields, {"a": 0}).passed is True


class TestMultipleFields:
    def test_reports_all_missing_in_order(self):
        fields = [
            _field("a", mandatory=True, label="A"),
            _field("b", mandatory=False, label="B"),
            _field("c", mandatory=True, label="C"),
        ]
        result = check_completeness(fields, {"a": ""})
        assert result.passed is False
        assert result.missing == ["A", "C"]

    def test_all_satisfied_passes(self):
        fields = [
            _field("a", mandatory=True, default="x"),
            _field("c", mandatory=True),
        ]
        assert check_completeness(fields, {"c": "y"}).passed is True

    def test_no_fields_passes(self):
        assert check_completeness([], {}).passed is True
