"""Unit tests for governed-tag domain key/value helpers (pure, no deps)."""
import pytest

from src.common.governed_tags import (
    domain_tag_value,
    parse_domain_tag_value,
    domain_import_order,
    ParsedDomainTag,
)


class TestDomainTagValue:
    def test_top_level(self):
        assert domain_tag_value("Finance") == "Finance"

    def test_subdomain(self):
        assert domain_tag_value("Payments", parent_name="Finance") == "Finance/Payments"

    def test_blank_parent_treated_as_top_level(self):
        assert domain_tag_value("Finance", parent_name="  ") == "Finance"

    def test_empty_name_raises(self):
        with pytest.raises(ValueError):
            domain_tag_value("")


class TestParseDomainTagValue:
    def test_top_level(self):
        assert parse_domain_tag_value("Finance") == ParsedDomainTag(None, "Finance")

    def test_subdomain(self):
        assert parse_domain_tag_value("Finance/Payments") == ParsedDomainTag("Finance", "Payments")

    def test_blank_returns_none(self):
        assert parse_domain_tag_value("   ") is None
        assert parse_domain_tag_value(None) is None

    def test_trailing_separator_is_not_a_subdomain(self):
        assert parse_domain_tag_value("Finance/") == ParsedDomainTag(None, "Finance")

    def test_deep_path_keeps_last_as_leaf(self):
        # "A/B/C" -> parent "A/B", leaf "C"
        assert parse_domain_tag_value("A/B/C") == ParsedDomainTag("A/B", "C")

    def test_roundtrip(self):
        v = domain_tag_value("Payments", parent_name="Finance")
        p = parse_domain_tag_value(v)
        assert p == ParsedDomainTag("Finance", "Payments")


class TestImportOrder:
    def test_parents_before_subdomains(self):
        tags = [
            ParsedDomainTag("Finance", "Payments"),
            ParsedDomainTag(None, "Finance"),
            ParsedDomainTag(None, "Sales"),
        ]
        ordered = domain_import_order(tags)
        # All top-level come before any subdomain.
        first_sub = next(i for i, t in enumerate(ordered) if t.is_subdomain)
        assert all(not ordered[i].is_subdomain for i in range(first_sub))
