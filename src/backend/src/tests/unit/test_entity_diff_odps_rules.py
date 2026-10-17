"""ODPS semver rule matrix (PRD #1086 slice 3).

The base product mirrors an ODPS export of the retail demo
(`GET /data-products/{id}/odps/export`).
"""

import copy
from typing import Dict

import pytest

from src.common.entity_diff import Bump, compare
from src.common.entity_diff.rules_odps import ODPS_PROFILE, ODPS_RULES


def _base() -> Dict:
    return {
        "kind": "DataProduct",
        "apiVersion": "v1.0.0",
        "id": "00700003-0000-4000-8000-000000000003",
        "status": "active",
        "name": "Demand Forecast Model Output v1",
        "version": "1.0.0",
        "domain": "Retail Analytics",
        "customProperties": [
            {"property": "ontosDomainId", "value": ["0000000d-0000-4000-8000-000000000013"]},
            {"property": "ontosEntityId", "value": "00700003-0000-4000-8000-000000000003"},
        ],
        "tenant": "retail-demo",
        "description": {"purpose": "Predicted demand", "usage": "Inventory planning"},
        "inputPorts": [
            {"name": "Prepared Sales Data", "version": "1.0.0", "contractId": "prepared-sales-contract-v1"},
        ],
        "outputPorts": [
            {"id": "e872f115", "name": "demand_forecast_table", "version": "1.0.0",
             "contractId": "demand-forecast-contract-v1", "status": "active", "type": "table",
             "server": {"location": "s3://lake/forecast/v1", "format": "delta"}, "containsPii": False},
        ],
        "managementPorts": [{"name": "observability", "content": "dashboard", "url": "https://dash"}],
        "support": [{"channel": "ml-support", "url": "https://teams.com/channels/ml-support", "tool": "teams"}],
        "team": {
            "name": "Analytics Team",
            "members": [
                {"username": "ml-lead@example.com", "role": "owner", "name": "Charlie ML"},
                {"username": "data-scientist@example.com", "role": "contributor", "name": "Dana Scientist"},
            ],
        },
    }


def _out(doc):
    return doc["outputPorts"][0]


CASES = [
    ("no-change", lambda d: None, Bump.NONE, None),
    ("version-and-ids-only", lambda d: (d.update(id="x", version="1.0.1"), _out(d).update(id="y")),
     Bump.NONE, None),
    ("status-only", lambda d: d.update(status="deprecated"), Bump.NONE, "status"),
    ("description-only", lambda d: d["description"].update(usage="More words"), Bump.PATCH, "description"),
    ("output-port-removed", lambda d: d.update(outputPorts=[]), Bump.MAJOR, "output-port-removed"),
    ("output-port-added", lambda d: d["outputPorts"].append({"name": "forecast_api", "type": "api"}),
     Bump.MINOR, "output-port-added"),
    ("output-port-contract-swapped", lambda d: _out(d).update(contractId="other-contract"),
     Bump.MAJOR, "output-port-contract"),
    ("output-port-major-version", lambda d: _out(d).update(version="2.0.0"), Bump.MAJOR, "output-port-version"),
    ("output-port-minor-version", lambda d: _out(d).update(version="1.1.0"), Bump.MINOR, "output-port-version"),
    ("output-port-patch-version", lambda d: _out(d).update(version="1.0.1"), Bump.PATCH, "output-port-version"),
    ("output-port-version-downgrade", lambda d: _out(d).update(version="0.9.0"), Bump.MAJOR,
     "output-port-version"),
    ("output-port-moved", lambda d: _out(d)["server"].update(location="s3://lake/forecast/v2"),
     Bump.MAJOR, "output-port-server"),
    ("output-port-type", lambda d: _out(d).update(type="view"), Bump.MAJOR, "output-port-type"),
    ("output-port-now-pii", lambda d: _out(d).update(containsPii=True), Bump.MAJOR, "output-port-pii"),
    ("output-port-status", lambda d: _out(d).update(status="deprecated"), Bump.NONE, "output-port-status"),
    ("optional-input-port-added", lambda d: d["inputPorts"].append({"name": "Weather", "contractId": "w"}),
     Bump.MINOR, "input-port-added"),
    ("required-input-port-added", lambda d: d["inputPorts"].append(
        {"name": "Weather", "contractId": "w", "required": True}), Bump.MAJOR, "input-port-added"),
    ("input-port-removed", lambda d: d.update(inputPorts=[]), Bump.PATCH, "input-port-removed"),
    ("input-port-contract-changed", lambda d: d["inputPorts"][0].update(contractId="v2"), Bump.PATCH, "input-port-contract"),
    ("management-port-added", lambda d: d["managementPorts"].append({"name": "alerts", "content": "x"}),
     Bump.MINOR, "management-port-added"),
    ("management-port-removed", lambda d: d.update(managementPorts=[]), Bump.PATCH, "management-port-removed"),
    ("support-added", lambda d: d["support"].append({"channel": "email", "url": "mailto:x"}),
     Bump.MINOR, "support-added"),
    ("support-removed", lambda d: d.update(support=[]), Bump.PATCH, "support-removed"),
    ("owner-removed", lambda d: d["team"]["members"].pop(0), Bump.PATCH, "team-member-removed"),
    ("member-added", lambda d: d["team"]["members"].append({"username": "x@example.com", "role": "contributor"}),
     Bump.PATCH, "team-member-added"),
    ("port-reorder", lambda d: d["outputPorts"].insert(0, d["outputPorts"].pop()), Bump.NONE, None),
]


@pytest.mark.parametrize("case_id,mutate,expected_bump,expected_rule", CASES, ids=[c[0] for c in CASES])
def test_odps_rule_matrix(case_id, mutate, expected_bump, expected_rule):
    base = _base()
    target = copy.deepcopy(base)
    mutate(target)

    result = compare(base, target, ODPS_PROFILE, ODPS_RULES)

    assert result.suggested_bump == expected_bump, [c.to_dict() for c in result.changes]
    if expected_rule is None:
        assert result.changes == []
    else:
        deciding = [c for c in result.changes if c.bump == expected_bump]
        assert any(c.rule_id == expected_rule for c in deciding), [c.to_dict() for c in result.changes]


def test_removed_output_port_path_and_suggested_version():
    base = _base()
    target = copy.deepcopy(base)
    target["outputPorts"] = []
    target["version"] = "1.0.1"

    result = compare(base, target, ODPS_PROFILE, ODPS_RULES)

    assert [c.path for c in result.changes] == ["outputPorts[demand_forecast_table]"]
    assert result.suggested_version == "2.0.0"
    assert result.version_consistent is False
