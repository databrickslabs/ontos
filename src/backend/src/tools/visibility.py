"""Which data products and contracts the search and list tools return.

``visibility``:

- ``published``: active items with a publication scope other than ``none``,
  the marketplace's rule (``GET /api/data-products/published``). The MCP default.
- ``readable``: everything the read rule lets the caller read
  (``src.tools.read_access``): published items plus the drafts and in-review
  items the caller owns or administers. The Ask Ontos default.

Both stay within the read rule. ``min_certification_level`` keeps items whose
certification level (the level order) is at least the given one, and
``include_history=False`` (the default, as in the REST lists) keeps one version
per version family. Everything is applied as ``exclude_ids`` before pagination,
counts and facets: the one-version-per-family step runs after the search's
query and filters, so it keeps the newest version that matches. Get-by-id tools
use the read rule only.
"""

from typing import Any, Dict, Iterable, List, Optional

from src.common.version_visibility import collapse_by_family
from src.tools import read_access
from src.tools.base import ToolContext, ToolResult

PUBLISHED = "published"
READABLE = "readable"
VISIBILITIES = (PUBLISHED, READABLE)
INVALID_VISIBILITY_CODE = "invalid_visibility"

VISIBILITY_DESCRIPTION = (
    "Which items to return: 'published' (active and published to the marketplace) or "
    "'readable' (everything you may read). Defaults to published, active items; set "
    "visibility='readable' for drafts or in-review items you own or administer."
)
VISIBILITY_PARAM = {"type": "string", "enum": list(VISIBILITIES),
                    "description": VISIBILITY_DESCRIPTION}
MIN_CERTIFICATION_PARAM = {
    "type": "integer",
    "description": "Optional: only items whose certification level (its order, 1 = lowest) "
                   "is at least this.",
}
INCLUDE_HISTORY_PARAM = {
    "type": "boolean",
    "description": "Return every version of a product or contract (default false: the "
                   "newest visible version of each).",
}

# Search index type -> (item id prefix, entity type of links and tags)
_KINDS = {
    "data-product": (read_access.PRODUCT_ITEM_PREFIX, "data_product"),
    "data-contract": (read_access.CONTRACT_ITEM_PREFIX, "data_contract"),
}


def _model(kind: str):
    if kind == "data-product":
        from src.db_models.data_products import DataProductDb
        return DataProductDb
    from src.db_models.data_contracts import DataContractDb
    return DataContractDb


def applied_visibility(ctx: ToolContext, visibility: Optional[str]) -> Optional[str]:
    """The visibility to apply: the argument, else the transport's default.

    ``None`` when the argument is not a known value.
    """
    value = (visibility or ctx.default_visibility or PUBLISHED).strip().lower()
    return value if value in VISIBILITIES else None


def invalid_visibility(visibility: Any, **data: Any) -> ToolResult:
    return ToolResult(
        success=False,
        error=f"Unknown visibility '{visibility}'. Use one of: {', '.join(VISIBILITIES)}.",
        error_code=INVALID_VISIBILITY_CODE,
        data=data,
    )


def is_published(row: Any) -> bool:
    """Active and published to the marketplace (publication scope other than none)."""
    status = (getattr(row, "status", "") or "").strip().lower()
    scope = (getattr(row, "publication_scope", "") or "none").strip().lower()
    return status == "active" and scope != "none"


def _candidate_rows(ctx: ToolContext, kind: str, *, visibility: str,
                    min_certification_level: Optional[int]) -> List[Any]:
    """The rows of ``kind`` the caller may read that pass the visibility and level."""
    rows = ctx.db.query(_model(kind)).all()
    readable = read_access.readable_ids(ctx, kind)
    if readable is not None:
        rows = [r for r in rows if str(r.id) in readable]
    if visibility == PUBLISHED:
        rows = [r for r in rows if is_published(r)]
    if min_certification_level is not None:
        rows = [r for r in rows
                if (getattr(r, "certification_level", None) or 0) >= min_certification_level]
    return rows


def _newest_per_family(rows: List[Any]) -> List[Any]:
    """One row per version family: the best-ranked (newest) of the given rows."""
    # The rows are already the visible ones, so every family may be ranked.
    families = {getattr(r, "version_family_id", None) or r.id for r in rows}
    return collapse_by_family(rows, elevated_family_ids=families, is_admin=True)


def allowed_ids_by_type(
    ctx: ToolContext,
    type_filter: Optional[str] = None,
    *,
    visibility: str,
    min_certification_level: Optional[int] = None,
    include_history: bool = False,
    query: str = "",
    filters: Optional[Dict[str, Optional[str]]] = None,
) -> Dict[str, set]:
    """For the search: index type -> the product / contract index ids to keep.

    The read rule, the visibility and the level select the candidate rows.
    Without ``include_history`` the candidates are first matched against the
    same query and filters as the search (one id-only search per type), and
    the newest *matching* version of each family is kept, as the REST lists
    filter first and collapse after. A type absent from the result is not
    restricted (a feature admin reading everything, all versions).
    """
    allowed: Dict[str, set] = {}
    for kind, (prefix, _entity_type) in _KINDS.items():
        if type_filter not in (None, "", kind):
            continue
        if (visibility == READABLE and min_certification_level is None and include_history
                and read_access.reads_all(ctx, kind)):
            continue
        rows = _candidate_rows(ctx, kind, visibility=visibility,
                               min_certification_level=min_certification_level)
        ids = {f"{prefix}{r.id}" for r in rows}
        if not include_history and ctx.search_manager is not None and rows:
            matched = set(ctx.search_manager.match_ids(
                query, type_filter=kind, filters=filters, allowed_ids_by_type={kind: ids},
            ))
            by_item = {f"{prefix}{r.id}": r for r in rows}
            rows = _newest_per_family([by_item[i] for i in matched if i in by_item])
            ids = {f"{prefix}{r.id}" for r in rows}
        allowed[kind] = ids
    return allowed


def entity_is_hidden(ctx: ToolContext, entity_type: str, entity_id: Any,
                     *, visibility: str) -> bool:
    """True when the entity belongs to a product or contract that is unreadable or
    outside ``visibility`` (schemas and properties follow their contract)."""
    if read_access.entity_is_unreadable(ctx, entity_type, entity_id):
        return True
    if visibility != PUBLISHED:
        return False
    owner = read_access.owning_row(entity_type, entity_id)
    if owner is None:
        return False
    kind, row_id = owner
    key = f"published_ids:{kind}"
    if key not in ctx.cache:
        rows = ctx.db.query(_model(kind)).all()
        ctx.cache[key] = {str(r.id) for r in rows if is_published(r)}
    return row_id not in ctx.cache[key]


def annotate(ctx: ToolContext, rows: Iterable[Dict[str, Any]], *, type_key: str = "type",
             id_key: str = "id", default_type: Optional[str] = None) -> None:
    """Add each product and contract row's status, publication scope and certification."""
    rows = list(rows)
    for kind, (_prefix, entity_type) in _KINDS.items():
        def _is_kind(r):
            t = r.get(type_key, default_type)
            return t in (kind, entity_type)
        ids = [r[id_key] for r in rows if _is_kind(r) and r.get(id_key)]
        if not ids:
            continue
        model = _model(kind)
        found = {m.id: m for m in ctx.db.query(model).filter(model.id.in_(ids)).all()}
        for r in rows:
            m = found.get(r.get(id_key)) if _is_kind(r) else None
            if m is not None:
                r["status"] = m.status
                r["publication_scope"] = m.publication_scope
                r["certification_level"] = m.certification_level
