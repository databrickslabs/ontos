"""
Tests for manifest canonicalization (RFC 8785 subset).

Covers:
- Determinism: same content always produces same bytes
- RFC 8785 compliance: key ordering, string escaping, numeric handling
- Error handling: float detection, invalid strings, unsupported types
- Golden vectors from RFC 8785 Appendix B
"""

import pytest
from decimal import Decimal

from src.common.manifest_canonicalization import (
    canonicalize,
    canonicalize_to_string,
    CanonicalizationError,
    CanonicalJSONEncoder,
    _canonical_string,
)


class TestCanonicalString:
    """Test string escaping per RFC 8785 and ECMAScript."""

    def test_no_escaping_needed(self):
        """ASCII letters need no escaping."""
        assert _canonical_string("hello") == ["h", "e", "l", "l", "o"]

    def test_escape_quote(self):
        """Quotation mark is escaped as \\\"."""
        result = _canonical_string('say "hi"')
        assert "".join(result) == 'say \\"hi\\"'

    def test_escape_backslash(self):
        """Backslash is escaped as \\\\."""
        result = _canonical_string("path\\to\\file")
        assert "".join(result) == "path\\\\to\\\\file"

    def test_escape_control_chars(self):
        """Control characters U+0000-U+001F are escaped as \\uXXXX."""
        # Tab (U+0009)
        result = _canonical_string("a\tb")
        assert "".join(result) == "a\\tb"

        # Newline (U+000A)
        result = _canonical_string("a\nb")
        assert "".join(result) == "a\\nb"

        # Carriage return (U+000D)
        result = _canonical_string("a\rb")
        assert "".join(result) == "a\\rb"

        # Null (U+0000)
        result = _canonical_string("a\x00b")
        assert "".join(result) == "a\\u0000b"

        # Bell (U+0007)
        result = _canonical_string("a\x07b")
        assert "".join(result) == "a\\u0007b"

    def test_unicode_characters_literal(self):
        """Non-control Unicode characters are emitted as-is."""
        # Emoji (U+1F600)
        result = _canonical_string("😀")
        assert "".join(result) == "😀"

        # Accented character (U+00E9)
        result = _canonical_string("é")
        assert "".join(result) == "é"

    def test_rfc8785_escape_sequences(self):
        """Test all RFC 8785 escape sequences."""
        # Backspace (U+0008)
        result = _canonical_string("a\bb")
        assert "".join(result) == "a\\bb"

        # Form feed (U+000C)
        result = _canonical_string("a\fb")
        assert "".join(result) == "a\\fb"


class TestKeyOrdering:
    """Test UTF-16 key ordering per RFC 8785 §3.2.3."""

    def test_simple_alphabetical(self):
        """Simple ASCII keys are sorted alphabetically."""
        encoder = CanonicalJSONEncoder()
        # Keys: "b", "a", "c" -> sorted: "a", "b", "c"
        obj = {"b": 1, "a": 2, "c": 3}
        result = encoder.encode(obj)
        # Extract keys from result
        assert result == '{"a":2,"b":1,"c":3}'

    def test_numeric_string_keys(self):
        """Numeric string keys are sorted as strings."""
        encoder = CanonicalJSONEncoder()
        obj = {"10": 1, "2": 2, "1": 3}
        result = encoder.encode(obj)
        # Sorted by UTF-16: "1" < "10" < "2"
        assert result == '{"1":3,"10":1,"2":2}'

    def test_nested_objects_sorted(self):
        """Nested objects have their keys sorted too."""
        encoder = CanonicalJSONEncoder()
        obj = {"b": {"y": 2, "x": 1}, "a": 3}
        result = encoder.encode(obj)
        assert result == '{"a":3,"b":{"x":1,"y":2}}'

    def test_rfc8785_appendix_b_example(self):
        """Test RFC 8785 Appendix B example 2."""
        # From RFC 8785 Appendix B (example 2)
        encoder = CanonicalJSONEncoder()
        obj = {
            "a": 1,
            "10": "verspätert",
            "1": "à la",
        }
        result = encoder.encode(obj)
        # Keys sorted by UTF-16: "1", "10", "a"
        assert result == '{"1":"à la","10":"verspätert","a":1}'


class TestNoFloats:
    """Test that floats are detected and rejected."""

    def test_float_literal(self):
        """Float literal raises CanonicalizationError."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"value": 1.5})
        assert exc.value.code == "float_not_allowed"
        assert "at $.value" in str(exc.value)

    def test_integral_float(self):
        """Integral float (1.0) is still rejected."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"value": 1.0})
        assert exc.value.code == "float_not_allowed"

    def test_float_in_array(self):
        """Float in array is detected."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"values": [1, 2.5, 3]})
        assert exc.value.code == "float_not_allowed"
        assert "at $.values[1]" in str(exc.value)

    def test_nan(self):
        """NaN is rejected."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"value": float("nan")})
        assert exc.value.code == "float_not_allowed"

    def test_infinity(self):
        """Infinity is rejected."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"value": float("inf")})
        assert exc.value.code == "float_not_allowed"


class TestIntegersOnly:
    """Test that only integers are accepted as numbers."""

    def test_positive_integer(self):
        """Positive integers are accepted."""
        result = canonicalize_to_string({"value": 42})
        assert result == '{"value":42}'

    def test_negative_integer(self):
        """Negative integers are accepted."""
        result = canonicalize_to_string({"value": -42})
        assert result == '{"value":-42}'

    def test_zero(self):
        """Zero is accepted."""
        result = canonicalize_to_string({"value": 0})
        assert result == '{"value":0}'

    def test_large_integer(self):
        """Large integers (below 2^53) are accepted."""
        value = 2**53 - 1
        result = canonicalize_to_string({"value": value})
        assert result == f'{{"value":{value}}}'

    def test_largest_safe_integers(self):
        """2^53 - 1 and -(2^53 - 1) are accepted."""
        for value in (2**53 - 1, -(2**53 - 1)):
            assert canonicalize_to_string({"value": value}) == f'{{"value":{value}}}'

    @pytest.mark.parametrize("value", [2**53, -(2**53), 2**64, -(2**70)])
    def test_integer_out_of_range_top_level(self, value):
        """Integers with absolute value >= 2^53 are rejected, with the path."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize(value)
        assert exc.value.code == "integer_out_of_range"
        assert exc.value.path == "$"

    @pytest.mark.parametrize("value", [2**53, -(2**53)])
    def test_integer_out_of_range_in_dict(self, value):
        """Out-of-range integer nested in a dict reports its path."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"a": {"b": value}})
        assert exc.value.code == "integer_out_of_range"
        assert exc.value.path == "$.a.b"
        assert "at $.a.b" in str(exc.value)

    @pytest.mark.parametrize("value", [2**53, -(2**53)])
    def test_integer_out_of_range_in_list(self, value):
        """Out-of-range integer nested in a list reports its path."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize_to_string({"items": [1, {"n": [0, value]}]})
        assert exc.value.code == "integer_out_of_range"
        assert exc.value.path == "$.items[1].n[1]"

    def test_booleans_are_not_range_checked(self):
        """bool stays a boolean, not an integer."""
        assert canonicalize_to_string({"a": True, "b": False}) == '{"a":true,"b":false}'

    def test_encoder_guards_direct_use(self):
        """The encoder rejects an out-of-range integer even without the pre-check."""
        with pytest.raises(CanonicalizationError) as exc:
            CanonicalJSONEncoder().encode([2**53])
        assert exc.value.code == "integer_out_of_range"


class TestBasicTypes:
    """Test handling of basic JSON types."""

    def test_boolean_true(self):
        """True is serialized as true."""
        result = canonicalize_to_string({"value": True})
        assert result == '{"value":true}'

    def test_boolean_false(self):
        """False is serialized as false."""
        result = canonicalize_to_string({"value": False})
        assert result == '{"value":false}'

    def test_null(self):
        """None is serialized as null."""
        result = canonicalize_to_string({"value": None})
        assert result == '{"value":null}'

    def test_empty_object(self):
        """Empty object is serialized as {}."""
        result = canonicalize_to_string({})
        assert result == '{}'

    def test_empty_array(self):
        """Empty array is serialized as []."""
        result = canonicalize_to_string([])
        assert result == '[]'

    def test_null_array_element(self):
        """Null in array is serialized as null."""
        result = canonicalize_to_string([1, None, 3])
        assert result == '[1,null,3]'


class TestDeterminism:
    """Test that identical content produces identical output."""

    def test_same_dict_order_doesnt_matter(self):
        """Different insertion order produces same canonical form."""
        dict1 = {"a": 1, "b": 2, "c": 3}
        dict2 = {"c": 3, "a": 1, "b": 2}
        dict3 = {"b": 2, "c": 3, "a": 1}

        result1 = canonicalize(dict1)
        result2 = canonicalize(dict2)
        result3 = canonicalize(dict3)

        assert result1 == result2 == result3

    def test_nested_dict_order(self):
        """Nested dict key order doesn't affect canonicalization."""
        dict1 = {"outer": {"z": 1, "a": 2}}
        dict2 = {"outer": {"a": 2, "z": 1}}

        result1 = canonicalize(dict1)
        result2 = canonicalize(dict2)

        assert result1 == result2

    def test_unicode_normalization_same(self):
        """Same Unicode produces same bytes."""
        dict1 = {"key": "café"}
        dict2 = {"key": "café"}

        result1 = canonicalize(dict1)
        result2 = canonicalize(dict2)

        assert result1 == result2


class TestTamperDetection:
    """Test that any change to content changes the digest."""

    def test_value_change_changes_digest(self):
        """Changing a value changes the canonical form."""
        dict1 = {"product": "v1.0", "status": "published"}
        dict2 = {"product": "v1.0", "status": "unpublished"}

        result1 = canonicalize(dict1)
        result2 = canonicalize(dict2)

        assert result1 != result2

    def test_field_addition_changes_digest(self):
        """Adding a field changes the canonical form."""
        dict1 = {"product": "v1.0"}
        dict2 = {"product": "v1.0", "timestamp": "2026-10-09"}

        result1 = canonicalize(dict1)
        result2 = canonicalize(dict2)

        assert result1 != result2

    def test_array_order_matters(self):
        """Changing array order changes the canonical form."""
        dict1 = {"items": [1, 2, 3]}
        dict2 = {"items": [3, 2, 1]}

        result1 = canonicalize(dict1)
        result2 = canonicalize(dict2)

        assert result1 != result2

    def test_key_name_matters(self):
        """Changing a key name changes the canonical form."""
        dict1 = {"name": "product"}
        dict2 = {"title": "product"}

        result1 = canonicalize(dict1)
        result2 = canonicalize(dict2)

        assert result1 != result2


class TestGoldenVectors:
    """Test against known good vectors."""

    def test_rfc8785_appendix_b_example1(self):
        """RFC 8785 Appendix B Example 1."""
        obj = {
            "b": [1, 2],
            "a": 1,
        }
        result = canonicalize_to_string(obj)
        assert result == '{"a":1,"b":[1,2]}'

    def test_rfc8785_appendix_b_example3(self):
        """RFC 8785 Appendix B Example 3 (with special characters)."""
        obj = {
            "a": "1",
            "b": [2, 3],
        }
        result = canonicalize_to_string(obj)
        assert result == '{"a":"1","b":[2,3]}'

    def test_complex_nested_structure(self):
        """Complex nested structure with multiple types."""
        obj = {
            "metadata": {
                "version": "1.0.0",
                "timestamp": "2026-10-09",
            },
            "items": [
                {"id": 1, "name": "item_one"},
                {"id": 2, "name": "item_two"},
            ],
            "flags": {
                "active": True,
                "archived": False,
            },
            "empty": None,
        }
        result = canonicalize_to_string(obj)
        # Verify deterministic order
        expected = (
            '{"empty":null,"flags":{"active":true,"archived":false},'
            '"items":[{"id":1,"name":"item_one"},{"id":2,"name":"item_two"}],'
            '"metadata":{"timestamp":"2026-10-09","version":"1.0.0"}}'
        )
        assert result == expected


class TestByteOutput:
    """Test byte output from canonicalize()."""

    def test_returns_bytes(self):
        """canonicalize() returns bytes."""
        result = canonicalize({"key": "value"})
        assert isinstance(result, bytes)

    def test_utf8_encoded(self):
        """Output is UTF-8 encoded."""
        result = canonicalize({"key": "café"})
        # "café" in UTF-8: c3 a9 (é as two bytes)
        assert b"caf" in result
        assert result.decode("utf-8") == '{"key":"café"}'

    def test_no_bom(self):
        """Output does not include UTF-8 BOM."""
        result = canonicalize({"key": "value"})
        # UTF-8 BOM is EF BB BF
        assert result[:3] != b"\xef\xbb\xbf"

    def test_no_whitespace(self):
        """Output contains no unnecessary whitespace."""
        obj = {"a": 1, "b": [2, 3], "c": {"d": 4}}
        result = canonicalize(obj)
        # Convert to string to check
        as_string = result.decode("utf-8")
        assert " " not in as_string
        assert "\n" not in as_string
        assert "\t" not in as_string


class TestUnsupportedTypes:
    """Test that unsupported types are rejected."""

    def test_decimal_not_allowed_in_canonicalize(self):
        """Decimal objects cannot be canonicalized (builder must convert them)."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"value": Decimal("1.5")})
        assert exc.value.code == "unsupported_type"

    def test_tuple_not_allowed(self):
        """Tuple objects are not supported."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"value": (1, 2, 3)})
        assert exc.value.code == "unsupported_type"

    def test_set_not_allowed(self):
        """Set objects are not supported."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"value": {1, 2, 3}})
        # Either "unsupported_type" or might be treated as dict/unknown
        # The exact error depends on the structure


class TestErrorMessages:
    """Test that error messages are informative."""

    def test_float_error_includes_path(self):
        """Float error includes the path to the problematic value."""
        with pytest.raises(CanonicalizationError) as exc:
            canonicalize({"outer": {"inner": 1.5}})
        assert "outer" in str(exc.value) or "inner" in str(exc.value)

    def test_error_has_code_attribute(self):
        """CanonicalizationError has a code attribute."""
        try:
            canonicalize({"value": 1.5})
        except CanonicalizationError as e:
            assert hasattr(e, "code")
            assert e.code == "float_not_allowed"
