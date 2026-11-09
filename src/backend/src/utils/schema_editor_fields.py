"""Fields of a schema object the schema editor doesn't send.

Saving a schema in the contract's schema editor recreates the schema object
from the payload. The editor only loads and sends some fields (names, types,
descriptions, granularity, relationships, semantic concepts, the columns and
their custom properties); the others are kept from the stored object when the
payload leaves them out: the ODCS ids, tags, custom properties and quality
checks of the object, the ids, quality checks, relationships and tags of its
columns, and authoritative definitions other than semantic concepts.
"""
from typing import Any, Dict, List, Optional

SEMANTIC_ASSIGNMENT = 'http://databricks.com/ontology/uc/semanticAssignment'

_OBJECT_FIELDS = ('id', 'tags', 'customProperties', 'quality')
_PROPERTY_FIELDS = ('id', 'quality', 'relationships', 'tags', 'itemType')


def _sent(payload: Dict[str, Any], key: str) -> bool:
    return payload.get(key) is not None


def _definitions(sent: Optional[List[Dict[str, Any]]], stored: Optional[List[Dict[str, Any]]]):
    """The editor's semantic concepts, plus the stored definitions of other
    types (the editor neither shows nor sends those). The editor sends no
    definitions at all when it has no concepts, so a stored concept the
    payload doesn't have was removed."""
    merged = [dict(d) for d in sent or []]
    seen = {(d.get('url'), d.get('type')) for d in merged}
    for d in stored or []:
        if d.get('type') == SEMANTIC_ASSIGNMENT:
            continue
        if (d.get('url'), d.get('type')) not in seen:
            merged.append(dict(d))
    return merged or None


def keep_unsent_fields(payload: Dict[str, Any], stored: Dict[str, Any]) -> Dict[str, Any]:
    """The schema object of an editor save, completed with the stored values of
    the fields it doesn't send. `stored` is the object as the ODCS export
    writes it."""
    merged = dict(payload)
    for key in _OBJECT_FIELDS:
        if not _sent(merged, key) and stored.get(key) is not None:
            merged[key] = stored[key]
    definitions = _definitions(merged.get('authoritativeDefinitions'), stored.get('authoritativeDefinitions'))
    if definitions is not None:
        merged['authoritativeDefinitions'] = definitions

    stored_columns = {p.get('name'): p for p in stored.get('properties') or []}
    columns = []
    for column in merged.get('properties') or []:
        column = column.model_dump(by_alias=True, exclude_unset=True) if hasattr(column, 'model_dump') else dict(column)
        previous = stored_columns.get(column.get('name'))
        if previous:
            for key in _PROPERTY_FIELDS:
                if not _sent(column, key) and previous.get(key) is not None:
                    column[key] = previous[key]
            definitions = _definitions(column.get('authoritativeDefinitions'), previous.get('authoritativeDefinitions'))
            if definitions is not None:
                column['authoritativeDefinitions'] = definitions
        columns.append(column)
    merged['properties'] = columns
    return merged
