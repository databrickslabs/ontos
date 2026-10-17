"""Turn a comparison into the API response (structured changes + YAML diff)."""

import difflib
import json
from typing import Any, Dict

import yaml

from . import ComparisonResult, DiffProfile, RuleSet, compare


def to_plain(doc: Any) -> Any:
    """JSON round-trip so builder output (datetimes, enums, Decimals) diffs and
    serializes as plain strings/numbers — the same values a YAML export shows."""
    return json.loads(json.dumps(doc, default=str))


def to_yaml(doc: Dict[str, Any]) -> str:
    return yaml.safe_dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def unified_yaml_diff(base_doc: Dict[str, Any], target_doc: Dict[str, Any],
                      base_label: str, target_label: str, context: int = 3) -> str:
    """Unified diff of the two normalized documents rendered as YAML, so the
    text view agrees with the structural changes (volatile fields stripped)."""
    return "".join(difflib.unified_diff(
        to_yaml(base_doc).splitlines(keepends=True),
        to_yaml(target_doc).splitlines(keepends=True),
        fromfile=base_label,
        tofile=target_label,
        n=context,
    ))


def _ref(meta: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": meta.get("id"), "name": meta.get("name"), "version": meta.get("version"),
            "status": meta.get("status")}


def build_diff_response(entity_type: str, base_meta: Dict[str, Any], target_meta: Dict[str, Any],
                        base_doc: Dict[str, Any], target_doc: Dict[str, Any],
                        profile: DiffProfile, rule_set: RuleSet) -> Dict[str, Any]:
    """Compare two file-model documents and shape the response.

    ``*_meta`` carry the rows' id/name/version/status (the documents' own
    ``version`` is stripped by the profiles, so versions come from here).
    """
    result: ComparisonResult = compare(to_plain(base_doc), to_plain(target_doc), profile, rule_set)
    result.base_version = base_meta.get("version")
    result.target_version = target_meta.get("version")
    return {
        "entity_type": entity_type,
        "base": _ref(base_meta),
        "target": _ref(target_meta),
        "changes": [c.to_dict() for c in result.changes],
        "counts": result.classification.counts(),
        "suggested_bump": result.suggested_bump.label,
        "suggested_version": result.suggested_version,
        "version_consistent": result.version_consistent,
        "unified_diff": unified_yaml_diff(
            result.base_document, result.target_document,
            f"{base_meta.get('name') or 'base'} {base_meta.get('version') or ''}".strip(),
            f"{target_meta.get('name') or 'target'} {target_meta.get('version') or ''}".strip(),
        ),
    }
