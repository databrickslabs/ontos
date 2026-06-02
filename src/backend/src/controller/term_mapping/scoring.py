"""Confidence-scoring signals + formula.

Lifted from onyx_ontology mapping_suggester._Signals — kept identical (incl.
the rounding step) so the 0.90 auto-accept threshold lands where stewards
expect. Don't tweak coefficients without updating the PRD threshold notes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List


# Public thresholds (same values as the source so reason strings agree).
AUTO_ACCEPT = 0.90
AUTO_REJECT = 0.40


@dataclass
class Signals:
    """All scoring signals for one source → target candidate pair."""
    name_similarity: float = 0.0
    type_compatible: bool = False
    fk_hint: bool = False
    pk_hint: bool = False
    # Human-readable bits glued together in render(); UI shows them verbatim.
    parts: List[str] = field(default_factory=list)

    @property
    def confidence(self) -> float:
        score = 0.0
        # Name match contributes up to 0.7.
        score += 0.7 * self.name_similarity
        # Type compatibility nudges +0.2 or -0.1; -0.1 keeps incompatible
        # pairs out of the auto-accept band without nuking them outright.
        score += 0.20 if self.type_compatible else -0.10
        # PK / FK hint = +0.1; either suffices, never stacks.
        if self.fk_hint or self.pk_hint:
            score += 0.10
        # Round to dodge float drift around AUTO_ACCEPT.
        return round(max(0.0, min(1.0, score)), 4)

    def render(self) -> str:
        return " ".join(p for p in self.parts if p) if self.parts else "No strong signal."
