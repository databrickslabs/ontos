"""Unit tests for the bulk get-by-ids MCP tools (#922).

`get_data_products` / `get_data_contracts` fetch full detail for several ids in
one call, capped by a server-enforced maximum (default 20, hard max 100), and
report misses + truncation so an agent can page instead of calling get N times.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.tools.base import ToolContext
from src.tools.data_products import GetDataProductsBulkTool
from src.tools.data_contracts import GetDataContractsBulkTool


def _run(coro):
    return asyncio.run(coro)


def _product(pid: str):
    return SimpleNamespace(
        id=pid, name=f"P{pid}", domain="sales", description={"purpose": "x"},
        status="active", version="1.0.0", outputPorts=[], owner_team_id=None,
        owner_team_name=None, tenant=None,
    )


def _products_ctx(known: dict) -> ToolContext:
    mgr = MagicMock()
    mgr.get_product.side_effect = lambda pid: known.get(pid)
    return ToolContext(db=MagicMock(), settings=MagicMock(), data_products_manager=mgr)


class TestBulkProducts:
    def test_returns_detail_and_reports_missing(self):
        ctx = _products_ctx({"a": _product("a"), "b": _product("b")})
        res = _run(GetDataProductsBulkTool().execute(ctx, product_ids=["a", "missing", "b"]))
        assert res.success
        assert {p["id"] for p in res.data["products"]} == {"a", "b"}
        assert res.data["not_found"] == ["missing"]
        assert res.data["returned"] == 2 and res.data["requested"] == 3
        assert res.data["truncated"] is False
        # Full-detail shape (not just a summary row).
        assert "output_ports" in res.data["products"][0]

    def test_default_limit_caps_at_20(self):
        known = {str(i): _product(str(i)) for i in range(30)}
        ctx = _products_ctx(known)
        res = _run(GetDataProductsBulkTool().execute(ctx, product_ids=list(known)))
        assert res.data["returned"] == 20
        assert res.data["requested"] == 30
        assert res.data["limit"] == 20
        assert res.data["truncated"] is True

    def test_server_max_clamps_limit(self):
        known = {str(i): _product(str(i)) for i in range(150)}
        ctx = _products_ctx(known)
        res = _run(GetDataProductsBulkTool().execute(ctx, product_ids=list(known), limit=1000))
        assert res.data["limit"] == 100  # clamped to MAX_LIMIT
        assert res.data["returned"] == 100
        assert res.data["truncated"] is True

    def test_duplicate_ids_collapsed(self):
        ctx = _products_ctx({"a": _product("a")})
        res = _run(GetDataProductsBulkTool().execute(ctx, product_ids=["a", "a", "a"]))
        assert res.data["requested"] == 1
        assert res.data["returned"] == 1


class TestBulkContracts:
    def _ctx(self, known: dict, monkeypatch):
        import src.repositories.data_contracts_repository as repo_mod
        # Repo returns an opaque db_obj (truthy) for known ids, None otherwise.
        monkeypatch.setattr(
            repo_mod.data_contract_repo, "get_with_all",
            lambda db, id: (object() if id in known else None),
        )
        mgr = MagicMock()
        # _build_contract_api_model maps the (ignored) db_obj back to the fake contract.
        self._order = iter(known.values())
        mgr._build_contract_api_model.side_effect = lambda db, obj: next(self._order)
        return ToolContext(db=MagicMock(), settings=MagicMock(), data_contracts_manager=mgr)

    def test_returns_detail_and_reports_missing(self, monkeypatch):
        known = {
            "c1": SimpleNamespace(id="c1", name="C1", domain="sales", description=None,
                                  status="active", version="1.0.0", owner_team_name="T", dataProduct=None),
        }
        ctx = self._ctx(known, monkeypatch)
        res = _run(GetDataContractsBulkTool().execute(ctx, contract_ids=["c1", "nope"]))
        assert res.success
        assert [c["id"] for c in res.data["contracts"]] == ["c1"]
        assert res.data["not_found"] == ["nope"]
        assert res.data["truncated"] is False

    def test_server_max_clamps_limit(self, monkeypatch):
        known = {
            str(i): SimpleNamespace(id=str(i), name=str(i), domain=None, description=None,
                                    status="active", version="1", owner_team_name=None, dataProduct=None)
            for i in range(150)
        }
        ctx = self._ctx(known, monkeypatch)
        res = _run(GetDataContractsBulkTool().execute(ctx, contract_ids=list(known), limit=1000))
        assert res.data["limit"] == 100
        assert res.data["returned"] == 100
        assert res.data["truncated"] is True
