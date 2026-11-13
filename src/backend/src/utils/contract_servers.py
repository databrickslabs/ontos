"""The ODCS fields of a contract server.

A server row has the common fields (``id``, ``server``, ``type``,
``description``, ``environment``) as columns and its ``roles`` and
``customProperties`` as JSON. Every other field of the server's type
(``host``, ``port``, ``format``, ``stagingDir``, ``serviceName`` ...) is a
key/value row, so the fields of every ODCS server type round-trip, including
the ones a type requires (``format`` for azure, ``dataset`` for bigquery ...).
"""
import json
from typing import Any, Dict, List, Optional

# Server fields that are columns of the server row (or JSON columns), not key/value rows
SERVER_COLUMNS = ('id', 'server', 'type', 'description', 'environment', 'roles',
                  'customProperties', 'properties')
# ODCS server fields that are not strings
_INTEGER_FIELDS = ('port',)


def property_values(server: Dict[str, Any]) -> Dict[str, str]:
    """The key/value rows of an ODCS server: its type's fields, then the
    entries of the Ontos ``properties`` map (the server form's extra fields)."""
    values: Dict[str, str] = {}
    extra = server.get('properties')
    items = list(server.items()) + list((extra if isinstance(extra, dict) else {}).items())
    for key, value in items:
        if key in SERVER_COLUMNS or value is None:
            continue
        values[key] = value if isinstance(value, str) else json.dumps(value)
    return values


def odcs_property_value(key: str, text: Optional[str]) -> Any:
    """A stored server field as ODCS has it: ``port`` as a number, a JSON
    object or array decoded, any other text as is."""
    if text is None:
        return None
    if key in _INTEGER_FIELDS:
        try:
            return int(text)
        except ValueError:
            return text
    if text[:1] in ('[', '{'):
        try:
            return json.loads(text)
        except ValueError:
            return text
    return text


def json_list_text(value: Any) -> Optional[str]:
    """``roles`` / ``customProperties`` for their JSON column."""
    return json.dumps(value) if value else None


def json_list(text: Optional[str]) -> Optional[List[Any]]:
    """A JSON column back as a list (``None`` when empty or unreadable)."""
    if not text:
        return None
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, list) and value else None


def keep_unsent_server_fields(servers: List[Dict[str, Any]], stored: List[Any]) -> None:
    """Complete the servers of a contract page save with the stored ``roles``
    and ``customProperties`` of a server the payload names without them (the
    server form doesn't edit them). A server is matched by its ODCS id, else by
    its ``server`` identifier."""
    by_id = {s.stable_id: s for s in stored if s.stable_id}
    by_name = {s.server: s for s in stored if s.server}
    for server in servers:
        row = by_id.get(server.get('id')) or by_name.get(server.get('server'))
        if row is None:
            continue
        if not server.get('id') and row.stable_id:
            server['id'] = row.stable_id
        if server.get('roles') is None and row.roles_json:
            server['roles'] = json_list(row.roles_json)
        if server.get('customProperties') is None and row.custom_properties_json:
            server['customProperties'] = json_list(row.custom_properties_json)
