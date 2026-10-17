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


def _base_keys(items: List[Any], shape: str, profile: DiffProfile) -> List[str]:
    keys = []
    for item in items:
        key = profile.identity(item, shape) if isinstance(item, dict) else None
        keys.append(key if key is not None else _content_key(item))
    return keys


def _repeated(keys: List[str]) -> set:
    seen, repeated = set(), set()
    for key in keys:
        (repeated if key in seen else seen).add(key)
    return repeated


def _keyed(items: List[Any], base_keys: List[str], qualify: set) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Map list items to identity keys.

    Keys in ``qualify`` (repeated on either side — e.g. two ODPS output ports
    both named ``orders`` at different versions) are qualified with the item's
    ``version`` when it has one; any remaining clash gets a positional suffix.
    Also returns each final key's base key.
    """
    keyed: Dict[str, Any] = {}
    bases: Dict[str, str] = {}
    for item, key in zip(items, base_keys, strict=True):
        base_key = key
        if key in qualify and isinstance(item, dict) and item.get("version") is not None:
            key = f"{key}@{item['version']}"
        base, n = key, 2
        while key in keyed:
            key = f"{base}~{n}"
            n += 1
        keyed[key] = item
        bases[key] = base_key
    return keyed, bases


def _pair_lone_leftovers(old_map: Dict[str, Any], old_bases: Dict[str, str],
                         new_map: Dict[str, Any], new_bases: Dict[str, str]) -> None:
    """After version-qualifying repeated keys, an item whose version changed no
    longer matches (orders@2.0.0 vs orders@2.1.0). When exactly one unmatched
    item per base key is left on each side, pair them (re-key the new one) so
    the change reads as a modification, not a removal + addition."""
    def leftovers(mapping, bases, other):
        grouped: Dict[str, List[str]] = {}
        for key in mapping:
            if key not in other:
                grouped.setdefault(bases[key], []).append(key)
        return grouped

    old_left = leftovers(old_map, old_bases, new_map)
    new_left = leftovers(new_map, new_bases, old_map)
    for base, old_keys in old_left.items():
        new_keys = new_left.get(base, [])
        if len(old_keys) == 1 and len(new_keys) == 1:
            new_map[old_keys[0]] = new_map.pop(new_keys[0])


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
        old_keys, new_keys = _base_keys(old, shape, profile), _base_keys(new, shape, profile)
        qualify = _repeated(old_keys) | _repeated(new_keys)
        old_map, old_bases = _keyed(old, old_keys, qualify)
        new_map, new_bases = _keyed(new, new_keys, qualify)
        if qualify:
            _pair_lone_leftovers(old_map, old_bases, new_map, new_bases)
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


def without_ignored(doc: Any, profile: DiffProfile, shape: str = "") -> Any:
    """Drop the profile's ignored fields — for display (e.g. the YAML text
    diff), so it doesn't show changes the structural diff deliberately hides."""
    if isinstance(doc, dict):
        out: Dict[str, Any] = {}
        for key, value in doc.items():
            child_shape = f"{shape}.{key}" if shape else key
            if not profile.ignore(child_shape):
                out[key] = without_ignored(value, profile, child_shape)
        return out
    if isinstance(doc, list):
        return [without_ignored(v, profile, f"{shape}[]") for v in doc]
    return doc
