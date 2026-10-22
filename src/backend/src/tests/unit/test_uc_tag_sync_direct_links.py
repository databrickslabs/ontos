"""Tests for uc_tag_sync handling of concepts linked directly to UC objects (#724)."""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "uc_tag_sync" / "uc_tag_sync.py"
)

SEMANTIC_CFG = [
    {
        "entity_type": "semantic_assignment",
        "enabled": True,
        "tag_key_format": "ontos_semantic_{LINK.SLUG}",
        "tag_value_format": "{LINK.IRI}",
    }
]
OPEX = "urn:glossary:finance/opex-spend"
PII = "urn:glossary:privacy/pii"


@pytest.fixture(scope="module")
def tag_sync():
    """Load the job script by path; it is not part of the ``src`` package.

    pyspark is only available on the job cluster, so a stub is registered when missing.
    """
    added = []
    if "pyspark.sql" not in sys.modules:
        try:
            import pyspark.sql  # noqa: F401
        except ImportError:
            pyspark = types.ModuleType("pyspark")
            pyspark_sql = types.ModuleType("pyspark.sql")
            pyspark_sql.SparkSession = object
            pyspark.sql = pyspark_sql
            sys.modules["pyspark"] = pyspark
            sys.modules["pyspark.sql"] = pyspark_sql
            added = ["pyspark", "pyspark.sql"]
    spec = importlib.util.spec_from_file_location("uc_tag_sync_under_test", _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in added:
        sys.modules.pop(name, None)


def _row(entity_type, entity_id, iri=OPEX, label=None):
    return {"entity_type": entity_type, "entity_id": entity_id, "iri": iri, "label": label}


def test_reader_selects_only_direct_uc_entity_types(tag_sync):
    engine = MagicMock()
    conn = engine.connect.return_value.__enter__.return_value
    conn.execute.return_value = [MagicMock(_mapping={"entity_id": "a.b.c"})]

    rows = tag_sync.read_direct_uc_links(engine, limit=5)

    assert rows == [{"entity_id": "a.b.c"}]
    sql, params = conn.execute.call_args.args[0].text, conn.execute.call_args.args[1]
    for etype in ("uc_catalog", "uc_schema", "uc_table", "uc_column"):
        assert f"'{etype}'" in sql
    assert "LIMIT :limit" in sql and params == {"limit": 5}


def test_table_links_become_datasets_with_deduped_links(tag_sync):
    infos = tag_sync.build_direct_link_infos(
        [
            _row("uc_table", "Main.Finance.Fact_Expenses", OPEX, "Opex"),
            _row("uc_table", "main.finance.fact_expenses", OPEX),
            _row("uc_table", "main.finance.fact_expenses", PII),
            _row("uc_table", "not.qualified"),
        ],
        None,
        None,
    )
    assert [d.fqn for d in infos.tables] == ["main.finance.fact_expenses"]
    ds = infos.tables[0]
    assert (ds.catalog, ds.schema, ds.table) == ("main", "finance", "fact_expenses")
    assert [link.iri for link in ds.semantic_links] == [OPEX, PII]
    assert ds.semantic_links[0].slug == "opex-spend"
    assert ds.asset_id is None and ds.contract_id is None


def test_default_catalog_and_schema_qualify_short_names(tag_sync):
    infos = tag_sync.build_direct_link_infos(
        [_row("uc_table", "t1"), _row("uc_schema", "s1"), _row("uc_column", "t1.c1")],
        "cat",
        "sch",
    )
    assert [d.fqn for d in infos.tables] == ["cat.sch.t1"]
    assert list(infos.schemas) == ["cat.s1"]
    assert [c.fqn for c in infos.columns] == ["cat.sch.t1.c1"]


def test_column_schema_and_catalog_links(tag_sync):
    infos = tag_sync.build_direct_link_infos(
        [
            _row("uc_column", "main.finance.t.amount", OPEX),
            _row("uc_column", "main.finance.t.amount", PII),
            _row("uc_column", "main.finance.t.other", PII),
            _row("uc_schema", "main.finance", PII),
            _row("uc_catalog", "main", OPEX),
            _row("uc_catalog", "main.finance", OPEX),  # malformed, skipped
            _row("uc_column", "t.c", OPEX),  # unresolvable without defaults, skipped
        ],
        None,
        None,
    )
    cols = {c.fqn: [link.iri for link in c.semantic_links] for c in infos.columns}
    assert cols == {
        "main.finance.t.amount": [OPEX, PII],
        "main.finance.t.other": [PII],
    }
    assert [(c.table_fqn, c.column) for c in infos.columns][0] == ("main.finance.t", "amount")
    assert [link.iri for link in infos.schemas["main.finance"]] == [PII]
    assert [link.iri for link in infos.catalogs["main"]] == [OPEX]
    assert infos.tables == []


def test_desired_for_links_uses_semantic_assignment_format(tag_sync):
    links = tag_sync.build_direct_link_infos([_row("uc_column", "a.b.c.d", OPEX)], None, None)
    desired = tag_sync.build_desired_for_links(links.columns[0].semantic_links, SEMANTIC_CFG)
    assert desired == {"ontos_semantic_opex_spend": OPEX}
    # Disabled / non-semantic configs contribute nothing to a link-only object.
    other = [{**SEMANTIC_CFG[0], "enabled": False}, {**SEMANTIC_CFG[0], "entity_type": "asset"}]
    assert tag_sync.build_desired_for_links(links.columns[0].semantic_links, other) == {}


def _asset_dataset(tag_sync, fqn, iris=(), **kw):
    cat, sch, tbl = fqn.split(".")
    links = [tag_sync.SemanticLink(iri=i, label=None, slug=tag_sync.slugify_iri(i)) for i in iris]
    base = dict(
        fqn=fqn, catalog=cat, schema=sch, table=tbl,
        contract_id=None, contract_name=None, contract_version=None, contract_status=None,
        product_id=None, product_name=None, product_version=None, product_status=None,
        domain_id=None, domain_name=None, semantic_links=links,
        asset_id="a-1", asset_type_name="Table",
    )
    base.update(kw)
    return tag_sync.DatasetTagInfo(**base)


def test_same_table_via_asset_and_direct_link_is_deduped(tag_sync):
    asset_ds = [_asset_dataset(tag_sync, "main.finance.t", [OPEX], domain_name="Finance")]
    direct = tag_sync.build_direct_link_infos(
        [_row("uc_table", "main.finance.t", OPEX), _row("uc_table", "main.finance.t", PII)],
        None,
        None,
    )

    merged = tag_sync.merge_dataset_tag_infos([], asset_ds, direct.tables)

    assert [d.fqn for d in merged] == ["main.finance.t"]
    assert [link.iri for link in merged[0].semantic_links] == [OPEX, PII]
    assert merged[0].asset_id == "a-1" and merged[0].domain_name == "Finance"
    desired = tag_sync.build_desired_for_dataset(merged[0], SEMANTIC_CFG)
    assert desired == {"ontos_semantic_opex_spend": OPEX, "ontos_semantic_pii": PII}
    # Order independence: merging again in a different order yields the same tags.
    merged2 = tag_sync.merge_dataset_tag_infos(
        [], [], direct.tables + [_asset_dataset(tag_sync, "main.finance.t", [OPEX])]
    )
    assert tag_sync.build_desired_for_dataset(merged2[0], SEMANTIC_CFG) == desired


def test_merge_without_direct_datasets_is_unchanged(tag_sync):
    contract = _asset_dataset(tag_sync, "m.s.t", [OPEX], asset_id=None, asset_type_name=None)
    asset = _asset_dataset(tag_sync, "m.s.t", [PII])
    merged = tag_sync.merge_dataset_tag_infos([contract], [asset])
    assert len(merged) == 1
    assert [link.iri for link in merged[0].semantic_links] == [OPEX, PII]


def test_direct_only_table_gets_only_semantic_tags(tag_sync):
    cfgs = SEMANTIC_CFG + [
        {"entity_type": "data_domain", "tag_key_format": "ontos_domain", "tag_value_format": "{DOMAIN.NAME}"},
        {"entity_type": "asset", "tag_key_format": "ontos_asset", "tag_value_format": "{ASSET.TYPE}"},
    ]
    direct = tag_sync.build_direct_link_infos([_row("uc_table", "a.b.c", OPEX)], None, None)
    assert tag_sync.build_desired_for_dataset(direct.tables[0], cfgs) == {
        "ontos_semantic_opex_spend": OPEX
    }


def test_aggregate_parent_desired_folds_in_direct_schema_and_catalog_links(tag_sync):
    ds = _asset_dataset(tag_sync, "main.finance.t", [OPEX])
    schema, catalog = tag_sync.aggregate_parent_desired(
        [ds],
        SEMANTIC_CFG,
        direct_schema_desired={"main.finance": {"ontos_semantic_opex_spend": PII, "k": "v"}},
        direct_catalog_desired={"other": {"k": "v"}},
    )
    assert schema["main.finance"] == {
        "ontos_semantic_opex_spend": ",".join(sorted([OPEX, PII])),
        "k": "v",
    }
    assert catalog["main"] == {"ontos_semantic_opex_spend": OPEX}
    assert catalog["other"] == {"k": "v"}
    # Without direct links the result is the same as before.
    assert tag_sync.aggregate_parent_desired([ds], SEMANTIC_CFG)[0] == {
        "main.finance": {"ontos_semantic_opex_spend": OPEX}
    }


def test_column_tag_statements(tag_sync):
    spark = MagicMock()
    tag_sync.assign_tag(spark, "COLUMN", "main.finance.t.amount", "k", "it's")
    tag_sync.unassign_tag(spark, "COLUMN", "main.finance.t.amount", "k")
    tag_sync.assign_tag(spark, "TABLE", "main.finance.t", "k", "v")
    stmts = [c.args[0] for c in spark.sql.call_args_list]
    assert stmts == [
        "ALTER TABLE main.finance.t ALTER COLUMN `amount` SET TAGS ('k' = 'it''s')",
        "ALTER TABLE main.finance.t ALTER COLUMN `amount` UNSET TAGS ('k')",
        "ALTER TABLE main.finance.t SET TAGS ('k' = 'v')",
    ]


def test_column_existing_tags_query_and_reconcile(tag_sync):
    spark = MagicMock()
    spark.sql.return_value.collect.return_value = [
        {"tag_name": "ontos_semantic_old", "tag_value": "x"},
        {"tag_name": "unrelated", "tag_value": "y"},
    ]
    ws = MagicMock()
    updated, removed, errors = tag_sync.reconcile_tags(
        ws, spark, "COLUMN", "main.finance.t.amount",
        {"ontos_semantic_opex_spend": OPEX}, "ontos_semantic_",
    )
    first = spark.sql.call_args_list[0].args[0]
    assert "information_schema.column_tags" in first and "column_name = 'amount'" in first
    assert (updated, removed, errors) == (1, 1, [])
    stmts = [c.args[0] for c in spark.sql.call_args_list[1:]]
    assert any("UNSET TAGS ('ontos_semantic_old')" in s for s in stmts)
    assert any("SET TAGS ('ontos_semantic_opex_spend'" in s for s in stmts)

    # Idempotent: when the column already has the desired tag nothing is written.
    spark.reset_mock()
    spark.sql.return_value.collect.return_value = [
        {"tag_name": "ontos_semantic_opex_spend", "tag_value": OPEX}
    ]
    assert tag_sync.reconcile_tags(
        ws, spark, "COLUMN", "main.finance.t.amount",
        {"ontos_semantic_opex_spend": OPEX}, "ontos_semantic_",
    ) == (0, 0, [])
    assert spark.sql.call_count == 1


def test_differently_cased_asset_and_direct_link_merge_into_one_dataset(tag_sync):
    # UC names are case-insensitive: one table, one reconcile, links unioned
    assets = tag_sync.build_asset_tag_infos(
        [{
            "asset_id": "a-1", "asset_type_name": "Table",
            "physical_name": "Demo_Catalog.Sales.Orders",
            "asset_semantic_iri": "urn:x:asset", "asset_semantic_label": "Asset concept",
        }],
        None,
        None,
    )
    direct = tag_sync.build_direct_link_infos(
        [_row("uc_table", "demo_catalog.sales.orders", iri="urn:x:direct")], None, None
    )
    merged = tag_sync.merge_dataset_tag_infos([], assets, direct.tables)

    assert [d.fqn for d in merged] == ["demo_catalog.sales.orders"]
    assert {link.iri for link in merged[0].semantic_links} == {"urn:x:asset", "urn:x:direct"}
    assert (merged[0].catalog, merged[0].schema) == ("demo_catalog", "sales")
