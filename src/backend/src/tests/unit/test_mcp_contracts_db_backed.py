"""MCP data-contracts get/list/delete must be DB-backed (#918).

Regression for the bug where these tools read the legacy in-memory ``self._contracts``
dict (empty in a deployed app) instead of Postgres, so a contract written via the
DB path (importer/UI) came back "not found". A contract created through
``create_from_upload`` lands in the DB but NOT in that dict — exactly the condition that
used to fail — so these tests assert the tools find/list/delete it.
"""
import asyncio
import uuid
from pathlib import Path

import pytest
from unittest.mock import MagicMock
from sqlalchemy.orm import Session

from src.controller.data_contracts_manager import DataContractsManager
from src.controller.data_products_manager import DataProductsManager
from src.db_models.data_contracts import DataContractDb
from src.tools.base import ToolContext
from src.tools.data_contracts import (
    GetDataContractTool,
    ListDataContractsTool,
    DeleteDataContractTool,
)
from src.tools.data_products import GetDataProductTool, DeleteDataProductTool


def _contract_manager() -> DataContractsManager:
    mgr = DataContractsManager(data_dir=Path("/tmp"))
    mgr._update_search_index = lambda *a, **k: None
    return mgr


def _odcs(name: str, **extra) -> dict:
    return {"apiVersion": "v3.1.0", "kind": "DataContract", "name": name,
            "version": "1.0.0", "status": "draft", **extra}


def _run(coro):
    return asyncio.run(coro)


class TestContractToolsAreDbBacked:
    def test_get_finds_db_written_contract(self, db_session: Session):
        mgr = _contract_manager()
        created = mgr.create_from_upload(db=db_session, parsed_odcs=_odcs("DB Only Contract"), current_user="a@b.com")
        # Sanity: it is NOT in the legacy in-memory store the old tool read.
        assert created.id not in getattr(mgr, "_contracts", {})

        ctx = ToolContext(db=db_session, settings=MagicMock(), data_contracts_manager=mgr)
        res = _run(GetDataContractTool().execute(ctx, contract_id=created.id))
        assert res.success is True
        assert res.data["id"] == created.id
        assert res.data["name"] == "DB Only Contract"

    def test_get_unknown_returns_not_found(self, db_session: Session):
        ctx = ToolContext(db=db_session, settings=MagicMock(), data_contracts_manager=_contract_manager())
        res = _run(GetDataContractTool().execute(ctx, contract_id=str(uuid.uuid4())))
        assert res.success is False and "not found" in (res.error or "").lower()

    def test_list_includes_db_written_contract(self, db_session: Session):
        mgr = _contract_manager()
        created = mgr.create_from_upload(db=db_session, parsed_odcs=_odcs("Listed DB Contract"), current_user="a@b.com")
        ctx = ToolContext(db=db_session, settings=MagicMock(), data_contracts_manager=mgr)
        res = _run(ListDataContractsTool().execute(ctx))
        assert res.success is True
        assert created.id in {c["id"] for c in res.data["contracts"]}

    def test_delete_removes_from_db(self, db_session: Session):
        mgr = _contract_manager()
        created = mgr.create_from_upload(db=db_session, parsed_odcs=_odcs("Deletable DB Contract"), current_user="a@b.com")
        ctx = ToolContext(db=db_session, settings=MagicMock(), data_contracts_manager=mgr)

        res = _run(DeleteDataContractTool().execute(ctx, contract_id=created.id))
        assert res.success is True
        # Gone from the database, not just an in-memory dict.
        assert db_session.get(DataContractDb, created.id) is None
        # And a subsequent get reports not-found.
        res2 = _run(GetDataContractTool().execute(ctx, contract_id=created.id))
        assert res2.success is False


class TestProductToolsStillWork:
    """Guard the duplicate-class cleanup in data_products.py (dead copies removed)."""

    @pytest.fixture
    def product_manager(self, db_session: Session) -> DataProductsManager:
        return DataProductsManager(
            db=db_session, ws_client=MagicMock(),
            notifications_manager=MagicMock(), tags_manager=MagicMock(),
        )

    def test_get_and_delete_product_db_backed(self, product_manager, db_session):
        created = product_manager.create_product(
            {"apiVersion": "v1.0.0", "kind": "DataProduct", "id": str(uuid.uuid4()),
             "name": "DB Product", "version": "1.0.0", "status": "active"},
            db=db_session, user="a@b.com",
        )
        ctx = ToolContext(db=db_session, settings=MagicMock(), data_products_manager=product_manager)
        got = _run(GetDataProductTool().execute(ctx, product_id=created.id))
        assert got.success is True and got.data["id"] == created.id
        deleted = _run(DeleteDataProductTool().execute(ctx, product_id=created.id))
        assert deleted.success is True
