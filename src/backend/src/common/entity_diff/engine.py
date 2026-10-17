"""Generic structural diff over JSON-like documents (dicts / lists / scalars).

Used to compare two versions of a versioned entity rendered as its file model
(ODCS for contracts, ODPS for products). The engine is entity-agnostic: a
``DiffProfile`` supplies how list items are identified (so lists of objects are
matched by key, not by index) and which fields are volatile and dropped before
comparison.

Paths are reported two ways:
- ``path``:  concrete, human-readable — ``schema[orders].properties[id].logicalType``
- ``shape``: the same path with list identities erased — ``schema[].properties[].logicalType``.
  Semver rules match on ``shape`` so one rule covers every schema/property.
"""

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

# Identity function for list items: (item, shape_of_the_list) -> key, or None
# when the item can't be keyed (falls back to a content hash).
IdentityFn = Callable[[Dict[str, Any], str], Optional[str]]

# Strip predicate: (shape, value) -> True to drop a dict field or list item
# (list items are offered with their ``...[]`` shape) before diffing.
StripFn = Callable[[str, Any], bool]

# Ignore predicate: shape -> True for fields that are never reported as changes
# but stay in the document, so identity functions can still match on them
# (e.g. ODCS stable ``id``s: identity metadata, not content).
IgnoreFn = Callable[[str], bool]


@dataclass(frozen=True)
class FieldChange:
    """One leaf- or subtree-level difference between two documents."""
    path: str
    shape: str
    op: str  # "added" | "removed" | "modified"
    old: Any = None
    new: Any = None


@dataclass
class DiffProfile:
    """Entity-specific knobs for the generic diff."""
    identity: IdentityFn
    strip: StripFn = field(default=lambda shape, value: False)
    ignore: IgnoreFn = field(default=lambda shape: False)


def _is_empty(value: Any) -> bool:
    return value is None or value == [] or value == {}


def _content_key(item: Any) -> str:
    raw = json.dumps(item, sort_keys=True, default=str)
    return "#" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:8]


def normalize(doc: Any, profile: DiffProfile, shape: str = "") -> Any:
    """Drop volatile and empty fields so None / [] / {} / missing compare equal."""
    if isinstance(doc, dict):
        out: Dict[str, Any] = {}
        for key, value in doc.items():
            child_shape = f"{shape}.{key}" if shape else key
            if profile.strip(child_shape, value):
                continue
            value = normalize(value, profile, child_shape)
            if not _is_empty(value):
                out[key] = value
        return out
    if isinstance(doc, list):
        item_shape = f"{shape}[]"
        items = [normalize(v, profile, item_shape) for v in doc if not profile.strip(item_shape, v)]
        return [v for v in items if not _is_empty(v)]
    return doc


def _keyed(items: List[Any], shape: str, profile: DiffProfile) -> Dict[str, Any]:
    """Map list items to identity keys; duplicate keys get a positional suffix."""
    keyed: Dict[str, Any] = {}
    for item in items:
        key = profile.identity(item, shape) if isinstance(item, dict) else None
        key = key if key is not None else _content_key(item)
        base, n = key, 2
        while key in keyed:
            key = f"{base}~{n}"
            n += 1
        keyed[key] = item
    return keyed


def _is_scalar_list(items: List[Any]) -> bool:
    return all(not isinstance(v, (dict, list)) for v in items)


def _walk(old: Any, new: Any, path: str, shape: str, profile: DiffProfile,
          out: List[FieldChange]) -> None:
    if isinstance(old, dict) and isinstance(new, dict):
        for key in list(old.keys()) + [k for k in new.keys() if k not in old]:
            child_path = f"{path}.{key}" if path else key
            child_shape = f"{shape}.{key}" if shape else key
            if profile.ignore(child_shape):
                continue
            # A missing side is diffed as an empty container of the other side's
            # type, so emptying a list reports per-item removals (which item
            # rules can classify) rather than one opaque "field removed".
            if key not in new:
                if isinstance(old[key], (dict, list)):
                    _walk(old[key], type(old[key])(), child_path, child_shape, profile, out)
                else:
                    out.append(FieldChange(child_path, child_shape, "removed", old=old[key]))
            elif key not in old:
                if isinstance(new[key], (dict, list)):
                    _walk(type(new[key])(), new[key], child_path, child_shape, profile, out)
                else:
                    out.append(FieldChange(child_path, child_shape, "added", new=new[key]))
            else:
                _walk(old[key], new[key], child_path, child_shape, profile, out)
        return

    if isinstance(old, list) and isinstance(new, list):
        item_shape = f"{shape}[]"
        if _is_scalar_list(old) and _is_scalar_list(new):
            # Scalar lists (tags, enum values) are compared as sets.
            for value in old:
                if value not in new:
                    out.append(FieldChange(f"{path}[{value}]", item_shape, "removed", old=value))
            for value in new:
                if value not in old:
                    out.append(FieldChange(f"{path}[{value}]", item_shape, "added", new=value))
            return
        old_map = _keyed(old, shape, profile)
        new_map = _keyed(new, shape, profile)
        for key in list(old_map.keys()) + [k for k in new_map.keys() if k not in old_map]:
            item_path = f"{path}[{key}]"
            if key not in new_map:
                out.append(FieldChange(item_path, item_shape, "removed", old=old_map[key]))
            elif key not in old_map:
                out.append(FieldChange(item_path, item_shape, "added", new=new_map[key]))
            else:
                _walk(old_map[key], new_map[key], item_path, item_shape, profile, out)
        return

    if old != new:
        out.append(FieldChange(path, shape, "modified", old=old, new=new))


def diff_documents(old: Dict[str, Any], new: Dict[str, Any],
                   profile: DiffProfile) -> Tuple[List[FieldChange], Dict[str, Any], Dict[str, Any]]:
    """Diff two documents.

    Returns the changes plus both normalized documents (callers render the
    normalized forms as YAML so the text diff agrees with the structural one).
    """
    old_n = normalize(old or {}, profile)
    new_n = normalize(new or {}, profile)
    changes: List[FieldChange] = []
    _walk(old_n, new_n, "", "", profile, changes)
    return changes, old_n, new_n
