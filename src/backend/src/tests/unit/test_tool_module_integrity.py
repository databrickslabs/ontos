"""Structural guards for the LLM/MCP tool modules.

Ported from #677 (Ferdinand van Butzelaar). The bugs it fixed landed via
#923 and #954; these guards keep them from coming back.

1. **No shadowed tool classes.** ``src/tools/data_products.py`` and
   ``src/tools/data_contracts.py`` once defined the same tool class twice.
   Python keeps the *last* definition, so maintenance edits went to the dead
   copy. The AST guard fails on any re-introduced duplicate in any tool module.

2. **Every registered tool declares its own scope.** ``BaseTool.required_scope``
   defaults to ``"*"`` (admin wildcard). A tool that silently inherits it
   disappears from ``tools/list`` for every least-privilege MCP token and
   rejects ``tools/call`` with SCOPE_VIOLATION. Tools that are deliberately
   ungated (e.g. ``get_app_state``) must say so with an explicit
   ``required_scope = None``.
"""

# Set test environment variables BEFORE any app imports
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import ast
from collections import Counter
from pathlib import Path

import pytest

from src.tools.base import BaseTool
from src.tools.registry import create_default_registry

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"


@pytest.fixture(scope="module")
def registered_tools():
    registry = create_default_registry()
    return {d["name"]: registry.get(d["name"]) for d in registry.get_mcp_definitions()}


@pytest.mark.parametrize("module_path", sorted(TOOLS_DIR.glob("*.py")), ids=lambda p: p.name)
def test_tool_module_defines_each_class_once(module_path: Path):
    """A duplicated class silently shadows the earlier definition, so edits
    to the earlier one never run. Fail loudly instead."""
    tree = ast.parse(module_path.read_text(), filename=str(module_path))
    counts = Counter(node.name for node in tree.body if isinstance(node, ast.ClassDef))
    duplicates = sorted(name for name, count in counts.items() if count > 1)
    assert not duplicates, (
        f"{module_path.name} defines {duplicates} more than once; the later "
        f"definition shadows the earlier one"
    )


def test_every_registered_tool_declares_its_own_required_scope(registered_tools):
    """Inheriting ``BaseTool.required_scope`` ('*') makes a tool invisible and
    uncallable for every non-admin MCP token."""
    assert registered_tools, "registry is empty"
    inherited = sorted(
        name for name, tool in registered_tools.items()
        if "required_scope" not in type(tool).__dict__
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
        ("get_data_products", "data-products:read"),
        ("list_data_products", "data-products:read"),
        ("create_draft_data_product", "data-products:write"),
        ("update_data_product", "data-products:write"),
        ("delete_data_product", "data-products:write"),
        ("search_data_contracts", "contracts:read"),
        ("get_data_contract", "contracts:read"),
        ("get_data_contracts", "contracts:read"),
        ("list_data_contracts", "contracts:read"),
        ("create_draft_data_contract", "contracts:write"),
        ("update_data_contract", "contracts:write"),
        ("delete_data_contract", "contracts:write"),
    ],
)
def test_product_and_contract_tool_scopes(registered_tools, tool_name: str, expected_scope: str):
    assert tool_name in registered_tools, f"{tool_name} is not registered"
    assert registered_tools[tool_name].required_scope == expected_scope
