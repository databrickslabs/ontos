"""Unit tests for term-mapping naming helpers.

Locks in bug fix #1 from the PRD: the source's _depluralize only knew the
-ies / trailing-s rules, so 'people', 'children', 'criteria' etc. silently
dropped (the depluralized form == original, then no entity match).
"""
from src.controller.term_mapping.naming import (
    depluralize,
    normalize,
    similarity,
    simplify_xsd,
    to_camel,
    to_pascal,
    type_group,
    types_compatible,
    xsd_for_column,
)


class TestNormalize:
    def test_strips_separators(self):
        assert normalize("Cust_Email") == "custemail"
        assert normalize("customer-id") == "customerid"
        assert normalize("CustomerID") == "customerid"

    def test_handles_none_and_empty(self):
        assert normalize("") == ""
        assert normalize(None) == ""  # type: ignore[arg-type]


class TestDepluralize:
    """Bug fix #1 regression tests — irregular plurals must singularise."""

    def test_irregulars(self):
        assert depluralize("people") == "person"
        assert depluralize("children") == "child"
        assert depluralize("men") == "man"
        assert depluralize("women") == "woman"
        assert depluralize("criteria") == "criterion"
        assert depluralize("indices") == "index"

    def test_standard_ies_rule(self):
        assert depluralize("categories") == "category"
        assert depluralize("entities") == "entity"

    def test_standard_s_rule(self):
        assert depluralize("orders") == "order"
        assert depluralize("customers") == "customer"

    def test_ss_endings_preserved(self):
        assert depluralize("address") == "address"
        assert depluralize("class") == "class"

    def test_short_words_untouched(self):
        # We only trim 's' on words > 2 chars to avoid mangling 'is', 'as'…
        assert depluralize("is") == "is"
        assert depluralize("ts") == "ts"


class TestSimilarity:
    def test_identity(self):
        assert similarity("abc", "abc") == 1.0

    def test_empty(self):
        assert similarity("", "abc") == 0.0
        assert similarity("abc", "") == 0.0

    def test_ordering(self):
        assert similarity("customer", "customers") > similarity("customer", "orders")


class TestCasing:
    def test_to_pascal(self):
        assert to_pascal("customer_orders") == "CustomerOrder"
        assert to_pascal("user-profile") == "UserProfile"
        assert to_pascal("") == "Entity"

    def test_to_camel(self):
        assert to_camel("customer_id") == "customerId"
        # Empty input flows through to_pascal's "Entity" fallback, lower-cased.
        assert to_camel("") == "entity"


class TestTypeCompat:
    def test_same_group(self):
        assert types_compatible("varchar", "string")
        assert types_compatible("bigint", "int")
        assert types_compatible("decimal", "double")

    def test_string_is_fallback_attr(self):
        # An attribute declared as string accepts anything (lossy but valid).
        assert types_compatible("bigint", "string")
        assert types_compatible("timestamp", "string")

    def test_incompatible(self):
        # int column → boolean attribute is not a free pass.
        assert not types_compatible("bigint", "boolean")
        assert not types_compatible("timestamp", "integer")

    def test_simplify_xsd_strips_prefix(self):
        assert simplify_xsd("xsd:string") == "string"
        assert simplify_xsd("http://www.w3.org/2001/XMLSchema#dateTime") == "dateTime"

    def test_xsd_for_column(self):
        assert xsd_for_column("varchar") == "xsd:string"
        assert xsd_for_column("bigint") == "xsd:long"
        assert xsd_for_column("boolean") == "xsd:boolean"


def test_type_group_unknown_defaults_to_string():
    assert type_group("uuidvariant") == "string"
    assert type_group("") == "string"
