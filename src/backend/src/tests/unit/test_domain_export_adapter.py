"""Unit tests for DomainExportAdapter — the single home for the primary/additional
domain split across ODCS/ODPS export, UC tags, and import round-trip.

#851 reworked the ODCS/ODPS domain round-trip onto namespaced custom properties:
``ontosDomainId`` (all assigned ids, primary first — authoritative for rebind) and
``ontosOriginalDomain`` (provenance). The legacy top-level ``domainIds``/``primaryDomainId``
and ``customProperties.additionalDomains`` are still READ on import (backward compat) but no
longer written on export.
"""
import pytest
from sqlalchemy.orm import Session

from src.controller.domain_export_adapter import (
    DomainExportAdapter,
    ADDITIONAL_DOMAINS_PROPERTY,
    ONTOS_DOMAIN_ID_PROPERTY,
    ONTOS_ORIGINAL_DOMAIN_PROPERTY,
    UC_DOMAIN_TAG,
)
from src.models.data_domains import DataDomainCreate
from src.repositories.data_domain_repository import data_domain_repo
from src.repositories.entity_domain_association_repository import entity_domain_repo

ENTITY = "data_contract"


@pytest.fixture
def adapter():
    return DomainExportAdapter()


@pytest.fixture
def domains(db_session: Session):
    ids = {}
    for name in ("Sales", "Marketing", "Finance"):
        d = data_domain_repo.create(db=db_session, obj_in=DataDomainCreate(name=name))
        ids[name] = d.id
    db_session.commit()
    return ids


def _assign(db, entity_id, domain_ids, primary):
    entity_domain_repo.set_domains_for_entity(
        db, entity_type=ENTITY, entity_id=entity_id,
        domain_ids=domain_ids, primary_domain_id=primary, assigned_by="tester",
    )
    db.commit()


def _cp(odcs, key):
    return next((c["value"] for c in odcs.get("customProperties", []) if c.get("property") == key), None)


class TestApplyOdcs:
    def test_emits_primary_name_and_ontos_domain_id(self, db_session, adapter, domains):
        _assign(db_session, "c1", [domains["Sales"], domains["Marketing"]], domains["Sales"])
        odcs = adapter.apply_odcs({}, db_session, ENTITY, "c1")
        assert odcs["domain"] == "Sales"  # ODCS standard single value = primary name
        ontos_ids = _cp(odcs, ONTOS_DOMAIN_ID_PROPERTY)
        assert ontos_ids[0] == domains["Sales"]  # primary first
        assert set(ontos_ids) == {domains["Sales"], domains["Marketing"]}
        # Legacy keys are no longer emitted.
        assert "domainIds" not in odcs and "primaryDomainId" not in odcs
        assert _cp(odcs, ADDITIONAL_DOMAINS_PROPERTY) is None

    def test_no_assignment_leaves_odcs_untouched(self, db_session, adapter, domains):
        odcs = adapter.apply_odcs({"existing": 1}, db_session, ENTITY, "unassigned")
        assert odcs == {"existing": 1}

    def test_replaces_stale_ontos_domain_id_entry(self, db_session, adapter, domains):
        _assign(db_session, "c1", [domains["Sales"], domains["Finance"]], domains["Sales"])
        odcs = {"customProperties": [{"property": ONTOS_DOMAIN_ID_PROPERTY, "value": ["stale-id"]}]}
        out = adapter.apply_odcs(odcs, db_session, ENTITY, "c1")
        entries = [c for c in out["customProperties"] if c.get("property") == ONTOS_DOMAIN_ID_PROPERTY]
        assert len(entries) == 1
        assert set(entries[0]["value"]) == {domains["Sales"], domains["Finance"]}


class TestMergeCustomProperties:
    """Guards the export round-trip: rebuilding customProperties must not drop the
    ontosDomainId entry apply_odcs injected (would lose the rebind key on export)."""

    def test_preserves_ontos_domain_id_when_rebuilding(self, adapter):
        applied = [{"property": ONTOS_DOMAIN_ID_PROPERTY, "value": ["id-a", "id-b"]}]
        rebuilt = [{"property": "sla", "value": "gold"}]
        out = adapter.merge_custom_properties(rebuilt, applied)
        assert {"property": "sla", "value": "gold"} in out
        assert _cp({"customProperties": out}, ONTOS_DOMAIN_ID_PROPERTY) == ["id-a", "id-b"]

    def test_no_previous_returns_rebuilt(self, adapter):
        rebuilt = [{"property": "sla", "value": "gold"}]
        assert adapter.merge_custom_properties(rebuilt, None) == rebuilt
        assert adapter.merge_custom_properties(rebuilt, []) == rebuilt

    def test_dedupes_stale_ontos_domain_id_in_rebuilt(self, adapter):
        applied = [{"property": ONTOS_DOMAIN_ID_PROPERTY, "value": ["fresh"]}]
        rebuilt = [{"property": ONTOS_DOMAIN_ID_PROPERTY, "value": ["stale"]}]
        out = adapter.merge_custom_properties(rebuilt, applied)
        entries = [c for c in out if c.get("property") == ONTOS_DOMAIN_ID_PROPERTY]
        assert len(entries) == 1 and entries[0]["value"] == ["fresh"]


class TestUcTags:
    def test_primary_then_additional(self, db_session, adapter, domains):
        _assign(db_session, "c1", [domains["Sales"], domains["Marketing"], domains["Finance"]], domains["Marketing"])
        tags = adapter.uc_tags(db_session, ENTITY, "c1")
        assert tags[0] == (UC_DOMAIN_TAG, "Marketing")
        additional = {(k, v) for k, v in tags[1:]}
        assert additional == {(f"{UC_DOMAIN_TAG}_1", "Finance"), (f"{UC_DOMAIN_TAG}_2", "Sales")}

    def test_empty_when_unassigned(self, db_session, adapter):
        assert adapter.uc_tags(db_session, ENTITY, "nope") == []


class TestParseOdcsRoundTrip:
    def test_round_trips_via_ontos_domain_id(self, db_session, adapter, domains):
        """export(apply_odcs) → import(parse_odcs) rebinds the exact ids, primary first."""
        _assign(db_session, "c1", [domains["Sales"], domains["Marketing"]], domains["Marketing"])
        odcs = adapter.apply_odcs({}, db_session, ENTITY, "c1")
        domain_ids, primary = adapter.parse_odcs(odcs, db_session)
        assert set(domain_ids) == {domains["Sales"], domains["Marketing"]}
        assert primary == domains["Marketing"]

    def test_reads_legacy_app_keys(self, db_session, adapter, domains):
        odcs = {"domainIds": [domains["Sales"], domains["Marketing"]], "primaryDomainId": domains["Marketing"]}
        domain_ids, primary = adapter.parse_odcs(odcs, db_session)
        assert set(domain_ids) == {domains["Sales"], domains["Marketing"]}
        assert primary == domains["Marketing"]

    def test_parses_odcs_standard_name(self, db_session, adapter, domains):
        odcs = {"domain": "Sales"}
        domain_ids, primary = adapter.parse_odcs(odcs, db_session)
        assert domain_ids == [domains["Sales"]] and primary == domains["Sales"]

    def test_reads_legacy_additional_domains_names(self, db_session, adapter, domains):
        odcs = {
            "domain": "Sales",
            "customProperties": [{"property": ADDITIONAL_DOMAINS_PROPERTY, "value": ["Marketing"]}],
        }
        domain_ids, primary = adapter.parse_odcs(odcs, db_session)
        assert primary == domains["Sales"]
        assert set(domain_ids) == {domains["Sales"], domains["Marketing"]}

    def test_unresolvable_name_left_unassigned_by_default(self, db_session, adapter, domains):
        domain_ids, primary = adapter.parse_odcs({"domain": "Nonexistent"}, db_session)
        assert domain_ids == [] and primary is None

    def test_create_missing_auto_creates_by_name(self, db_session, adapter, domains):
        domain_ids, primary = adapter.parse_odcs(
            {"domain": "BrandNewDomain"}, db_session, create_missing=True, created_by="alice",
        )
        assert len(domain_ids) == 1 and primary == domain_ids[0]
        created = data_domain_repo.get_by_name(db_session, name="BrandNewDomain")
        assert created is not None and created.id == domain_ids[0]

    def test_stale_ontos_id_falls_through_to_name(self, db_session, adapter, domains):
        """A recorded ontosDomainId that no longer exists must fall back to the `domain` name."""
        odcs = {
            "domain": "Sales",
            "customProperties": [{"property": ONTOS_DOMAIN_ID_PROPERTY, "value": ["ghost-id"]}],
        }
        domain_ids, primary = adapter.parse_odcs(odcs, db_session)
        assert domain_ids == [domains["Sales"]] and primary == domains["Sales"]


class TestExtractOriginalDomainStrings:
    def test_prefers_existing_ontos_original(self, adapter):
        odcs = {
            "domain": "RenamedInOntos",
            "customProperties": [{"property": ONTOS_ORIGINAL_DOMAIN_PROPERTY, "value": ["TrueOriginal"]}],
        }
        assert adapter.extract_original_domain_strings(odcs) == ["TrueOriginal"]

    def test_falls_back_to_domain_and_additional(self, adapter):
        odcs = {
            "domain": "Sales",
            "customProperties": [{"property": ADDITIONAL_DOMAINS_PROPERTY, "value": ["Marketing"]}],
        }
        assert adapter.extract_original_domain_strings(odcs) == ["Sales", "Marketing"]

    def test_empty_when_no_domain(self, adapter):
        assert adapter.extract_original_domain_strings({}) == []
