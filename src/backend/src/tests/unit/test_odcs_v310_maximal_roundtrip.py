"""Round trip of a maximal ODCS v3.1.0 contract (#610).

`tests/data/odcs/maximal.odcs_v3_1_0.yaml` has every field of the v3.1.0 JSON
schema, each kind once (all 34 server types). It is uploaded and exported; every
value of the file must come back unchanged, except the known gaps listed in
`KNOWN_GAPS`. A field that stops round-tripping fails the test, and so does a
gap that is fixed but still listed. The export must also be valid against the
vendored v3.1.0 schema, and a re-import of the export must export the same.
"""
import copy
import json
import re
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest
import yaml
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.db_models.data_contracts import DataContractDb

DATA = Path(__file__).parent.parent / "data" / "odcs" / "maximal.odcs_v3_1_0.yaml"
SCHEMA = Path(__file__).parent.parent.parent / "schemas" / "odcs-json-schema-v3.1.0.json"

# Field paths (arrays as `[]`; a leading `*.` matches at any depth) whose values
# are known not to round-trip yet, with the reason. Everything below a path is
# covered.
KNOWN_GAPS = {
    'schema[].properties[].properties': 'nested columns of an object column are not stored',
    'schema[].properties[].items': 'the ODCS `items` of an array column is not stored',
    'schema[].properties[].logicalTypeOptions':
        'the import reads the options flat (v2 style), not from logicalTypeOptions',
    '*.customProperties[].description': 'custom properties have no description column',
    '*.authoritativeDefinitions[].description':
        'authoritative definitions have no description column',
    '*.quality[].customProperties': 'quality checks have no custom properties table',
    '*.quality[].authoritativeDefinitions': 'quality checks have no authoritative definitions',
    '*.quality[].arguments': 'quality checks have no arguments column',
    '*.quality[].rule': 'the deprecated `rule` goes out as `metric` (intended)',
    'description.customProperties': 'the description object has no custom properties table',
    'description.authoritativeDefinitions':
        'stored with the root authoritativeDefinitions, which the export writes in both places',
    'support[].customProperties': 'support channels have no custom properties table',
    'team.members[].tags': 'team members have no tags column',
    'team.members[].customProperties': 'team members have no custom properties table',
    'team.members[].authoritativeDefinitions': 'team members have no authoritative definitions',
}

# List items are matched by these keys (first one present), else by position
MATCH_KEYS = {
    'schema': ('name',), 'properties': ('name',), 'servers': ('id', 'server'),
    'customProperties': ('property',), 'authoritativeDefinitions': ('url',),
    'quality': ('id', 'name'), 'roles': ('role',), 'support': ('channel',),
    'slaProperties': ('property',), 'members': ('username',), 'relationships': ('id', 'to'),
}
# Compared whole
OPAQUE = {'value', 'valueExt', 'implementation', 'examples', 'tags', 'transformSourceObjects',
          'mustBe', 'mustNotBe', 'mustBeBetween', 'mustNotBeBetween', 'from', 'to'}
TIMESTAMPS = {'contractCreatedTs'}


def _manager():
    return DataContractsManager(data_dir=Path("/tmp"))


def _same(field, a, b):
    if field in TIMESTAMPS and isinstance(a, str) and isinstance(b, str):
        parse = lambda v: datetime.fromisoformat(v.replace('Z', '+00:00'))  # noqa: E731
        return parse(a) == parse(b)
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))
                                       and not isinstance(a, bool) and not isinstance(b, bool)):
        return False
    return a == b


def _match(field, item, candidates, used, index):
    if isinstance(item, dict):
        for key in MATCH_KEYS.get(field, ()):
            if item.get(key) is None:
                continue
            for j, candidate in enumerate(candidates):
                if j in used or not isinstance(candidate, dict):
                    continue
                if candidate.get(key) == item[key]:
                    return j
    return index if index < len(candidates) and index not in used else None


def losses(source, export, path='', field=''):
    """(field path, 'missing' | 'changed') of every value of `source` that the
    export doesn't have; values only in the export are ignored."""
    out = []
    if isinstance(source, dict) and field not in OPAQUE:
        target = export if isinstance(export, dict) else {}
        for key, value in source.items():
            sub = f'{path}.{key}' if path else key
            if key not in target:
                out.append((sub, 'missing'))
            else:
                out.extend(losses(value, target[key], sub, key))
    elif isinstance(source, list) and field not in OPAQUE:
        target = export if isinstance(export, list) else []
        used = set()
        for i, item in enumerate(source):
            j = _match(field, item, target, used, i)
            if j is None:
                out.append((f'{path}[]', 'missing'))
                continue
            used.add(j)
            out.extend(losses(item, target[j], f'{path}[]', field))
    elif not _same(field, source, export):
        out.append((path, 'changed'))
    return out


def _gap_of(path):
    for entry in KNOWN_GAPS:
        rx = re.escape(entry).replace(r'\*\.', r'(?:.*\.)?', 1)
        if re.match(rx + r'(?:$|[.\[])', path):
            return entry
    return None


def _upload(db_session, document):
    manager = _manager()
    # With "Create missing domains", so the file's domain is assigned and exported
    contract = manager.create_from_upload(
        db_session, copy.deepcopy(document), current_user='alice', create_missing_domains=True)
    db_session.commit()
    db_session.expire_all()
    stored = db_session.get(DataContractDb, contract.id)
    return manager, manager.build_odcs_from_db(stored, db_session)


@pytest.fixture
def document():
    return yaml.safe_load(DATA.read_text())


@pytest.fixture
def exported(db_session: Session, document):
    _, export = _upload(db_session, document)
    # The export is a YAML file: compare what a reader of that file gets
    return yaml.safe_load(yaml.safe_dump(export, sort_keys=False))


def test_every_field_round_trips_except_the_known_gaps(document, exported):
    lost = losses(document, exported)

    new = sorted({f'{path} ({kind})' for path, kind in lost if _gap_of(path) is None})
    assert not new, 'lost on upload + export:\n' + '\n'.join(new)


def test_no_known_gap_is_fixed(document, exported):
    seen = {_gap_of(path) for path, _ in losses(document, exported)}

    fixed = sorted(set(KNOWN_GAPS) - seen)
    assert not fixed, 'these round-trip now, remove them from KNOWN_GAPS: ' + ', '.join(fixed)


def test_the_export_is_valid_odcs_v3_1_0(exported):
    validator = jsonschema.Draft202012Validator(json.loads(SCHEMA.read_text()))

    errors = sorted(
        f"{'/'.join(map(str, e.absolute_path))}: {e.message[:160]}"
        for e in validator.iter_errors(exported)
    )
    assert not errors, '\n'.join(errors)


def _without_ontos_ids(document):
    """The export without what a re-import changes by design: the contract id
    and the ontos* provenance custom properties that carry it."""
    doc = copy.deepcopy(document)
    doc.pop('id', None)
    doc['customProperties'] = [
        cp for cp in doc.get('customProperties') or []
        if not str(cp.get('property', '')).startswith(('ontos', 'sourceId'))
    ]
    return doc


def test_a_reimport_of_the_export_exports_the_same(db_session, exported):
    _, again = _upload(db_session, exported)
    again = yaml.safe_load(yaml.safe_dump(again, sort_keys=False))

    lost = sorted({f'{p} ({k})' for p, k in losses(_without_ontos_ids(exported),
                                                   _without_ontos_ids(again))})
    assert not lost, 'lost on re-import:\n' + '\n'.join(lost)
