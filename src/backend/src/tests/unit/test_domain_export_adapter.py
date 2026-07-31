"""Unit tests for DomainExportAdapter — the single home for the primary/additional
domain split across ODCS/ODPS export, UC tags, and import round-trip (#520)."""
import pytest
from sqlalchemy.orm import Session

from src.controller.domain_export_adapter import (
    DomainExportAdapter,
    ADDITIONAL_DOMAINS_PROPERTY,
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


class TestApplyOdcs:
    def test_primary_name_and_additional_extension(self, db_session, adapter, domains):
        _assign(db_session, "c1", [domains["Sales"], domains["Marketing"]], domains["Sales"])
        odcs = adapter.apply_odcs({}, db_session, ENTITY, "c1")
        assert odcs["domain"] == "Sales"  # ODCS standard single value = primary name
        assert odcs["primaryDomainId"] == domains["Sales"]
        assert set(odcs["domainIds"]) == {domains["Sales"], domains["Marketing"]}
        assert odcs["domainIds"][0] == domains["Sales"]  # primary first
        additional = [c for c in odcs["customProperties"] if c.get("property") == ADDITIONAL_DOMAINS_PROPERTY]
        assert additional and additional[0]["value"] == ["Marketing"]

    def test_no_assignment_leaves_odcs_untouched(self, db_session, adapter, domains):
        odcs = adapter.apply_odcs({"existing": 1}, db_session, ENTITY, "unassigned")
        assert odcs == {"existing": 1}

    def test_replaces_stale_additional_domains_entry(self, db_session, adapter, domains):
        _assign(db_session, "c1", [domains["Sales"], domains["Finance"]], domains["Sales"])
        odcs = {"customProperties": [{"property": ADDITIONAL_DOMAINS_PROPERTY, "value": ["Stale"]}]}
        out = adapter.apply_odcs(odcs, db_session, ENTITY, "c1")
        entries = [c for c in out["customProperties"] if c.get("property") == ADDITIONAL_DOMAINS_PROPERTY]
        assert len(entries) == 1 and entries[0]["value"] == ["Finance"]


class TestMergeCustomProperties:
    """Guards the export round-trip: rebuilding customProperties must not drop the
    additionalDomains entry apply_odcs injected (would lose additional domains on export)."""

    def test_preserves_additional_domains_when_rebuilding(self, adapter):
        applied = [{"property": ADDITIONAL_DOMAINS_PROPERTY, "value": ["Marketing", "Finance"]}]
        rebuilt = [{"property": "sla", "value": "gold"}]
        out = adapter.merge_custom_properties(rebuilt, applied)
        assert {"property": "sla", "value": "gold"} in out
        addl = [c for c in out if c.get("property") == ADDITIONAL_DOMAINS_PROPERTY]
        assert addl and addl[0]["value"] == ["Marketing", "Finance"]

    def test_no_previous_returns_rebuilt(self, adapter):
        rebuilt = [{"property": "sla", "value": "gold"}]
        assert adapter.merge_custom_properties(rebuilt, None) == rebuilt
        assert adapter.merge_custom_properties(rebuilt, []) == rebuilt

    def test_dedupes_stale_additional_in_rebuilt(self, adapter):
        applied = [{"property": ADDITIONAL_DOMAINS_PROPERTY, "value": ["Fresh"]}]
        rebuilt = [{"property": ADDITIONAL_DOMAINS_PROPERTY, "value": ["Stale"]}]
        out = adapter.merge_custom_properties(rebuilt, applied)
        addl = [c for c in out if c.get("property") == ADDITIONAL_DOMAINS_PROPERTY]
        assert len(addl) == 1 and addl[0]["value"] == ["Fresh"]


class TestUcTags:
    def test_primary_then_additional(self, db_session, adapter, domains):
        _assign(db_session, "c1", [domains["Sales"], domains["Marketing"], domains["Finance"]], domains["Marketing"])
        tags = adapter.uc_tags(db_session, ENTITY, "c1")
        # Primary first under the canonical key, then one numbered tag per additional
        # domain (UC holds one value per key, so additionals cannot share a key).
        assert tags[0] == (UC_DOMAIN_TAG, "Marketing")
        additional = {(k, v) for k, v in tags[1:]}
        assert additional == {(f"{UC_DOMAIN_TAG}_1", "Finance"), (f"{UC_DOMAIN_TAG}_2", "Sales")}

    def test_empty_when_unassigned(self, db_session, adapter):
        assert adapter.uc_tags(db_session, ENTITY, "nope") == []


class TestParseOdcsRoundTrip:
    def test_round_trips_app_keys(self, db_session, adapter, domains):
        _assign(db_session, "c1", [domains["Sales"], domains["Marketing"]], domains["Marketing"])
        odcs = adapter.apply_odcs({}, db_session, ENTITY, "c1")
        domain_ids, primary = adapter.parse_odcs(odcs, db_session)
        assert set(domain_ids) == {domains["Sales"], domains["Marketing"]}
        assert primary == domains["Marketing"]

    def test_parses_odcs_standard_names(self, db_session, adapter, domains):
        odcs = {
            "domain": "Sales",
            "customProperties": [{"property": ADDITIONAL_DOMAINS_PROPERTY, "value": ["Marketing"]}],
        }
        domain_ids, primary = adapter.parse_odcs(odcs, db_session)
        assert primary == domains["Sales"]
        assert set(domain_ids) == {domains["Sales"], domains["Marketing"]}

    def test_unresolvable_name_is_skipped(self, db_session, adapter, domains):
        domain_ids, primary = adapter.parse_odcs({"domain": "Nonexistent"}, db_session)
        assert domain_ids == [] and primary is None

    def test_filters_nonexistent_ids(self, db_session, adapter, domains):
        odcs = {"domainIds": [domains["Sales"], "ghost-id"], "primaryDomainId": "ghost-id"}
        domain_ids, primary = adapter.parse_odcs(odcs, db_session)
        assert domain_ids == [domains["Sales"]]
        assert primary == domains["Sales"]  # invalid primary falls back to first existing
