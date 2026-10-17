"""Turn a comparison into the API response (structured changes + YAML diff)."""

import difflib
import json
from typing import Any, Dict

import yaml

from . import ComparisonResult, DiffProfile, RuleSet, compare
from .engine import without_ignored
from .semver import Bump, next_version


def to_plain(doc: Any) -> Any:
    """JSON round-trip so builder output (datetimes, enums, Decimals) diffs and
    serializes as plain strings/numbers — the same values a YAML export shows."""
    return json.loads(json.dumps(doc, default=str))


def to_yaml(doc: Dict[str, Any]) -> str:
    return yaml.safe_dump(doc, default_flow_style=False, sort_keys=False, allow_unicode=True)


def unified_yaml_diff(base_doc: Dict[str, Any], target_doc: Dict[str, Any],
                      base_label: str, target_label: str, context: int = 3) -> str:
    """Unified diff of two documents rendered as YAML. Callers pass the
    normalized documents with ignored fields removed, so the text view agrees
    with the structural changes."""
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
            without_ignored(result.base_document, profile), without_ignored(result.target_document, profile),
            f"{base_meta.get('name') or 'base'} {base_meta.get('version') or ''}".strip(),
            f"{target_meta.get('name') or 'target'} {target_meta.get('version') or ''}".strip(),
        ),
    }


_LEGACY_CHANGE_TYPE = {"major": "breaking", "minor": "feature", "patch": "fix", "none": "none"}


def _legacy_line(change: Dict[str, Any]) -> str:
    return f"{change['message']}: {change['path']}"


def legacy_parent_diff(diff: Dict[str, Any]) -> Dict[str, Any]:
    """Shape an engine diff (draft vs. parent) like the legacy
    ``get_diff_from_parent`` response the commit-draft dialogs consume.

    A commit always mints a new version, so "no change" still suggests a
    patch bump (the dialogs' radio group has no "none").
    """
    changes = diff["changes"]
    by_bump = {b: [_legacy_line(c) for c in changes if c["bump"] == b] for b in ("major", "minor", "patch")}
    bump = diff["suggested_bump"]
    sections = [
        (f"Breaking changes ({len(by_bump['major'])})", by_bump["major"]),
        (f"New features ({len(by_bump['minor'])})", by_bump["minor"]),
        (f"Improvements ({len(by_bump['patch'])})", by_bump["patch"]),
    ]
    summary = "\n\n".join(
        title + ":\n" + "\n".join(f"- {line}" for line in lines) for title, lines in sections if lines
    ) or "No significant changes detected"
    suggested_bump = bump if bump != "none" else "patch"
    parent_version = diff["base"]["version"] or "0.0.0"
    return {
        "parent_id": diff["base"]["id"],
        "parent_version": parent_version,
        "parent_status": diff["base"]["status"],
        "suggested_bump": suggested_bump,
        "suggested_version": next_version(parent_version, Bump[suggested_bump.upper()]),
        "analysis": {
            "change_type": _LEGACY_CHANGE_TYPE[bump],
            "version_bump": bump,
            "summary": summary,
            "breaking_changes": by_bump["major"],
            "new_features": by_bump["minor"],
            "fixes": by_bump["patch"],
            "changes": changes,
            "counts": diff["counts"],
        },
    }
