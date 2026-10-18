"""Unit tests for the Settings → SQL scoring compiler (no database needed).

Execution parity with the in-memory scorer is covered by
tests/integration/test_search_settings_parity_pg.py against real Postgres.
"""
import copy

from src.models.search_config import (
    AssetTypeConfig,
    FieldConfig,
    MatchType,
    SearchConfig,
    SortField,
)
from src.repositories import search_scoring_sql as ss


def _config() -> SearchConfig:
    cfg = SearchConfig()
    cfg.asset_types["data-product"] = AssetTypeConfig(
        enabled=True, inherit_defaults=True,
        extra_fields={"owner": FieldConfig(indexed=True, match_type=MatchType.SUBSTRING, priority=4, boost=1.5)},
    )
    cfg.asset_types["asset"] = AssetTypeConfig(enabled=True, inherit_defaults=True)
    return cfg


def test_user_controlled_names_are_bound_not_inlined():
    """Field names, type names and tokens come from Settings / the query and must
    only reach SQL as bind parameters."""
    cfg = _config()
    evil_field = "x'); DROP TABLE search_documents; --"
    evil_type = "t'; DELETE FROM search_documents; --"
    cfg.asset_types[evil_type] = AssetTypeConfig(
        enabled=True, extra_fields={evil_field: FieldConfig(indexed=True)},
    )
    s = ss.build_scoring_sql(cfg, ["drop", "x"])
    sql = " ".join([s.base_select, s.lateral_joins, s.score_expr, s.priority_expr, s.order_by])
    assert evil_field not in sql and "DROP TABLE" not in sql
    assert evil_type not in sql and "DELETE FROM" not in sql
    assert evil_field in s.params.values()
    assert evil_type in s.params.values()
    assert {"drop", "x"} <= set(s.params.values())


def test_disabled_types_predicate_and_namespace():
    cfg = _config()
    cfg.asset_types["data-product"].enabled = False
    pred, params = ss.disabled_where_only(cfg)
    assert "type <> ALL(" in pred
    assert ["data-product"] in params.values()
    # Separate namespace from build_scoring_sql's params, so both can share a statement.
    assert all(k.startswith("ssd_") for k in params)
    assert all(k.startswith("ss_") for k in ss.build_scoring_sql(cfg, ["a"]).params)


def test_disabling_asset_also_excludes_unconfigured_asset_subtypes():
    cfg = _config()
    cfg.asset_types["asset"].enabled = False
    pred, params = ss.disabled_where_only(cfg)
    assert "type LIKE 'asset-%'" in pred
    assert sorted(cfg.asset_types) in [sorted(v) for v in params.values() if isinstance(v, list)]


def test_no_disabled_types_means_no_predicate():
    pred, params = ss.disabled_where_only(_config())
    assert pred == "" and params == {}


def test_order_by_follows_ranking_with_deterministic_tiebreak():
    cfg = _config()
    assert ss.order_by_sql(cfg).startswith("priority ASC, score DESC")
    cfg2 = copy.deepcopy(cfg)
    cfg2.ranking.primary_sort = SortField.TITLE_ASC
    cfg2.ranking.secondary_sort = SortField.BOOST_SCORE
    cfg2.ranking.tertiary_sort = SortField.MATCH_PRIORITY
    order = ss.order_by_sql(cfg2)
    assert order.index("COLLATE") < order.index("score DESC") < order.index("priority ASC")
    assert order.endswith("id ASC")


def test_one_lateral_per_token_including_duplicates():
    """Duplicate terms count twice, like search_scoring.tokenize + score_item."""
    s = ss.build_scoring_sql(_config(), ["data", "data", "sales"])
    assert s.lateral_joins.count("LEFT JOIN LATERAL") == 3
    assert "CAST(3 AS float8)" in s.score_expr


def test_branch_order_mirrors_get_all_field_configs():
    """Explicit types first, then asset-* → asset, then defaults (TRUE)."""
    cfg = _config()
    branches = ss._branches(cfg)
    conds = [c for c, _ in branches]
    assert conds[-1] == "TRUE"
    assert "type LIKE 'asset-%'" in conds
    assert conds.index("type LIKE 'asset-%'") == len(conds) - 2
    product_fields = dict(branches)["type = {ty:data-product}"]
    assert set(product_fields) == {"title", "description", "tags", "owner"}


def test_non_finite_boost_is_neutralised():
    assert ss._f8(float("inf")) == "CAST(0.0 AS float8)"
    assert ss._f8(1.5) == "CAST(1.5 AS float8)"


def test_field_boost_sql_follows_type_overrides():
    from src.repositories.search_scoring_sql import field_boost_sql
    from src.models.search_config import AssetTypeConfig, FieldConfig

    cfg = _config()
    cfg.asset_types["data-product"] = AssetTypeConfig(
        enabled=True, inherit_defaults=True, fields={"title": FieldConfig(boost=7.0)},
    )
    sql, params = field_boost_sql(cfg, "title")
    assert "CAST(7.0 AS float8)" in sql                    # per-type override
    assert f"CAST({cfg.defaults.fields.title.boost!r} AS float8)" in sql  # defaults branch
    assert "data-product" in params.values()               # type names are bound, not inlined
    assert all(k.startswith("bmb_") for k in params)


def test_field_boost_sql_takes_the_highest_of_several_fields():
    from src.repositories.search_scoring_sql import field_boost_sql

    cfg = _config()
    tags = cfg.defaults.fields.tags.boost
    sql, _ = field_boost_sql(cfg, ("tags", "owner"))   # data-product's owner boost (1.5) beats tags
    assert f"CAST({max(tags, 1.5)!r} AS float8)" in sql
    none_sql, _ = field_boost_sql(cfg, ("not-a-field",))
    assert "CAST(0.0 AS float8)" in none_sql
