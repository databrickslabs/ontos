"""
Shared, tokenized search scoring over SearchIndexItem lists.

This module is the single source of truth for *how* a query matches an item.
Both the REST `SearchManager` and the MCP tools call into it so matching and
ranking behave identically everywhere.

Design notes
------------
- **Tokenized matching**: the query is split into terms and each term is matched
  independently against the item's configured fields. An item's score is the
  sum of its best per-term field scores, multiplied by *term coverage* (the
  fraction of query terms that matched). This is what lets a plain-language
  query like "customer churn data product" match a product titled
  "Customer Churn" — the whole phrase is never a substring of any single field,
  but the individual terms are.
- **Pure / auth-free**: these functions never look at users or permissions.
  Callers (REST vs MCP) apply their own access control on top.
- **List mode**: an empty or ``*`` query is treated as "list everything that
  passes the filters", but always paginated with a ``total_count`` — never an
  unbounded dump.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

from src.common.search_interfaces import SearchIndexItem
from src.models.search_config import (
    FieldConfig,
    MatchType,
    RankingConfig,
    SearchConfig,
    SortField,
)

# Split on any run of non-word characters (keeps unicode letters/digits/underscore).
_TOKEN_RE = re.compile(r"[^\w]+", re.UNICODE)

# Extra_data keys used for facet counts.
_FACET_FIELDS = ("domain", "status", "owner")
# Extra_data keys surfaced on every result dict (superset of facet fields).
_RESULT_FIELDS = ("domain", "status", "owner", "version")


def tokenize(query: str) -> List[str]:
    """Lower-case and split a query into non-empty search terms."""
    if not query:
        return []
    return [t for t in _TOKEN_RE.split(query.lower()) if t]


def is_list_query(query: Optional[str]) -> bool:
    """Whether the query means 'list everything' (empty or the ``*`` wildcard)."""
    return not query or query.strip() == "" or query.strip() == "*"


def get_field_value(item: SearchIndexItem, field_name: str) -> Optional[str]:
    """Get a searchable string value from a SearchIndexItem field or extra_data.

    Mirrors the standard/extra_data resolution the SearchManager used, so
    behaviour is unchanged for configured fields.
    """
    if field_name == "title":
        return item.title
    if field_name == "description":
        return item.description
    if field_name == "tags":
        return " ".join(str(t) for t in item.tags) if item.tags else None
    if field_name == "type":
        return item.type
    if field_name == "id":
        return item.id

    if item.extra_data and field_name in item.extra_data:
        value = item.extra_data[field_name]
        if isinstance(value, (list, tuple, set)):
            return " ".join(str(v) for v in value)
        return str(value) if value is not None else None

    return None


def get_field_values(item: SearchIndexItem, field_name: str) -> List[str]:
    """Return a field's discrete values (for exact filtering).

    Unlike :func:`get_field_value` (which joins lists into one searchable
    string for scoring), this keeps multi-valued fields — e.g. a product's
    assigned ``domains`` — as separate values so a filter can match any one of
    them exactly.
    """
    if field_name == "tags":
        return [str(t) for t in item.tags] if item.tags else []
    if item.extra_data and field_name in item.extra_data:
        value = item.extra_data[field_name]
        if isinstance(value, (list, tuple, set)):
            return [str(v) for v in value if v is not None]
        return [str(value)] if value is not None else []
    single = get_field_value(item, field_name)
    return [single] if single else []


def fuzzy_match(value: str, token: str) -> float:
    """Lightweight fuzzy score in [0, 1] (substring > subsequence > char overlap)."""
    if token in value:
        return 0.9

    # All token characters appear in order (subsequence match) -> typo tolerant.
    token_idx = 0
    for char in value:
        if token_idx < len(token) and char == token[token_idx]:
            token_idx += 1
    if token_idx == len(token):
        return 0.7

    # Character-set overlap at the start of the value.
    token_set = set(token)
    value_set = set(value[: len(token) * 2])
    overlap = len(token_set & value_set) / len(token_set) if token_set else 0.0
    return 0.5 if overlap >= 0.8 else 0.0


def check_match(value: str, token: str, match_type: MatchType) -> float:
    """Score how well a single query *token* matches a field value, in [0, 1]."""
    if not value:
        return 0.0
    value_lower = value.lower()

    if match_type == MatchType.EXACT:
        return 1.0 if value_lower == token else 0.0

    if match_type == MatchType.PREFIX:
        if value_lower.startswith(token):
            return 1.0
        for word in re.split(r"[\s/]+", value_lower):
            if word.startswith(token):
                return 0.9  # non-leading word match
        return 0.0

    if match_type == MatchType.SUBSTRING:
        if token in value_lower:
            if value_lower.startswith(token):
                return 1.0
            if f" {token}" in value_lower:
                return 0.9
            return 0.8
        return 0.0

    if match_type == MatchType.FUZZY:
        return fuzzy_match(value_lower, token)

    return 0.0


@dataclass
class ScoredItem:
    """An item that matched the query, with the info needed to rank it."""
    item: SearchIndexItem
    total_score: float          # sum(best per-term field score) * term coverage
    field_priority: int         # priority of the best-matching field (lower = better)
    matched_tokens: int         # how many query terms matched at least one field
    total_tokens: int           # how many query terms there were

    @property
    def coverage(self) -> float:
        return self.matched_tokens / self.total_tokens if self.total_tokens else 0.0


def score_item(
    item: SearchIndexItem,
    tokens: List[str],
    config: SearchConfig,
) -> Optional[ScoredItem]:
    """Score one item against pre-tokenized query terms. Returns None if no term matched."""
    field_configs = config.get_all_field_configs(item.type)
    if not field_configs:
        return None

    total_score = 0.0
    best_priority = 10_000
    matched = 0

    for token in tokens:
        token_best = 0.0
        token_best_priority = 10_000
        for field_name, field_config in field_configs.items():
            if not field_config.indexed:
                continue
            value = get_field_value(item, field_name)
            if value is None:
                continue
            quality = check_match(value, token, field_config.match_type)
            if quality <= 0:
                continue
            field_score = field_config.boost * quality
            if field_score > token_best:
                token_best = field_score
                token_best_priority = field_config.priority
        if token_best > 0:
            matched += 1
            total_score += token_best
            best_priority = min(best_priority, token_best_priority)

    if matched == 0:
        return None

    coverage = matched / len(tokens) if tokens else 1.0
    return ScoredItem(
        item=item,
        total_score=total_score * coverage,
        field_priority=best_priority,
        matched_tokens=matched,
        total_tokens=len(tokens),
    )


def _sort_key(scored: ScoredItem, ranking: RankingConfig):
    """Build a sort key honoring the configured ranking order."""
    keys: List[Any] = []
    for sort_field in (ranking.primary_sort, ranking.secondary_sort, ranking.tertiary_sort):
        if sort_field == SortField.MATCH_PRIORITY:
            keys.append(scored.field_priority)                  # lower = better
        elif sort_field == SortField.BOOST_SCORE:
            keys.append(-scored.total_score)                    # higher = better
        elif sort_field == SortField.TITLE_ASC:
            keys.append((scored.item.title or "").lower())
        elif sort_field == SortField.TITLE_DESC:
            keys.append(tuple(-ord(c) for c in (scored.item.title or "").lower()))
    return tuple(keys)


def score_and_rank(
    items: Iterable[SearchIndexItem],
    query: str,
    config: SearchConfig,
) -> List[ScoredItem]:
    """Score every item against the query and return them ranked (best first).

    Used by the REST SearchManager, which then applies permission filtering.
    Returns an empty list for an empty query.
    """
    tokens = tokenize(query)
    if not tokens:
        return []
    scored = [s for s in (score_item(item, tokens, config) for item in items) if s is not None]
    scored.sort(key=lambda s: _sort_key(s, config.ranking))
    return scored


def _passes_filters(
    item: SearchIndexItem,
    type_filter: Optional[str],
    filters: Optional[Dict[str, Optional[str]]],
) -> bool:
    """Apply the type filter and any field filters.

    A filter matches when its value equals (case-insensitively) *any* of the
    field's discrete values — so a filter is exact (``domain='Sales'`` does not
    match "Sales Ops") yet still matches multi-valued fields like a product's
    assigned ``domains``.
    """
    if type_filter and item.type != type_filter:
        return False
    if filters:
        for key, wanted in filters.items():
            if wanted is None or wanted == "":
                continue
            wl = wanted.lower()
            values = get_field_values(item, key)
            if not any(wl == v.lower() for v in values):
                return False
    return True


def _compute_facets(items: List[SearchIndexItem], top_tags: int = 10) -> Dict[str, Dict[str, int]]:
    """Count candidates by type and by common extra_data fields, plus top tags.

    Gives the agent concrete values to narrow on instead of broadening to ``*``.
    """
    facets: Dict[str, Dict[str, int]] = {"type": {}}
    for f in _FACET_FIELDS:
        facets[f] = {}
    tag_counts: Dict[str, int] = {}

    for item in items:
        facets["type"][item.type] = facets["type"].get(item.type, 0) + 1
        for f in _FACET_FIELDS:
            value = get_field_value(item, f)
            if value:
                facets[f][value] = facets[f].get(value, 0) + 1
        for tag in item.tags or []:
            tag_counts[str(tag)] = tag_counts.get(str(tag), 0) + 1

    # Trim empty facet groups and keep only the top tags.
    facets = {k: v for k, v in facets.items() if v}
    if tag_counts:
        facets["tags"] = dict(
            sorted(tag_counts.items(), key=lambda kv: kv[1], reverse=True)[:top_tags]
        )
    return facets


def _entity_id(item: SearchIndexItem) -> str:
    """The bare entity id (index ids look like ``product::<uuid>``)."""
    return item.id.split("::", 1)[1] if "::" in item.id else item.id


def _to_result(item: SearchIndexItem, score: Optional[float]) -> Dict[str, Any]:
    """Render an item as a compact MCP result dict."""
    result: Dict[str, Any] = {
        "id": _entity_id(item),
        "type": item.type,
        "title": item.title,
        "description": (item.description[:200] if item.description else None),
        "link": item.link,
        "tags": (item.tags[:5] if item.tags else []),
        "feature_id": item.feature_id,
    }
    for f in _RESULT_FIELDS:
        value = get_field_value(item, f)
        if value:
            result[f] = value
    if score is not None:
        result["relevance_score"] = round(score, 4)
    return result


def search_index(
    items: Iterable[SearchIndexItem],
    query: str,
    config: SearchConfig,
    *,
    type_filter: Optional[str] = None,
    filters: Optional[Dict[str, Optional[str]]] = None,
    limit: int = 20,
    offset: int = 0,
    include_facets: bool = True,
) -> Dict[str, Any]:
    """Search/list index items for MCP tools: paginated, faceted, filtered.

    - A real query is tokenized, scored and ranked.
    - An empty/``*`` query is "list mode": all filtered items, ranked by title,
      still paginated with a total_count (never an unbounded dump).

    Returns a dict with ``results``, ``total_count``, ``returned``, ``offset``,
    ``limit``, ``has_more``, ``facets`` and ``query``.
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    candidates = [it for it in items if _passes_filters(it, type_filter, filters)]

    if is_list_query(query):
        ranked = sorted(candidates, key=lambda it: (it.title or "").lower())
        total = len(ranked)
        page = ranked[offset : offset + limit]
        results = [_to_result(it, None) for it in page]
    else:
        scored = score_and_rank(candidates, query, config)
        total = len(scored)
        page = scored[offset : offset + limit]
        results = [_to_result(s.item, s.total_score) for s in page]

    return {
        "results": results,
        "total_count": total,
        "returned": len(results),
        "offset": offset,
        "limit": limit,
        "has_more": (offset + len(results)) < total,
        "facets": _compute_facets(candidates) if include_facets else {},
        "query": query,
    }
