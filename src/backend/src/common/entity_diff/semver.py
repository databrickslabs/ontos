"""Semver classification of structural diffs.

A rule set is an ordered list of ``Rule``s; the first rule whose shape pattern,
op and predicate all match a change decides that change's bump. Unmatched
changes fall back to the rule set's default (PATCH). The overall bump is the
highest bump across all changes.
"""

import re
from dataclasses import dataclass, field
from enum import IntEnum
from fnmatch import fnmatchcase
from typing import Callable, Iterable, List, Optional, Sequence, Tuple

from .engine import FieldChange


class Bump(IntEnum):
    NONE = 0
    PATCH = 1
    MINOR = 2
    MAJOR = 3

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Rule:
    """Classifies changes whose ``shape`` matches ``shape`` (fnmatch glob).

    ``ops`` limits the rule to added/removed/modified; ``when`` is an optional
    predicate over the change; ``bump`` may be a constant or a function of the
    change (for direction-dependent rules such as maxLength up vs. down).
    """
    rule_id: str
    shape: str
    bump: object  # Bump | Callable[[FieldChange], Bump]
    message: str
    ops: Tuple[str, ...] = ("added", "removed", "modified")
    when: Optional[Callable[[FieldChange], bool]] = None

    def matches(self, change: FieldChange) -> bool:
        if change.op not in self.ops or not fnmatchcase(change.shape, self.shape):
            return False
        return self.when is None or bool(self.when(change))

    def bump_for(self, change: FieldChange) -> Bump:
        return self.bump(change) if callable(self.bump) else self.bump


@dataclass(frozen=True)
class ClassifiedChange:
    path: str
    shape: str
    op: str
    old: object
    new: object
    bump: Bump
    rule_id: str
    message: str

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "op": self.op,
            "old": self.old,
            "new": self.new,
            "bump": self.bump.label,
            "rule_id": self.rule_id,
            "message": self.message,
        }


@dataclass
class RuleSet:
    rules: Sequence[Rule]
    default_bump: Bump = Bump.PATCH
    default_rule_id: str = "default"

    def classify_one(self, change: FieldChange) -> ClassifiedChange:
        for rule in self.rules:
            if rule.matches(change):
                return ClassifiedChange(change.path, change.shape, change.op, change.old, change.new,
                                        rule.bump_for(change), rule.rule_id, rule.message)
        return ClassifiedChange(change.path, change.shape, change.op, change.old, change.new,
                                self.default_bump, self.default_rule_id, f"{change.op.capitalize()} {change.path}")


@dataclass
class Classification:
    changes: List[ClassifiedChange] = field(default_factory=list)

    @property
    def bump(self) -> Bump:
        return max((c.bump for c in self.changes), default=Bump.NONE)

    def counts(self) -> dict:
        counts = {b.label: 0 for b in (Bump.MAJOR, Bump.MINOR, Bump.PATCH, Bump.NONE)}
        for c in self.changes:
            counts[c.bump.label] += 1
        return counts


def classify(changes: Iterable[FieldChange], rule_set: RuleSet) -> Classification:
    return Classification([rule_set.classify_one(c) for c in changes])


_SEMVER = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def parse_version(version: Optional[str]) -> Optional[Tuple[int, int, int]]:
    match = _SEMVER.match((version or "").strip())
    return tuple(int(g) for g in match.groups()) if match else None  # type: ignore[return-value]


def next_version(current: Optional[str], bump: Bump) -> str:
    """Next semver for ``bump``; NONE keeps the version. Unparseable → 1.0.0."""
    parsed = parse_version(current)
    if parsed is None:
        return "1.0.0"
    major, minor, patch = parsed
    if bump == Bump.MAJOR:
        return f"{major + 1}.0.0"
    if bump == Bump.MINOR:
        return f"{major}.{minor + 1}.0"
    if bump == Bump.PATCH:
        return f"{major}.{minor}.{patch + 1}"
    return f"{major}.{minor}.{patch}"


def version_bump_between(base: Optional[str], target: Optional[str]) -> Optional[Bump]:
    """The bump actually applied going from ``base`` to ``target`` (None if unparseable
    or if target is not newer)."""
    b, t = parse_version(base), parse_version(target)
    if b is None or t is None or t <= b:
        return None
    if t[0] > b[0]:
        return Bump.MAJOR
    if t[1] > b[1]:
        return Bump.MINOR
    return Bump.PATCH


def is_version_consistent(base: Optional[str], target: Optional[str], required: Bump) -> Optional[bool]:
    """Whether ``target`` reflects at least ``required`` relative to ``base``.

    None when it can't be judged (unparseable versions, or target not newer —
    e.g. comparing an older version against a newer one).
    """
    if required == Bump.NONE:
        return True
    applied = version_bump_between(base, target)
    if applied is None:
        return None
    return applied >= required
