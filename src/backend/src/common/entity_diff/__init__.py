"""Version diff + semver classification for versioned entities (PRD #1086).

Entity-agnostic structural diff (``engine``), semver rule machinery
(``semver``) and per-format profiles/rule sets (``rules_odcs``; ODPS follows).
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .engine import DiffProfile, FieldChange, diff_documents
from .semver import (
    Bump,
    Classification,
    ClassifiedChange,
    Rule,
    RuleSet,
    classify,
    is_version_consistent,
    next_version,
)


class VersionFamilyMismatch(ValueError):
    """The two entities compared belong to different version families."""


class EntityNotFound(LookupError):
    """An entity to compare doesn't exist. (Dedicated so callers don't catch
    every LookupError — KeyError/IndexError are LookupErrors too.)"""


def family_key(row: Any) -> Optional[str]:
    """The version-family key, with the same fallback clones use."""
    return getattr(row, "version_family_id", None) or getattr(row, "id", None)


@dataclass
class ComparisonResult:
    classification: Classification
    base_document: Dict[str, Any]
    target_document: Dict[str, Any]
    base_version: Optional[str]
    target_version: Optional[str]

    @property
    def changes(self) -> List[ClassifiedChange]:
        return self.classification.changes

    @property
    def suggested_bump(self) -> Bump:
        return self.classification.bump

    @property
    def suggested_version(self) -> str:
        return next_version(self.base_version, self.suggested_bump)

    @property
    def version_consistent(self) -> Optional[bool]:
        return is_version_consistent(self.base_version, self.target_version, self.suggested_bump)


def compare(base: Dict[str, Any], target: Dict[str, Any], profile: DiffProfile,
            rule_set: RuleSet) -> ComparisonResult:
    """Diff two file-model documents and classify every change."""
    changes, base_n, target_n = diff_documents(base, target, profile)
    return ComparisonResult(
        classification=classify(changes, rule_set),
        base_document=base_n,
        target_document=target_n,
        base_version=(base or {}).get("version"),
        target_version=(target or {}).get("version"),
    )


__all__ = [
    "Bump",
    "Classification",
    "ClassifiedChange",
    "ComparisonResult",
    "DiffProfile",
    "EntityNotFound",
    "FieldChange",
    "Rule",
    "RuleSet",
    "VersionFamilyMismatch",
    "classify",
    "compare",
    "diff_documents",
    "family_key",
    "is_version_consistent",
    "next_version",
]
