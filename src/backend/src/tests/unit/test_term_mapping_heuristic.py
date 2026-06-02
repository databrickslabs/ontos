"""Unit tests for HeuristicSuggester.

Locks in two bug fixes called out in the PRD:
  * Bug fix #2 — label similarity is capped by name similarity (the source's
    max(name, label) let descriptive labels push 'id' columns to 0.95
    auto-accept on the wrong concept).
  * Bug fix #3 — pairs the steward has rejected before are skipped (the
    source had no persistent queue and re-proposed the same noise on every
    run).

And the foundational positive cases: container, FK-by-stem, property-by-name,
PK-by-property fallback.
"""
from typing import List

from src.controller.term_mapping.engines import HeuristicSuggester
from src.controller.term_mapping.types import ConceptCandidate, TargetEntity


class _Source:
    """Minimal ConceptSource stand-in. The engine only calls .classes() and
    .properties(), so we don't need the real graph plumbing."""

    def __init__(
        self,
        classes: List[ConceptCandidate] | None = None,
        properties: List[ConceptCandidate] | None = None,
    ):
        self._classes = classes or []
        self._properties = properties or []

    def classes(self):
        return self._classes

    def properties(self):
        return self._properties


def _customer_class() -> ConceptCandidate:
    return ConceptCandidate(
        iri="http://retail.example/Customer",
        label="Customer",
        source_context="urn:semantic-model:retail",
    )


def _identifier_prop() -> ConceptCandidate:
    return ConceptCandidate(
        iri="http://purl.org/dc/terms/identifier",
        label="identifier",
        source_context="urn:semantic-model:retail",
        is_class=False,
        range_type="xsd:string",
    )


def _email_prop(label_comment: str = "") -> ConceptCandidate:
    return ConceptCandidate(
        iri="http://retail.example/email",
        label="email",
        comment=label_comment,
        source_context="urn:semantic-model:retail",
        is_class=False,
        range_type="xsd:string",
    )


class TestContainerMatch:
    def test_singular_plural_collapse(self):
        eng = HeuristicSuggester(concepts=_Source(classes=[_customer_class()]))
        target = TargetEntity(
            entity_type="asset",
            entity_id="t1",
            name="customers",
            label="customers",
        )
        drafts = eng.suggest([target])
        assert len(drafts) == 1
        assert drafts[0].target_concept_iri == "http://retail.example/Customer"
        assert drafts[0].suggestion_kind == "entity_assignment"
        # Container assignments are type-agnostic → high confidence.
        assert drafts[0].confidence >= 0.9
        assert drafts[0].auto_apply is True

    def test_no_match_below_threshold(self):
        eng = HeuristicSuggester(concepts=_Source(classes=[_customer_class()]))
        target = TargetEntity(
            entity_type="asset",
            entity_id="t-x",
            name="invoices",
            label="invoices",
        )
        drafts = eng.suggest([target])
        # similarity('invoice','customer') < 0.6 → no match.
        assert drafts == []


class TestForeignKeyHeuristic:
    def test_fk_stem_matches_class(self):
        eng = HeuristicSuggester(concepts=_Source(classes=[_customer_class()]))
        target = TargetEntity(
            entity_type="asset",
            entity_id="c1",
            name="customer_id",
            label="customer_id",
            type_label="bigint",
            parent_entity_id="orders",
            parent_name="orders",
        )
        drafts = eng.suggest([target])
        assert len(drafts) == 1
        d = drafts[0]
        assert d.target_concept_iri == "http://retail.example/Customer"
        assert d.engine_metadata and d.engine_metadata.get("fk_hint") is True
        assert d.confidence == 1.0  # perfect stem + type + fk

    def test_self_fk_is_skipped(self):
        """When the column lives ON the table that matches the stem, it's a
        PK candidate, not an FK to itself."""
        eng = HeuristicSuggester(concepts=_Source(classes=[_customer_class()]))
        target = TargetEntity(
            entity_type="asset",
            entity_id="c1",
            name="customer_id",
            label="customer_id",
            type_label="bigint",
            parent_entity_id="customers",
            parent_name="customers",  # parent IS the matched concept
            is_pk=True,
        )
        drafts = eng.suggest([target])
        # Either zero drafts (no PK property concept) or a PK-flavoured draft
        # — but never an FK pointing customers → Customer (would be self-FK).
        for d in drafts:
            assert d.engine_metadata is None or not d.engine_metadata.get("fk_hint")

    def test_id_only_column_not_fk(self):
        # `id` alone is the PK heuristic's territory, not FK.
        eng = HeuristicSuggester(concepts=_Source(classes=[_customer_class()]))
        target = TargetEntity(
            entity_type="asset",
            entity_id="c1",
            name="id",
            label="id",
            type_label="bigint",
            parent_entity_id="t1",
            parent_name="customers",
            is_pk=True,
        )
        drafts = eng.suggest([target])
        # No id/identifier property concept loaded → falls through; that's ok.
        for d in drafts:
            assert not (d.engine_metadata and d.engine_metadata.get("fk_hint"))


class TestPrimaryKeyHeuristic:
    def test_pk_maps_to_identifier_property(self):
        eng = HeuristicSuggester(
            concepts=_Source(
                classes=[_customer_class()],
                properties=[_identifier_prop()],
            )
        )
        target = TargetEntity(
            entity_type="data_contract_property",
            entity_id="c#cust#id",
            name="id",
            label="id",
            type_label="bigint",
            parent_entity_id="c#cust",
            parent_name="cust",
            is_pk=True,
        )
        drafts = eng.suggest([target])
        assert any(d.target_concept_iri == _identifier_prop().iri for d in drafts)
        # PK match gets pk_hint metadata.
        pk_draft = next(d for d in drafts if d.target_concept_iri == _identifier_prop().iri)
        assert pk_draft.engine_metadata and pk_draft.engine_metadata.get("pk_hint")


class TestPropertyMatch:
    def test_property_name_match(self):
        eng = HeuristicSuggester(concepts=_Source(properties=[_email_prop()]))
        target = TargetEntity(
            entity_type="data_contract_property",
            entity_id="c#cust#email",
            name="email",
            label="email",
            type_label="string",
            parent_entity_id="c#cust",
            parent_name="cust",
        )
        drafts = eng.suggest([target])
        assert len(drafts) == 1
        d = drafts[0]
        assert d.target_concept_iri == _email_prop().iri
        assert d.suggestion_kind == "attribute_assignment"
        assert d.confidence >= 0.9

    def test_label_similarity_capped_by_name(self):
        """Bug fix #2: in the source repo max(name_sim, label_sim) let a long
        descriptive label drive a column called 'id' to 0.95 against a
        property literally labelled 'email' (because the label text mentioned
        'identifier' in passing). We now cap label by name."""
        # Property whose human label/comment is long and mentions 'id' so
        # a naïve max would over-reward similarity.
        chatty = ConceptCandidate(
            iri="http://retail.example/preferredContactEmail",
            label="email",
            comment="The email address used as the primary identifier id key",
            source_context="urn:semantic-model:retail",
            is_class=False,
            range_type="xsd:string",
        )
        eng = HeuristicSuggester(concepts=_Source(properties=[chatty]))
        target = TargetEntity(
            entity_type="data_contract_property",
            entity_id="c#cust#id",
            name="id",
            label="id",
            type_label="bigint",
            parent_entity_id="c#cust",
            parent_name="cust",
        )
        drafts = eng.suggest([target])
        # The engine may emit 0 drafts (low name_sim below 0.45) or 1 with a
        # modest confidence well below auto-accept. The bug would have been
        # emitting a draft with confidence >= 0.9.
        for d in drafts:
            assert d.confidence < 0.9, f"label drove past auto-accept: {d}"


class TestAlreadyDecidedGuard:
    """Bug fix #3: the source had no persistent queue, so a rejected pair
    would reappear on the very next run. We accept a callback the engine
    invokes per draft to suppress those."""

    def test_rejected_pair_is_pruned(self):
        eng = HeuristicSuggester(
            concepts=_Source(classes=[_customer_class()]),
            already_decided=lambda et, eid, iri: iri.endswith("/Customer"),
        )
        target = TargetEntity(
            entity_type="asset",
            entity_id="t1",
            name="customers",
            label="customers",
        )
        drafts = eng.suggest([target])
        # The only candidate is /Customer, which we said was already rejected.
        assert drafts == []

    def test_other_pairs_unaffected(self):
        eng = HeuristicSuggester(
            concepts=_Source(
                classes=[_customer_class()],
                properties=[_email_prop()],
            ),
            already_decided=lambda et, eid, iri: iri.endswith("/Customer"),
        )
        # /Customer is blocked for the container target,
        # but /email is fine for the property target.
        targets = [
            TargetEntity(
                entity_type="asset",
                entity_id="t1",
                name="customers",
                label="customers",
            ),
            TargetEntity(
                entity_type="data_contract_property",
                entity_id="c#cust#email",
                name="email",
                label="email",
                type_label="string",
                parent_entity_id="c#cust",
                parent_name="cust",
            ),
        ]
        drafts = eng.suggest(targets)
        iris = {d.target_concept_iri for d in drafts}
        assert _email_prop().iri in iris
        assert "http://retail.example/Customer" not in iris
