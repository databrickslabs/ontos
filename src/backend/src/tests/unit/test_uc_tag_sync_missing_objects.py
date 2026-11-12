"""uc_tag_sync skips a UC object that no longer exists instead of aborting the run.

Spark is a fake that raises the Unity Catalog error for objects that are gone and
keeps tags in memory for the rest; the workspace client is a MagicMock. The real tag
read / write functions run, so the error handling is the production path.
"""

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_MODULE_PATH = (
    Path(__file__).resolve().parents[2] / "workflows" / "uc_tag_sync"
    / "uc_tag_sync.py"
)

KEY = "ontos_semantic_pii"
PII = "urn:glossary:privacy/pii"
CFG = [{
    "entity_type": "semantic_assignment", "enabled": True,
    "tag_key_format": "ontos_semantic_{LINK.SLUG}", "tag_value_format": "{LINK.IRI}",
}]


@pytest.fixture(scope="module")
def tag_sync():
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
    spec = importlib.util.spec_from_file_location("uc_tag_sync_missing_under_test",
                                                   _MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.TAG_SQL_SLEEP = lambda _s: None
    yield module
    for name in added:
        sys.modules.pop(name, None)


class FakeSpark:
    """spark.sql() raising ``errors[marker]`` when the statement mentions ``marker``."""

    def __init__(self, errors=None):
        self.errors = errors or {}
        self.statements = []

    def sql(self, statement):
        self.statements.append(statement)
        for marker, message in self.errors.items():
            if marker in statement:
                raise Exception(message)
        result = MagicMock()
        result.collect.return_value = []
        return result

    def sets(self):
        return [s for s in self.statements if "SET TAGS" in s]


def _dataset(tag_sync, fqn):
    cat, sch, tbl = fqn.split(".")
    return tag_sync.DatasetTagInfo(
        fqn=fqn, catalog=cat, schema=sch, table=tbl,
        contract_id=None, contract_name=None, contract_version=None,
        contract_status=None, product_id=None, product_name=None,
        product_version=None, product_status=None, domain_id=None,
        domain_name=None,
        semantic_links=[tag_sync.SemanticLink(iri=PII, label=None,
                                              slug=tag_sync.slugify_iri(PII))],
        asset_id="a-1", asset_type_name="Table",
    )


def _run(tag_sync, spark, fqns, previous=None):
    direct = tag_sync.build_direct_link_infos([], None, None)
    datasets = [_dataset(tag_sync, f) for f in fqns]
    return tag_sync.sync_tags(
        MagicMock(), spark, datasets, direct, CFG, tag_sync.TagOwnership(),
        previous=previous,
    )


TABLES = ["main.a.one", "gone.crm.customers", "main.a.three"]


@pytest.mark.parametrize("marker,error", [
    ("`gone`", "[CATALOG_NOT_FOUND] Catalog 'gone' was not found."),
    ("schema_name = 'crm'", "[SCHEMA_NOT_FOUND] The schema `gone`.`crm` cannot be found."),
    ("table_name = 'customers'",
     "[TABLE_OR_VIEW_NOT_FOUND] The table or view `gone`.`crm`.`customers` cannot be found."),
])
def test_missing_object_is_skipped_and_the_rest_is_synced(tag_sync, marker, error):
    spark = FakeSpark({marker: error})
    result = _run(tag_sync, spark, TABLES)

    assert result.errors == []
    assert any("TABLE main.a.one SET" in s for s in spark.sets())
    assert any("TABLE main.a.three SET" in s for s in spark.sets())
    assert any("TABLE gone.crm.customers" in item and "not found" in item
               for item in result.skipped)
    assert "gone.crm.customers" not in result.delivered["TABLE"]
    assert set(result.delivered["TABLE"]) == {"main.a.one", "main.a.three"}


def test_object_dropped_between_read_and_write_is_skipped(tag_sync):
    spark = FakeSpark({"ALTER TABLE gone.crm.customers": "[TABLE_OR_VIEW_NOT_FOUND] x"})
    result = _run(tag_sync, spark, TABLES)

    assert result.errors == []
    assert any("TABLE main.a.one SET" in s for s in spark.sets())
    assert any("TABLE main.a.three SET" in s for s in spark.sets())
    assert any("TABLE gone.crm.customers" in item for item in result.skipped)


def test_missing_column_is_skipped(tag_sync):
    spark = FakeSpark({"ALTER COLUMN `nope`": "[UNRESOLVED_COLUMN.WITH_SUGGESTION] nope"})
    direct = tag_sync.build_direct_link_infos(
        [
            {"entity_type": "uc_column", "entity_id": "main.a.t.nope", "iri": PII,
             "label": None},
            {"entity_type": "uc_column", "entity_id": "main.a.t.ok", "iri": PII,
             "label": None},
        ],
        None, None,
    )
    result = tag_sync.sync_tags(MagicMock(), spark, [], direct, CFG,
                                tag_sync.TagOwnership(), previous=None)

    assert result.errors == []
    assert result.updated == 1
    assert len(result.skipped) == 1 and "COLUMN main.a.t.nope" in result.skipped[0]
    assert "main.a.t.nope" not in result.delivered["COLUMN"]


def test_missing_object_is_not_retried(tag_sync):
    spark = FakeSpark({"ALTER TABLE gone.crm.customers": "[TABLE_OR_VIEW_NOT_FOUND] x"})
    _run(tag_sync, spark, TABLES)
    attempts = [s for s in spark.statements if "ALTER TABLE gone.crm.customers" in s]
    assert len(attempts) == 1


def test_other_errors_still_fail_the_object(tag_sync):
    spark = FakeSpark({"ALTER TABLE gone.crm.customers": "[PERMISSION_DENIED] APPLY TAG"})
    result = _run(tag_sync, spark, TABLES)

    assert len(result.errors) == 1 and "gone.crm.customers" in result.errors[0]
    assert result.skipped == []
    assert any("TABLE main.a.three SET" in s for s in spark.sets())


def test_unlinked_object_that_was_dropped_is_skipped_and_forgotten(tag_sync):
    spark = FakeSpark({"`gone`": "[CATALOG_NOT_FOUND] Catalog 'gone' was not found."})
    previous = {"TABLE": {"gone.crm.old": {KEY: PII}}, "COLUMN": {}, "SCHEMA": {},
                "CATALOG": {}}
    result = _run(tag_sync, spark, ["main.a.one"], previous=previous)

    assert result.errors == []
    assert len(result.skipped) == 1 and "gone.crm.old" in result.skipped[0]
    assert "gone.crm.old" not in result.delivered["TABLE"]


def test_skip_warning_names_the_object_not_the_error(tag_sync, capsys):
    secret = "/Volumes/secret/path"
    spark = FakeSpark({"table_name = 'customers'":
                       f"[TABLE_OR_VIEW_NOT_FOUND] {secret}"})
    _run(tag_sync, spark, TABLES)
    out = capsys.readouterr().out
    assert "gone.crm.customers" in out
    assert secret not in out
