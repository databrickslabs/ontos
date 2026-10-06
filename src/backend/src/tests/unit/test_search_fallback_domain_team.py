"""Search findability fallback for ODCS/ODPS-supplied domain & team.

When an imported contract/product carries a `domain` or team that does NOT match a native
Ontos entity (create_missing off → no native assignment), the supplied value must still be
findable via search. The importer preserves the domain string as the `ontosOriginalDomain`
custom property (#851); these tests assert the search index now surfaces that string plus the
supplied team (name + members), and that the shared search path (used by both UI global search
and the MCP search_* tools) matches on them.
"""
import uuid
from pathlib import Path

import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.controller.search_manager import SearchManager
from src.db_models.data_contracts import DataContractDb


# Names chosen to be absent from the native taxonomy so nothing resolves/auto-creates.
UNMATCHED_CONTRACT_DOMAIN = "sales-fallback-xyz"
UNMATCHED_PRODUCT_DOMAIN = "exec-fallback-xyz"
CONTRACT_TEAM = "Sales Analytics Team"
PRODUCT_TEAM = "Executive Reporting Team"


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


def _odcs(name: str, **extra) -> dict:
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "name": name,
            "version": "1.0.0", "status": "draft", **extra}


def _odps(name: str, **extra) -> dict:
    return {"apiVersion": "v1.0.0", "kind": "DataProduct", "id": str(uuid.uuid4()),
            "name": name, "version": "1.0.0", "status": "active", **extra}


def _ids(results) -> set:
    return {r.get("id") for r in results}


class TestContractSearchFallback:
    def test_index_surfaces_supplied_domain_and_team(self, db_session):
        mgr = _contract_manager()
        created = mgr.create_from_upload(
            db=db_session,
            parsed_odcs=_odcs(
                "Sales Aggregates Fallback",
                domain=UNMATCHED_CONTRACT_DOMAIN,
                team={"name": CONTRACT_TEAM,
                      "members": [{"username": "aturing@example.com", "name": "Alan Turing", "role": "owner"}]},
            ),
            current_user="a@b.com",
        )
        db_obj = db_session.get(DataContractDb, created.id)
        item = mgr._build_search_index_item(db_obj, db_session)

        # Unmatched domain string is preserved and indexed (tags + primary domain extra_data).
        assert UNMATCHED_CONTRACT_DOMAIN in item.tags
        assert item.extra_data["domain"] == UNMATCHED_CONTRACT_DOMAIN
        # Supplied team (object name + member) is indexed; owner falls back to the supplied team.
        assert CONTRACT_TEAM in item.tags
        assert item.extra_data["owner"] == CONTRACT_TEAM
        assert "Alan Turing" in item.extra_data["team_members"]

    def test_shared_search_finds_contract_by_supplied_values(self, db_session):
        mgr = _contract_manager()
        created = mgr.create_from_upload(
            db=db_session,
            parsed_odcs=_odcs(
                "Sales Aggregates Searchable",
                domain=UNMATCHED_CONTRACT_DOMAIN,
                team={"name": CONTRACT_TEAM, "members": []},
            ),
            current_user="a@b.com",
        )
        item = mgr._build_search_index_item(db_session.get(DataContractDb, created.id), db_session)

        sm = SearchManager([])  # no live managers; we seed the index directly
        sm.index = [item]
        by_domain = sm.query_index(UNMATCHED_CONTRACT_DOMAIN, type_filter="data-contract")
        by_team = sm.query_index(CONTRACT_TEAM, type_filter="data-contract")
        # Result ids are the bare entity id (the type prefix is stripped by the scorer).
        assert created.id in _ids(by_domain["results"])
        assert created.id in _ids(by_team["results"])


class TestProductSearchFallback:
    def test_index_surfaces_supplied_domain_and_team(self, product_manager, db_session):
        created = product_manager.create_product(
            _odps(
                "Executive Dashboard Fallback",
                domain=UNMATCHED_PRODUCT_DOMAIN,
                team={"name": PRODUCT_TEAM,
                      "members": [{"username": "ghopper@example.com", "name": "Grace Hopper", "role": "owner"}]},
            ),
            db=db_session, user="a@b.com", create_missing_domains=False,
        )
        api = product_manager.get_product(created.id)
        item = product_manager._build_search_index_item(api)

        assert UNMATCHED_PRODUCT_DOMAIN in item.tags
        assert UNMATCHED_PRODUCT_DOMAIN in item.extra_data["domains"]
        assert item.extra_data["domain"] == UNMATCHED_PRODUCT_DOMAIN
        # Team already indexed pre-change; assert the supplied team stays findable.
        assert item.extra_data["product_team"] == PRODUCT_TEAM
        assert item.extra_data["owner"] == PRODUCT_TEAM  # falls back to product team when no native owner
        assert "Grace Hopper" in item.extra_data["team_members"]

    def test_shared_search_finds_product_by_supplied_values(self, product_manager, db_session):
        created = product_manager.create_product(
            _odps("Executive Dashboard Searchable", domain=UNMATCHED_PRODUCT_DOMAIN,
                  team={"name": PRODUCT_TEAM, "members": []}),
            db=db_session, user="a@b.com", create_missing_domains=False,
        )
        item = product_manager._build_search_index_item(product_manager.get_product(created.id))

        sm = SearchManager([])  # no live managers; we seed the index directly
        sm.index = [item]
        by_domain = sm.query_index(UNMATCHED_PRODUCT_DOMAIN, type_filter="data-product")
        by_team = sm.query_index(PRODUCT_TEAM, type_filter="data-product")
        assert created.id in _ids(by_domain["results"])
        assert created.id in _ids(by_team["results"])


class TestNativeDomainNotDuplicated:
    def test_resolved_domain_indexed_once(self, db_session):
        """A domain that DID resolve natively must not be double-indexed by the original-string
        fallback (the de-dupe guard)."""
        from src.models.data_domains import DataDomainCreate
        from src.repositories.data_domain_repository import data_domain_repo
        name = "SearchDedupeDomain"
        if not data_domain_repo.get_by_name(db_session, name=name):
            data_domain_repo.create(db=db_session, obj_in=DataDomainCreate(name=name))
            db_session.commit()

        mgr = _contract_manager()
        created = mgr.create_from_upload(
            db=db_session, parsed_odcs=_odcs("C dedupe", domain=name), current_user="a@b.com",
        )
        item = mgr._build_search_index_item(db_session.get(DataContractDb, created.id), db_session)
        assert item.tags.count(name) == 1
