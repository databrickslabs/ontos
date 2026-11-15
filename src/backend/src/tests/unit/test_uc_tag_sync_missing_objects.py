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


# What Unity Catalog raised on a workspace for ALTER TABLE t ALTER COLUMN <missing>
# SET TAGS (SQLSTATE 42703).
MISSING_COLUMN_ERROR = (
    "[COLUMN_NOT_FOUND_IN_TABLE] Column `nope` not found in table `main`.`a`.`t`. "
    "SQLSTATE: 42703"
)


def _columns(tag_sync, *names):
    return tag_sync.build_direct_link_infos(
        [{"entity_type": "uc_column", "entity_id": f"main.a.t.{n}", "iri": PII,
          "label": None} for n in names],
        None, None,
    )


def test_missing_column_is_skipped(tag_sync):
    spark = FakeSpark({"ALTER COLUMN `nope`": MISSING_COLUMN_ERROR})
    result = tag_sync.sync_tags(MagicMock(), spark, [], _columns(tag_sync, "nope", "ok"),
                                CFG, tag_sync.TagOwnership(), previous=None)

    assert result.errors == []
    assert result.updated == 1
    assert len(result.skipped) == 1 and "COLUMN main.a.t.nope" in result.skipped[0]
    assert "main.a.t.nope" not in result.delivered["COLUMN"]


def test_missing_column_is_not_retried(tag_sync, monkeypatch):
    sleeps = []
    monkeypatch.setattr(tag_sync, "TAG_SQL_SLEEP", sleeps.append)
    spark = FakeSpark({"ALTER COLUMN `nope`": MISSING_COLUMN_ERROR})
    tag_sync.sync_tags(MagicMock(), spark, [], _columns(tag_sync, "nope"), CFG,
                       tag_sync.TagOwnership(), previous=None)

    assert len([s for s in spark.statements if "ALTER COLUMN `nope`" in s]) == 1
    assert sleeps == []


def test_unresolved_column_in_a_tag_read_fails_the_object(tag_sync):
    """A column error in the job's own information_schema query is not a missing
    object: skipping it would hide a broken query behind a green run."""
    spark = FakeSpark({"table_name = 'customers'":
                       "[UNRESOLVED_COLUMN.WITH_SUGGESTION] `tag_name` cannot be resolved"})
    result = _run(tag_sync, spark, TABLES)

    assert result.skipped == []
    assert result.failed_objects == ["TABLE gone.crm.customers"]


def test_column_not_found_outside_a_column_alter_fails_the_object(tag_sync):
    spark = FakeSpark({"ALTER TABLE gone.crm.customers SET": MISSING_COLUMN_ERROR})
    result = _run(tag_sync, spark, TABLES)

    assert result.skipped == []
    assert result.failed_objects == ["TABLE gone.crm.customers"]


def test_unresolved_column_is_not_retried(tag_sync, monkeypatch):
    sleeps = []
    monkeypatch.setattr(tag_sync, "TAG_SQL_SLEEP", sleeps.append)
    spark = FakeSpark({"ALTER COLUMN `nope`": "[UNRESOLVED_COLUMN] nope"})
    result = tag_sync.sync_tags(MagicMock(), spark, [], _columns(tag_sync, "nope"), CFG,
                                tag_sync.TagOwnership(), previous=None)

    assert result.failed_objects == ["COLUMN main.a.t.nope"]
    assert sleeps == []


def test_missing_object_is_not_retried(tag_sync, monkeypatch):
    sleeps = []
    monkeypatch.setattr(tag_sync, "TAG_SQL_SLEEP", sleeps.append)
    spark = FakeSpark({"ALTER TABLE gone.crm.customers": "[TABLE_OR_VIEW_NOT_FOUND] x"})
    _run(tag_sync, spark, TABLES)
    attempts = [s for s in spark.statements if "ALTER TABLE gone.crm.customers" in s]
    assert len(attempts) == 1
    assert sleeps == []


# What a workspace returned for a read of <catalog>.information_schema without USE
# CATALOG (SQLSTATE 42501): not zero rows and not a not-found class.
NO_USE_CATALOG_ERROR = (
    "[INSUFFICIENT_PERMISSIONS] Insufficient privileges: User does not have USE CATALOG "
    "on Catalog 'gone'. SQLSTATE: 42501"
)


@pytest.mark.parametrize("previous", [None, "recorded"])
def test_permission_denied_on_the_tag_read_fails_the_object(tag_sync, previous):
    """The job can't read the catalog's information_schema: the object fails (the run
    goes red) instead of being skipped as missing, and keeps its record."""
    spark = FakeSpark({"FROM `gone`.information_schema": NO_USE_CATALOG_ERROR})
    prev = _previous("gone.crm.customers") if previous else None
    result = _run(tag_sync, spark, TABLES, previous=prev)

    assert result.skipped == []
    # The table and the schema / catalog its tags roll up to.
    assert result.failed_objects == [
        "TABLE gone.crm.customers", "SCHEMA gone.crm", "CATALOG gone"]
    assert any("TABLE main.a.three SET" in s for s in spark.sets())
    if previous:
        assert result.delivered["TABLE"]["gone.crm.customers"] == {KEY: PII}


def test_permission_denied_on_an_unlinked_object_keeps_its_record(tag_sync):
    spark = FakeSpark({"FROM `gone`.information_schema": NO_USE_CATALOG_ERROR})
    result = _run(tag_sync, spark, ["main.a.one"], previous=_previous("gone.crm.old"))

    assert result.skipped == []
    assert result.delivered["TABLE"]["gone.crm.old"] == {KEY: PII}


def test_other_errors_still_fail_the_object(tag_sync):
    spark = FakeSpark({"ALTER TABLE gone.crm.customers": "[PERMISSION_DENIED] APPLY TAG"})
    result = _run(tag_sync, spark, TABLES)

    assert len(result.errors) == 1 and "gone.crm.customers" in result.errors[0]
    assert result.skipped == []
    assert any("TABLE main.a.three SET" in s for s in spark.sets())


def _previous(fqn):
    return {"TABLE": {fqn: {KEY: PII}}, "COLUMN": {}, "SCHEMA": {}, "CATALOG": {}}


def test_unlinked_missing_object_is_skipped_and_its_record_kept(tag_sync):
    """UC also says not found for an object the job can't see: keep the record."""
    spark = FakeSpark({"`gone`": "[CATALOG_NOT_FOUND] Catalog 'gone' was not found."})
    result = _run(tag_sync, spark, ["main.a.one"], previous=_previous("gone.crm.old"))

    assert result.errors == []
    assert len(result.skipped) == 1 and "gone.crm.old" in result.skipped[0]
    assert result.delivered["TABLE"]["gone.crm.old"] == {KEY: PII}


@pytest.mark.parametrize("partial", [False, True])
def test_linked_missing_object_with_a_record_is_skipped_once_and_kept(tag_sync, partial):
    spark = FakeSpark({"table_name = 'customers'": "[TABLE_OR_VIEW_NOT_FOUND] x"})
    direct = tag_sync.build_direct_link_infos([], None, None)
    result = tag_sync.sync_tags(
        MagicMock(), spark, [_dataset(tag_sync, "gone.crm.customers")], direct, CFG,
        tag_sync.TagOwnership(), previous=_previous("gone.crm.customers"),
        partial=partial,
    )

    assert result.errors == []
    assert len(result.skipped) == 1
    assert result.delivered["TABLE"]["gone.crm.customers"] == {KEY: PII}


def test_skip_warning_names_the_object_not_the_error(tag_sync, capsys):
    secret = "/Volumes/secret/path"
    spark = FakeSpark({"table_name = 'customers'":
                       f"[TABLE_OR_VIEW_NOT_FOUND] {secret}"})
    _run(tag_sync, spark, TABLES)
    out = capsys.readouterr().out
    assert "gone.crm.customers" in out
    assert secret not in out


def _ws_creating_tag_keys_fails(message):
    ws = MagicMock()
    ws.tags.create.side_effect = Exception(message)
    return ws


def test_tag_key_that_already_exists_is_not_an_error(tag_sync):
    ws = _ws_creating_tag_keys_fails("Tag key ontos_x ALREADY_EXISTS")
    direct = tag_sync.build_direct_link_infos([], None, None)
    result = tag_sync.sync_tags(ws, FakeSpark(), [_dataset(tag_sync, "main.a.one")],
                                direct, CFG, tag_sync.TagOwnership(), previous=None)
    assert result.errors == []
    assert result.updated >= 1


def test_sdk_already_exists_error_code_is_not_an_error(tag_sync):
    class SdkError(Exception):
        error_code = "RESOURCE_ALREADY_EXISTS"

    ws = MagicMock()
    ws.tags.create.side_effect = SdkError("tag key is taken")
    direct = tag_sync.build_direct_link_infos([], None, None)
    result = tag_sync.sync_tags(ws, FakeSpark(), [_dataset(tag_sync, "main.a.one")],
                                direct, CFG, tag_sync.TagOwnership(), previous=None)
    assert result.errors == []


def test_tag_key_creation_failure_is_a_warning_when_the_tag_is_set(tag_sync, capsys):
    ws = _ws_creating_tag_keys_fails("[PERMISSION_DENIED] /secret/path")
    spark = FakeSpark()
    direct = tag_sync.build_direct_link_infos([], None, None)
    result = tag_sync.sync_tags(ws, spark, [_dataset(tag_sync, "main.a.one")],
                                direct, CFG, tag_sync.TagOwnership(), previous=None)
    assert result.errors == []
    assert result.failed_objects == []
    assert any("TABLE main.a.one SET" in q for q in spark.sets())
    assert any("TABLE main.a.one" in w for w in result.warnings)
    out = capsys.readouterr().out
    assert "TABLE main.a.one" in out and "/secret/path" not in out


def test_tag_key_and_write_both_failing_fail_the_object_once(tag_sync):
    ws = _ws_creating_tag_keys_fails("[PERMISSION_DENIED] cannot create tag key")
    spark = FakeSpark({"ALTER TABLE main.a.one": "[PERMISSION_DENIED] APPLY TAG"})
    direct = tag_sync.build_direct_link_infos([], None, None)
    result = tag_sync.sync_tags(ws, spark, [_dataset(tag_sync, "main.a.one")],
                                direct, CFG, tag_sync.TagOwnership(), previous=None)
    table_errors = [e for e in result.errors if "TABLE main.a.one" in e]
    assert len(table_errors) == 2
    assert result.failed_objects.count("TABLE main.a.one") == 1


def test_missing_object_while_creating_the_tag_key_is_skipped(tag_sync):
    ws = _ws_creating_tag_keys_fails("[TABLE_OR_VIEW_NOT_FOUND] x")
    direct = tag_sync.build_direct_link_infos([], None, None)
    result = tag_sync.sync_tags(ws, FakeSpark(), [_dataset(tag_sync, "main.a.one")],
                                direct, CFG, tag_sync.TagOwnership(), previous=None)
    assert result.errors == []
    assert any("TABLE main.a.one" in item for item in result.skipped)


def test_failed_objects_are_counted_once_each(tag_sync):
    spark = FakeSpark({"ALTER TABLE main.a.one": "[PERMISSION_DENIED] APPLY TAG"})
    result = _run(tag_sync, spark, ["main.a.one", "main.a.three"])
    assert result.failed_objects == ["TABLE main.a.one"]
    assert len(result.errors) == 1


def test_a_tag_policy_rejection_is_not_retried(tag_sync, monkeypatch):
    """A governed tag policy that doesn't allow the value: the error a workspace
    returned. A retry can't fix it, so the statement runs once and the object fails."""
    sleeps = []
    monkeypatch.setattr(tag_sync, "TAG_SQL_SLEEP", sleeps.append)
    spark = FakeSpark({"ALTER TABLE gone.crm.customers SET": (
        "[INVALID_PARAMETER_VALUE.UC_TAG_POLICY_VALUE_NOT_ALLOWED] The value is not "
        "allowed by the tag policy."
    )})
    result = _run(tag_sync, spark, TABLES)

    assert len([s for s in spark.statements
                if "ALTER TABLE gone.crm.customers SET" in s]) == 1
    assert sleeps == []
    assert result.failed_objects == ["TABLE gone.crm.customers"]


SECRET = "urn:glossary:privacy/secret"


def _two_link_dataset(tag_sync, fqn):
    d = _dataset(tag_sync, fqn)
    d.semantic_links.append(tag_sync.SemanticLink(iri=SECRET, label=None,
                                                  slug=tag_sync.slugify_iri(SECRET)))
    return d


def _two_tag_keys(tag_sync):
    return (f"ontos_semantic_{tag_sync.slugify_iri(PII)}",
            f"ontos_semantic_{tag_sync.slugify_iri(SECRET)}")


def test_a_tag_written_before_the_object_goes_missing_is_recorded(tag_sync):
    """Tag A is set, then tag B's ALTER finds the table gone: the record keeps A next to
    the earlier record, so a later unlink of the table removes A instead of leaving it
    behind."""
    key_a, key_b = _two_tag_keys(tag_sync)
    spark = FakeSpark({f"SET TAGS ('{key_b}'": "[TABLE_OR_VIEW_NOT_FOUND] dropped"})
    previous = {"TABLE": {"main.a.t": {"ontos_semantic_old": "x"}}, "COLUMN": {},
                "SCHEMA": {}, "CATALOG": {}}
    direct = tag_sync.build_direct_link_infos([], None, None)
    result = tag_sync.sync_tags(MagicMock(), spark,
                                [_two_link_dataset(tag_sync, "main.a.t")], direct, CFG,
                                tag_sync.TagOwnership(), previous=previous)

    assert any("TABLE main.a.t" in item for item in result.skipped)
    assert any(f"SET TAGS ('{key_a}'" in s for s in spark.sets())
    assert result.delivered["TABLE"]["main.a.t"] == {"ontos_semantic_old": "x",
                                                     key_a: PII}


def test_a_tag_key_creation_failure_is_warned_once_per_key(tag_sync, capsys):
    ws = _ws_creating_tag_keys_fails("[PERMISSION_DENIED] cannot create tag key")
    result = _run_ws(tag_sync, ws, ["main.a.one", "main.a.three"])

    assert result.errors == []
    assert len(result.warnings) == 1
    assert "main.a.one" in result.warnings[0]
    assert capsys.readouterr().out.count("could not be created") == 1


def _run_ws(tag_sync, ws, fqns):
    direct = tag_sync.build_direct_link_infos([], None, None)
    return tag_sync.sync_tags(ws, FakeSpark(), [_dataset(tag_sync, f) for f in fqns],
                              direct, CFG, tag_sync.TagOwnership(), previous=None)


@pytest.mark.parametrize("linked", [False, True])
def test_a_recorded_column_that_is_gone_is_skipped_on_removal(tag_sync, monkeypatch,
                                                               linked):
    """UNSET TAGS on a dropped column (unlinked: cleanup; linked: a recorded tag no
    longer desired) raises COLUMN_NOT_FOUND_IN_TABLE: skipped, record kept."""
    monkeypatch.setattr(tag_sync, "get_existing_prefixed_tags",
                        lambda _s, t, n, _p: {"ontos_old": "x"} if t == "COLUMN" else {})
    spark = FakeSpark({"ALTER COLUMN `nope`": MISSING_COLUMN_ERROR})
    previous = {"TABLE": {}, "COLUMN": {"main.a.t.nope": {"ontos_old": "x"}},
                "SCHEMA": {}, "CATALOG": {}}
    direct = _columns(tag_sync, "nope") if linked else _columns(tag_sync)
    result = tag_sync.sync_tags(MagicMock(), spark, [], direct, CFG,
                                tag_sync.TagOwnership(), previous=previous)

    assert any("UNSET TAGS ('ontos_old')" in s for s in spark.statements)
    assert result.failed_objects == []
    assert any("COLUMN main.a.t.nope" in item for item in result.skipped)
    assert result.delivered["COLUMN"]["main.a.t.nope"]["ontos_old"] == "x"
