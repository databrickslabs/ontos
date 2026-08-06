"""Unit tests for the LLM/MCP tool modules' structural integrity and their
data-product / data-contract implementations.

Three layers under test:

1. **No shadowed tool classes.** ``src/tools/data_products.py`` and
   ``src/tools/data_contracts.py`` each used to define the same tool class
   twice. Python keeps the *last* definition, so the copy that maintenance
   commits kept editing (junction-table domains, ``required_scope``) was the
   dead one. The AST guard below fails on any re-introduced duplicate in any
   tool module.

2. **Every registered tool declares its own scope.** ``BaseTool.required_scope``
   defaults to ``"*"`` (admin wildcard). A tool that silently inherits it
   disappears from ``tools/list`` for every least-privilege MCP token and
   rejects ``tools/call`` with SCOPE_VIOLATION. That is exactly what the
   shadowing caused for five registered tools.

3. **Contract/product tools read the database.** The shadowing copies called
   ``DataContractsManager.list_contracts()`` / ``get_contract()``, which are
   the legacy in-memory store — never populated at runtime, so the tools
   always reported zero contracts. The surviving copies query the ORM, so
   these tests insert real rows and assert the tools find them.
"""

# Set test environment variables BEFORE any app imports
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import ast
import uuid
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session
from src.db_models.data_contracts import DataContractDb
from src.db_models.data_products import DataProductDb, DescriptionDb, OutputPortDb
from src.tools.base import BaseTool, ToolContext
from src.tools.registry import create_default_registry

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def ctx(db_session: Session) -> ToolContext:
    """ToolContext over the in-memory test DB with stub managers."""
    return ToolContext(
        db=db_session,
        settings=MagicMock(),
        data_products_manager=MagicMock(),
        data_contracts_manager=MagicMock(),
    )


def _make_contract(db: Session, *, name: str, status: str = "active", purpose: str = None) -> str:
    contract_id = str(uuid.uuid4())
    db.add(DataContractDb(
        id=contract_id,
        name=name,
        version="1.0.0",
        status=status,
        version_family_id=contract_id,
        description_purpose=purpose,
    ))
    db.commit()
    return contract_id


def _make_product(
    db: Session,
    *,
    name: str,
    status: str = "active",
    purpose: str = None,
    output_port: str = None,
) -> str:
    product_id = str(uuid.uuid4())
    db.add(DataProductDb(
        id=product_id,
        name=name,
        version="1.0.0",
        status=status,
        version_family_id=product_id,
    ))
    if purpose is not None:
        db.add(DescriptionDb(id=str(uuid.uuid4()), product_id=product_id, purpose=purpose))
    if output_port is not None:
        db.add(OutputPortDb(
            id=str(uuid.uuid4()), product_id=product_id, name=output_port, version="1.0.0"
        ))
    db.commit()
    return product_id


# ---------------------------------------------------------------------------
# 1. Structural guards
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module_path", sorted(TOOLS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_tool_module_defines_each_class_once(module_path: Path):
    """A duplicated class silently shadows the earlier definition, so edits
    to the earlier one never run. Fail loudly instead."""
    tree = ast.parse(module_path.read_text(), filename=str(module_path))
    counts = Counter(
        node.name for node in tree.body if isinstance(node, ast.ClassDef)
    )
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    assert not duplicates, (
        f"{module_path.name} defines {duplicates} more than once; the later "
        f"definition shadows the earlier one"
    )


def test_every_registered_tool_declares_its_own_required_scope():
    """Inheriting ``BaseTool.required_scope`` ('*') makes a tool invisible and
    uncallable for every non-admin MCP token."""
    registry = create_default_registry()
    tools = [registry.get(d["name"]) for d in registry.get_mcp_definitions()]

    inherited = sorted(
        t.name for t in tools if "required_scope" not in type(t).__dict__
    )
    assert not inherited, (
        f"tools {inherited} inherit the wildcard scope "
        f"{BaseTool.required_scope!r} instead of declaring their own"
    )


@pytest.mark.parametrize(
    "tool_name,expected_scope",
    [
        ("search_data_products", "data-products:read"),
        ("get_data_product", "data-products:read"),
        ("list_data_products", "data-products:read"),
        ("delete_data_product", "data-products:write"),
        ("search_data_contracts", "contracts:read"),
        ("get_data_contract", "contracts:read"),
        ("list_data_contracts", "contracts:read"),
        ("delete_data_contract", "contracts:write"),
    ],
)
def test_product_and_contract_tool_scopes(tool_name: str, expected_scope: str):
    registry = create_default_registry()
    tool = registry.get(tool_name)
    assert tool is not None, f"{tool_name} is not registered"
    assert tool.required_scope == expected_scope


# ---------------------------------------------------------------------------
# 2. Data contract tools operate on the database
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_data_contracts_finds_persisted_contract(ctx: ToolContext, db_session: Session):
    _make_contract(db_session, name="Customer Master Contract", purpose="Golden record")

    result = await create_default_registry().execute(
        "search_data_contracts", ctx, {"query": "customer"}
    )

    assert result.success, result.error
    names = [c["name"] for c in result.data["contracts"]]
    assert names == ["Customer Master Contract"]
    assert result.data["contracts"][0]["description"] == "Golden record"


@pytest.mark.asyncio
async def test_search_data_contracts_matches_on_purpose_text(ctx: ToolContext, db_session: Session):
    """``DataContractDb`` has no ``description`` attribute — the purpose lives
    in ``description_purpose``. Reading the wrong one raised AttributeError."""
    _make_contract(db_session, name="Contract A", purpose="Revenue reporting")

    result = await create_default_registry().execute(
        "search_data_contracts", ctx, {"query": "revenue"}
    )

    assert result.success, result.error
    assert [c["name"] for c in result.data["contracts"]] == ["Contract A"]


@pytest.mark.asyncio
async def test_get_data_contract_reads_from_database(ctx: ToolContext, db_session: Session):
    contract_id = _make_contract(db_session, name="Orders Contract", purpose="Order events")

    result = await create_default_registry().execute(
        "get_data_contract", ctx, {"contract_id": contract_id}
    )

    assert result.success, result.error
    assert result.data["name"] == "Orders Contract"
    assert result.data["description"] == "Order events"


@pytest.mark.asyncio
async def test_list_data_contracts_filters_by_status(ctx: ToolContext, db_session: Session):
    _make_contract(db_session, name="Active Contract", status="active")
    _make_contract(db_session, name="Draft Contract", status="draft")

    result = await create_default_registry().execute(
        "list_data_contracts", ctx, {"status": "draft"}
    )

    assert result.success, result.error
    assert [c["name"] for c in result.data["contracts"]] == ["Draft Contract"]


# ---------------------------------------------------------------------------
# 3. Data product tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_data_products_is_registered_and_returns_products(ctx: ToolContext, db_session: Session):
    """Regression for #660: the tool passed ``domain``/``status`` kwargs that
    ``DataProductsManager.list_products`` does not accept."""
    _make_product(db_session, name="Customer 360", purpose="Unified customer view")

    result = await create_default_registry().execute("list_data_products", ctx, {})

    assert result.success, result.error
    assert [p["name"] for p in result.data["products"]] == ["Customer 360"]
    assert result.data["products"][0]["description"] == "Unified customer view"


@pytest.mark.asyncio
async def test_list_data_products_filters_by_status_and_limit(ctx: ToolContext, db_session: Session):
    _make_product(db_session, name="Product A", status="active")
    _make_product(db_session, name="Product B", status="draft")
    _make_product(db_session, name="Product C", status="draft")

    result = await create_default_registry().execute(
        "list_data_products", ctx, {"status": "draft", "limit": 1}
    )

    assert result.success, result.error
    assert len(result.data["products"]) == 1
    assert result.data["products"][0]["status"] == "draft"


@pytest.mark.asyncio
async def test_search_data_products_matches_structured_description(ctx: ToolContext, db_session: Session):
    """``DataProductDb.description`` is a relationship to ``DescriptionDb``,
    not a JSON string, so ``.get('purpose')`` silently returned None and
    description search never matched."""
    _make_product(db_session, name="Unrelated Name", purpose="Warehouse inventory levels")

    result = await create_default_registry().execute(
        "search_data_products", ctx, {"query": "inventory"}
    )

    assert result.success, result.error
    assert [p["name"] for p in result.data["products"]] == ["Unrelated Name"]
    assert result.data["products"][0]["description"] == "Warehouse inventory levels"


@pytest.mark.asyncio
async def test_get_data_product_returns_description_and_output_ports(ctx: ToolContext, db_session: Session):
    """``output_ports`` is a relationship to ``OutputPortDb``, so the old
    ``isinstance(port, dict)`` branch never matched and output_tables was
    always empty."""
    product_id = _make_product(
        db_session, name="Sales Product", purpose="Sales facts", output_port="main.sales.facts"
    )

    result = await create_default_registry().execute(
        "get_data_product", ctx, {"product_id": product_id}
    )

    assert result.success, result.error
    assert result.data["name"] == "Sales Product"
    assert result.data["description"] == "Sales facts"
    assert result.data["output_tables"] == ["main.sales.facts"]
