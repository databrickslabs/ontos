"""Unit tests for the generic entity diff engine and semver helpers (PRD #1086)."""

import pytest

from src.common.entity_diff import Bump, DiffProfile, diff_documents
from src.common.entity_diff.semver import (
    Rule,
    RuleSet,
    classify,
    is_version_consistent,
    next_version,
    version_bump_between,
)

BY_NAME = DiffProfile(identity=lambda item, shape: item.get("name"))


def _ops(changes):
    return {(c.path, c.op) for c in changes}


class TestDiffDocuments:
    def test_identical_documents_have_no_changes(self):
        doc = {"name": "x", "schema": [{"name": "a", "properties": [{"name": "id"}]}]}
        changes, _, _ = diff_documents(doc, doc, BY_NAME)
        assert changes == []

    def test_lists_are_matched_by_identity_not_index(self):
        old = {"schema": [{"name": "a"}, {"name": "b"}]}
        new = {"schema": [{"name": "b"}, {"name": "a"}]}
        changes, _, _ = diff_documents(old, new, BY_NAME)
        assert changes == []

    def test_added_removed_modified_paths(self):
        old = {"schema": [{"name": "orders", "properties": [
            {"name": "id", "logicalType": "string"},
            {"name": "gone"},
        ]}]}
        new = {"schema": [{"name": "orders", "properties": [
            {"name": "id", "logicalType": "integer"},
            {"name": "fresh"},
        ]}]}
        changes, _, _ = diff_documents(old, new, BY_NAME)
        assert _ops(changes) == {
            ("schema[orders].properties[id].logicalType", "modified"),
            ("schema[orders].properties[gone]", "removed"),
            ("schema[orders].properties[fresh]", "added"),
        }
        modified = next(c for c in changes if c.op == "modified")
        assert modified.shape == "schema[].properties[].logicalType"
        assert (modified.old, modified.new) == ("string", "integer")

    def test_none_empty_and_missing_compare_equal(self):
        old = {"description": None, "tags": [], "servers": {}}
        new = {}
        changes, _, _ = diff_documents(old, new, BY_NAME)
        assert changes == []

    def test_emptied_list_reports_per_item_removals(self):
        """Emptying a list normalizes the key away; the diff must still report
        each removed item (so item-level rules apply), not one opaque field."""
        changes, _, _ = diff_documents({"roles": [{"name": "a"}, {"name": "b"}]}, {"roles": []}, BY_NAME)
        assert _ops(changes) == {("roles[a]", "removed"), ("roles[b]", "removed")}
        assert {c.shape for c in changes} == {"roles[]"}

    def test_scalar_lists_compare_as_sets(self):
        changes, _, _ = diff_documents({"tags": ["a", "b"]}, {"tags": ["b", "a", "c"]}, BY_NAME)
        assert _ops(changes) == {("tags[c]", "added")}

    def test_unkeyable_items_fall_back_to_content_hash(self):
        profile = DiffProfile(identity=lambda item, shape: None)
        old = {"quality": [{"rule": "notNull"}]}
        new = {"quality": [{"rule": "notNull"}, {"rule": "unique"}]}
        changes, _, _ = diff_documents(old, new, profile)
        assert [c.op for c in changes] == ["added"]
        assert changes[0].new == {"rule": "unique"}

    def test_duplicate_identity_keys_are_disambiguated(self):
        old = {"items": [{"name": "dup", "v": 1}, {"name": "dup", "v": 2}]}
        new = {"items": [{"name": "dup", "v": 1}]}
        changes, _, _ = diff_documents(old, new, BY_NAME)
        assert _ops(changes) == {("items[dup~2]", "removed")}

    def test_strip_drops_fields_and_list_items(self):
        profile = DiffProfile(
            identity=lambda item, shape: item.get("property"),
            strip=lambda shape, value: shape == "id" or (
                shape == "customProperties[]" and value.get("property") == "volatile"),
        )
        old = {"id": "1", "customProperties": [{"property": "volatile", "value": "a"}]}
        new = {"id": "2", "customProperties": [{"property": "volatile", "value": "b"}]}
        changes, old_n, _ = diff_documents(old, new, profile)
        assert changes == []
        assert old_n == {}


class TestClassification:
    RULES = RuleSet(rules=[
        Rule("removed", "schema[]", Bump.MAJOR, "removed", ops=("removed",)),
        Rule("doc", "description", Bump.PATCH, "doc"),
        Rule("lifecycle", "status", Bump.NONE, "status"),
    ])

    def _classify(self, old, new):
        changes, _, _ = diff_documents(old, new, BY_NAME)
        return classify(changes, self.RULES)

    def test_overall_bump_is_highest(self):
        result = self._classify(
            {"description": "a", "schema": [{"name": "x"}]},
            {"description": "b", "schema": []},
        )
        assert result.bump == Bump.MAJOR
        assert result.counts()["major"] == 1 and result.counts()["patch"] == 1

    def test_no_changes_is_none(self):
        assert self._classify({"a": 1}, {"a": 1}).bump == Bump.NONE

    def test_none_rule_does_not_bump(self):
        assert self._classify({"status": "draft"}, {"status": "active"}).bump == Bump.NONE

    def test_unmatched_change_defaults_to_patch(self):
        result = self._classify({"other": 1}, {"other": 2})
        assert result.bump == Bump.PATCH
        assert result.changes[0].rule_id == "default"

    def test_glob_brackets_are_literal(self):
        """`[` must not start a character class (fnmatch would never match this)."""
        rules = RuleSet(rules=[Rule("two-brackets", "schema[].properties[].logicalType", Bump.MAJOR, "t")])
        old = {"schema": [{"name": "s", "properties": [{"name": "p", "logicalType": "string"}]}]}
        new = {"schema": [{"name": "s", "properties": [{"name": "p", "logicalType": "integer"}]}]}
        changes, _, _ = diff_documents(old, new, BY_NAME)
        assert classify(changes, rules).changes[0].rule_id == "two-brackets"

    def test_ignored_fields_are_not_reported_but_still_match(self):
        profile = DiffProfile(identity=lambda item, shape: item.get("id"), ignore=lambda shape: shape.endswith(".id"))
        old = {"items": [{"id": "a", "name": "old"}]}
        new = {"items": [{"id": "a", "name": "new"}]}
        changes, _, _ = diff_documents(old, new, profile)
        assert _ops(changes) == {("items[a].name", "modified")}

    def test_first_matching_rule_wins(self):
        rules = RuleSet(rules=[
            Rule("first", "a", Bump.MINOR, "first"),
            Rule("second", "a", Bump.MAJOR, "second"),
        ])
        changes, _, _ = diff_documents({"a": 1}, {"a": 2}, BY_NAME)
        assert classify(changes, rules).changes[0].rule_id == "first"


class TestVersionHelpers:
    @pytest.mark.parametrize("current,bump,expected", [
        ("1.2.3", Bump.MAJOR, "2.0.0"),
        ("1.2.3", Bump.MINOR, "1.3.0"),
        ("1.2.3", Bump.PATCH, "1.2.4"),
        ("1.2.3", Bump.NONE, "1.2.3"),
        ("v1.2.3", Bump.PATCH, "1.2.4"),
        ("1.0.0-draft", Bump.MINOR, "1.1.0"),
        ("2.1", Bump.MAJOR, "3.0.0"),
        ("2", Bump.PATCH, "2.0.1"),
        (1.0, Bump.MINOR, "1.1.0"),
        ("not-a-version", Bump.PATCH, "1.0.0"),
        (None, Bump.MAJOR, "1.0.0"),
    ])
    def test_next_version(self, current, bump, expected):
        assert next_version(current, bump) == expected

    @pytest.mark.parametrize("base,target,expected", [
        ("1.0.0", "2.0.0", Bump.MAJOR),
        ("1.0.0", "1.1.0", Bump.MINOR),
        ("1.0.0", "1.0.1", Bump.PATCH),
        ("1.0.0", "1.0.0", None),
        ("2.0.0", "1.0.0", None),
        ("x", "1.0.0", None),
    ])
    def test_version_bump_between(self, base, target, expected):
        assert version_bump_between(base, target) == expected

    def test_version_consistency(self):
        assert is_version_consistent("1.0.0", "2.0.0", Bump.MAJOR) is True
        assert is_version_consistent("1.0.0", "1.0.1", Bump.MAJOR) is False
        assert is_version_consistent("1.0.0", "1.1.0", Bump.PATCH) is True
        assert is_version_consistent("1.0.0", "1.0.0", Bump.NONE) is True
        # Older-vs-newer or unparseable: can't judge
        assert is_version_consistent("2.0.0", "1.0.0", Bump.MAJOR) is None
