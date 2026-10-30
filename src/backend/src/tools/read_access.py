"""The product and contract read rules, applied to what the assistant tools return.

The same rules as the REST routes: ``src.common.product_read_rule`` for data
products and ``DataContractsManager.readable_contracts`` for data contracts,
with the caller's facts resolved once per request in ``ctx.caller``. Without a
caller a tool reads like a consumer: published items only.

An item the caller can't read is answered like a missing one; the result's
``denied_reason`` (audit only) says it was the read rule.
"""

from typing import Any, Iterable, List, Optional

from src.common.logging import get_logger
from src.common.product_read_rule import can_read_product as _can_read_product_rule
from src.tools.base import ToolCaller, ToolContext, ToolResult

logger = get_logger(__name__)

NOT_READABLE = "not_readable"
PRODUCT_ITEM_PREFIX = "product::"
CONTRACT_ITEM_PREFIX = "contract::"

_ANONYMOUS = ToolCaller(email=None, auth_path="none")


def _caller(ctx: ToolContext) -> ToolCaller:
    return ctx.caller or _ANONYMOUS


def can_read_product(ctx: ToolContext, product: Any) -> bool:
    caller = _caller(ctx)
    if caller.full_access:
        return True
    try:
        return _can_read_product_rule(
            ctx.db,
            product,
            is_admin=caller.products_admin,
            caller_email=caller.email,
            caller_groups=caller.groups,
            caller_team_ids=caller.team_ids,
        )
    except Exception:
        logger.exception("Product read rule failed for %s; denying", getattr(product, "id", None))
        return False


def readable_contract_rows(ctx: ToolContext, rows: Iterable[Any]) -> List[Any]:
    """The contract rows (``DataContractDb``) the caller may read, in their order."""
    rows = list(rows)
    caller = _caller(ctx)
    if caller.full_access or caller.contracts_admin:
        return rows
    manager = ctx.data_contracts_manager
    if manager is None or not hasattr(manager, "readable_contracts"):
        # Without the manager only the consumer part of the rule can be applied.
        from src.controller.data_contracts_manager import DataContractsManager

        return [
            r for r in rows
            if not r.draft_owner_id and DataContractsManager._visible_to_non_admin(r, set())
        ]
    return manager.readable_contracts(
        ctx.db,
        rows,
        is_admin=False,
        caller_email=caller.email,
        caller_team_ids=caller.team_ids,
    )


def can_read_contract(ctx: ToolContext, row: Any) -> bool:
    try:
        return bool(readable_contract_rows(ctx, [row]))
    except Exception:
        logger.exception("Contract read rule failed for %s; denying", getattr(row, "id", None))
        return False


def hidden_item_ids(ctx: ToolContext, type_filter: Optional[str] = None) -> set:
    """Search index ids (``product::<id>``, ``contract::<id>``) the caller can't read.

    Passed to the search as ``exclude_ids`` so the rows are dropped before
    pagination and facets.
    """
    hidden: set = set()
    if type_filter in (None, "", "data-product"):
        hidden |= _hidden_products(ctx)
    if type_filter in (None, "", "data-contract"):
        hidden |= _hidden_contracts(ctx)
    return hidden


def _hidden_products(ctx: ToolContext) -> set:
    caller = _caller(ctx)
    if caller.full_access or caller.products_admin:
        return set()
    from src.common.product_read_rule import is_published_product
    from src.db_models.data_products import DataProductDb

    rows = ctx.db.query(DataProductDb).all()
    return {
        f"{PRODUCT_ITEM_PREFIX}{r.id}"
        for r in rows
        if not is_published_product(r) and not can_read_product(ctx, r)
    }


def _hidden_contracts(ctx: ToolContext) -> set:
    caller = _caller(ctx)
    if caller.full_access or caller.contracts_admin:
        return set()
    from src.db_models.data_contracts import DataContractDb

    rows = ctx.db.query(DataContractDb).all()
    readable = {r.id for r in readable_contract_rows(ctx, rows)}
    return {f"{CONTRACT_ITEM_PREFIX}{r.id}" for r in rows if r.id not in readable}


# Entity types (semantic links, tag assignments, cost items) under a read rule.
_ITEM_PREFIX_BY_ENTITY_TYPE = {
    "data_product": PRODUCT_ITEM_PREFIX,
    "data_contract": CONTRACT_ITEM_PREFIX,
}


def entity_is_unreadable(ctx: ToolContext, entity_type: str, entity_id: str) -> bool:
    """True when the product or contract exists and the caller can't read it.

    Other entity types, and ids that don't exist, are not under a read rule here.
    """
    if entity_type == "data_product":
        from src.db_models.data_products import DataProductDb

        row = ctx.db.get(DataProductDb, entity_id)
        return row is not None and not can_read_product(ctx, row)
    if entity_type == "data_contract":
        from src.db_models.data_contracts import DataContractDb

        row = ctx.db.get(DataContractDb, entity_id)
        return row is not None and not can_read_contract(ctx, row)
    return False


def hidden_entity_keys(ctx: ToolContext) -> set:
    """``(entity_type, entity_id)`` of every product and contract the caller can't read."""
    hidden = hidden_item_ids(ctx)
    keys = set()
    for entity_type, prefix in _ITEM_PREFIX_BY_ENTITY_TYPE.items():
        keys |= {(entity_type, i[len(prefix):]) for i in hidden if i.startswith(prefix)}
    return keys


def denied(ctx: ToolContext, tool_name: str, result: ToolResult, ids: Iterable[str]) -> ToolResult:
    """Mark ``result`` as limited by the read rule (audit only) and log it."""
    ids = list(ids)
    if not ids:
        return result
    caller = _caller(ctx)
    logger.info(
        "[%s] read rule: %d item(s) answered as not found; caller=%s auth_path=%s",
        tool_name, len(ids), caller.email, caller.auth_path,
    )
    result.denied_reason = NOT_READABLE
    return result
