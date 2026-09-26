"""Postgres full-text search over the ``search_documents`` table.

Data layer for the ``postgres`` SEARCH_BACKEND. All SQL here is Postgres-specific
(weighted ``tsvector`` + ``websearch_to_tsquery`` + ``ts_rank_cd``, JSONB filters)
and is therefore exercised by the local-Postgres integration test, not the SQLite
unit suite.

Result shape matches ``controller.search_scoring.search_index`` so the search
backends are interchangeable and MCP tools / the REST route need no changes.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.search_interfaces import SearchIndexItem

logger = get_logger(__name__)

# extra_data keys surfaced on every result (mirrors search_scoring._RESULT_FIELDS).
_RESULT_FIELDS = ("domain", "status", "owner", "version")
# Filter keys we accept and how they map to SQL (whitelist — never interpolate raw keys).
_EQ_FILTER_COLUMNS = {"status": "status", "domain": "domain", "category": "category"}


def _entity_id(item_id: str) -> str:
    return item_id.split("::", 1)[1] if "::" in item_id else item_id


def _aux_text(item: SearchIndexItem) -> str:
    """Lower-weight searchable text: tags + domain(s)/owner from extra_data."""
    parts: List[str] = [str(t) for t in (item.tags or [])]
    for key in ("domain", "owner"):
        val = item.extra_data.get(key) if item.extra_data else None
        if val:
            parts.append(str(val))
    domains = item.extra_data.get("domains") if item.extra_data else None
    if isinstance(domains, (list, tuple)):
        parts.extend(str(d) for d in domains)
    return " ".join(p for p in parts if p)


def upsert_documents(db: Session, items: Iterable[SearchIndexItem]) -> int:
    """Insert or update search_documents rows for the given items. Returns the count."""
    rows = list(items)
    if not rows:
        return 0
    stmt = text(
        """
        INSERT INTO search_documents
            (id, entity_id, type, feature_id, title, description, aux_text, tags, extra_data, link, updated_at)
        VALUES
            (:id, :entity_id, :type, :feature_id, :title, :description, :aux_text,
             CAST(:tags AS jsonb), CAST(:extra_data AS jsonb), :link, now())
        ON CONFLICT (id) DO UPDATE SET
            entity_id = EXCLUDED.entity_id,
            type = EXCLUDED.type,
            feature_id = EXCLUDED.feature_id,
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            aux_text = EXCLUDED.aux_text,
            tags = EXCLUDED.tags,
            extra_data = EXCLUDED.extra_data,
            link = EXCLUDED.link,
            updated_at = now()
        """
    )
    for item in rows:
        db.execute(stmt, {
            "id": item.id,
            "entity_id": _entity_id(item.id),
            "type": item.type,
            "feature_id": item.feature_id,
            "title": item.title,
            "description": item.description,
            "aux_text": _aux_text(item),
            "tags": json.dumps([str(t) for t in (item.tags or [])]),
            "extra_data": json.dumps(item.extra_data or {}),
            "link": item.link,
        })
    return len(rows)


def delete_document(db: Session, item_id: str) -> None:
    db.execute(text("DELETE FROM search_documents WHERE id = :id"), {"id": item_id})


def delete_by_type(db: Session, type_: str) -> None:
    db.execute(text("DELETE FROM search_documents WHERE type = :t"), {"t": type_})


def _where(
    query: str,
    type_filter: Optional[str],
    filters: Optional[Dict[str, Optional[str]]],
    allowed_features: Optional[Iterable[str]],
) -> tuple[str, Dict[str, Any], bool]:
    """Build the shared WHERE clause + params. Returns (sql, params, has_query)."""
    clauses: List[str] = []
    params: Dict[str, Any] = {}
    has_query = bool(query) and query.strip() not in ("", "*")

    if type_filter:
        clauses.append("type = :type_filter")
        params["type_filter"] = type_filter
    if allowed_features is not None:
        clauses.append("feature_id = ANY(:allowed_features)")
        params["allowed_features"] = list(allowed_features)
    for key, val in (filters or {}).items():
        if not val:
            continue
        if key == "domains":
            # Case-insensitive membership in the assigned-domains JSONB array.
            clauses.append(
                "EXISTS (SELECT 1 FROM jsonb_array_elements_text(extra_data->'domains') d "
                "WHERE lower(d) = lower(:f_domains))"
            )
            params["f_domains"] = val
        elif key in _EQ_FILTER_COLUMNS:
            clauses.append(f"lower(extra_data->>'{_EQ_FILTER_COLUMNS[key]}') = lower(:f_{key})")
            params[f"f_{key}"] = val
        # unknown filter keys are ignored (never interpolated)
    if has_query:
        clauses.append("search_tsv @@ websearch_to_tsquery('english', :q)")
        params["q"] = query

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params, has_query


def _row_to_result(row: Any, with_score: bool) -> Dict[str, Any]:
    m = row._mapping
    tags = m["tags"]
    if isinstance(tags, str):
        tags = json.loads(tags)
    extra = m["extra_data"]
    if isinstance(extra, str):
        extra = json.loads(extra)
    extra = extra or {}
    desc = m["description"]
    result: Dict[str, Any] = {
        "id": m["entity_id"],
        "type": m["type"],
        "title": m["title"],
        "description": (desc[:200] if desc else None),
        "link": m["link"],
        "tags": (tags or [])[:5],
        "feature_id": m["feature_id"],
    }
    for f in _RESULT_FIELDS:
        if extra.get(f):
            result[f] = extra[f]
    if with_score:
        result["relevance_score"] = round(float(m["rank"]), 4)
    return result


def _facets(db: Session, where: str, params: Dict[str, Any], top_tags: int = 10) -> Dict[str, Dict[str, int]]:
    """Facet counts over the same filtered candidate set (mirrors the memory backend)."""
    facets: Dict[str, Dict[str, int]] = {}

    def _and(extra: str) -> str:
        # Append a condition to the shared WHERE (or start one if there is none).
        return f"{where} AND {extra}" if where else f" WHERE {extra}"

    # type facet
    rows = db.execute(
        text(f"SELECT type AS k, count(*) AS n FROM search_documents{where} GROUP BY type"),
        params,
    )
    counts = {r._mapping["k"]: r._mapping["n"] for r in rows if r._mapping["k"]}
    if counts:
        facets["type"] = counts

    # domain / status facets from extra_data
    for facet_key, expr in (("domain", "extra_data->>'domain'"), ("status", "extra_data->>'status'")):
        rows = db.execute(
            text(f"SELECT {expr} AS k, count(*) AS n FROM search_documents{_and(f'{expr} IS NOT NULL')} GROUP BY k"),
            params,
        )
        counts = {r._mapping["k"]: r._mapping["n"] for r in rows if r._mapping["k"]}
        if counts:
            facets[facet_key] = counts

    # top tags — unnest the tags JSONB array. The shared WHERE references only
    # base-table columns, so it applies unchanged under the CROSS JOIN LATERAL.
    tag_rows = db.execute(
        text(
            "SELECT t AS k, count(*) AS n FROM search_documents "
            "CROSS JOIN LATERAL jsonb_array_elements_text(tags) t"
            f"{where} GROUP BY t ORDER BY n DESC LIMIT :top_tags"
        ),
        {**params, "top_tags": top_tags},
    )
    tags = {r._mapping["k"]: r._mapping["n"] for r in tag_rows if r._mapping["k"]}
    if tags:
        facets["tags"] = tags

    return facets


def search(
    db: Session,
    query: str,
    *,
    type_filter: Optional[str] = None,
    filters: Optional[Dict[str, Optional[str]]] = None,
    allowed_features: Optional[Iterable[str]] = None,
    limit: int = 25,
    offset: int = 0,
    include_facets: bool = True,
) -> Dict[str, Any]:
    """Full-text search over search_documents; result shape matches search_scoring.search_index."""
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    where, params, has_query = _where(query, type_filter, filters, allowed_features)

    if has_query:
        sql = (
            "SELECT entity_id, type, title, description, link, tags, extra_data, feature_id, "
            "ts_rank_cd(search_tsv, websearch_to_tsquery('english', :q)) AS rank, "
            "count(*) OVER() AS total_count "
            f"FROM search_documents{where} "
            "ORDER BY rank DESC, lower(title) ASC LIMIT :limit OFFSET :offset"
        )
    else:
        sql = (
            "SELECT entity_id, type, title, description, link, tags, extra_data, feature_id, "
            "count(*) OVER() AS total_count "
            f"FROM search_documents{where} "
            "ORDER BY lower(title) ASC LIMIT :limit OFFSET :offset"
        )
    rows = list(db.execute(text(sql), {**params, "limit": limit, "offset": offset}))
    total = int(rows[0]._mapping["total_count"]) if rows else 0
    results = [_row_to_result(r, with_score=has_query) for r in rows]

    return {
        "results": results,
        "total_count": total,
        "returned": len(results),
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(results)) < total,
        "facets": _facets(db, where, params) if include_facets else {},
        "query": query,
    }
