"""Postgres search over the ``search_documents`` table.

Data layer for the ``postgres`` SEARCH_BACKEND. Ranking is compiled from the
advanced-search Settings (``SearchConfig``) by ``search_scoring_sql`` so results
match the in-memory backend exactly; JSONB filters, permissions, pagination and
facets are SQL. All SQL here is Postgres-specific and is exercised by the
local-Postgres integration tests, not the SQLite unit suite.

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
from src.controller.search_scoring import is_list_query, tokenize
from src.models.search_config import SearchConfig
from src.repositories import search_scoring_sql
from src.repositories.search_engine import SearchEngine

logger = get_logger(__name__)

# extra_data keys surfaced on every result (mirrors search_scoring._RESULT_FIELDS).
_RESULT_FIELDS = ("domain", "status", "owner", "version")
# extra_data keys counted as facets (mirrors search_scoring._FACET_FIELDS).
_FACET_FIELDS = ("domain", "status", "owner")
_COLS = "id, entity_id, type, title, description, link, tags, extra_data, feature_id"


def _default_config() -> SearchConfig:
    from src.common.search_config_loader import get_search_config
    return get_search_config()
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


_UPSERT_COLS = ("id", "entity_id", "type", "feature_id", "title", "description", "aux_text", "tags", "extra_data", "link")
_CONTENT_COLS = _UPSERT_COLS[1:]


def upsert_documents(db: Session, items: Iterable[SearchIndexItem]) -> int:
    """Insert or update search_documents rows for the given items, in one
    statement. Rows whose content is unchanged are left alone (no write, and
    ``updated_at`` keeps meaning "content last changed"), so a reconcile that
    re-sends the whole catalog only writes what actually differs. Returns the
    number of distinct items sent."""
    by_id: Dict[str, SearchIndexItem] = {}
    for item in items:
        by_id[item.id] = item  # last one wins; ON CONFLICT can't touch a row twice
    if not by_id:
        return 0
    rows = list(by_id.values())
    cols = ", ".join(_UPSERT_COLS)
    stmt = text(
        f"""
        INSERT INTO search_documents ({cols}, updated_at)
        SELECT u.id, u.entity_id, u.type, u.feature_id, u.title, u.description, u.aux_text,
               CAST(u.tags AS jsonb), CAST(u.extra_data AS jsonb), u.link, now()
        FROM unnest(
            CAST(:id AS text[]), CAST(:entity_id AS text[]), CAST(:type AS text[]),
            CAST(:feature_id AS text[]), CAST(:title AS text[]), CAST(:description AS text[]),
            CAST(:aux_text AS text[]), CAST(:tags AS text[]), CAST(:extra_data AS text[]),
            CAST(:link AS text[])
        ) AS u({cols})
        ON CONFLICT (id) DO UPDATE SET
            {", ".join(f"{c} = EXCLUDED.{c}" for c in _CONTENT_COLS)},
            updated_at = now()
        WHERE ({", ".join(f"search_documents.{c}" for c in _CONTENT_COLS)})
              IS DISTINCT FROM ({", ".join(f"EXCLUDED.{c}" for c in _CONTENT_COLS)})
        """
    )
    db.execute(stmt, {
        "id": [it.id for it in rows],
        "entity_id": [_entity_id(it.id) for it in rows],
        "type": [it.type for it in rows],
        "feature_id": [it.feature_id for it in rows],
        "title": [it.title for it in rows],
        "description": [it.description for it in rows],
        "aux_text": [_aux_text(it) for it in rows],
        "tags": [json.dumps([str(t) for t in (it.tags or [])]) for it in rows],
        "extra_data": [json.dumps(it.extra_data or {}) for it in rows],
        "link": [it.link for it in rows],
    })
    return len(rows)


def delete_documents(db: Session, item_ids: Iterable[str]) -> int:
    ids = list(item_ids)
    if not ids:
        return 0
    res = db.execute(text("DELETE FROM search_documents WHERE id = ANY(:ids)"), {"ids": ids})
    return int(res.rowcount or 0)


def delete_document(db: Session, item_id: str) -> None:
    db.execute(text("DELETE FROM search_documents WHERE id = :id"), {"id": item_id})


def delete_by_type(db: Session, type_: str) -> None:
    db.execute(text("DELETE FROM search_documents WHERE type = :t"), {"t": type_})


def _where(
    type_filter: Optional[str],
    filters: Optional[Dict[str, Optional[str]]],
    allowed_features: Optional[Iterable[str]],
    disabled_where: str = "",
) -> tuple[str, Dict[str, Any]]:
    """Build the shared candidate WHERE clause + params (filters, permissions,
    disabled asset types). Query matching is done by the scoring CTE."""
    clauses: List[str] = []
    params: Dict[str, Any] = {}

    if disabled_where:
        clauses.append(disabled_where)
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

    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def _matches_cte(
    config: SearchConfig,
    tokens: List[str],
    where: str,
) -> tuple[str, Dict[str, Any], str]:
    """``WITH ... matches AS (...)`` over the filtered candidates, plus params and
    the ORDER BY body. ``matches`` has the base columns + ``score``/``priority``
    and only rows where at least one token matched (search_scoring.score_item)."""
    s = search_scoring_sql.build_scoring_sql(config, tokens)
    cte = (
        f"WITH b AS (SELECT {_COLS}, {s.base_select} FROM search_documents{where}), "
        f"scored AS (SELECT b.id, b.entity_id, b.type, b.title, b.description, b.link, b.tags, "
        f"b.extra_data, b.feature_id, {s.score_expr} AS score, {s.priority_expr} AS priority, "
        f"{s.matched_expr} AS matched FROM b {s.lateral_joins}), "
        f"matches AS (SELECT * FROM scored WHERE matched > 0) "
    )
    return cte, s.params, s.order_by


def _row_to_result(row: Any, with_score: bool, fields: Optional[List[str]] = None) -> Dict[str, Any]:
    """Postgres backend row → MCP result dict (mirror of ``_to_result`` in
    ``search_scoring.py``). ``feature_id`` is intentionally omitted; it
    duplicates ``type`` for MCP consumers."""
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
    }
    for f in _RESULT_FIELDS:
        if extra.get(f):
            result[f] = extra[f]
    if with_score:
        result["relevance_score"] = round(float(m["score"]), 4)
    if fields:
        allowed = set(fields) | {"id"}
        result = {k: v for k, v in result.items() if k in allowed}
    return result


def _facets(
    db: Session, prefix: str, rel: str, params: Dict[str, Any], top_tags: int = 10
) -> Dict[str, Dict[str, int]]:
    """Facet counts over ``rel`` (the result set: scored matches, or the filtered
    list), with ``prefix`` holding any ``WITH`` clause ``rel`` depends on."""
    facets: Dict[str, Dict[str, int]] = {}

    rows = db.execute(text(f"{prefix}SELECT r.type AS k, count(*) AS n FROM {rel} AS r GROUP BY r.type"), params)
    counts = {r._mapping["k"]: r._mapping["n"] for r in rows if r._mapping["k"]}
    if counts:
        facets["type"] = counts

    for facet_key in _FACET_FIELDS:  # whitelisted literals, never user input
        expr = f"r.extra_data->>'{facet_key}'"
        rows = db.execute(
            text(f"{prefix}SELECT {expr} AS k, count(*) AS n FROM {rel} AS r WHERE {expr} IS NOT NULL GROUP BY k"),
            params,
        )
        counts = {r._mapping["k"]: r._mapping["n"] for r in rows if r._mapping["k"]}
        if counts:
            facets[facet_key] = counts

    tag_rows = db.execute(
        text(
            f"{prefix}SELECT t AS k, count(*) AS n FROM {rel} AS r "
            "CROSS JOIN LATERAL jsonb_array_elements_text(r.tags) t "
            "GROUP BY t ORDER BY n DESC, t ASC LIMIT :top_tags"
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
    fields: Optional[List[str]] = None,
    config: Optional[SearchConfig] = None,
    engine: Optional[SearchEngine] = None,
    trgm_threshold: float = 0.45,
) -> Dict[str, Any]:
    """Settings-driven search over search_documents; result shape matches
    search_scoring.search_index (list mode for an empty / ``*`` query).

    When ``engine`` has pg_trgm and the query matches nothing, falls back to
    trigram word similarity on titles (typo tolerance)."""
    config = config or _default_config()
    limit = max(1, min(limit, 100))
    offset = max(0, offset)
    disabled, dparams = search_scoring_sql.disabled_where_only(config)
    where, params = _where(type_filter, filters, allowed_features, disabled)
    params.update(dparams)
    page = {"limit": limit, "offset": offset}

    if is_list_query(query):
        prefix, rel = "", f"(SELECT * FROM search_documents{where})"
        sql = (
            f"SELECT {_COLS}, count(*) OVER() AS total_count FROM search_documents{where} "
            f"ORDER BY {search_scoring_sql.list_order_sql()} LIMIT :limit OFFSET :offset"
        )
        with_score = False
    else:
        tokens = tokenize(query)
        if not tokens:  # e.g. only punctuation: nothing can match (score_and_rank -> [])
            return _empty(query, limit, offset)
        prefix, sparams, order_by = _matches_cte(config, tokens, where)
        params.update(sparams)
        rel = "matches"
        sql = (
            f"{prefix}SELECT *, count(*) OVER() AS total_count FROM matches "
            f"ORDER BY {order_by} LIMIT :limit OFFSET :offset"
        )
        with_score = True

    rows = list(db.execute(text(sql), {**params, **page}))
    if rows:
        total = int(rows[0]._mapping["total_count"])
    elif offset > 0:  # page past the end: the window count has no row to ride on
        total = int(db.execute(text(f"{prefix}SELECT count(*) FROM {rel} AS r"), params).scalar() or 0)
    else:
        total = 0

    if with_score and total == 0 and engine is not None and engine.has_trgm:
        fb = _trgm_fallback(db, query, where, params, trgm_threshold, limit=limit, offset=offset, engine=engine)
        if fb is not None:
            rows, total, rel, params = fb
            prefix = ""

    results = [_row_to_result(r, with_score=with_score, fields=fields) for r in rows]

    return {
        "results": results,
        "total_count": total,
        "returned": len(results),
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(results)) < total,
        "facets": _facets(db, prefix, rel, params) if include_facets else {},
        "query": query,
    }


def _trgm_rel(where: str, engine: SearchEngine) -> str:
    """Rows whose title is word-similar to the query (pg_trgm ``<%``), over the
    same filtered candidates. Uses the GIN trigram index on ``lower(title)``."""
    cond = f"(:trgm_q {engine.trgm_op('<%')} lower(title))"
    return (
        f"(SELECT {_COLS}, CAST({engine.trgm('word_similarity')}(:trgm_q, lower(title)) AS float8) AS score "
        f"FROM search_documents{where}{' AND ' if where else ' WHERE '}{cond})"
    )


def _trgm_fallback(
    db: Session, query: str, where: str, params: Dict[str, Any], threshold: float,
    *, limit: int, offset: int, engine: SearchEngine,
) -> Optional[tuple[List[Any], int, str, Dict[str, Any]]]:
    """Typo tolerance: when the Settings-driven match finds nothing, rank titles
    by trigram word similarity. Returns (rows, total, rel, params) or None if
    pg_trgm can't be used here (logged; search then returns no results, as the
    in-memory backend would)."""
    tq = " ".join(tokenize(query))
    if not tq:
        return None
    fparams = {**params, "trgm_q": tq, "trgm_thr": str(float(threshold))}
    rel = _trgm_rel(where, engine)
    try:
        # Transaction-local threshold for the <% operator.
        db.execute(text("SELECT set_config('pg_trgm.word_similarity_threshold', :trgm_thr, true)"), fparams)
        rows = list(db.execute(
            text(
                f"SELECT r.*, count(*) OVER() AS total_count FROM {rel} AS r "
                f"ORDER BY r.score DESC, {search_scoring_sql.list_order_sql()} LIMIT :limit OFFSET :offset"
            ),
            {**fparams, "limit": limit, "offset": offset},
        ))
        if rows:
            total = int(rows[0]._mapping["total_count"])
        else:
            total = int(db.execute(text(f"SELECT count(*) FROM {rel} AS r"), fparams).scalar() or 0)
        return rows, total, rel, fparams
    except Exception as e:  # pg_trgm missing/not on search_path, etc.
        logger.warning(f"Trigram fallback unavailable, skipping: {e}")
        db.rollback()
        return None


def _empty(query: str, limit: int, offset: int) -> Dict[str, Any]:
    return {
        "results": [], "total_count": 0, "returned": 0, "offset": offset,
        "limit": limit, "has_more": False, "facets": {}, "query": query,
    }


def _row_to_item(row: Any) -> SearchIndexItem:
    """Reconstruct a full SearchIndexItem from a search_documents row (for the REST path)."""
    m = row._mapping
    tags = m["tags"]
    if isinstance(tags, str):
        tags = json.loads(tags)
    extra = m["extra_data"]
    if isinstance(extra, str):
        extra = json.loads(extra)
    return SearchIndexItem(
        id=m["id"],
        type=m["type"],
        title=m["title"],
        description=m["description"],
        link=m["link"] or "",
        tags=[str(t) for t in (tags or [])],
        feature_id=m["feature_id"],
        extra_data=extra or {},
    )


def _search_by_tag(
    db: Session, pattern: str, allowed_features: Optional[Iterable[str]], limit: int,
    config: SearchConfig,
) -> List[SearchIndexItem]:
    """Mirror SearchManager._filter_by_tag: exact match when the pattern has a '/',
    otherwise namespace-prefix match (tag == pattern or starts with 'pattern/')."""
    exact = "/" in pattern
    clauses = ["lower(t) = lower(:p)"]
    params: Dict[str, Any] = {"p": pattern, "limit": limit}
    if not exact:
        clauses.append("lower(t) LIKE lower(:pp)")
        params["pp"] = f"{pattern}/%"
    tag_cond = " OR ".join(clauses)
    where = [f"EXISTS (SELECT 1 FROM jsonb_array_elements_text(tags) t WHERE {tag_cond})"]
    if allowed_features is not None:
        where.append("feature_id = ANY(:allowed_features)")
        params["allowed_features"] = list(allowed_features)
    disabled, dparams = search_scoring_sql.disabled_where_only(config)
    if disabled:
        where.append(disabled)
        params.update(dparams)
    sql = (
        f"SELECT {_COLS} FROM search_documents WHERE {' AND '.join(where)} "
        f"ORDER BY {search_scoring_sql.list_order_sql()} LIMIT :limit"
    )
    return [_row_to_item(r) for r in db.execute(text(sql), params)]


def search_index_items(
    db: Session,
    query: str,
    *,
    allowed_features: Optional[Iterable[str]] = None,
    limit: int = 200,
    config: Optional[SearchConfig] = None,
    engine: Optional[SearchEngine] = None,
    trgm_threshold: float = 0.45,
) -> List[SearchIndexItem]:
    """Ranked SearchIndexItems for the REST path (caller applies permission filtering).

    Same Settings-driven ranking (and trigram typo fallback) as ``search``;
    supports the ``tag:`` prefix like the in-memory SearchManager. A query with
    no searchable terms returns nothing (as ``score_and_rank`` does).
    """
    config = config or _default_config()
    limit = max(1, min(limit, 500))
    q = (query or "").strip()
    if q.lower().startswith("tag:"):
        return _search_by_tag(db, q[4:].strip(), allowed_features, limit, config)

    tokens = tokenize(q)
    if not tokens:
        return []
    disabled, dparams = search_scoring_sql.disabled_where_only(config)
    where, params = _where(None, None, allowed_features, disabled)
    params.update(dparams)
    prefix, sparams, order_by = _matches_cte(config, tokens, where)
    params.update(sparams)
    sql = f"{prefix}SELECT {_COLS} FROM matches ORDER BY {order_by} LIMIT :limit"
    items = [_row_to_item(r) for r in db.execute(text(sql), {**params, "limit": limit})]
    if not items and engine is not None and engine.has_trgm:
        fb = _trgm_fallback(db, q, where, params, trgm_threshold, limit=limit, offset=0, engine=engine)
        if fb is not None:
            items = [_row_to_item(r) for r in fb[0]]
    return items


def replace_all(db: Session, items: Iterable[SearchIndexItem]) -> int:
    """Full rebuild: clear the table and re-insert all items (one transaction)."""
    db.execute(text("DELETE FROM search_documents"))
    return upsert_documents(db, items)


# --- background reconcile primitives (SearchManager._reconcile_postgres) ------

# Advisory-lock key so only one app replica reconciles at a time (arbitrary,
# stable 64-bit value; "ontos-search-reconcile").
RECONCILE_LOCK_KEY = 0x6F6E746F73535243


def count_documents(db: Session) -> int:
    return int(db.execute(text("SELECT count(*) FROM search_documents")).scalar() or 0)


def delete_missing(db: Session, types: Iterable[str], keep_ids: Iterable[str]) -> int:
    """Drop rows of ``types`` whose id isn't in ``keep_ids`` (entities deleted
    while their incremental removal was missed). Types absent from ``types``
    are never touched, so a manager that returned nothing (for instance because
    it swallowed an error) can't empty its part of the index. Returns the
    number of rows removed."""
    types = sorted(set(types))
    if not types:
        return 0
    res = db.execute(
        text("DELETE FROM search_documents WHERE type = ANY(:types) AND NOT (id = ANY(:ids))"),
        {"types": types, "ids": list(set(keep_ids))},
    )
    return int(res.rowcount or 0)


def try_reconcile_lock(db: Session) -> bool:
    """Session-level advisory lock; held until ``release_reconcile_lock`` or the
    connection closes, so a crashed replica never leaves it stuck."""
    return bool(db.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": RECONCILE_LOCK_KEY}).scalar())


def release_reconcile_lock(db: Session) -> None:
    db.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": RECONCILE_LOCK_KEY})
