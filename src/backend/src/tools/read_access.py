"""The product and contract read rules, applied to what the assistant tools return.

The same rules as the REST routes: ``src.common.product_read_rule`` for data
products and ``DataContractsManager.readable_contracts`` for data contracts,
with the caller's facts resolved once per request in ``ctx.caller``. Without a
caller a tool reads like a consumer: published items only.

The filter is an allow-list: a product or contract (or anything that belongs to
one: a contract's schemas and properties, its graph node) is returned only when
its id is in the caller's readable set, computed from the committed rows. So an
index entry or link whose row the caller can't see, for any reason, is left out.
Feature admins skip the filter. The readable sets are kept in ``ctx.cache`` for
the request.

An item the caller can't read is answered like a missing one; the result's
``denied_reason`` (audit only) says it was the read rule.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

from src.common.features import FeatureAccessLevel
from src.common.logging import get_logger
from src.common.product_read_rule import can_read_product as _can_read_product_rule
from src.tools.base import ToolCaller, ToolContext, ToolResult

logger = get_logger(__name__)

NOT_READABLE = "not_readable"
PRODUCT_ITEM_PREFIX = "product::"
CONTRACT_ITEM_PREFIX = "contract::"
PRODUCT_TYPE = "data-product"
CONTRACT_TYPE = "data-contract"

_ANONYMOUS = ToolCaller(email=None, auth_path="none")

# Entity types (semantic links, tag assignments, cost items, graph nodes) and
# the kind of row whose read rule applies. Schema and property ids are
# ``<contract_id>#<schema>[#<property>]``.
_KIND_BY_ENTITY_TYPE = {
    "data_product": PRODUCT_TYPE,
    "data_contract": CONTRACT_TYPE,
    "data_contract_schema": CONTRACT_TYPE,
    "data_contract_property": CONTRACT_TYPE,
}
_ITEM_PREFIX_BY_KIND = {PRODUCT_TYPE: PRODUCT_ITEM_PREFIX, CONTRACT_TYPE: CONTRACT_ITEM_PREFIX}
# The feature whose Read-only level a product / contract item needs, as the
# REST GETs (PermissionChecker(..., READ_ONLY)).
FEATURE_BY_KIND = {PRODUCT_TYPE: "data-products", CONTRACT_TYPE: "data-contracts"}
_GRAPH_PREFIX = "urn:ontos:"


def _caller(ctx: ToolContext) -> ToolCaller:
    return ctx.caller or _ANONYMOUS


def has_read_level(ctx: ToolContext, kind: str) -> bool:
    """Whether the caller has the feature's Read-only level for products (or contracts).

    A feature admin (``products_admin`` / ``contracts_admin``) has it.
    """
    caller = _caller(ctx)
    if caller.full_access or reads_all(ctx, kind):
        return True
    return caller.has_level(FEATURE_BY_KIND[kind], FeatureAccessLevel.READ_ONLY)


def allowed_features(ctx: ToolContext) -> Optional[List[str]]:
    """Features whose index rows the caller may see in ``global_search``, as
    ``/api/search`` keeps a row only with Read-only on its ``feature_id``.

    ``None`` = every feature.
    """
    caller = _caller(ctx)
    if caller.full_access:
        return None
    features = {f for f in caller.permissions
                if caller.has_level(f, FeatureAccessLevel.READ_ONLY)}
    features |= {FEATURE_BY_KIND[k] for k in FEATURE_BY_KIND if has_read_level(ctx, k)}
    return sorted(features)


def can_read_product(ctx: ToolContext, product: Any) -> bool:
    caller = _caller(ctx)
    if caller.full_access:
        return True
    if not has_read_level(ctx, PRODUCT_TYPE):
        return False
    try:
        return _can_read_product_rule(
            ctx.db,
            product,
            is_admin=caller.products_admin,
            caller_email=caller.email,
            caller_groups=caller.groups,
            caller_team_ids=caller.team_ids,
            caller_project_ids=caller.project_ids,
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
    if not has_read_level(ctx, CONTRACT_TYPE):
        return []
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


def reads_all(ctx: ToolContext, kind: str) -> bool:
    """Whether the caller reads every product (or contract): no filter at all."""
    caller = _caller(ctx)
    if caller.full_access:
        return True
    return caller.products_admin if kind == PRODUCT_TYPE else caller.contracts_admin


def readable_ids(ctx: ToolContext, kind: str) -> Optional[set]:
    """Ids of the products (``data-product``) or contracts the caller may read.

    ``None`` when the caller reads them all; empty without the feature's
    Read-only level. Computed once per request.
    """
    if reads_all(ctx, kind):
        return None
    if not has_read_level(ctx, kind):
        return set()
    key = f"readable_ids:{kind}"
    if key not in ctx.cache:
        from sqlalchemy.orm import lazyload, load_only

        # Only the columns the rule reads, and none of the eager relationships.
        if kind == PRODUCT_TYPE:
            from src.db_models.data_products import DataProductDb as M

            cols = (M.id, M.status, M.draft_owner_id, M.owner_team_id, M.project_id)
            rows = ctx.db.query(M).options(load_only(*cols), lazyload("*")).all()
            ctx.cache[key] = {str(r.id) for r in rows if can_read_product(ctx, r)}
        else:
            from src.db_models.data_contracts import DataContractDb as M

            cols = (M.id, M.status, M.draft_owner_id, M.owner_team_id, M.version_family_id)
            rows = ctx.db.query(M).options(load_only(*cols), lazyload("*")).all()
            ctx.cache[key] = {str(r.id) for r in readable_contract_rows(ctx, rows)}
    return ctx.cache[key]


def allowed_ids_by_type(ctx: ToolContext, type_filter: Optional[str] = None) -> Dict[str, set]:
    """For the search: index type -> the index ids (``product::<id>``) the caller may see.

    A type that is not in the dict is not filtered (other types, or a feature
    admin). Passed to the search so the filter applies before pagination,
    counts and facets.
    """
    allowed: Dict[str, set] = {}
    for kind, prefix in _ITEM_PREFIX_BY_KIND.items():
        if type_filter not in (None, "", kind):
            continue
        ids = readable_ids(ctx, kind)
        if ids is not None:
            allowed[kind] = {f"{prefix}{i}" for i in ids}
    return allowed


def owning_row(entity_type: str, entity_id: Any) -> Optional[Tuple[str, str]]:
    """``(kind, row id)`` whose read rule applies to the entity, or None."""
    kind = _KIND_BY_ENTITY_TYPE.get(str(entity_type or ""))
    if kind is None or entity_id is None:
        return None
    row_id = str(entity_id)
    if kind == CONTRACT_TYPE:
        row_id = row_id.split("#", 1)[0]
    return kind, row_id


def entity_is_unreadable(ctx: ToolContext, entity_type: str, entity_id: Any) -> bool:
    """True when the entity belongs to a product or contract the caller can't read.

    Other entity types are not under a read rule here. An id without a
    committed row the caller may read counts as unreadable (fail closed).
    """
    owner = owning_row(entity_type, entity_id)
    if owner is None:
        return False
    kind, row_id = owner
    ids = readable_ids(ctx, kind)
    return ids is not None and row_id not in ids


def graph_entity(iri: Any) -> Optional[Tuple[str, str]]:
    """``(entity_type, entity_id)`` of an app-entity graph node (``urn:ontos:<type>:<id>``)."""
    text = str(iri or "")
    if not text.startswith(_GRAPH_PREFIX):
        return None
    entity_type, sep, entity_id = text[len(_GRAPH_PREFIX):].partition(":")
    if not sep or entity_type not in _KIND_BY_ENTITY_TYPE or not entity_id:
        return None
    return entity_type, entity_id


def iri_is_unreadable(ctx: ToolContext, iri: Any) -> bool:
    """True for the graph node of a product or contract (or its schema/property) the
    caller can't read."""
    entity = graph_entity(iri)
    return entity is not None and entity_is_unreadable(ctx, *entity)


def unreadable_target(
    ctx: ToolContext, tool_name: str, entity_type: str, entity_id: Any, error: str
) -> Optional[ToolResult]:
    """For tools that change or link an entity: ``error`` (the tool's own "not
    found" answer) when the entity belongs to a product or contract the caller
    can't read, else None. Checked before anything is read or written, so the
    answer is the same as for a missing id."""
    if not entity_is_unreadable(ctx, entity_type, entity_id):
        return None
    return denied(ctx, tool_name, ToolResult(success=False, error=error), [str(entity_id)])


PROJECT_MEMBERSHIP_CODE = "project_membership_required"


def project_refusal(ctx: ToolContext, project_id: Optional[str], what: str) -> Optional[ToolResult]:
    """The REST PUT's project rule: only a project member may edit ``what`` in a project."""
    if not project_id:
        return None
    caller = _caller(ctx)
    if caller.full_access or caller.project_ids is None or str(project_id) in caller.project_ids:
        return None
    return ToolResult(
        success=False,
        error=f"You must be a member of the project to edit this {what}",
        error_code=PROJECT_MEMBERSHIP_CODE,
    )


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
