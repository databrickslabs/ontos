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


def upsert_documents(db: Session, items: Iterable[SearchIndexItem], *, count_inserted: bool = False) -> int:
    """Insert or update search_documents rows for the given items, in one
    statement. Rows whose content is unchanged are left alone (no write, and
    ``updated_at`` keeps meaning "content last changed"), so a reconcile that
    re-sends the whole catalog only writes what actually differs. Returns the
    number of distinct items sent, or with ``count_inserted`` only the newly
    inserted ones (updates of existing ids don't count)."""
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
               CAST(u.tags AS jsonb), CAST(u.extra_data AS jsonb), u.link, clock_timestamp()
        FROM unnest(
            CAST(:id AS text[]), CAST(:entity_id AS text[]), CAST(:type AS text[]),
            CAST(:feature_id AS text[]), CAST(:title AS text[]), CAST(:description AS text[]),
            CAST(:aux_text AS text[]), CAST(:tags AS text[]), CAST(:extra_data AS text[]),
            CAST(:link AS text[])
        ) AS u({cols})
        ON CONFLICT (id) DO UPDATE SET
            {", ".join(f"{c} = EXCLUDED.{c}" for c in _CONTENT_COLS)},
            -- clock_timestamp (not the transaction start): an update that waited
            -- on the embedding worker's row lock must still read as newer than
            -- the embedding stored meanwhile, or it would never be re-embedded.
            updated_at = clock_timestamp()
        WHERE ({", ".join(f"search_documents.{c}" for c in _CONTENT_COLS)})
              IS DISTINCT FROM ({", ".join(f"EXCLUDED.{c}" for c in _CONTENT_COLS)})
        RETURNING (xmax = 0) AS inserted
        """
    )
    result = db.execute(stmt, {
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
    inserted = sum(1 for r in result if r.inserted)
    return inserted if count_inserted else len(rows)


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


# Field tsvector -> the Settings field(s) whose boost weights it. aux_text carries
# tags + domains + owner + concept labels, so it takes the highest of those
# fields' boosts for the row's type (a domain/owner match counts even where tags
# aren't indexed).
_BM25_FIELDS = (
    ("title_tsv", ("title",)),
    ("description_tsv", ("description",)),
    ("aux_tsv", ("tags", "domain", "domains", "owner", "owner_team")),
)


def bm25_rank(
    db: Session,
    query: str,
    *,
    config: Optional[SearchConfig] = None,
    engine: Optional[SearchEngine] = None,
    type_filter: Optional[str] = None,
    filters: Optional[Dict[str, Optional[str]]] = None,
    allowed_features: Optional[Iterable[str]] = None,
    limit: int = 100,
) -> List[tuple[str, float]]:
    """BM25 ranked list ``[(search_documents.id, score)]``, best first (lakebase engine).

    One top-K query per field, so each uses its ``lakebase_bm25`` index order
    (Block-Max WAND pushdown), then the per-field BM25 scores are combined as
    sum(Settings field boost for the row's type x BM25). It applies the same
    filters, permissions and disabled types as ``search``. This is a ranking
    *signal* for hybrid fusion (#1061); keyword results are unaffected.
    Returns ``[]`` off the lakebase engine or for a query without terms.
    """
    from src.repositories.search_engine import BM25_INDEXES

    if engine is None or not engine.has_bm25:
        return []
    q = (query or "").strip()
    if is_list_query(q) or not tokenize(q):
        return []
    config = config or _default_config()
    limit = max(1, min(limit, 1000))
    per_field_k = min(max(limit * 3, 100), 1000)

    disabled, dparams = search_scoring_sql.disabled_where_only(config)
    where, params = _where(type_filter, filters, allowed_features, disabled)
    params = {**params, **dparams, "bm25_q": q, "bm25_k": per_field_k, "bm25_limit": limit}
    to_query = engine.bm25("to_bm25query")
    op = engine.bm25_op()

    # A stopword-only query ("the") has terms for the app tokenizer but an empty
    # english tsvector; return nothing instead of handing BM25 an empty query.
    nonempty = "to_tsvector('english', :bm25_q) <> ''::tsvector"
    ctes, terms = [], []
    for i, (col, field_names) in enumerate(_BM25_FIELDS):
        boost_sql, bparams = search_scoring_sql.field_boost_sql(config, field_names, ns=f"bmb{i}")
        params.update(bparams)
        dist = f"{col} {op} {to_query}(to_tsvector('english', :bm25_q), '{BM25_INDEXES[col]}'::regclass)"
        # Rows whose type doesn't weight this field (boost 0) are excluded inside
        # the top-K, so they can't take slots from rows that would score.
        cond = f"({boost_sql}) > 0 AND {nonempty}"
        field_where = f"{where} AND {cond}" if where else f" WHERE {cond}"
        ctes.append(
            f"f{i} AS (SELECT id, ({boost_sql}) * -({dist}) AS s FROM search_documents{field_where} "
            f"ORDER BY {dist} LIMIT :bm25_k)"
        )
        terms.append(f"SELECT id, s FROM f{i}")
    sql = (
        "WITH " + ", ".join(ctes) + " "
        f"SELECT id, sum(s) AS score FROM ({' UNION ALL '.join(terms)}) u "
        "GROUP BY id HAVING sum(s) > 0 ORDER BY score DESC, id ASC LIMIT :bm25_limit"
    )
    ext_schema = engine.ext_schemas.get("lakebase_text")
    if ext_schema:
        # lakebase_text's own SQL functions name their types unqualified, so the
        # extension schema must be on search_path, which the app pins to its own
        # schema. Append it for this transaction only (is_local=true).
        # Idempotent, so repeated calls in one transaction don't keep growing it;
        # appended last, so the app schema still wins any name lookup.
        db.execute(
            text(
                "SELECT set_config('search_path', CASE WHEN :s = ANY(current_schemas(false)) "
                "THEN current_setting('search_path') "
                "ELSE current_setting('search_path') || ', ' || quote_ident(:s) END, true)"
            ),
            {"s": ext_schema},
        )
    return [(r._mapping["id"], float(r._mapping["score"])) for r in db.execute(text(sql), params)]


# --- embeddings (#1060) ------------------------------------------------------

# A row needs (re-)embedding when its content is newer than its embedding, or
# when the embedding is missing (e.g. the column was re-created) unless the
# endpoint rejected that exact text before ("rejected:<hash>").
_PENDING_EMBEDDING = (
    "(embedded_at IS NULL OR embedded_at < updated_at "
    "OR (embedding IS NULL AND COALESCE(embedding_hash, '') NOT LIKE 'rejected:%'))"
)
REJECTED_HASH_PREFIX = "rejected:"


def claim_pending_embeddings(db: Session, limit: int, lease_seconds: float = 300.0) -> List[Dict[str, Any]]:
    """Lease up to ``limit`` pending rows, oldest first, and return them.

    The lease is a timestamp, not a row lock: the caller commits right away and
    calls the endpoint with no transaction open, so writes to those rows never
    wait on the endpoint. Replicas skip leased rows; a lease that outlives a
    crashed worker expires after ``lease_seconds``."""
    rows = db.execute(text(
        "UPDATE search_documents d SET embedding_claimed_at = clock_timestamp() "
        "FROM (SELECT id FROM search_documents "
        f"      WHERE {_PENDING_EMBEDDING} AND (embedding_claimed_at IS NULL "
        "        OR embedding_claimed_at < clock_timestamp() - make_interval(secs => :lease)) "
        "      ORDER BY updated_at, id LIMIT :lim FOR UPDATE SKIP LOCKED) c "
        "WHERE d.id = c.id "
        "RETURNING d.id, d.title, d.description, d.aux_text, d.embedding_hash, d.updated_at, "
        "(d.embedding IS NOT NULL) AS has_embedding"
    ), {"lim": max(1, int(limit)), "lease": float(lease_seconds)})
    return sorted((dict(r._mapping) for r in rows), key=lambda r: (r["updated_at"], r["id"]))


def store_embeddings(db: Session, results: Iterable[Dict[str, Any]], engine: SearchEngine) -> int:
    """Write embedding results ``{id, updated_at, hash, vector?, rejected?}``.

    - ``vector``: store it.
    - no ``vector``: content unchanged (hash matched), only mark it current.
    - ``rejected``: the endpoint refused this text; keep it from being retried
      until the text changes.

    Each write only applies if the row's ``updated_at`` is still the claimed
    one; a row edited meanwhile stays pending and is embedded again. Returns
    the number of rows written."""
    n = 0
    vec_type = engine.vec("vector")
    guard = "WHERE id = :id AND updated_at = :u"
    for r in results:
        params = {"id": r["id"], "u": r["updated_at"], "h": r["hash"]}
        if r.get("rejected"):
            sql = ("UPDATE search_documents SET embedding = NULL, embedding_hash = :h, "
                   f"embedded_at = clock_timestamp() {guard}")
            params["h"] = REJECTED_HASH_PREFIX + r["hash"]
        elif r.get("vector") is None:
            sql = f"UPDATE search_documents SET embedded_at = clock_timestamp(), embedding_hash = :h {guard}"
        else:
            sql = (f"UPDATE search_documents SET embedding = CAST(:v AS {vec_type}), embedding_hash = :h, "
                   f"embedded_at = clock_timestamp() {guard}")
            params["v"] = "[" + ",".join(repr(float(x)) for x in r["vector"]) + "]"
        n += int(db.execute(text(sql), params).rowcount or 0)
    return n


def release_embedding_claims(db: Session, ids: Iterable[str]) -> None:
    ids = list(ids)
    if ids:
        db.execute(text("UPDATE search_documents SET embedding_claimed_at = NULL WHERE id = ANY(:ids)"),
                   {"ids": ids})


def count_pending_embeddings(db: Session) -> int:
    return int(db.execute(text(f"SELECT count(*) FROM search_documents WHERE {_PENDING_EMBEDDING}")).scalar() or 0)


def vector_rank(
    db: Session,
    query_vector: List[float],
    *,
    config: Optional[SearchConfig] = None,
    engine: Optional[SearchEngine] = None,
    type_filter: Optional[str] = None,
    filters: Optional[Dict[str, Optional[str]]] = None,
    allowed_features: Optional[Iterable[str]] = None,
    limit: int = 100,
) -> List[tuple[str, float]]:
    """Semantic ranked list ``[(id, cosine similarity)]``, best first, over rows
    that have an embedding. Uses the engine's ANN index (HNSW / lakebase_ann)
    via ``ORDER BY embedding <=> :q LIMIT``; same filters, permissions and
    disabled types as keyword search. A signal for hybrid fusion (#1061)."""
    if engine is None or not engine.embedding_dim or not query_vector:
        return []
    config = config or _default_config()
    limit = max(1, min(limit, 1000))
    disabled, dparams = search_scoring_sql.disabled_where_only(config)
    where, params = _where(type_filter, filters, allowed_features, disabled)
    cond = "embedding IS NOT NULL"
    where = f"{where} AND {cond}" if where else f" WHERE {cond}"
    dist = f"embedding {engine.vec_op('<=>')} CAST(:qvec AS {engine.vec('vector')})"
    params = {
        **params, **dparams, "vr_limit": limit,
        "qvec": "[" + ",".join(repr(float(x)) for x in query_vector) + "]",
    }
    if engine.vector_index_method == "hnsw":
        _hnsw_filtered_scan(db, limit)
    sql = f"SELECT id, 1 - ({dist}) AS sim FROM search_documents{where} ORDER BY {dist} LIMIT :vr_limit"
    ranked = [(r._mapping["id"], float(r._mapping["sim"])) for r in db.execute(text(sql), params)]
    return sorted(ranked, key=lambda r: -r[1])  # relaxed_order may return near-ties out of order


def _hnsw_filtered_scan(db: Session, limit: int) -> None:
    """HNSW returns at most ``hnsw.ef_search`` (default 40) candidates and the
    WHERE filters apply after that, so a filtered query (type, permissions,
    disabled types) could come back nearly empty. pgvector >= 0.8 keeps
    scanning until ``limit`` rows pass the filters (``iterative_scan``); the
    larger ``ef_search`` also helps older versions. Transaction-local."""
    try:
        with db.begin_nested():
            db.execute(text("SELECT set_config('hnsw.ef_search', :ef, true)"), {"ef": str(min(1000, max(40, limit)))})
        with db.begin_nested():
            db.execute(text("SELECT set_config('hnsw.iterative_scan', 'relaxed_order', true)"))
    except Exception as e:  # pgvector < 0.8: no iterative scan
        logger.debug(f"hnsw.iterative_scan unavailable: {e}")


def replace_all(db: Session, items: Iterable[SearchIndexItem]) -> int:
    """Full rebuild: make the table exactly ``items`` (one transaction). Rows
    that stay keep their embeddings; unchanged ones aren't rewritten."""
    rows = list(items)
    db.execute(text("DELETE FROM search_documents WHERE NOT (id = ANY(:ids))"), {"ids": [it.id for it in rows]})
    return upsert_documents(db, rows)


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
