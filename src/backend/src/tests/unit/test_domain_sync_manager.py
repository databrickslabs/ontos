"""
Unit tests for DomainSyncManager (#761).

Exercises both directions against a fake UC domains client:
- Import (UC -> Ontos): places UC's 2-level tree into Ontos, is idempotent by
  uc_domain_id, and can nest under a chosen target root.
- Export (Ontos -> UC): maps anchor children -> UC roots, grandchildren -> UC
  subdomains, and skips anything deeper than UC's two-level cap.
- Previews write nothing.
"""
import uuid
from typing import List, Optional

import pytest
from sqlalchemy.orm import Session

from src.common.uc_domains_client import UcDomain
from src.controller.domain_sync_manager import DomainSyncManager
from src.db_models.data_domains import DataDomain
from src.models.domain_sync import SyncAction


class FakeUcClient:
    """In-memory stand-in for UcDomainsClient."""

    def __init__(self, domains: Optional[List[UcDomain]] = None):
        self._domains: List[UcDomain] = list(domains or [])
        self.created: List[UcDomain] = []
        self._seq = 0

    def list_domains(self) -> List[UcDomain]:
        return list(self._domains)

    def create_domain(self, name, *, parent_domain_id=None, description=None, tag_key=None) -> UcDomain:
        self._seq += 1
        d = UcDomain(
            domain_id=f"uc-{self._seq}",
            name=name,
            tag_key=tag_key or name.lower().replace(" ", "_"),
            description=description,
            parent_domain_id=parent_domain_id,
        )
        self._domains.append(d)
        self.created.append(d)
        return d


def _mk(db: Session, name: str, parent: Optional[DataDomain] = None, uc_domain_id: Optional[str] = None) -> DataDomain:
    d = DataDomain(
        name=name,
        parent_id=parent.id if parent else None,
        uc_domain_id=uc_domain_id,
        created_by="test@example.com",
    )
    db.add(d)
    db.flush()
    db.refresh(d)
    return d


def _by_name(db: Session, name: str) -> Optional[DataDomain]:
    return db.query(DataDomain).filter(DataDomain.name == name).first()


# ======================================================================
# Import: UC -> Ontos
# ======================================================================

def _uc_two_level():
    return [
        UcDomain(domain_id="r1", name="Sales", tag_key="sales"),
        UcDomain(domain_id="r2", name="Marketing", tag_key="marketing"),
        UcDomain(domain_id="s1", name="EMEA", tag_key="emea", parent_domain_id="r1"),
        UcDomain(domain_id="s2", name="APAC", tag_key="apac", parent_domain_id="r1"),
    ]


def test_import_creates_two_level_tree_at_top_level(db_session: Session):
    mgr = DomainSyncManager(FakeUcClient(_uc_two_level()))
    result = mgr.execute_import(db=db_session, target_root_id=None, user_id="tester")

    assert result.created == 4
    assert result.matched == 0
    assert result.errors == 0

    sales = _by_name(db_session, "Sales")
    emea = _by_name(db_session, "EMEA")
    assert sales is not None and sales.parent_id is None
    assert sales.uc_domain_id == "r1"
    # subdomain nested under its root
    assert emea is not None and emea.parent_id == sales.id
    assert emea.uc_domain_id == "s1"

    # levels reported correctly
    levels = {(n.name, n.level) for n in result.nodes}
    assert ("Sales", 1) in levels and ("EMEA", 2) in levels


def test_import_is_idempotent_by_uc_domain_id(db_session: Session):
    client = FakeUcClient(_uc_two_level())
    mgr = DomainSyncManager(client)
    mgr.execute_import(db=db_session, target_root_id=None, user_id="tester")
    db_session.commit()

    # Re-run: everything should MATCH, nothing created.
    result2 = mgr.execute_import(db=db_session, target_root_id=None, user_id="tester")
    assert result2.created == 0
    assert result2.matched == 4
    assert db_session.query(DataDomain).count() == 4


def test_import_matches_existing_by_name_and_backfills_uc_id(db_session: Session):
    # Pre-existing Ontos domain with the same name but no uc_domain_id.
    _mk(db_session, "Sales")
    db_session.commit()

    mgr = DomainSyncManager(FakeUcClient([UcDomain(domain_id="r1", name="Sales", tag_key="sales")]))
    result = mgr.execute_import(db=db_session, target_root_id=None, user_id="tester")

    assert result.matched == 1 and result.created == 0
    sales = _by_name(db_session, "Sales")
    assert sales.uc_domain_id == "r1"  # backfilled
    assert db_session.query(DataDomain).count() == 1


def test_import_under_target_root(db_session: Session):
    root = _mk(db_session, "Organization")
    db_session.commit()

    mgr = DomainSyncManager(FakeUcClient(_uc_two_level()))
    mgr.execute_import(db=db_session, target_root_id=uuid.UUID(root.id), user_id="tester")

    sales = _by_name(db_session, "Sales")
    assert sales.parent_id == root.id  # UC roots placed under chosen root


def test_import_preview_writes_nothing(db_session: Session):
    mgr = DomainSyncManager(FakeUcClient(_uc_two_level()))
    preview = mgr.preview_import(db=db_session, target_root_id=None)

    assert preview.to_create == 4
    assert preview.to_match == 0
    assert db_session.query(DataDomain).count() == 0  # nothing persisted


# ======================================================================
# Export: Ontos -> UC
# ======================================================================

def test_export_maps_levels_and_skips_too_deep(db_session: Session):
    # Ontos tree:  Org -> Sales(L1) -> EMEA(L2) -> Team(L3, too deep)
    org = _mk(db_session, "Org")
    sales = _mk(db_session, "Sales", parent=org)
    emea = _mk(db_session, "EMEA", parent=sales)
    _mk(db_session, "Team", parent=emea)
    db_session.commit()

    client = FakeUcClient([])
    mgr = DomainSyncManager(client)
    result = mgr.execute_export(db=db_session, anchor_domain_id=uuid.UUID(org.id), user_id="tester")

    # Sales -> UC root, EMEA -> UC subdomain, Team -> skipped
    assert result.created == 2
    assert result.skipped == 1
    assert result.errors == 0

    created_names = {d.name: d for d in client.created}
    assert "Sales" in created_names and created_names["Sales"].parent_domain_id is None
    assert "EMEA" in created_names and created_names["EMEA"].parent_domain_id == created_names["Sales"].domain_id
    assert "Team" not in created_names

    # uc_domain_id written back onto the exported Ontos domains
    db_session.refresh(sales)
    assert sales.uc_domain_id == created_names["Sales"].domain_id

    skip_node = next(n for n in result.nodes if n.name == "Team")
    assert skip_node.action == SyncAction.SKIP and skip_node.level == 3


def test_export_no_anchor_uses_top_level(db_session: Session):
    top = _mk(db_session, "Finance")           # top-level -> UC root
    _mk(db_session, "Payroll", parent=top)      # child -> UC subdomain
    db_session.commit()

    client = FakeUcClient([])
    mgr = DomainSyncManager(client)
    result = mgr.execute_export(db=db_session, anchor_domain_id=None, user_id="tester")

    assert result.created == 2
    names = {d.name: d for d in client.created}
    assert names["Finance"].parent_domain_id is None
    assert names["Payroll"].parent_domain_id == names["Finance"].domain_id


def test_export_idempotent_by_uc_domain_id(db_session: Session):
    top = _mk(db_session, "Finance", uc_domain_id="uc-existing")
    db_session.commit()

    # UC already has that domain.
    client = FakeUcClient([UcDomain(domain_id="uc-existing", name="Finance", tag_key="finance")])
    mgr = DomainSyncManager(client)
    result = mgr.execute_export(db=db_session, anchor_domain_id=None, user_id="tester")

    assert result.matched == 1 and result.created == 0
    assert client.created == []  # nothing created on UC


def test_export_preview_writes_nothing(db_session: Session):
    org = _mk(db_session, "Org")
    _mk(db_session, "Sales", parent=org)
    db_session.commit()

    client = FakeUcClient([])
    mgr = DomainSyncManager(client)
    preview = mgr.preview_export(db=db_session, anchor_domain_id=uuid.UUID(org.id))

    assert preview.to_create == 1
    assert client.created == []  # no UC writes during preview


def test_export_unknown_anchor_raises(db_session: Session):
    mgr = DomainSyncManager(FakeUcClient([]))
    with pytest.raises(ValueError):
        mgr.preview_export(db=db_session, anchor_domain_id=uuid.uuid4())
