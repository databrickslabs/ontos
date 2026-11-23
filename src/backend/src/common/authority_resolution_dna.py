"""DNA-Coefficient engine (v1) for the Authority Resolution feature.

Pure, dependency-free scoring so it is trivially unit-testable and free of any
DB or Databricks coupling. The manager feeds it evidence rows (dicts) read from
the AR's bound source; this module decides, per row, whether documented authority
diverged from what actually happened, and rolls the rows up into a single
DNA-Coefficient.

Polarity follows the ARF paper: the coefficient is a **divergence** — ``0.0``
means documented authority exactly matches lived practice, higher is worse.

v1 uses the *decision-log divergence* instrument only (Organizational Network
Analysis and structured elicitation are deferred composite terms). The exact
composite is Ontos-authored and expected to evolve under methodology review; it
is intentionally simple and explainable here. Admins may tune it per domain via
``scoring_config`` without changing this contract: the set of divergent rows and
the direction are stable; only the per-reason weight applied to the magnitude
changes.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.common.compliance_dsl import evaluate_rule_strict

# Direction flags (ARF `arf:direction`).
DIR_ACTUAL_EXCEEDS = "actual-exceeds-documented"
DIR_DOCUMENTED_EXCEEDS = "documented-exceeds-actual"
DIR_BALANCED = "balanced"
DIR_NONE = "none"

# Directions an author-configurable criterion may declare.
DIR_NEUTRAL = "neutral"


@dataclass
class Criterion:
    """One author-configurable decision criterion.

    ``rule`` is a Compliance-DSL rule (``ASSERT obj.<field> …``) evaluated against
    the decision request (gate) or a normalised evidence row (divergence). A
    criterion that *fails* is a denial (gate) or a divergence (DNAco), signed by
    ``direction`` and scaled by ``weight``. ``code`` labels the reason; ``message``
    is the human-readable denial text.
    """
    code: str
    rule: str
    direction: str = DIR_NEUTRAL
    weight: float = 1.0
    dimension: str = "people"                    # which DNAco dimension this criterion scores
    message: Optional[str] = None
    # How the runtime gate treats a failure (src.common.authority_rule): a check
    # or rule constraint denies, an unfulfilled duty makes the decision
    # conditional. The DNA engine counts every failure as a divergence.
    kind: str = "check"
    # The Authority Policy clause this criterion enforces; cited in denial reasons.
    clause: Optional[str] = None


@dataclass
class RowDivergence:
    """The verdict for one evidence row.

    ``contributions`` holds one ``(dimension, weight, sign, failed)`` tuple per check that
    was evaluated on the row. ``sign`` is the check's direction (+1 actual-exceeds-documented,
    -1 documented-exceeds-actual, 0 neutral). The engine reads these, not ``reasons``, so the
    per-dimension position and the per-row magnitude come from the same evaluation.
    """
    diverged: bool
    signed: int                                  # sign of the row's weighted position: +1, -1 or 0
    reasons: List[str] = field(default_factory=list)
    actor_identity: Optional[str] = None
    action: Optional[str] = None
    object_id: Optional[str] = None
    value: Optional[float] = None
    # The observation the row came from (ADM ``observation_id``), for provenance.
    ref: Optional[str] = None
    contributions: List[Tuple[str, float, int, bool]] = field(default_factory=list)
    # True when a criterion read an operand the row doesn't carry: the row is left out of
    # the sample (an unknown is not a divergence).
    skipped: bool = False


@dataclass
class DimensionScore:
    """One DNAco dimension (ADM section 8.2 style, but author-defined: ``people``, ``policy``...)."""
    position: float        # signed, weighted mean over the sample, in [-1, +1]
    magnitude: float       # share of sampled rows that failed a check of this dimension, in [0, 1]
    weight: float          # total weight of the dimension's evaluated checks


@dataclass
class DnaResult:
    """The DNA-Coefficient for a sample of rows (ADM v0.4 section 8, the signed form).

    ``magnitude`` is the share of sampled rows that diverge on *any* dimension, counted per
    row, so a row that diverges one way on one dimension and the other way on another still
    counts once and nothing cancels. ``position`` is the weighted signed mean over all
    checks, in [-1, +1]. The activation ceiling gates on ``magnitude``.
    """
    magnitude: float
    position: float
    direction: str
    sampled_count: int
    divergent_count: int
    dimensions: Dict[str, DimensionScore] = field(default_factory=dict)
    rows: List[RowDivergence] = field(default_factory=list)
    # Rows that lack an operand a criterion reads: not measured, not divergent (see RowDivergence.skipped).
    skipped_count: int = 0


def combine_dimensions(scores: Iterable[float]) -> float:
    """Combine per-dimension divergence scores into one overall value in [0, 1].

    Retained for the legacy (noisy-OR) runs that persisted it, and as a reference for
    the probabilistic union. The DNA-Coefficient no longer uses it (#1294 slice 4, S5): the
    magnitude is the per-row share in :func:`compute_dnaco`.
    """
    product = 1.0
    for s in scores:
        product *= (1.0 - max(0.0, min(1.0, s)))
    return round(1.0 - product, 4)


# --------------------------------------------------------------------------- #
# Coercion helpers — evidence columns may arrive as strings, ints, bools, etc. #
# --------------------------------------------------------------------------- #

def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().rstrip("%")
    try:
        return float(s)
    except ValueError:
        return None


def _truthy(v: Any) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    return str(v).strip().lower() in {"1", "true", "yes", "y", "t", "present", "signed"}


# Canonical request/evidence fields whose types we coerce before DSL evaluation
# (evidence columns arrive as strings; the DSL compares strictly).
_NUMERIC_FIELDS = ("value",)
_BOOL_FIELDS = ("escalated", "cosign_present")


def normalize_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Coerce a request/evidence row's known fields to comparable Python types so
    author DSL rules (``obj.value <= 0.15``, ``obj.escalated = True``) evaluate
    correctly against raw evidence columns."""
    out = dict(row)
    for f in _NUMERIC_FIELDS:
        if f in out and out[f] is not None:
            fv = _to_float(out[f])
            if fv is not None:
                out[f] = fv
    for f in _BOOL_FIELDS:
        if f in out and out[f] is not None:
            out[f] = _truthy(out[f])
    return out


def _direction_sign(direction: Optional[str]) -> int:
    if direction == DIR_ACTUAL_EXCEEDS:
        return 1
    if direction == DIR_DOCUMENTED_EXCEEDS:
        return -1
    return 0


# --------------------------------------------------------------------------- #
# Core evaluation                                                             #
# --------------------------------------------------------------------------- #

_ASSERT_CLAUSE_RE = re.compile(r"^\s*(?:MATCH\s*\([^)]*\)\s*)?ASSERT\b", re.S)


def has_assert_clause(rule: Optional[str]) -> bool:
    """True for ``ASSERT …`` or ``MATCH (…) ASSERT …`` (keyword case as the
    evaluator expects); an 'ASSERT' inside a literal does not count."""
    return bool(rule and _ASSERT_CLAUSE_RE.match(rule))


def rule_parse_error(rule: Optional[str]) -> Optional[str]:
    """Why ``rule`` can't be parsed, or None. ``evaluate_rule_on_object`` folds
    parse errors into an ordinary failure, so callers check this first to tell
    a malformed rule (configuration error) from a failing one (policy result)."""
    from src.common.compliance_dsl import Lexer, Parser

    m = _ASSERT_CLAUSE_RE.match(rule or "")
    if not m:
        return "rule must contain an ASSERT clause"
    try:
        Parser(Lexer(rule[m.end():].strip()).tokenize()).parse_expression()
    except Exception as e:
        return str(e) or type(e).__name__
    return None


def evaluate_row(criteria: List[Criterion], row: Dict[str, Any]) -> RowDivergence:
    """Decide whether a single evidence row diverges, by running each criterion's
    rule against it: a criterion that **fails** is a divergence on its dimension.

    Every evaluated check contributes ``(dimension, weight, sign, failed)``; the sign is
    the check's direction, zeroed when the check passes.
    """
    norm = normalize_row(row)
    reasons: List[str] = []
    contributions: List[Tuple[str, float, int, bool]] = []
    for c in criteria:
        if rule_parse_error(c.rule):
            # A malformed rule must not fabricate divergence.
            continue
        outcome = evaluate_rule_strict(c.rule, norm)
        if outcome.passed is None:
            # The row lacks an operand the criterion reads: it can't be measured, so it
            # is skipped (and counted in the run's notes), never a divergence.
            return RowDivergence(
                diverged=False, signed=0, skipped=True,
                actor_identity=str(norm["actor_identity"]) if norm.get("actor_identity") is not None else None,
                action=str(norm["action"]) if norm.get("action") is not None else None,
                object_id=str(norm["object_id"]) if norm.get("object_id") is not None else None,
                value=_to_float(norm.get("value")),
            )
        w = float(c.weight if c.weight is not None else 1.0)
        # Only a check with weight above zero can diverge. A weight-0 check is informational:
        # it is evaluated and shown, but never makes a row diverge or moves the magnitude.
        gating = (not outcome.passed) and w > 0
        if gating:
            reasons.append(c.code)
        contributions.append((c.dimension or "people", w, _direction_sign(c.direction), gating))

    weight_total = sum(w for _, w, _, _ in contributions)
    signed_total = sum(w * sign for _, w, sign, failed in contributions if failed)
    position = signed_total / weight_total if weight_total > 0 else 0.0
    return RowDivergence(
        diverged=bool(reasons),
        signed=(position > 0) - (position < 0),
        reasons=reasons,
        actor_identity=str(norm["actor_identity"]) if norm.get("actor_identity") is not None else None,
        action=str(norm["action"]) if norm.get("action") is not None else None,
        object_id=str(norm["object_id"]) if norm.get("object_id") is not None else None,
        value=_to_float(norm.get("value")),
        ref=str(norm["observation_id"]) if norm.get("observation_id") is not None else None,
        contributions=contributions,
    )


def compute_dnaco(criteria: List[Criterion], rows: List[Dict[str, Any]]) -> DnaResult:
    """Roll a sample of evidence rows up into the signed DNA-Coefficient.

    Per dimension, the **position** is the weighted signed mean of the checks over the
    sample, in [-1, +1]: a failed check contributes its direction times its weight, a
    passed check contributes zero. The combined position uses every dimension's weight.

    The **magnitude** is the share of sampled rows that fail a check on any dimension,
    counted once per row (no cancellation between dimensions or directions). It replaces
    the earlier noisy-OR over per-dimension scores (#1294 S5, N3). The per-dimension
    magnitude is the share of rows failing a check of that dimension.

    ``direction`` is the sign of the combined position when there is any divergence.
    """
    evaluated = [evaluate_row(criteria, r) for r in rows]
    skipped_count = sum(1 for rd in evaluated if rd.skipped)
    evaluated = [rd for rd in evaluated if not rd.skipped]
    sampled = len(evaluated)
    divergent = [rd for rd in evaluated if rd.diverged]
    dims = sorted({(c.dimension or "people") for c in criteria})

    if sampled == 0:
        return DnaResult(
            magnitude=0.0, position=0.0, direction=DIR_NONE, sampled_count=0, divergent_count=0,
            dimensions={d: DimensionScore(0.0, 0.0, 0.0) for d in dims}, rows=evaluated,
            skipped_count=skipped_count,
        )

    weight = {d: 0.0 for d in dims}
    signed = {d: 0.0 for d in dims}
    failing_rows = {d: 0 for d in dims}
    for rd in evaluated:
        failed_here = set()
        for dim, w, sign, failed in rd.contributions:
            weight[dim] += w
            if failed:
                signed[dim] += w * sign
                failed_here.add(dim)
        for dim in failed_here:
            failing_rows[dim] += 1

    dimensions = {
        d: DimensionScore(
            position=round(max(-1.0, min(1.0, signed[d] / weight[d])), 4) if weight[d] > 0 else 0.0,
            magnitude=round(failing_rows[d] / sampled, 4),
            weight=round(weight[d], 4),
        )
        for d in dims
    }
    total_weight = sum(weight.values())
    combined = round(max(-1.0, min(1.0, sum(signed.values()) / total_weight)), 4) if total_weight > 0 else 0.0
    magnitude = round(len(divergent) / sampled, 4)

    if not divergent:
        direction = DIR_NONE
    elif combined > 0:
        direction = DIR_ACTUAL_EXCEEDS
    elif combined < 0:
        direction = DIR_DOCUMENTED_EXCEEDS
    else:
        direction = DIR_BALANCED

    return DnaResult(
        magnitude=magnitude,
        position=combined,
        direction=direction,
        sampled_count=sampled,
        divergent_count=len(divergent),
        dimensions=dimensions,
        rows=evaluated,
        skipped_count=skipped_count,
    )


def maturity_level(*, has_object: bool, dna_measured: bool, fully_affirmed: bool) -> str:
    """Derive the ARF Authority Maturity Level (L0-L5) from AR state.

    L5 (agent-design audited) is out of scope for this feature and never returned.
    """
    if fully_affirmed and dna_measured:
        return "L4"          # Tri/N-Functionally-Affirmed
    if dna_measured:
        return "L3"          # DNA-Measured
    if has_object:
        return "L2"          # Object-Resolved
    return "L1"              # Documented
