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

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from src.common.compliance_dsl import evaluate_rule_on_object

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


@dataclass
class RowDivergence:
    """The verdict for one evidence row."""
    diverged: bool
    signed: int                                  # +1 actual-exceeds-doc, -1 doc-exceeds-actual, 0 neutral
    reasons: List[str] = field(default_factory=list)
    weight: float = 1.0                          # max weight across this row's failed criteria
    dimension_weights: Dict[str, float] = field(default_factory=dict)  # {dimension: max weight of failed criteria this row}
    actor_identity: Optional[str] = None
    action: Optional[str] = None
    object_id: Optional[str] = None
    value: Optional[float] = None


@dataclass
class DnaResult:
    """The rolled-up DNA-Coefficient for a sample of rows."""
    magnitude: float                             # 0.0 = best, higher = worse (<= 1.0)
    direction: str
    sampled_count: int
    divergent_count: int
    dimensions: Dict[str, float] = field(default_factory=dict)  # per-dimension score 0-1 (evidence-based)
    rows: List[RowDivergence] = field(default_factory=list)


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

def evaluate_row(criteria: List[Criterion], row: Dict[str, Any]) -> RowDivergence:
    """Decide whether a single evidence row diverges, by running each criterion's
    rule against it: a criterion that **fails** is a divergence, contributing its
    ``weight`` to the row and its ``direction`` to the aggregate sign."""
    norm = normalize_row(row)
    reasons: List[str] = []
    weights: List[float] = []
    signed = 0
    dim_weights: Dict[str, float] = {}
    for c in criteria:
        try:
            passed, _ = evaluate_rule_on_object(c.rule, norm)
        except Exception:
            # A malformed rule must not fabricate divergence.
            passed = True
        if not passed:
            reasons.append(c.code)
            w = c.weight if c.weight is not None else 1.0
            weights.append(w)
            signed += _direction_sign(c.direction)
            dim = c.dimension or "people"
            dim_weights[dim] = max(dim_weights.get(dim, 0.0), w)

    diverged = len(reasons) > 0
    signed = (signed > 0) - (signed < 0)   # clamp to {-1, 0, +1}
    value = _to_float(norm.get("value"))
    return RowDivergence(
        diverged=diverged,
        signed=signed,
        reasons=reasons,
        weight=max(weights) if weights else 1.0,
        dimension_weights=dim_weights,
        actor_identity=str(norm["actor_identity"]) if norm.get("actor_identity") is not None else None,
        action=str(norm["action"]) if norm.get("action") is not None else None,
        object_id=str(norm["object_id"]) if norm.get("object_id") is not None else None,
        value=value,
    )


def compute_dnaco(criteria: List[Criterion], rows: List[Dict[str, Any]]) -> DnaResult:
    """Roll a sample of evidence rows up into per-dimension DNAco scores.

    Criteria are grouped by their ``dimension`` (e.g. ``people``). For each
    dimension, its score is the weighted fraction of rows that failed a criterion
    of that dimension (``0.0`` best, capped at ``1.0``). The evidence-side
    ``magnitude`` is the **additive** combine ``min(1.0, Σ dimension_scores)``
    (the manager adds non-evidence dimensions like ``structural`` and recomputes
    the overall). ``direction`` is the sign of the aggregate authority-level delta.
    """
    evaluated = [evaluate_row(criteria, r) for r in rows]
    sampled = len(evaluated)
    divergent = [rd for rd in evaluated if rd.diverged]
    dims = {(c.dimension or "people") for c in criteria}

    if sampled == 0:
        return DnaResult(magnitude=0.0, direction=DIR_NONE, sampled_count=0, divergent_count=0,
                         dimensions={d: 0.0 for d in dims}, rows=evaluated)

    dimensions = {
        d: round(min(1.0, sum(rd.dimension_weights.get(d, 0.0) for rd in divergent) / sampled), 4)
        for d in dims
    }
    magnitude = round(min(1.0, sum(dimensions.values())), 4)

    signed_total = sum(rd.signed for rd in divergent)
    if not divergent:
        direction = DIR_NONE
    elif signed_total > 0:
        direction = DIR_ACTUAL_EXCEEDS
    elif signed_total < 0:
        direction = DIR_DOCUMENTED_EXCEEDS
    else:
        direction = DIR_BALANCED

    return DnaResult(
        magnitude=magnitude,
        direction=direction,
        sampled_count=sampled,
        divergent_count=len(divergent),
        dimensions=dimensions,
        rows=evaluated,
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
