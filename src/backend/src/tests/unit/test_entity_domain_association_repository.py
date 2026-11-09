"""Unit tests for EntityDomainAssociationRepository (the multi-domain deep module).

Covers replace-all semantics, the at-most-one-primary invariant, idempotent upserts,
batch reads, any-of inverse lookups, and deletion-support queries.
"""
import pytest
from sqlalchemy.orm import Session

from src.models.data_domains import DataDomainCreate
from src.repositories.data_domain_repository import data_domain_repo
from src.repositories.entity_domain_association_repository import entity_domain_repo


ENTITY = "data_product"


@pytest.fixture
def domains(db_session: Session):
    """Create three domains: Sales, Marketing, Finance. Returns {name: id}."""
    ids = {}
    for name in ("Sales", "Marketing", "Finance"):
        d = data_domain_repo.create(db=db_session, obj_in=DataDomainCreate(name=name))
        ids[name] = d.id
    db_session.commit()
    return ids


def _set(db, entity_id, domain_ids, primary=None):
    return entity_domain_repo.set_domains_for_entity(
        db, entity_type=ENTITY, entity_id=entity_id,
        domain_ids=domain_ids, primary_domain_id=primary, assigned_by="tester",
    )


class TestSetDomainsForEntity:
    def test_assign_single_defaults_primary(self, db_session, domains):
        result = _set(db_session, "e1", [domains["Sales"]])
        db_session.commit()
        assert len(result) == 1
        assert result[0].domain_id == domains["Sales"]
        assert result[0].is_primary is True

    def test_assign_multiple_first_is_primary_by_default(self, db_session, domains):
        result = _set(db_session, "e1", [domains["Sales"], domains["Marketing"]])
        db_session.commit()
        primaries = [d for d in result if d.is_primary]
        assert len(primaries) == 1
        assert primaries[0].domain_id == domains["Sales"]

    def test_explicit_primary(self, db_session, domains):
        result = _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Marketing"])
        db_session.commit()
        primaries = [d for d in result if d.is_primary]
        assert len(primaries) == 1 and primaries[0].domain_id == domains["Marketing"]

    def test_replace_all_add_remove(self, db_session, domains):
        _set(db_session, "e1", [domains["Sales"], domains["Marketing"]])
        db_session.commit()
        result = _set(db_session, "e1", [domains["Marketing"], domains["Finance"]], primary=domains["Finance"])
        db_session.commit()
        got = {d.domain_id for d in result}
        assert got == {domains["Marketing"], domains["Finance"]}
        assert entity_domain_repo.get_primary_domain_id(db_session, entity_type=ENTITY, entity_id="e1") == domains["Finance"]

    def test_swap_primary_only(self, db_session, domains):
        _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Sales"])
        db_session.commit()
        _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Marketing"])
        db_session.commit()
        assert entity_domain_repo.get_primary_domain_id(db_session, entity_type=ENTITY, entity_id="e1") == domains["Marketing"]

    def test_remove_all_leaves_unassigned(self, db_session, domains):
        _set(db_session, "e1", [domains["Sales"]])
        db_session.commit()
        result = _set(db_session, "e1", [])
        db_session.commit()
        assert result == []
        assert entity_domain_repo.get_primary_domain_id(db_session, entity_type=ENTITY, entity_id="e1") is None

    def test_idempotent(self, db_session, domains):
        _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Sales"])
        db_session.commit()
        r2 = _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Sales"])
        db_session.commit()
        assert {d.domain_id for d in r2} == {domains["Sales"], domains["Marketing"]}
        assert len([d for d in r2 if d.is_primary]) == 1

    def test_dedupe_domain_ids(self, db_session, domains):
        result = _set(db_session, "e1", [domains["Sales"], domains["Sales"], domains["Marketing"]])
        db_session.commit()
        assert len(result) == 2

    def test_primary_not_in_set_raises(self, db_session, domains):
        with pytest.raises(ValueError):
            _set(db_session, "e1", [domains["Sales"]], primary=domains["Marketing"])

    def test_unknown_domain_raises(self, db_session, domains):
        with pytest.raises(ValueError):
            _set(db_session, "e1", ["does-not-exist"])


class TestBatchAndInverse:
    def test_batch_reads(self, db_session, domains):
        _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Sales"])
        _set(db_session, "e2", [domains["Finance"]])
        db_session.commit()
        got = entity_domain_repo.get_domains_for_entities(db_session, entity_type=ENTITY, entity_ids=["e1", "e2", "e3"])
        assert {d.domain_id for d in got["e1"]} == {domains["Sales"], domains["Marketing"]}
        assert [d.domain_id for d in got["e2"]] == [domains["Finance"]]
        assert got["e3"] == []
        # e1 primary first
        assert got["e1"][0].is_primary is True and got["e1"][0].domain_id == domains["Sales"]

    def test_find_entity_ids_any_of(self, db_session, domains):
        _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Sales"])
        _set(db_session, "e2", [domains["Marketing"]])
        _set(db_session, "e3", [domains["Finance"]])
        db_session.commit()
        got = set(entity_domain_repo.find_entity_ids_by_domains(
            db_session, domain_ids=[domains["Marketing"], domains["Finance"]], entity_type=ENTITY))
        assert got == {"e1", "e2", "e3"}

    def test_find_entity_ids_primary_only(self, db_session, domains):
        _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Sales"])
        _set(db_session, "e2", [domains["Marketing"]])
        db_session.commit()
        got = set(entity_domain_repo.find_entity_ids_by_domain(
            db_session, domain_id=domains["Marketing"], entity_type=ENTITY, primary_only=True))
        assert got == {"e2"}  # e1 has Marketing as additional, not primary


class TestDeletionSupport:
    def test_entities_with_primary_domain(self, db_session, domains):
        _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Sales"])
        _set(db_session, "e2", [domains["Marketing"]], primary=domains["Marketing"])
        db_session.commit()
        blockers = entity_domain_repo.get_entities_with_primary_domain(db_session, domain_id=domains["Marketing"])
        assert (ENTITY, "e2") in blockers
        assert (ENTITY, "e1") not in blockers  # Marketing is additional for e1

    def test_remove_all_for_domain(self, db_session, domains):
        _set(db_session, "e1", [domains["Sales"], domains["Marketing"]], primary=domains["Sales"])
        db_session.commit()
        removed = entity_domain_repo.remove_all_for_domain(db_session, domain_id=domains["Marketing"])
        db_session.commit()
        assert removed == 1
        remaining = entity_domain_repo.get_domains_for_entity(db_session, entity_type=ENTITY, entity_id="e1")
        assert {d.domain_id for d in remaining} == {domains["Sales"]}

    def test_assignment_counts(self, db_session, domains):
        _set(db_session, "e1", [domains["Marketing"]], primary=domains["Marketing"])
        _set(db_session, "e2", [domains["Sales"], domains["Marketing"]], primary=domains["Sales"])
        db_session.commit()
        counts = entity_domain_repo.get_assignment_counts_for_domain(db_session, domain_id=domains["Marketing"])
        assert counts[ENTITY]["primary"] == 1
        assert counts[ENTITY]["additional"] == 1
