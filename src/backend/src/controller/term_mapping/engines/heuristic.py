"""Deterministic heuristic suggester.

Ported from onyx_ontology mapping_suggester.suggest_mappings with three fixes
called out in the PRD:

  1. Irregular plurals: source's _depluralize only knew the -ies/-s rules and
     silently dropped tables like 'people' or 'children'. naming.depluralize
     here checks an irregular table first.

  2. ``label`` similarity is *capped* by ``name`` similarity. The source took
     ``max(name, label)`` which let a long label string ride to a 0.95
     auto-accept on a column called "id" by virtue of label "Identifier of
     the customer", which steward never expected. We now multiply (label
     similarity is a tiebreaker, not a primary signal).

  3. Skip pairs the steward already rejected in a prior run (see
     MappingSuggestionRepository.is_pair_already_decided). The source had no
     persistent queue so it kept re-proposing the same noisy candidates.

The engine ONLY emits SuggestionDraft objects — persistence and concurrency
are the manager's responsibility.
"""
from __future__ import annotations

import logging
from typing import Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from ..concept_source import ConceptSource
from ..naming import (
    depluralize,
    normalize,
    similarity,
    to_camel,
    types_compatible,
)
from ..scoring import AUTO_ACCEPT, AUTO_REJECT, Signals
from ..types import ConceptCandidate, SuggestionDraft, TargetEntity

logger = logging.getLogger(__name__)


# Predicate for "should I skip this (source, iri) pair because the steward
# already rejected it before?"
DecidedFn = Callable[[str, str, str], bool]


class HeuristicSuggester:
    """Configurable heuristic engine; one instance per run.

    Parameters mirror the source's signatures so the well-trodden scoring
    semantics carry over.
    """

    name = "heuristic"

    def __init__(
        self,
        *,
        concepts: ConceptSource,
        already_decided: Optional[DecidedFn] = None,
        auto_accept: float = AUTO_ACCEPT,
        auto_reject: float = AUTO_REJECT,
    ):
        self._concepts = concepts
        self._already_decided = already_decided or (lambda *_: False)
        self._auto_accept = auto_accept
        self._auto_reject = auto_reject

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def suggest(self, targets: List[TargetEntity]) -> List[SuggestionDraft]:
        # Pre-load concepts once per run.
        classes = self._concepts.classes()
        properties = self._concepts.properties()

        # Build a stem index so we can resolve FK references in O(1).
        stem_index: Dict[str, ConceptCandidate] = {}
        for c in classes:
            stem = depluralize(normalize(c.label))
            stem_index.setdefault(stem, c)

        drafts: List[SuggestionDraft] = []
        for target in targets:
            kind = self._target_kind(target)
            if kind == "container":
                draft = self._suggest_for_container(target, classes)
            else:
                draft = self._suggest_for_attribute(
                    target, classes, properties, stem_index
                )
            if draft is None:
                continue
            if self._already_decided(
                draft.source_entity_type,
                draft.source_entity_id,
                draft.target_concept_iri,
            ):
                # Steward rejected this exact pair before; silently drop it
                # so it doesn't haunt the queue.
                continue
            drafts.append(draft)
        return drafts

    # ------------------------------------------------------------------
    # Per-target logic
    # ------------------------------------------------------------------
    def _target_kind(self, target: TargetEntity) -> str:
        if target.entity_type in ("data_contract_property",):
            return "attribute"
        if target.entity_type == "asset":
            return "attribute" if target.parent_entity_id else "container"
        return "container"

    def _suggest_for_container(
        self,
        target: TargetEntity,
        classes: List[ConceptCandidate],
    ) -> Optional[SuggestionDraft]:
        """Pick the best class concept for a top-level target (table-like)."""
        if not classes:
            return None

        target_norm = normalize(target.name)
        target_singular = depluralize(target_norm)

        best: Optional[ConceptCandidate] = None
        best_score = 0.0
        for c in classes:
            label_norm = normalize(c.label)
            label_singular = depluralize(label_norm)
            sim_plural = similarity(target_norm, label_norm)
            sim_singular = similarity(target_singular, label_singular)
            score = max(sim_plural, sim_singular)
            if score > best_score:
                best_score = score
                best = c

        if best is None or best_score < 0.6:
            return None

        # Container assignments don't get an explicit type signal, so we
        # tag type_compatible=True (a class match is type-agnostic).
        signals = Signals(
            name_similarity=best_score,
            type_compatible=True,
            parts=[
                f"Name '{target.name}' ~= concept '{best.label}' "
                f"(similarity {best_score:.2f}) in {_short_ctx(best.source_context)}.",
            ],
        )
        confidence = signals.confidence
        if confidence <= self._auto_reject:
            return None
        return SuggestionDraft(
            source_entity_type=target.entity_type,
            source_entity_id=target.entity_id,
            source_label=target.label,
            suggestion_kind="entity_assignment",
            target_concept_iri=best.iri,
            target_concept_label=best.label,
            confidence=confidence,
            reason=signals.render(),
            auto_apply=confidence >= self._auto_accept,
            engine=self.name,
            engine_metadata={
                "source_context": best.source_context,
                "stem_match_score": round(best_score, 4),
            },
        )

    def _suggest_for_attribute(
        self,
        target: TargetEntity,
        classes: List[ConceptCandidate],
        properties: List[ConceptCandidate],
        stem_index: Dict[str, ConceptCandidate],
    ) -> Optional[SuggestionDraft]:
        col_lower = (target.name or "").lower()
        col_norm = normalize(col_lower)

        # ---------- FK heuristic ----------
        if col_lower.endswith("_id") and col_lower != "id":
            stem = normalize(col_lower[:-3])
            stem_singular = depluralize(stem)
            target_concept = stem_index.get(stem_singular) or stem_index.get(stem)
            # Skip if the column's parent IS that concept already (would be a
            # self-FK; almost always means we should have hit the PK path).
            # Depluralize both sides — parent table 'customers' and concept
            # 'Customer' must collapse to the same key to recognise the match.
            parent_norm = depluralize(normalize(target.parent_name or ""))
            concept_norm = depluralize(normalize(target_concept.label)) if target_concept else ""
            if target_concept is not None and parent_norm != concept_norm:
                sim_score = similarity(stem_singular, depluralize(normalize(target_concept.label)))
                type_ok = (target.type_label or "").lower() in (
                    "bigint", "long", "int", "integer", "string", "uuid", "varchar"
                )
                signals = Signals(
                    name_similarity=sim_score,
                    type_compatible=type_ok,
                    fk_hint=True,
                    parts=[
                        f"Column '{target.name}' ends in '_id' and stem '{stem_singular}' matches "
                        f"concept '{target_concept.label}' (similarity {sim_score:.2f}).",
                        "Type is identifier-compatible." if type_ok
                        else f"Type '{target.type_label}' is unusual for an id column — verify.",
                    ],
                )
                confidence = signals.confidence
                if confidence > self._auto_reject:
                    return SuggestionDraft(
                        source_entity_type=target.entity_type,
                        source_entity_id=target.entity_id,
                        source_label=target.label,
                        suggestion_kind="entity_assignment",
                        target_concept_iri=target_concept.iri,
                        target_concept_label=target_concept.label,
                        confidence=confidence,
                        reason=signals.render(),
                        auto_apply=confidence >= self._auto_accept,
                        engine=self.name,
                        engine_metadata={
                            "fk_hint": True,
                            "source_context": target_concept.source_context,
                        },
                    )

        # ---------- PK heuristic ----------
        parent_stem = depluralize(normalize(target.parent_name or ""))
        looks_like_pk = target.is_pk or col_norm == "id" or (
            col_lower.endswith("_id") and parent_stem == normalize(col_lower[:-3])
        )
        if looks_like_pk:
            # Try property concepts first (e.g. dcterms:identifier).
            id_props = [p for p in properties if normalize(p.label) in {"id", "identifier", "uri"}]
            if id_props:
                pick = id_props[0]
                signals = Signals(
                    name_similarity=1.0,
                    type_compatible=True,
                    pk_hint=True,
                    parts=[
                        f"Column '{target.name}' is the primary key of '{target.parent_name or 'parent'}'.",
                        f"Maps to property '{pick.label}' from {_short_ctx(pick.source_context)}.",
                    ],
                )
                confidence = signals.confidence
                if confidence > self._auto_reject:
                    return SuggestionDraft(
                        source_entity_type=target.entity_type,
                        source_entity_id=target.entity_id,
                        source_label=target.label,
                        suggestion_kind="attribute_assignment",
                        target_concept_iri=pick.iri,
                        target_concept_label=pick.label,
                        confidence=confidence,
                        reason=signals.render(),
                        auto_apply=confidence >= self._auto_accept,
                        engine=self.name,
                        engine_metadata={"pk_hint": True, "source_context": pick.source_context},
                    )

        # ---------- Generic property match ----------
        return self._best_property_match(target, properties)

    def _best_property_match(
        self,
        target: TargetEntity,
        properties: List[ConceptCandidate],
    ) -> Optional[SuggestionDraft]:
        if not properties:
            return None

        col_norm = normalize(target.name)
        col_camel = normalize(to_camel(target.name))

        best: Optional[ConceptCandidate] = None
        best_name_sim = 0.0
        best_label_sim = 0.0
        for prop in properties:
            prop_norm = normalize(prop.label)
            name_sim = max(
                similarity(col_norm, prop_norm),
                similarity(col_camel, prop_norm),
            )
            label_sim = similarity(col_norm, normalize(prop.comment)) if prop.comment else 0.0
            if name_sim > best_name_sim:
                best_name_sim = name_sim
                best_label_sim = label_sim
                best = prop

        if best is None or best_name_sim < 0.45:
            return None

        # Bug fix #2: cap label-similarity contribution by name-similarity.
        # The source's max(name, label) over-rewarded long descriptive labels.
        combined = best_name_sim + 0.1 * min(best_label_sim, best_name_sim)
        combined = min(combined, 1.0)

        type_ok = types_compatible(target.type_label, best.range_type)
        signals = Signals(
            name_similarity=combined,
            type_compatible=type_ok,
            parts=[
                f"Column '{target.name}' name matches property '{best.label}' "
                f"(similarity {best_name_sim:.2f}) in {_short_ctx(best.source_context)}.",
                f"Type '{target.type_label}' is "
                + ("compatible with" if type_ok else "DIFFERENT from")
                + f" range '{best.range_type or '?'}'.",
            ],
        )
        confidence = signals.confidence
        if confidence <= self._auto_reject:
            return None
        return SuggestionDraft(
            source_entity_type=target.entity_type,
            source_entity_id=target.entity_id,
            source_label=target.label,
            suggestion_kind="attribute_assignment",
            target_concept_iri=best.iri,
            target_concept_label=best.label,
            confidence=confidence,
            reason=signals.render(),
            auto_apply=confidence >= self._auto_accept,
            engine=self.name,
            engine_metadata={
                "source_context": best.source_context,
                "name_similarity": round(best_name_sim, 4),
                "label_similarity": round(best_label_sim, 4),
                "range_type": best.range_type,
            },
        )


# ---------- helpers ----------

def _short_ctx(ctx: str) -> str:
    """Trim 'urn:semantic-model:retail_v1' down to 'retail_v1' for reason strings."""
    if not ctx:
        return ""
    return ctx.rsplit(":", 1)[-1]


def build_already_decided_fn(db: Session, repo) -> DecidedFn:
    """Wire the manager's repo into the engine's decided-pair check.

    Defined here (not in manager.py) so engines stay portable across managers.
    """
    def _check(entity_type: str, entity_id: str, iri: str) -> bool:
        try:
            return repo.is_pair_already_decided(
                db,
                source_entity_type=entity_type,
                source_entity_id=entity_id,
                target_concept_iri=iri,
            )
        except Exception:  # pragma: no cover
            return False
    return _check
