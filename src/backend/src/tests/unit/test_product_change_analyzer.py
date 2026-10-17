"""
Unit tests for ProductChangeAnalyzer null-safety.

Regression coverage for a customer 500 where a data product with no team
(`owner_team_id IS NULL`, no `data_product_teams` row) crashed the analyzer
on `old_product.get('team', {}).get('members', [])`. The chained-`.get()`
default only fires for missing keys; when the key is present but the value
is None (the common API serialization case), the default is skipped and
`.get(...)` blows up on NoneType.
"""
from typing import Dict

import pytest

from src.utils.product_change_analyzer import (
    ChangeType,
    ProductChangeAnalyzer,
)


def _empty_product(version: str = "1.0.0") -> Dict:
    """Product with all top-level optional collections explicitly set to None.

    Mirrors the response-builder output for a data product whose team,
    description, support, and ports are all unpopulated.
    """
    return {
        "id": f"product-{version}",
        "name": "test-product",
        "version": version,
        "team": None,
        "description": None,
        "support": None,
        "inputPorts": None,
        "outputPorts": None,
        "managementPorts": None,
    }


class TestProductChangeAnalyzerNullSafety:
    """Regression tests: analyzer must not crash on None-valued fields."""

    def test_analyze_with_all_none_fields_does_not_raise(self):
        """Smoke test: analyzer survives a product with every optional field None."""
        analyzer = ProductChangeAnalyzer()
        old_product = _empty_product("1.0.0")
        new_product = _empty_product("1.0.0")

        # Should not raise AttributeError on NoneType.
        result = analyzer.analyze(old_product, new_product)

        assert result.change_type == ChangeType.NONE
        assert result.version_bump == "none"
        assert result.port_changes == []
        assert result.team_changes == []
        assert result.support_changes == []
        assert result.breaking_changes == []
        assert result.new_features == []
        assert result.fixes == []
        assert "No significant changes" in result.summary

    def test_analyze_team_none_to_populated(self):
        """Adding a team to a product that previously had none is a feature, not a crash."""
        analyzer = ProductChangeAnalyzer()
        old_product = _empty_product()
        new_product = {
            **_empty_product(),
            "team": {
                "members": [
                    {"name": "alice", "email": "alice@example.com", "role": "owner"},
                ]
            },
        }

        result = analyzer.analyze(old_product, new_product)

        assert result.change_type == ChangeType.FEATURE
        assert any("alice" in entry for entry in result.new_features)

    def test_analyze_team_present_but_members_none(self):
        """`team` present but `members` is None — second-level None must not crash."""
        analyzer = ProductChangeAnalyzer()
        product = {
            **_empty_product(),
            "team": {"members": None},
        }

        # Both sides identical → no changes, no crash.
        result = analyzer.analyze(product, product)

        assert result.change_type == ChangeType.NONE
        assert result.team_changes == []

    def test_analyze_port_lists_none(self):
        """Adding output ports to a product whose port lists were None is a feature."""
        analyzer = ProductChangeAnalyzer()
        old_product = _empty_product()
        new_product = {
            **_empty_product(),
            "outputPorts": [
                {"name": "main", "contractId": "c1", "version": "1.0.0"},
            ],
        }

        result = analyzer.analyze(old_product, new_product)

        assert result.change_type == ChangeType.FEATURE
        assert any("main" in feat for feat in result.new_features)

    def test_analyze_support_none(self):
        """Support list is None on both sides — no crash, no changes."""
        analyzer = ProductChangeAnalyzer()
        product = _empty_product()

        result = analyzer.analyze(product, product)

        assert result.support_changes == []
        assert result.change_type == ChangeType.NONE

    def test_analyze_description_none(self):
        """Description None on both sides — no crash, no patch-level fix recorded."""
        analyzer = ProductChangeAnalyzer()
        product = _empty_product()

        result = analyzer.analyze(product, product)

        assert all("description" not in fix.lower() for fix in result.fixes)
        assert result.change_type == ChangeType.NONE

    def test_member_with_none_role_does_not_crash(self):
        """A team member with role=None must not blow up role.lower()."""
        analyzer = ProductChangeAnalyzer()
        old_product = {
            **_empty_product(),
            "team": {
                "members": [
                    {"name": "bob", "email": "bob@example.com", "role": None},
                ]
            },
        }
        # Remove bob in the new version.
        new_product = _empty_product()

        result = analyzer.analyze(old_product, new_product)

        # bob without a critical role → patch-level fix, not breaking.
        assert result.change_type == ChangeType.FIX
        assert any("bob" in entry for entry in result.fixes)


def _with_ports(key: str, ports) -> Dict:
    return {**_empty_product(), key: ports}


class TestInputPortRules:
    """Input ports have no `required` field: the rules use fields that exist."""

    def test_removing_an_input_port_is_breaking(self):
        old = _with_ports("inputPorts", [{"name": "in", "version": "1", "contractId": "c1"}])
        new = _with_ports("inputPorts", [])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert result.change_type == ChangeType.BREAKING
        assert result.version_bump == "major"
        assert any("in" in c for c in result.breaking_changes)

    def test_adding_an_input_port_is_a_feature(self):
        old = _with_ports("inputPorts", [])
        new = _with_ports("inputPorts", [{"name": "in", "version": "1", "contractId": "c1"}])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert result.change_type == ChangeType.FEATURE
        assert result.breaking_changes == []


def _out(**over) -> Dict:
    port = {
        "name": "o", "version": "1", "contractId": "c1", "assetType": "table",
        "assetIdentifier": "main.sales.orders", "containsPii": False,
    }
    return {**port, **over}


class TestOutputPortChanges:
    """Changes to an output port that consumers read are breaking."""

    @pytest.mark.parametrize("over", [
        {"assetIdentifier": "main.sales.orders_v2"},
        {"assetType": "view"},
        {"server": {"host": "kafka-b"}},
        {"contractId": None},
    ])
    def test_repointing_or_unlinking_is_breaking(self, over):
        old = _with_ports("outputPorts", [_out(server={"host": "kafka-a"})])
        new = _with_ports("outputPorts", [_out(**{"server": {"host": "kafka-a"}, **over})])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert result.change_type == ChangeType.BREAKING
        assert result.version_bump == "major"

    @pytest.mark.parametrize("stored, sent", [
        ('{"host": "kafka-a", "port": null}', {"host": "kafka-a"}),
        ('{bad', '{bad'),
    ])
    def test_a_server_stored_as_json_text_compares_by_value(self, stored, sent):
        old = _with_ports("outputPorts", [_out(server=stored)])
        new = _with_ports("outputPorts", [_out(server=sent)])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert result.change_type == ChangeType.NONE

    def test_a_server_stored_as_json_text_that_changed_is_breaking(self):
        old = _with_ports("outputPorts", [_out(server='{"host": "kafka-a"}')])
        new = _with_ports("outputPorts", [_out(server={"host": "kafka-b"})])

        assert ProductChangeAnalyzer().analyze(old, new).change_type == ChangeType.BREAKING

    @pytest.mark.parametrize("over", [
        {"status": "deprecated"},
        {"containsPii": True},
        {"description": "new text"},
        {"deliveryMethodId": "dm-2"},
    ])
    def test_other_attribute_changes_are_a_patch(self, over):
        old = _with_ports("outputPorts", [_out(deliveryMethodId="dm-1")])
        new = _with_ports("outputPorts", [_out(**{"deliveryMethodId": "dm-1", **over})])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert result.change_type == ChangeType.FIX

    def test_unchanged_port_with_empty_values_is_not_a_change(self):
        old = _with_ports("outputPorts", [_out(description=None, containsPii=None)])
        new = _with_ports("outputPorts", [_out(description="", containsPii=False)])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert result.change_type == ChangeType.NONE

    def test_left_out_delivery_method_is_not_a_change(self):
        old = _with_ports("outputPorts", [_out(deliveryMethodId="dm-1")])
        new = _with_ports("outputPorts", [_out()])

        assert ProductChangeAnalyzer().analyze(old, new).change_type == ChangeType.NONE


class TestPortIdentity:
    """The repository keeps an output port by id, the analyzer matches by name."""

    def test_same_name_with_a_new_id_is_breaking(self):
        old = _with_ports("outputPorts", [_out(id="p1")])
        new = _with_ports("outputPorts", [_out(id="p2")])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert result.change_type == ChangeType.BREAKING
        assert any("Recreated" in c for c in result.breaking_changes)

    def test_same_name_without_an_id_is_breaking(self):
        old = _with_ports("outputPorts", [_out(id="p1")])
        new = _with_ports("outputPorts", [_out()])

        assert ProductChangeAnalyzer().analyze(old, new).change_type == ChangeType.BREAKING

    def test_same_id_is_not_a_change(self):
        old = _with_ports("outputPorts", [_out(id="p1")])
        new = _with_ports("outputPorts", [_out(id="p1")])

        assert ProductChangeAnalyzer().analyze(old, new).change_type == ChangeType.NONE

    def test_ids_are_ignored_when_the_old_side_has_none(self):
        old = _with_ports("outputPorts", [_out()])
        new = _with_ports("outputPorts", [_out(id="p1")])

        assert ProductChangeAnalyzer().analyze(old, new).change_type == ChangeType.NONE

    def test_dropping_one_of_two_same_named_ports_is_seen(self):
        old = _with_ports("outputPorts", [_out(id="p1"), _out(id="p2")])
        new = _with_ports("outputPorts", [_out(id="p1")])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert result.change_type == ChangeType.BREAKING
        assert any("Removed" in c for c in result.breaking_changes)


    def test_reordering_two_same_named_ports_is_not_a_change(self):
        """The repository updates each by id, so each is compared with itself."""
        old = _with_ports("outputPorts", [_out(id="p1", contractId="c1"),
                                          _out(id="p2", contractId="c2")])
        new = _with_ports("outputPorts", [_out(id="p2", contractId="c2"),
                                          _out(id="p1", contractId="c1")])

        assert ProductChangeAnalyzer().analyze(old, new).change_type == ChangeType.NONE

    def test_a_same_named_port_without_an_id_takes_the_unpaired_stored_one(self):
        old = _with_ports("outputPorts", [_out(id="p1", contractId="c1"),
                                          _out(id="p2", contractId="c2")])
        new = _with_ports("outputPorts", [_out(contractId="c2"),
                                          _out(id="p1", contractId="c1")])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert any("Recreated" in c for c in result.breaking_changes)
        assert not any("contract" in c for c in result.breaking_changes)

    def test_a_port_renamed_under_its_id_is_still_removed_and_added(self):
        old = _with_ports("outputPorts", [_out(id="p1", name="a")])
        new = _with_ports("outputPorts", [_out(id="p1", name="b")])

        result = ProductChangeAnalyzer().analyze(old, new)

        assert any("Removed output port: a" in c for c in result.breaking_changes)


class TestSnakeCaseKeys:
    """POST /data-products/compare takes caller-supplied dicts: aliases work too."""

    def test_snake_case_port_lists_are_analyzed(self):
        old = {"output_ports": [{"name": "o", "version": "1", "contract_id": "c1"}],
               "support_channels": [{"channel": "slack", "url": "u"}]}
        new = {"output_ports": [], "support_channels": []}

        result = ProductChangeAnalyzer().analyze(old, new)

        assert result.change_type == ChangeType.BREAKING
        assert any("Removed output port" in c for c in result.breaking_changes)
        assert any("slack" in f for f in result.fixes)


class TestProductChangeAnalyzerAliasedKeys:
    """Regression: the DataProduct API model dumps ports/support under snake_case
    aliases (`model_dump(by_alias=True)`), which the analyzer used to ignore —
    every product diff came out as patch/none regardless of port changes."""

    def test_removed_output_port_under_alias_is_breaking(self):
        old_product = {**_empty_product(), "output_ports": [{"name": "main"}]}
        new_product = {**_empty_product(), "output_ports": []}

        result = ProductChangeAnalyzer().analyze(old_product, new_product)

        assert result.change_type == ChangeType.BREAKING
        assert result.version_bump == "major"
        assert any("main" in c for c in result.breaking_changes)

    def test_mixed_alias_and_field_name_shapes(self):
        """Old side aliased (DB → API dump), new side field names (frontend/ODPS)."""
        old_product = {**_empty_product(), "input_ports": [{"name": "src"}]}
        new_product = {**_empty_product(), "inputPorts": [{"name": "src"}, {"name": "extra"}]}

        result = ProductChangeAnalyzer().analyze(old_product, new_product)

        assert result.change_type != ChangeType.NONE
        assert any(pc.port_name == "extra" for pc in result.port_changes)

    def test_support_channels_alias(self):
        old_product = {**_empty_product(), "support_channels": [{"channel": "slack"}]}
        new_product = {**_empty_product(), "support_channels": [{"channel": "slack"}, {"channel": "email"}]}

        result = ProductChangeAnalyzer().analyze(old_product, new_product)

        assert any("email" in f for f in result.new_features)


class TestProductChangeAnalyzerPartialMode:
    """Update payloads omit (or null) sections they don't touch; in partial mode
    those must not be read as removals, or every PUT would 409."""

    def test_partial_skips_unprovided_sections(self):
        old_product = {**_empty_product(), "output_ports": [{"name": "main"}]}
        payload = {"name": "renamed", "output_ports": None}

        result = ProductChangeAnalyzer().analyze(old_product, payload, partial=True)

        assert result.change_type == ChangeType.NONE
        assert result.breaking_changes == []

    def test_partial_still_detects_explicit_removal(self):
        old_product = {**_empty_product(), "output_ports": [{"name": "main"}]}
        payload = {"output_ports": []}

        result = ProductChangeAnalyzer().analyze(old_product, payload, partial=True)

        assert result.change_type == ChangeType.BREAKING

    def test_full_mode_treats_none_as_removal(self):
        old_product = {**_empty_product(), "output_ports": [{"name": "main"}]}
        new_product = _empty_product()

        result = ProductChangeAnalyzer().analyze(old_product, new_product)

        assert result.change_type == ChangeType.BREAKING
