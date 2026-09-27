"""Manager-level tests for domain reconciliation on import + round-trip (#851).

Verifies the wiring through the managers (not just the adapter): best-effort match,
no silent auto-create, the opt-in create_missing toggle, the ontosOriginalDomain
provenance property, and a lossless export→re-import rebind via ontosDomainId.
"""
import uuid
from pathlib import Path

import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.domain_export_adapter import (
    ONTOS_DOMAIN_ID_PROPERTY,
    ONTOS_ORIGINAL_DOMAIN_PROPERTY,
)
from src.models.data_domains import DataDomainCreate
from src.repositories.data_domain_repository import data_domain_repo
from src.repositories.entity_domain_association_repository import entity_domain_repo


def _contract_manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path("/tmp"))
    mgr._update_search_index = lambda *a, **k: None
    return mgr


@pytest.fixture
def product_manager(db_session: Session) -> DataProductsManager:
    return DataProductsManager(
        db=db_session, ws_client=MagicMock(),
        notifications_manager=MagicMock(), tags_manager=MagicMock(),
    )


@pytest.fixture
def sales_domain(db_session: Session) -> str:
    # The managers under test call db.commit(), so rows persist across tests in the shared
    # session — get-or-create keeps this unique-named domain idempotent across the module.
    existing = data_domain_repo.get_by_name(db_session, name="Sales")
    if existing:
        return existing.id
    d = data_domain_repo.create(db=db_session, obj_in=DataDomainCreate(name="Sales"))
    db_session.commit()
    return d.id


def _odcs(name: str, **extra) -> dict:
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "name": name,
            "version": "1.0.0", "status": "draft", **extra}


def _assigned_ids(db, entity_type, entity_id):
    assigned = entity_domain_repo.get_domains_for_entity(db, entity_type=entity_type, entity_id=entity_id)
    return {a.domain_id for a in assigned}, next((a.domain_id for a in assigned if a.is_primary), None)


class TestContractDomainReconcile:
    def test_matches_existing_domain_by_name(self, db_session, sales_domain):
        mgr = _contract_manager()
        created = mgr.create_from_upload(db=db_session, parsed_odcs=_odcs("C match", domain="Sales"), current_user="a@b.com")
        ids, primary = _assigned_ids(db_session, "data_contract", created.id)
        assert ids == {sales_domain} and primary == sales_domain

    def test_unknown_domain_left_unassigned_but_provenance_kept(self, db_session, sales_domain):
        mgr = _contract_manager()
        created = mgr.create_from_upload(
            db=db_session, parsed_odcs=_odcs("C ghost", domain="GhostDomain"), current_user="a@b.com",
        )
        ids, _ = _assigned_ids(db_session, "data_contract", created.id)
        assert ids == set()  # no silent auto-create
        # Provenance recorded on export.
        odcs = mgr.build_odcs_from_db(created, db_session)
        original = next((c["value"] for c in odcs.get("customProperties", [])
                         if c.get("property") == ONTOS_ORIGINAL_DOMAIN_PROPERTY), None)
        assert original == ["GhostDomain"]

    def test_create_missing_toggle_creates_and_assigns(self, db_session, sales_domain):
        mgr = _contract_manager()
        created = mgr.create_from_upload(
            db=db_session, parsed_odcs=_odcs("C create", domain="FreshDomain"),
            current_user="a@b.com", create_missing_domains=True,
        )
        ids, primary = _assigned_ids(db_session, "data_contract", created.id)
        made = data_domain_repo.get_by_name(db_session, name="FreshDomain")
        assert made is not None and ids == {made.id} and primary == made.id

    def test_export_emits_ontos_domain_id_and_reimport_rebinds(self, db_session, sales_domain):
        mgr = _contract_manager()
        created = mgr.create_from_upload(db=db_session, parsed_odcs=_odcs("C rt", domain="Sales"), current_user="a@b.com")
        odcs = mgr.build_odcs_from_db(created, db_session)
        ontos_ids = next((c["value"] for c in odcs.get("customProperties", [])
                          if c.get("property") == ONTOS_DOMAIN_ID_PROPERTY), None)
        assert ontos_ids == [sales_domain]
        # Re-import the exported dict → rebinds to the same domain id via ontosDomainId.
        odcs["name"] = "C rt reimport"
        reimported = mgr.create_from_upload(db=db_session, parsed_odcs=odcs, current_user="a@b.com")
        ids, primary = _assigned_ids(db_session, "data_contract", reimported.id)
        assert ids == {sales_domain} and primary == sales_domain


class TestProductDomainReconcile:
    def test_matches_existing_domain_by_name(self, product_manager, db_session, sales_domain):
        created = product_manager.create_product(
            {"name": "P match", "version": "1.0.0", "productType": "sourceAligned", "domain": "Sales"},
            db=db_session, user="a@b.com", preserve_source_id=True,
        )
        ids, primary = _assigned_ids(db_session, "data_product", created.id)
        assert ids == {sales_domain} and primary == sales_domain

    def test_unknown_domain_left_unassigned_by_default(self, product_manager, db_session, sales_domain):
        created = product_manager.create_product(
            {"name": "P ghost", "version": "1.0.0", "productType": "sourceAligned", "domain": "GhostDomain"},
            db=db_session, user="a@b.com", preserve_source_id=True,
        )
        ids, _ = _assigned_ids(db_session, "data_product", created.id)
        assert ids == set()

    def test_create_missing_toggle_creates_and_assigns(self, product_manager, db_session, sales_domain):
        created = product_manager.create_product(
            {"name": "P create", "version": "1.0.0", "productType": "sourceAligned", "domain": "FreshProdDomain"},
            db=db_session, user="a@b.com", preserve_source_id=True, create_missing_domains=True,
        )
        made = data_domain_repo.get_by_name(db_session, name="FreshProdDomain")
        ids, primary = _assigned_ids(db_session, "data_product", created.id)
        assert made is not None and ids == {made.id} and primary == made.id
