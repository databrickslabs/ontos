"""A failed domain tool ends its transaction (#1667).

A create or move with a parent takes the domain hierarchy lock, held until the
transaction ends. The chat and MCP tools share one session for the whole
request: without a rollback a refused parent would keep the lock across the
LLM's next turns and every other parent change would wait.
"""
import asyncio
import uuid
from unittest.mock import MagicMock, patch

from src.controller.data_domains_manager import (
    DataDomainManager,
    DomainParentCycleError,
    DomainParentNotFoundError,
)
from src.tools.base import ToolContext
from src.tools.domains import CreateDomainTool, DeleteDomainTool, UpdateDomainTool


def _ctx():
    return ToolContext(db=MagicMock(), settings=MagicMock())


def test_refused_move_rolls_back():
    ctx = _ctx()
    error = DomainParentCycleError("loop", domainId="a", parentId="b")
    with patch.object(DataDomainManager, "update_domain", side_effect=error):
        result = asyncio.run(UpdateDomainTool().execute(
            ctx, domain_id=str(uuid.uuid4()), parent_id=str(uuid.uuid4())))

    assert result.success is False
    ctx.db.rollback.assert_called_once()
    ctx.db.commit.assert_not_called()


def test_refused_create_rolls_back():
    ctx = _ctx()
    error = DomainParentNotFoundError("missing", parentId="p")
    with patch.object(DataDomainManager, "create_domain", side_effect=error):
        result = asyncio.run(CreateDomainTool().execute(
            ctx, name="Child", parent_id=str(uuid.uuid4())))

    assert result.success is False
    ctx.db.rollback.assert_called_once()
    ctx.db.commit.assert_not_called()


def test_failed_delete_rolls_back():
    ctx = _ctx()
    with patch.object(DataDomainManager, "delete_domain", side_effect=RuntimeError("boom")):
        result = asyncio.run(DeleteDomainTool().execute(ctx, domain_id=str(uuid.uuid4())))

    assert result.success is False
    ctx.db.rollback.assert_called_once()
