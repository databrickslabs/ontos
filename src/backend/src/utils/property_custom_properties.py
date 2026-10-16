"""Property-level (column) and schema-object ODCS customProperties.

ODCS lets every schema object and property carry ``customProperties``. They arrive in two
shapes: the ODCS list ``[{"property": ..., "value": ..., "id": ...}]`` (file
import, ODCS payloads) and the ``{name: value}`` dict the schema property editor
sends. Values are stored as JSON so they round-trip with their type (an Avro
field number stays a number, a string stays a string).
"""
import json
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from src.db_models.data_contracts import SchemaObjectCustomPropertyDb, SchemaPropertyCustomPropertyDb


def property_custom_property_rows(
    property_id: str, custom_props: Any, previous_ids: Optional[Dict[str, str]] = None,
) -> List[SchemaPropertyCustomPropertyDb]:
    """Rows for ``custom_props`` (list or dict form) of the property ``property_id``.

    ``previous_ids`` maps a custom property name to the ODCS id it had before
    the property was recreated: the dict form carries no ids, so an edit in the
    schema property editor keeps them this way.
    """
    if isinstance(custom_props, dict):
        entries = [{'property': k, 'value': v} for k, v in custom_props.items()]
    elif isinstance(custom_props, list):
        entries = [e for e in custom_props if isinstance(e, dict)]
    else:
        return []
    rows = []
    for entry in entries:
        name = entry.get('property')
        if not name:
            continue
        rows.append(SchemaPropertyCustomPropertyDb(
            property_id=property_id,
            stable_id=entry.get('id') or (previous_ids or {}).get(name),
            property=name,
            value=json.dumps(entry.get('value')),
        ))
    return rows


def object_custom_property_rows(
    schema_object_id: str, custom_props: Any,
) -> List[SchemaObjectCustomPropertyDb]:
    """Rows for the ``customProperties`` (list or dict form) of a schema object."""
    if isinstance(custom_props, dict):
        entries = [{'property': k, 'value': v} for k, v in custom_props.items()]
    elif isinstance(custom_props, list):
        entries = [e for e in custom_props if isinstance(e, dict)]
    else:
        return []
    return [
        SchemaObjectCustomPropertyDb(
            schema_object_id=schema_object_id,
            stable_id=entry.get('id'),
            property=entry['property'],
            value=json.dumps(entry.get('value')),
        )
        for entry in entries if entry.get('property')
    ]


def decode_value(raw: Optional[str]) -> Any:
    """The stored value; text that isn't JSON (e.g. written by hand) as is."""
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return raw


def odcs_custom_properties(rows: Iterable[SchemaPropertyCustomPropertyDb]) -> List[Dict[str, Any]]:
    """The ODCS list form, for export."""
    out = []
    for row in rows:
        item: Dict[str, Any] = {'property': row.property, 'value': decode_value(row.value)}
        if row.stable_id:
            item['id'] = row.stable_id
        out.append(item)
    return out


def custom_properties_by_property(
    db: Session, property_ids: List[str],
) -> Dict[str, Dict[str, Any]]:
    """``{property_id: {name: value}}`` for the API, in one query."""
    if not property_ids:
        return {}
    rows = (
        db.query(SchemaPropertyCustomPropertyDb)
        .filter(SchemaPropertyCustomPropertyDb.property_id.in_(property_ids))
        .all()
    )
    out: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        out.setdefault(row.property_id, {})[row.property] = decode_value(row.value)
    return out


def stable_ids_by_property(db: Session, schema_object_id: str) -> Dict[str, Dict[str, str]]:
    """``{property name: {custom property name: ODCS id}}`` of a schema object,
    read before the object is recreated."""
    from src.db_models.data_contracts import SchemaPropertyDb

    rows = (
        db.query(SchemaPropertyDb.name, SchemaPropertyCustomPropertyDb.property,
                 SchemaPropertyCustomPropertyDb.stable_id)
        .join(SchemaPropertyCustomPropertyDb,
              SchemaPropertyCustomPropertyDb.property_id == SchemaPropertyDb.id)
        .filter(SchemaPropertyDb.object_id == schema_object_id,
                SchemaPropertyCustomPropertyDb.stable_id.isnot(None))
        .all()
    )
    out: Dict[str, Dict[str, str]] = {}
    for prop_name, cp_name, stable_id in rows:
        out.setdefault(prop_name, {})[cp_name] = stable_id
    return out
