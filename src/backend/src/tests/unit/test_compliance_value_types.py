"""Unit tests for the Compliance Templates value-type engine.

Pure-function, table-driven coverage of validation/coercion and "is-set"
semantics for every value type (mirrors the compliance-DSL evaluator tests).
"""
import pytest

from src.common.compliance_value_types import (
    ComplianceValueType,
    ValueTypeError,
    coerce_value,
    is_set,
)


class TestCoerceString:
    def test_plain_string_passes_through(self):
        assert coerce_value("string", "hello") == "hello"

    def test_empty_string_allowed_at_write(self):
        # Empty is allowed on write; "unset" is a completeness concern.
        assert coerce_value("string", "") == ""

    def test_non_string_rejected(self):
        with pytest.raises(ValueTypeError):
            coerce_value("string", 123)


class TestCoerceNumeric:
    @pytest.mark.parametrize("raw,expected", [
        (5, 5),
        (5.0, 5),          # integral float normalized to int
        (5.5, 5.5),
        ("42", 42),
        ("3.14", 3.14),
        ("  7  ", 7),      # surrounding whitespace tolerated
        (-2, -2),
    ])
    def test_valid_numbers(self, raw, expected):
        assert coerce_value("numeric", raw) == expected

    @pytest.mark.parametrize("raw", ["abc", "", "  ", "1.2.3", [1], {"n": 1}])
    def test_invalid_numbers_rejected(self, raw):
        with pytest.raises(ValueTypeError):
            coerce_value("numeric", raw)

    def test_boolean_rejected_as_numeric(self):
        # bool is a subclass of int; must not silently become 1/0.
        with pytest.raises(ValueTypeError):
            coerce_value("numeric", True)


class TestCoerceBoolean:
    @pytest.mark.parametrize("raw,expected", [
        (True, True),
        (False, False),
        ("true", True),
        ("False", False),
        ("YES", True),
        ("no", False),
        (1, True),
        (0, False),
    ])
    def test_valid_booleans(self, raw, expected):
        assert coerce_value("boolean", raw) is expected

    @pytest.mark.parametrize("raw", ["maybe", "2", 2, "", []])
    def test_invalid_booleans_rejected(self, raw):
        with pytest.raises(ValueTypeError):
            coerce_value("boolean", raw)


class TestCoerceDate:
    @pytest.mark.parametrize("raw,expected", [
        ("2026-08-13", "2026-08-13"),
        ("2026-08-13T10:30:00", "2026-08-13"),   # datetime -> date component
    ])
    def test_valid_dates(self, raw, expected):
        assert coerce_value("date", raw) == expected

    @pytest.mark.parametrize("raw", ["not-a-date", "2026-13-40", "", "08/13/2026"])
    def test_invalid_dates_rejected(self, raw):
        with pytest.raises(ValueTypeError):
            coerce_value("date", raw)


class TestCoerceRange:
    def test_valid_range(self):
        assert coerce_value("range", {"low": 1, "high": 10}) == {"low": 1, "high": 10}

    def test_equal_bounds_allowed(self):
        assert coerce_value("range", {"low": 5, "high": 5}) == {"low": 5, "high": 5}

    def test_string_bounds_coerced(self):
        assert coerce_value("range", {"low": "1", "high": "2.5"}) == {"low": 1, "high": 2.5}

    def test_low_greater_than_high_rejected(self):
        with pytest.raises(ValueTypeError):
            coerce_value("range", {"low": 10, "high": 1})

    @pytest.mark.parametrize("raw", [
        {"low": 1},                 # missing high
        {"high": 1},                # missing low
        [1, 10],                    # not an object
        {"low": "x", "high": 10},   # non-numeric bound
    ])
    def test_malformed_range_rejected(self, raw):
        with pytest.raises(ValueTypeError):
            coerce_value("range", raw)


class TestCoerceEnum:
    VOCAB = ["low", "medium", "high"]

    def test_member_accepted(self):
        assert coerce_value("enum", "medium", self.VOCAB) == "medium"

    def test_non_member_rejected(self):
        with pytest.raises(ValueTypeError):
            coerce_value("enum", "urgent", self.VOCAB)

    def test_missing_vocabulary_rejected(self):
        with pytest.raises(ValueTypeError):
            coerce_value("enum", "medium", None)

    def test_non_string_rejected(self):
        with pytest.raises(ValueTypeError):
            coerce_value("enum", 3, self.VOCAB)


class TestCoerceMultiEnum:
    VOCAB = ["pii", "phi", "financial"]

    def test_subset_accepted(self):
        assert coerce_value("multi_enum", ["pii", "financial"], self.VOCAB) == ["pii", "financial"]

    def test_empty_list_allowed_at_write(self):
        assert coerce_value("multi_enum", [], self.VOCAB) == []

    def test_deduplicates_preserving_order(self):
        assert coerce_value("multi_enum", ["pii", "pii", "phi"], self.VOCAB) == ["pii", "phi"]

    def test_non_member_rejected(self):
        with pytest.raises(ValueTypeError):
            coerce_value("multi_enum", ["pii", "unknown"], self.VOCAB)

    def test_non_list_rejected(self):
        with pytest.raises(ValueTypeError):
            coerce_value("multi_enum", "pii", self.VOCAB)


class TestCoerceMisc:
    def test_none_passes_through_for_every_type(self):
        for vt in ComplianceValueType:
            assert coerce_value(vt, None) is None

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError):
            coerce_value("banana", "x")


class TestIsSet:
    @pytest.mark.parametrize("vt,value,expected", [
        # Boolean: both true and false count as set.
        ("boolean", True, True),
        ("boolean", False, True),
        ("boolean", None, False),
        # String / Enum / Date: non-empty, non-whitespace.
        ("string", "x", True),
        ("string", "", False),
        ("string", "   ", False),
        ("enum", "high", True),
        ("enum", "", False),
        ("date", "2026-08-13", True),
        ("date", "", False),
        # Numeric: any number (incl. 0), but not bool.
        ("numeric", 0, True),
        ("numeric", 3.5, True),
        ("numeric", None, False),
        # MultiEnum: at least one selection.
        ("multi_enum", ["a"], True),
        ("multi_enum", [], False),
        # Range: both bounds present.
        ("range", {"low": 1, "high": 2}, True),
        ("range", {"low": 1, "high": None}, False),
        ("range", {"low": None, "high": 2}, False),
    ])
    def test_is_set(self, vt, value, expected):
        assert is_set(vt, value) is expected

    def test_numeric_bool_not_counted_as_set(self):
        # A stray bool must not read as a numeric "set".
        assert is_set("numeric", True) is False
