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

# Direction flags (ARF `arf:direction`).
DIR_ACTUAL_EXCEEDS = "actual-exceeds-documented"
DIR_DOCUMENTED_EXCEEDS = "documented-exceeds-actual"
DIR_BALANCED = "balanced"
DIR_NONE = "none"


@dataclass
class ARSpec:
    """The *documented* half of the comparison, extracted from the AR Definition."""
    documented_approver: Optional[str] = None   # actor_identity / heldBy
    threshold: Optional[float] = None            # domain_context.threshold
    action: Optional[str] = None
    required_cosign: bool = False                # whether a co-sign is documented as required


@dataclass
class RowDivergence:
    """The verdict for one evidence row."""
    diverged: bool
    signed: int                                  # +1 actual-exceeds-doc, -1 doc-exceeds-actual, 0 neutral
    reasons: List[str] = field(default_factory=list)
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


def _get(row: Dict[str, Any], column_map: Dict[str, str], key: str) -> Any:
    """Fetch an AR element from a row via the column map. Returns None if unmapped/missing."""
    col = column_map.get(key)
    if not col:
        return None
    return row.get(col)


# --------------------------------------------------------------------------- #
# Core evaluation                                                             #
# --------------------------------------------------------------------------- #

def evaluate_row(spec: ARSpec, row: Dict[str, Any], column_map: Dict[str, str]) -> RowDivergence:
    """Decide whether a single evidence row diverges from the documented authority.

    v1 predicates:
      * ``approver_mismatch`` — the actual approver differs from the documented
        role-holder (neutral direction on its own).
      * ``threshold_breach_without_escalation`` — the decision value exceeded the
        documented threshold with no escalation recorded (actual exceeds documented).
      * ``missing_cosign`` — a required co-sign is absent (documented exceeds actual).
    """
    reasons: List[str] = []
    signed = 0

    actual_approver = _get(row, column_map, "actual_approver")
    documented_approver = _get(row, column_map, "documented_approver") or spec.documented_approver
    value = _to_float(_get(row, column_map, "value"))
    escalated = _truthy(_get(row, column_map, "escalated"))
    cosign_present = _truthy(_get(row, column_map, "cosign_present"))
    action = _get(row, column_map, "action")
    object_id = _get(row, column_map, "object_id")

    # 1. Approver mismatch (only when both sides are known).
    if actual_approver and documented_approver and str(actual_approver).strip() != str(documented_approver).strip():
        reasons.append("approver_mismatch")

    # 2. Threshold breached without escalation → actual exceeded documented scope.
    if value is not None and spec.threshold is not None and value > spec.threshold and not escalated:
        reasons.append("threshold_breach_without_escalation")
        signed += 1

    # 3. Required co-sign missing → documented required more than actually happened.
    if spec.required_cosign and not cosign_present:
        reasons.append("missing_cosign")
        signed -= 1

    diverged = len(reasons) > 0
    # Clamp the aggregate row sign to {-1, 0, +1}.
    signed = (signed > 0) - (signed < 0)
    return RowDivergence(
        diverged=diverged,
        signed=signed,
        reasons=reasons,
        actor_identity=str(actual_approver) if actual_approver is not None else None,
        action=str(action) if action is not None else None,
        object_id=str(object_id) if object_id is not None else None,
        value=value,
    )


def compute_dnaco(
    spec: ARSpec,
    rows: List[Dict[str, Any]],
    column_map: Dict[str, str],
    scoring_config: Optional[Dict[str, Any]] = None,
) -> DnaResult:
    """Roll a sample of evidence rows up into a single DNA-Coefficient.

    ``magnitude`` defaults to the fraction of sampled decisions that diverge
    (``0.0`` best). Admins may supply ``scoring_config['reason_weights']`` (a map
    of reason → weight, default ``1.0``) to weight some divergence kinds more
    heavily; a row's contribution is the max weight across its reasons, and the
    magnitude is capped at ``1.0``. ``direction`` is the sign of the aggregate
    authority-level delta across divergent rows.
    """
    scoring_config = scoring_config or {}
    reason_weights: Dict[str, float] = scoring_config.get("reason_weights", {}) or {}

    evaluated = [evaluate_row(spec, r, column_map) for r in rows]
    sampled = len(evaluated)
    divergent = [rd for rd in evaluated if rd.diverged]

    if sampled == 0:
        return DnaResult(magnitude=0.0, direction=DIR_NONE, sampled_count=0, divergent_count=0, rows=evaluated)

    weighted_sum = 0.0
    for rd in divergent:
        row_weight = max((reason_weights.get(reason, 1.0) for reason in rd.reasons), default=1.0)
        weighted_sum += row_weight
    magnitude = min(1.0, weighted_sum / sampled)

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
        magnitude=round(magnitude, 4),
        direction=direction,
        sampled_count=sampled,
        divergent_count=len(divergent),
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
