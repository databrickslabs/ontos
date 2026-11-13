"""ODPS v1.0.0 upload -> export fidelity (#610).

Uploads the maximal ODPS v1.0.0 document (every field of the standard), exports it and
compares both by field path. The fields the export still drops are listed in KNOWN_GAPS;
a new loss fails the test, and so does a gap that was fixed but is still listed.
"""
import datetime
import json
from pathlib import Path

import jsonschema
import pytest
import yaml
from fastapi.testclient import TestClient

_DATA = Path(__file__).parent.parent / "data" / "odps" / "maximal.odps_v1_0_0.yaml"
_SCHEMA = Path(__file__).parent.parent.parent / "schemas" / "odps-json-schema-v1.0.0.json"

# Fields the product (or one of its parts) does not store at all today: the import drops
# them, so the export cannot carry them. Each entry is a schema-style field path.
KNOWN_GAPS = {
    # Structured description: authoritative definitions and custom properties (no tables)
    "description.authoritativeDefinitions[].description",
    "description.authoritativeDefinitions[].type",
    "description.authoritativeDefinitions[].url",
    "description.customProperties[].description",
    "description.customProperties[].property",
    "description.customProperties[].value",
    # Input ports: tags, custom properties, authoritative definitions
    "inputPorts[].authoritativeDefinitions[].description",
    "inputPorts[].authoritativeDefinitions[].type",
    "inputPorts[].authoritativeDefinitions[].url",
    "inputPorts[].customProperties[].description",
    "inputPorts[].customProperties[].property",
    "inputPorts[].customProperties[].value",
    "inputPorts[].tags",
    # Management ports: tags, custom properties, authoritative definitions
    "managementPorts[].authoritativeDefinitions[].description",
    "managementPorts[].authoritativeDefinitions[].type",
    "managementPorts[].authoritativeDefinitions[].url",
    "managementPorts[].customProperties[].description",
    "managementPorts[].customProperties[].property",
    "managementPorts[].customProperties[].value",
    "managementPorts[].tags",
    # Output ports: tags, custom properties, authoritative definitions
    "outputPorts[].authoritativeDefinitions[].description",
    "outputPorts[].authoritativeDefinitions[].type",
    "outputPorts[].authoritativeDefinitions[].url",
    "outputPorts[].customProperties[].description",
    "outputPorts[].customProperties[].property",
    "outputPorts[].customProperties[].value",
    "outputPorts[].tags",
    # Support channels: tags, custom properties, authoritative definitions
    "support[].authoritativeDefinitions[].description",
    "support[].authoritativeDefinitions[].type",
    "support[].authoritativeDefinitions[].url",
    "support[].customProperties[].description",
    "support[].customProperties[].property",
    "support[].customProperties[].value",
    "support[].tags",
    # Team and team members: tags, custom properties, authoritative definitions
    "team.authoritativeDefinitions[].description",
    "team.authoritativeDefinitions[].type",
    "team.authoritativeDefinitions[].url",
    "team.customProperties[].description",
    "team.customProperties[].property",
    "team.customProperties[].value",
    "team.members[].authoritativeDefinitions[].description",
    "team.members[].authoritativeDefinitions[].type",
    "team.members[].authoritativeDefinitions[].url",
    "team.members[].customProperties[].description",
    "team.members[].customProperties[].property",
    "team.members[].customProperties[].value",
    "team.members[].tags",
    "team.tags",
}

# Lists whose items are free-form values, compared whole.
_OPAQUE = {"value", "tags"}


def _leaves(node, path="", out=None):
    """Map schema-style path -> list of (instance path, value) for every leaf."""
    out = {} if out is None else out
    if isinstance(node, dict):
        for key, val in node.items():
            sub = f"{path}.{key}" if path else key
            if key in _OPAQUE:
                out.setdefault(sub, []).append(val)
            else:
                _leaves(val, sub, out)
    elif isinstance(node, list):
        for item in node:
            _leaves(item, f"{path}[]", out)
    else:
        out.setdefault(path, []).append(node)
    return out


def _at(doc, path):
    """All values at a schema-style path of the exported document."""
    nodes = [doc]
    for part in path.replace("[]", ".[]").split("."):
        nxt = []
        for node in nodes:
            if part == "[]":
                nxt.extend(node if isinstance(node, list) else [])
            elif isinstance(node, dict) and part in node:
                nxt.append(node[part])
        nodes = nxt
    return nodes


def _same(path, sent, got):
    if path == "productCreatedTs":
        parse = lambda s: datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))  # noqa: E731
        return parse(sent) == parse(got)
    return sent == got


def _lost_paths(sent, exported):
    """Paths where a value of the uploaded document is absent or changed in the export."""
    lost = set()
    for path, values in _leaves(sent).items():
        got = _at(exported, path)
        for value in values:
            if not any(_same(path, value, g) for g in got):
                lost.add(path)
    return lost


@pytest.fixture
def uploaded(client: TestClient):
    raw = _DATA.read_bytes()
    resp = client.post(
        "/api/data-products/upload",
        files={"files": (_DATA.name, raw, "application/x-yaml")},
        data={"create_missing_domains": "true", "adopt_ids": "true"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["created"] == 1, resp.text
    return yaml.safe_load(raw), body["created_ids"][0]


def _export(client, product_id):
    resp = client.get(f"/api/data-products/{product_id}/odps/export")
    assert resp.status_code == 200, resp.text
    return yaml.safe_load(resp.content)


def test_the_maximal_odps_document_exports_all_it_stores(client, uploaded):
    sent, product_id = uploaded
    exported = _export(client, product_id)
    lost = _lost_paths(sent, exported)
    assert lost - KNOWN_GAPS == set(), "fields lost by the export"
    assert KNOWN_GAPS - lost == set(), "known gaps now fixed: remove them from KNOWN_GAPS"


def test_the_odps_export_validates_against_the_vendored_schema(client, uploaded):
    _, product_id = uploaded
    exported = _export(client, product_id)
    schema = json.loads(_SCHEMA.read_text())
    errors = list(jsonschema.Draft202012Validator(schema).iter_errors(exported))
    assert [e.message for e in errors] == []


def test_the_export_keeps_the_type_of_custom_property_values(client, uploaded):
    _, product_id = uploaded
    props = {c["property"]: c["value"] for c in _export(client, product_id)["customProperties"]}
    assert props["prodCpStr"] == "prod-cp-value"
    assert props["prodCpNum"] == 42
    assert props["prodCpObj"] == {"nested": [1, "two"]}


def test_the_export_keeps_the_stored_creation_timestamp(client, uploaded):
    _, product_id = uploaded
    exported = _export(client, product_id)
    created = datetime.datetime.fromisoformat(
        str(exported["productCreatedTs"]).replace("Z", "+00:00")
    )
    assert created == datetime.datetime(2024, 6, 7, 8, 9, 10, tzinfo=datetime.timezone.utc)


def test_re_importing_an_export_keeps_the_original_domain_as_a_list(client, uploaded):
    _, product_id = uploaded
    exported = _export(client, product_id)
    resp = client.post(
        "/api/data-products/upload",
        files={"files": ("re.yaml", yaml.safe_dump(exported).encode(), "application/x-yaml")},
        data={"on_duplicate": "new"},
    )
    assert resp.status_code == 200, resp.text
    new_id = resp.json()["created_ids"][0]
    original = {
        c["property"]: c["value"] for c in _export(client, new_id)["customProperties"]
    }["ontosOriginalDomain"]
    assert original == ["maximal-domain"]
