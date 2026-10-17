"""ODCS semver rule matrix (PRD #1086).

Each case mutates a realistic contract (shaped like a `build_odcs_from_db`
export of the retail demo) and asserts the overall bump plus the rule that
decided it.
"""

import copy
from typing import Callable, Dict

import pytest

from src.common.entity_diff import Bump, compare
from src.common.entity_diff.rules_odcs import ODCS_PROFILE, ODCS_RULES


def _base() -> Dict:
    return {
        "id": "00400001-0000-4000-8000-000000000001",
        "kind": "DataContract",
        "apiVersion": "v3.1.0",
        "version": "1.0.0",
        "status": "active",
        "domain": "Customer",
        "customProperties": [
            {"property": "ontosDomainId", "value": ["00000007-0000-4000-8000-000000000007"]},
            {"property": "ontosEntityId", "value": "00400001-0000-4000-8000-000000000001"},
        ],
        "description": {"purpose": "Core customer data", "usage": "Apps and analytics"},
        "schema": [{
            "name": "customers",
            "physicalName": "customers",
            "quality": [{"type": "sql", "query": "SELECT COUNT(*) FROM customers", "mustBeGreaterThan": 0,
                         "name": "non_empty"}],
            "properties": [
                {"name": "customer_id", "logicalType": "string", "required": True, "unique": True,
                 "primaryKey": True, "primaryKeyPosition": 1, "physicalName": "customer_id",
                 "description": "Unique customer identifier",
                 "quality": [{"rule": "notNull", "type": "library", "description": "never NULL",
                              "severity": "error"}]},
                {"name": "email", "logicalType": "string", "required": False, "unique": False,
                 "logicalTypeOptions": {"maxLength": 255}, "physicalType": "varchar(255)"},
                {"name": "lifetime_value", "logicalType": "double", "required": False},
            ],
        }],
        "servers": [{"server": "prod", "type": "databricks", "environment": "prod",
                     "catalog": "retail", "schema": "customer", "description": "Production"}],
        "roles": [{"role": "analyst", "access": "read"}],
    }


def _props(doc):
    return doc["schema"][0]["properties"]


def _prop(doc, name):
    return next(p for p in _props(doc) if p["name"] == name)


Mutation = Callable[[Dict], None]

CASES = [
    # (id, mutation, expected overall bump, expected deciding rule)
    ("no-change", lambda d: None, Bump.NONE, None),
    ("version-and-ids-only", lambda d: d.update(
        id="other", version="1.0.1",
        customProperties=[{"property": "ontosDomainId", "value": ["00000007-0000-4000-8000-000000000007"]},
                          {"property": "ontosEntityId", "value": "other"}]),
     Bump.NONE, None),
    ("status-only", lambda d: d.update(status="deprecated"), Bump.NONE, "status"),
    ("api-version-only", lambda d: d.update(apiVersion="v3.2.0"), Bump.NONE, "api-version"),
    ("description-only", lambda d: d["description"].update(purpose="Better words"), Bump.PATCH, "default"),
    ("schema-removed", lambda d: d.update(schema=[]), Bump.MAJOR, "schema-removed"),
    ("schema-added", lambda d: d["schema"].append({"name": "addresses", "properties": [{"name": "id"}]}),
     Bump.MINOR, "schema-added"),
    ("optional-property-removed", lambda d: _props(d).remove(_prop(d, "lifetime_value")),
     Bump.MAJOR, "property-removed"),
    ("optional-property-added", lambda d: _props(d).append({"name": "nickname", "logicalType": "string"}),
     Bump.MINOR, "property-added"),
    ("required-property-added", lambda d: _props(d).append(
        {"name": "country", "logicalType": "string", "required": True}), Bump.MAJOR, "property-added"),
    ("incompatible-type-change", lambda d: _prop(d, "customer_id").update(logicalType="integer"),
     Bump.MAJOR, "property-logical-type"),
    ("compatible-type-change", lambda d: _prop(d, "lifetime_value").update(logicalType="float"),
     Bump.PATCH, "property-logical-type"),
    ("physical-type-change", lambda d: _prop(d, "email").update(physicalType="varchar(100)"),
     Bump.MAJOR, "property-physical-type"),
    ("physical-rename", lambda d: _prop(d, "customer_id").update(physicalName="cust_id"),
     Bump.MAJOR, "property-physical-name"),
    ("became-required", lambda d: _prop(d, "email").update(required=True), Bump.MAJOR, "property-required"),
    ("became-optional", lambda d: _prop(d, "customer_id").update(required=False),
     Bump.PATCH, "property-required"),
    ("became-unique", lambda d: _prop(d, "email").update(unique=True), Bump.MAJOR, "property-unique"),
    ("primary-key-change", lambda d: _prop(d, "email").update(primaryKey=True), Bump.MAJOR,
     "property-primary-key"),
    ("max-length-lowered", lambda d: _prop(d, "email")["logicalTypeOptions"].update(maxLength=100),
     Bump.MAJOR, "property-type-options"),
    ("max-length-raised", lambda d: _prop(d, "email")["logicalTypeOptions"].update(maxLength=500),
     Bump.MINOR, "property-type-options"),
    ("pattern-added", lambda d: _prop(d, "email")["logicalTypeOptions"].update(pattern="^.+@.+$"),
     Bump.MAJOR, "property-type-options"),
    ("quality-added", lambda d: _prop(d, "email").update(quality=[{"rule": "notNull", "type": "library"}]),
     Bump.MAJOR, "quality-added"),
    ("quality-removed", lambda d: _prop(d, "customer_id").pop("quality"), Bump.PATCH, "quality-removed"),
    ("quality-metadata", lambda d: _prop(d, "customer_id")["quality"][0].update(description="reworded"),
     Bump.PATCH, "quality-metadata"),
    ("quality-threshold", lambda d: d["schema"][0]["quality"][0].update(mustBeGreaterThan=100),
     Bump.MAJOR, "quality-changed"),
    ("server-removed", lambda d: d.update(servers=[]), Bump.MAJOR, "server-removed"),
    ("server-added", lambda d: d["servers"].append({"server": "dev", "type": "databricks"}),
     Bump.MINOR, "server-added"),
    ("server-moved", lambda d: d["servers"][0].update(catalog="retail_v2"), Bump.MAJOR, "server-changed"),
    ("server-description", lambda d: d["servers"][0].update(description="Prod (EU)"), Bump.PATCH,
     "server-description"),
    ("role-removed", lambda d: d.update(roles=[]), Bump.MAJOR, "role-removed"),
    ("role-added", lambda d: d["roles"].append({"role": "steward", "access": "write"}), Bump.MINOR, "role-added"),
    ("sla-added", lambda d: d.update(slaProperties=[{"property": "latency", "value": 4, "unit": "h"}]),
     Bump.MINOR, "sla-changed"),
    ("property-reorder", lambda d: _props(d).reverse(), Bump.NONE, None),
]


@pytest.mark.parametrize("case_id,mutate,expected_bump,expected_rule", CASES, ids=[c[0] for c in CASES])
def test_odcs_rule_matrix(case_id, mutate, expected_bump, expected_rule):
    base = _base()
    target = copy.deepcopy(base)
    mutate(target)

    result = compare(base, target, ODCS_PROFILE, ODCS_RULES)

    assert result.suggested_bump == expected_bump, [c.to_dict() for c in result.changes]
    if expected_rule is None:
        assert result.changes == []
    else:
        deciding = [c for c in result.changes if c.bump == expected_bump]
        assert any(c.rule_id == expected_rule for c in deciding), [c.to_dict() for c in result.changes]


def test_nested_property_rules_apply_at_any_depth():
    base = _base()
    _prop(base, "email").update(logicalType="object", properties=[{"name": "domain", "logicalType": "string"}])
    target = copy.deepcopy(base)
    _prop(target, "email")["properties"] = []

    result = compare(base, target, ODCS_PROFILE, ODCS_RULES)

    assert result.suggested_bump == Bump.MAJOR
    assert result.changes[0].path == "schema[customers].properties[email].properties[domain]"
    assert result.changes[0].rule_id == "property-removed"


def test_suggested_version_and_consistency():
    base = _base()
    target = copy.deepcopy(base)
    _props(target).remove(_prop(target, "lifetime_value"))
    target["version"] = "1.0.1"  # patch bump for a breaking change

    result = compare(base, target, ODCS_PROFILE, ODCS_RULES)

    assert result.suggested_version == "2.0.0"
    assert result.version_consistent is False

    target["version"] = "2.0.0"
    assert compare(base, target, ODCS_PROFILE, ODCS_RULES).version_consistent is True


def test_change_dict_shape_for_api():
    base = _base()
    target = copy.deepcopy(base)
    _prop(target, "customer_id").update(logicalType="integer")

    change = compare(base, target, ODCS_PROFILE, ODCS_RULES).changes[0].to_dict()

    assert change == {
        "path": "schema[customers].properties[customer_id].logicalType",
        "op": "modified",
        "old": "string",
        "new": "integer",
        "bump": "major",
        "rule_id": "property-logical-type",
        "message": "Property logical type changed",
    }
