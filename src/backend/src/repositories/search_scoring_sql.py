"""Compile ``SearchConfig`` + a tokenized query into Postgres scoring SQL.

The Postgres search backend must rank exactly like the in-memory scorer
(``controller.search_scoring.score_item`` / ``score_and_rank``) so switching
``SEARCH_BACKEND`` doesn't change results. This module reproduces that scorer
in SQL:

- per-type effective field configs (``SearchConfig.get_all_field_configs``),
- the four match types with the same quality values,
- per-term best field (first field wins ties) × boost, summed, × term coverage,
- ranking by the configured primary/secondary/tertiary sort.

Arithmetic is ``float8`` in the same operation order as Python, so scores are
bit-identical, and titles sort with ``COLLATE "C"`` (codepoint order, like
Python ``str`` comparison).

Every value that comes from configuration or the query (field names, type
names, tokens, patterns) is a bind parameter; only validated numbers
(boost/priority) and generated aliases are inlined.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from collections.abc import Sequence
from typing import Any, Union

from src.models.search_config import FieldConfig, MatchType, SearchConfig, SortField

# Fields resolved from base columns; anything else comes from extra_data
# (mirrors search_scoring.get_field_value).
_STD_VALUE_SQL = {
    "title": "lower(title)",
    "description": "lower(description)",
    "tags": "lower((SELECT string_agg(x, ' ') FROM jsonb_array_elements_text(tags) x))",
    "type": "lower(type)",
    "id": "lower(id)",
}

_TITLE_KEY = "lower(coalesce(title, '')) COLLATE \"C\""

_RE_SPECIAL = set("\\^$.|?*+()[]{}")


def _re_escape(s: str) -> str:
    return "".join("\\" + c if c in _RE_SPECIAL else c for c in s)


def _f8(x: float) -> str:
    """Inline a validated config number as float8 (never user text)."""
    v = float(x)
    if not math.isfinite(v):
        v = 0.0
    return f"CAST({v!r} AS float8)"


_Q1 = "CAST(1.0 AS float8)"
_Q09 = "CAST(0.9 AS float8)"
_Q08 = "CAST(0.8 AS float8)"
_Q07 = "CAST(0.7 AS float8)"
_Q05 = "CAST(0.5 AS float8)"
_Q0 = "CAST(0.0 AS float8)"


@dataclass
class _Binder:
    ns: str = "ss"
    params: dict[str, Any] = field(default_factory=dict)
    _n: int = 0

    def bind(self, value: Any, prefix: str) -> str:
        name = f"{self.ns}_{prefix}{self._n}"
        self._n += 1
        self.params[name] = value
        return f":{name}"


@dataclass
class _Token:
    text: str
    t: str            # bound token
    word_re: str      # bound regex: token at start of a word (PREFIX non-leading)
    subseq_re: str    # bound regex: token chars in order (FUZZY)
    chars: list[str]  # bound distinct chars (FUZZY overlap)


def _bind_token(token: str, b: _Binder) -> _Token:
    return _Token(
        text=token,
        t=b.bind(token, "t"),
        word_re=b.bind("(^|[[:space:]/])" + _re_escape(token), "wre"),
        subseq_re=b.bind(".*".join(_re_escape(c) for c in token), "sre"),
        chars=[b.bind(c, "ch") for c in sorted(set(token))],
    )


def _quality(v: str, tok: _Token, match_type: MatchType) -> str:
    """SQL for search_scoring.check_match(value, token, match_type); NULL value -> 0."""
    n = len(tok.text)
    if match_type == MatchType.EXACT:
        return f"CASE WHEN {v} = {tok.t} THEN {_Q1} ELSE {_Q0} END"
    if match_type == MatchType.PREFIX:
        return (
            f"CASE WHEN left({v}, {n}) = {tok.t} THEN {_Q1} "
            f"WHEN {v} ~ {tok.word_re} THEN {_Q09} ELSE {_Q0} END"
        )
    if match_type == MatchType.SUBSTRING:
        return (
            f"CASE WHEN left({v}, {n}) = {tok.t} THEN {_Q1} "
            f"WHEN strpos({v}, ' ' || {tok.t}) > 0 THEN {_Q09} "
            f"WHEN strpos({v}, {tok.t}) > 0 THEN {_Q08} ELSE {_Q0} END"
        )
    if match_type == MatchType.FUZZY:
        # fuzzy_match: substring 0.9 > in-order subsequence 0.7 > >=80% of the
        # token's distinct chars within the value's first 2*len chars 0.5.
        head = f"left({v}, {2 * n})"
        hits = " + ".join(f"(CASE WHEN strpos({head}, {c}) > 0 THEN 1 ELSE 0 END)" for c in tok.chars)
        return (
            f"CASE WHEN {v} IS NULL OR {v} = '' THEN {_Q0} "
            f"WHEN strpos({v}, {tok.t}) > 0 THEN {_Q09} "
            f"WHEN {v} ~ {tok.subseq_re} THEN {_Q07} "
            f"WHEN ({hits}) * 10 >= 8 * {len(tok.chars)} THEN {_Q05} ELSE {_Q0} END"
        )
    return _Q0


@dataclass
class ScoringSql:
    """Pieces the repository splices into its query."""
    base_select: str          # extra columns for the base CTE (branch + lowered field values)
    lateral_joins: str        # per-token LEFT JOIN LATERAL blocks over the base CTE alias "b"
    score_expr: str           # float8 relevance (total_score * coverage)
    priority_expr: str        # best field priority (lower = better)
    matched_expr: str         # number of tokens that matched
    order_by: str             # ORDER BY clause body (no keyword)
    params: dict[str, Any]


def _branches(config: SearchConfig) -> list[tuple[str, dict[str, FieldConfig]]]:
    """(type-match SQL template, effective field configs) in CASE order.

    Order mirrors get_all_field_configs: an explicitly configured type first,
    then ``asset-*`` falling back to the ``asset`` config, then the defaults.
    Templates use ``{ty}`` placeholders filled with bound names by the caller.
    """
    out: list[tuple[str, dict[str, FieldConfig]]] = []
    for name in config.asset_types:
        out.append((f"type = {{ty:{name}}}", config.get_all_field_configs(name)))
    if "asset" in config.asset_types:
        out.append(("type LIKE 'asset-%'", config.get_all_field_configs("asset")))
    out.append(("TRUE", config.get_all_field_configs("__default__")))
    return out


def disabled_types_sql(config: SearchConfig, b: _Binder) -> str:
    """Predicate keeping only enabled types (mirrors SearchManager._is_item_enabled)."""
    disabled = [n for n, a in config.asset_types.items() if not a.enabled]
    if not disabled:
        return ""
    preds = [f"type <> ALL({b.bind(disabled, 'dis')})"]
    asset_cfg = config.asset_types.get("asset")
    if asset_cfg is not None and not asset_cfg.enabled:
        configured = list(config.asset_types.keys())
        preds.append(f"NOT (type LIKE 'asset-%' AND type <> ALL({b.bind(configured, 'cfg')}))")
    return " AND ".join(preds)


def order_by_sql(config: SearchConfig) -> str:
    parts: list[str] = []
    for sf in (config.ranking.primary_sort, config.ranking.secondary_sort, config.ranking.tertiary_sort):
        if sf == SortField.MATCH_PRIORITY:
            parts.append("priority ASC")
        elif sf == SortField.BOOST_SCORE:
            parts.append("score DESC")
        elif sf == SortField.TITLE_ASC:
            parts.append(f"{_TITLE_KEY} ASC")
        elif sf == SortField.TITLE_DESC:
            parts.append(f"{_TITLE_KEY} DESC")
    parts.append("id ASC")  # deterministic final tiebreak
    return ", ".join(parts)


def _fill_types(template: str, config: SearchConfig, b: _Binder, ty_names: dict[str, str]) -> str:
    """Replace ``_branches``' ``{ty:<name>}`` placeholders with bound type names,
    binding each name once per statement (``ty_names`` caches the bindings)."""
    out = template
    for name in config.asset_types:
        ph = f"{{ty:{name}}}"
        if ph in out:
            if name not in ty_names:
                ty_names[name] = b.bind(name, "ty")
            out = out.replace(ph, ty_names[name])
    return out


def build_scoring_sql(config: SearchConfig, tokens: list[str]) -> ScoringSql:
    """Compile the config scorer for ``tokens`` (already lower-cased by tokenize)."""
    b = _Binder()
    branches = _branches(config)

    # One bound name per configured type name.
    ty_names: dict[str, str] = {}

    def _fill(template: str) -> str:
        return _fill_types(template, config, b, ty_names)

    # Base CTE: which branch applies to the row, plus each distinct field value once.
    branch_case = "CASE " + " ".join(
        f"WHEN {_fill(cond)} THEN {i}" for i, (cond, _) in enumerate(branches)
    ) + " END"
    value_alias: dict[str, str] = {}
    value_cols: list[str] = []
    for _, fcs in branches:
        for fname in fcs:
            if fname in value_alias:
                continue
            alias = f"v{len(value_alias)}"
            value_alias[fname] = alias
            if fname in _STD_VALUE_SQL:
                expr = _STD_VALUE_SQL[fname]
            else:
                k = b.bind(fname, "fk")
                expr = (
                    f"lower(CASE jsonb_typeof(extra_data -> {k}) WHEN 'array' THEN "
                    f"(SELECT string_agg(x, ' ') FROM jsonb_array_elements_text(extra_data -> {k}) x) "
                    f"ELSE extra_data ->> {k} END)"
                )
            value_cols.append(f"{expr} AS {alias}")
    base_select = ", ".join([f"{branch_case} AS br"] + value_cols)

    toks = [_bind_token(t, b) for t in tokens]
    laterals: list[str] = []
    for i, tok in enumerate(toks):
        rows: list[str] = []
        for bi, (_, fcs) in enumerate(branches):
            for ord_, (fname, fc) in enumerate(fcs.items()):
                q = _quality(f"b.{value_alias[fname]}", tok, fc.match_type)
                rows.append(f"({bi}, {ord_}, {_f8(fc.boost)} * ({q}), {int(fc.priority)})")
        if not rows:
            laterals.append(f"LEFT JOIN LATERAL (SELECT CAST(NULL AS float8) AS s{i}, CAST(NULL AS int) AS p{i}) t{i} ON TRUE")
            continue
        laterals.append(
            f"LEFT JOIN LATERAL (SELECT f.score AS s{i}, f.prio AS p{i} "
            f"FROM (VALUES {', '.join(rows)}) AS f(br, ord, score, prio) "
            f"WHERE f.br = b.br AND f.score > 0 "
            f"ORDER BY f.score DESC, f.ord ASC LIMIT 1) t{i} ON TRUE"
        )

    n = len(toks)
    raw = " + ".join([_Q0] + [f"coalesce(s{i}, {_Q0})" for i in range(n)])
    matched = " + ".join(["0"] + [f"(CASE WHEN s{i} IS NOT NULL THEN 1 ELSE 0 END)" for i in range(n)])
    score = f"(({raw}) * (CAST(({matched}) AS float8) / CAST({max(n, 1)} AS float8)))"
    priority = (
        f"coalesce(LEAST({', '.join(f'p{i}' for i in range(n))}), 10000)" if n else "10000"
    )

    return ScoringSql(
        base_select=base_select,
        lateral_joins=" ".join(laterals),
        score_expr=score,
        priority_expr=priority,
        matched_expr=f"({matched})",
        order_by=order_by_sql(config),
        params=b.params,
    )


def list_order_sql() -> str:
    """List mode (empty / ``*`` query): title order like search_scoring.search_index."""
    return f"{_TITLE_KEY} ASC, id ASC"


def disabled_where_only(config: SearchConfig) -> tuple[str, dict[str, Any]]:
    """Disabled-type predicate + params, in the ``ssd`` namespace so they can't
    collide with ``build_scoring_sql``'s ``ss`` params in the same statement."""
    b = _Binder(ns="ssd")
    return disabled_types_sql(config, b), b.params


def field_boost_sql(
    config: SearchConfig, field_names: Union[str, Sequence[str]], ns: str = "bmb",
) -> tuple[str, dict[str, Any]]:
    """Per-row Settings boost of one field, or the highest of several (0 where the
    type indexes none of them), as a CASE over the same type branches as the
    scorer. Used to weight the per-field BM25 scores (lakebase engine)."""
    names = [field_names] if isinstance(field_names, str) else list(field_names)
    b = _Binder(ns=ns)
    ty_names: dict[str, str] = {}
    whens: list[str] = []
    for cond, fcs in _branches(config):
        boosts = [fcs[n].boost for n in names if n in fcs and fcs[n].indexed]
        whens.append(f"WHEN {_fill_types(cond, config, b, ty_names)} THEN {_f8(max(boosts, default=0.0))}")
    return "CASE " + " ".join(whens) + " END", b.params
