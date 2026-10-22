"""uc_tag_sync writes the lifecycle status of the product using a table (#998).

Covers the default ``ontos_lifecycle_status`` entry, the shared-table rule (the product
or contract with the best status decides the status tag and the single-valued name
tags), output ports without a contract, and retries of tag statements.
"""

import importlib.util
import json
import sys
import types
import uuid
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from src.db_models.data_contracts import DataContractDb, SchemaObjectDb
from src.db_models.data_domains import DataDomain
from src.db_models.data_products import DataProductDb, OutputPortDb
from src.db_models.domain_associations import EntityDomainAssociationDb

_JOB_DIR = Path(__file__).resolve().parents[2] / "workflows" / "uc_tag_sync"
STATUS_KEY = "ontos_lifecycle_status"
NAME_KEY = "ontos_product_name"
TABLE = "main.sales.orders"


@pytest.fixture(scope="module")
def tag_sync():
    """Load the job script by path; pyspark is stubbed when missing."""
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
    spec = importlib.util.spec_from_file_location("uc_tag_sync_lifecycle_under_test",
                                                  _JOB_DIR / "uc_tag_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    yield module
    for name in added:
        sys.modules.pop(name, None)


@pytest.fixture(scope="module")
def default_configs():
    """The tag_sync_configs default an admin gets in the job configuration dialog."""
    workflow = yaml.safe_load((_JOB_DIR / "uc_tag_sync.yaml").read_text())
    param = next(p for p in workflow["configurable_parameters"]
                 if p["name"] == "tag_sync_configs")
    return param["default"]


def _contract_row(product, status, domain=None, contract="c-1"):
    """A read_contracts_and_links row: one per product publishing the schema object."""
    return {
        "contract_id": contract, "contract_name": f"contract {contract}",
        "contract_version": "1.0", "contract_status": "active",
        "product_name_from_contract": None, "object_id": f"obj-{contract}",
        "schema_name": "orders", "physical_name": TABLE,
        "schema_semantic_iri": None, "schema_semantic_label": None,
        "domain_id": None, "domain_name": None, "contract_additional_domains": None,
        "product_id": f"id-{product}", "product_name": product,
        "product_version": "1.0", "product_status": status,
        "product_domain": domain, "product_additional_domains": None,
    }


def _port_row(product, status, domain=None):
    """A read_output_ports_without_contract row."""
    return {
        "port_id": f"port-{product}", "physical_name": TABLE,
        "product_id": f"id-{product}", "product_name": product,
        "product_version": "1.0", "product_status": status,
        "product_domain": domain, "product_additional_domains": None,
    }


def _desired_from_contract_rows(tag_sync, rows, configs):
    datasets = tag_sync.merge_dataset_tag_infos(
        tag_sync.build_dataset_tag_infos(rows, None, None), []
    )
    assert len(datasets) == 1
    return tag_sync.build_desired_for_dataset(datasets[0], configs)


def _desired_from_port_rows(tag_sync, rows, configs):
    datasets = tag_sync.merge_dataset_tag_infos(
        tag_sync.build_output_port_tag_infos(rows, None, None), []
    )
    assert len(datasets) == 1
    return tag_sync.build_desired_for_dataset(datasets[0], configs)


def test_default_config_tags_the_product_status(tag_sync, default_configs):
    lifecycle = [c for c in default_configs if c["tag_key_format"] == STATUS_KEY]
    assert [(c["entity_type"], c["enabled"], c["tag_value_format"]) for c in lifecycle] == [
        ("data_contract", False, "{CONTRACT.STATUS}"),
        ("data_product", True, "{PRODUCT.STATUS}"),
    ]
    assert {c.get("mapping") for c in lifecycle} == {"lifecycle_status"}
    # The dialog's main card edits the first entry without a mapping id: the name entry.
    first_product = next(c for c in default_configs
                         if c["entity_type"] == "data_product" and not c.get("mapping"))
    assert first_product["tag_key_format"] == NAME_KEY

    desired = _desired_from_contract_rows(
        tag_sync, [_contract_row("orders", "deprecated")], default_configs
    )

    # The contract entry is disabled: the contract's own status ("active") isn't used.
    assert desired[STATUS_KEY] == "deprecated"
    assert desired[NAME_KEY] == "orders"


def test_status_precedence_follows_the_prd_table(tag_sync):
    statuses = ["active", "approved", "under_review", "proposed", "sandbox", "draft",
                "deprecated", "retired"]
    assert [tag_sync.status_precedence(s) for s in statuses] == list(range(1, 9))
    assert tag_sync.status_precedence("Deprecated") == 7
    assert tag_sync.status_precedence("certified") > tag_sync.status_precedence("retired")
    assert tag_sync.status_precedence(None) > tag_sync.status_precedence("retired")


# (first product, its status), (second product, its status) -> deciding product
SHARED_CASES = [
    (("beta", "active"), ("alpha", "deprecated"), ("beta", "active")),
    (("beta", "deprecated"), ("alpha", "deprecated"), ("alpha", "deprecated")),
    (("beta", "deprecated"), ("alpha", "retired"), ("beta", "deprecated")),
    (("beta", "retired"), ("alpha", "retired"), ("alpha", "retired")),
    (("beta", "active"), ("alpha", "active"), ("alpha", "active")),
    (("beta", "draft"), ("alpha", "approved"), ("alpha", "approved")),
]


@pytest.mark.parametrize("first, second, deciding", SHARED_CASES)
@pytest.mark.parametrize("reverse", [False, True])
def test_two_products_on_one_contract_table(tag_sync, default_configs, first, second,
                                            deciding, reverse):
    rows = [_contract_row(name, status, domain=f"domain-{name}")
            for name, status in (first, second)]
    if reverse:
        rows.reverse()
    cfgs = default_configs + [{"entity_type": "data_domain", "enabled": True,
                               "tag_key_format": "x_domain", "tag_value_format": "{DOMAIN.NAME}"}]

    desired = _desired_from_contract_rows(tag_sync, rows, cfgs)

    name, status = deciding
    assert desired[STATUS_KEY] == status
    assert desired[NAME_KEY] == name
    # The contract has no domain: the domain comes from the same (deciding) product.
    assert desired["x_domain"] == f"domain-{name}"


@pytest.mark.parametrize("first, second, deciding", SHARED_CASES)
@pytest.mark.parametrize("reverse", [False, True])
def test_two_products_on_one_table_through_ports_without_contract(
    tag_sync, default_configs, first, second, deciding, reverse
):
    rows = [_port_row(name, status) for name, status in (first, second)]
    if reverse:
        rows.reverse()

    desired = _desired_from_port_rows(tag_sync, rows, default_configs)

    assert (desired[NAME_KEY], desired[STATUS_KEY]) == deciding


@pytest.mark.parametrize("reverse", [False, True])
def test_product_fields_come_from_one_product_across_sources(tag_sync, reverse):
    # Product "beta" reaches the table through a contract, "alpha" through a port
    # without contract; the fields of one product must never mix with the other's.
    contract = tag_sync.build_dataset_tag_infos(
        [_contract_row("beta", "deprecated")], None, None)
    port = tag_sync.build_output_port_tag_infos([_port_row("alpha", "active")], None, None)
    contract[0].product_version, port[0].product_version = "9.9", "1.0"
    inputs = port + contract if reverse else contract + port

    merged = tag_sync.merge_dataset_tag_infos(inputs, [])

    assert len(merged) == 1
    d = merged[0]
    assert (d.product_id, d.product_name, d.product_version, d.product_status) == (
        "id-alpha", "alpha", "1.0", "active")
    # The contract fields still come from the contract.
    assert d.contract_id == "c-1"


@pytest.mark.parametrize("reverse", [False, True])
def test_two_contracts_naming_one_table(tag_sync, reverse):
    cfg = [{"entity_type": "data_contract", "enabled": True,
            "tag_key_format": STATUS_KEY, "tag_value_format": "{CONTRACT.STATUS}"},
           {"entity_type": "data_contract", "enabled": True,
            "tag_key_format": "ontos_contract_name", "tag_value_format": "{CONTRACT.NAME}"}]
    old = _contract_row("p", "active", contract="c-old")
    old["contract_status"] = "deprecated"
    new = _contract_row("p", "active", contract="c-new")
    rows = [new, old] if reverse else [old, new]
    datasets = tag_sync.build_dataset_tag_infos(rows, None, None)
    assert len(datasets) == 2  # one per schema object

    merged = tag_sync.merge_dataset_tag_infos(datasets, [])

    desired = tag_sync.build_desired_for_dataset(merged[0], cfg)
    assert desired == {STATUS_KEY: "active", "ontos_contract_name": "contract c-new"}


@pytest.mark.parametrize("reverse", [False, True])
def test_an_asset_implementing_two_contracts_uses_the_deciding_one(tag_sync, reverse):
    def asset_row(contract, status, product, product_status):
        return {
            "asset_id": "a-1", "asset_name": "orders", "physical_name": TABLE,
            "asset_type_name": "Table", "domain_id": None, "domain_name": None,
            "asset_additional_domains": None,
            "contract_id": contract, "contract_name": contract, "contract_version": "1",
            "contract_status": status, "product_id": product, "product_name": product,
            "product_version": "1", "product_status": product_status,
            "product_domain": None, "product_additional_domains": None,
            "asset_semantic_iri": None, "asset_semantic_label": None,
        }

    rows = [asset_row("c-a", "retired", "p-a", "retired"),
            asset_row("c-b", "active", "p-b", "deprecated")]
    if reverse:
        rows.reverse()

    [d] = tag_sync.build_asset_tag_infos(rows, None, None)

    assert (d.contract_name, d.contract_status) == ("c-b", "active")
    assert (d.product_name, d.product_status) == ("p-b", "deprecated")


# --- Readers against the test database ------------------------------------------


class _ArrayAgg:
    """SQLite stand-in for Postgres array_agg; returns the list as JSON text."""

    def __init__(self):
        self.items = []

    def step(self, value):
        if value is not None:
            self.items.append(value)

    def finalize(self):
        return json.dumps(self.items) if self.items else None


class _SessionEngine:
    """Runs the reader on the test session's connection, so it sees its rows."""

    def __init__(self, session):
        self._session = session

    @contextmanager
    def connect(self):
        yield self._session.connection()


@pytest.fixture
def engine(db_session):
    raw = db_session.connection().connection.driver_connection
    raw.create_aggregate("array_agg", 1, _ArrayAgg)
    return _SessionEngine(db_session)


def _decode(rows):
    return [{**r, "product_additional_domains":
             json.loads(r["product_additional_domains"] or "[]")} for r in rows]


def _product(db, name, status):
    product = DataProductDb(id=f"id-{name}-{uuid.uuid4().hex[:6]}", api_version="v1.0.0",
                            kind="DataProduct", status=status, name=name, version="1.0")
    db.add(product)
    db.flush()
    return product


def _port(db, product, identifier, contract_id=None, asset_type="table"):
    db.add(OutputPortDb(product_id=product.id, name=f"{product.name}-port", version="1",
                        contract_id=contract_id, asset_type=asset_type,
                        asset_identifier=identifier))
    db.flush()


def _domain(db, entity_id, name, primary):
    domain = db.query(DataDomain).filter_by(name=name).first()
    if domain is None:
        domain = DataDomain(name=name, created_by="test@example.com")
        db.add(domain)
        db.flush()
    db.add(EntityDomainAssociationDb(domain_id=domain.id, entity_id=entity_id,
                                     entity_type="data_product", is_primary=primary))
    db.flush()


def test_ports_without_contract_reader_reads_every_product_status(tag_sync, db_session,
                                                                  engine):
    table = f"main.sales.t_{uuid.uuid4().hex[:6]}"
    retired = _product(db_session, "zeta", "retired")
    deprecated = _product(db_session, "beta", "deprecated")
    active = _product(db_session, "alpha", "active")
    for p in (retired, deprecated, active):
        _port(db_session, p, table)
    _domain(db_session, active.id, "Sales", primary=True)
    _domain(db_session, active.id, "Finance", primary=False)
    _domain(db_session, active.id, "Ops", primary=False)
    # Not read: a port with a contract (read through it), a non-table port, no identifier.
    other = _product(db_session, "other", "active")
    _port(db_session, other, table, contract_id="c-1")
    _port(db_session, other, "/Workspace/notebook", asset_type="notebook")
    _port(db_session, other, None)

    rows = [r for r in _decode(tag_sync.read_output_ports_without_contract(engine))
            if r["physical_name"] == table]

    assert [(r["product_name"], r["product_status"]) for r in rows] == [
        ("alpha", "active"), ("beta", "deprecated"), ("zeta", "retired")]
    assert rows[0]["product_domain"] == "Sales"
    assert rows[0]["product_additional_domains"] == ["Finance", "Ops"]
    [d] = tag_sync.merge_dataset_tag_infos(
        tag_sync.build_output_port_tag_infos(rows, None, None), [])
    assert (d.product_name, d.product_status, d.domain_name) == ("alpha", "active", "Sales")
    assert d.additional_domain_names == ["Finance", "Ops"]


def test_contract_reader_rows_build_the_deciding_product(tag_sync, db_session, engine,
                                                         default_configs):
    table = f"main.sales.t_{uuid.uuid4().hex[:6]}"
    contract = DataContractDb(id=f"c-{uuid.uuid4().hex[:6]}", name="orders",
                              version="1.0", status="active")
    db_session.add(contract)
    db_session.flush()
    db_session.add(SchemaObjectDb(contract_id=contract.id, name="orders",
                                  physical_name=table))
    for name, status in (("alpha", "deprecated"), ("beta", "active")):
        _port(db_session, _product(db_session, name, status), table, contract_id=contract.id)

    rows = [r for r in _decode(tag_sync.read_contracts_and_links(engine))
            if r["physical_name"] == table]

    assert len(rows) == 2
    desired = _desired_from_contract_rows(tag_sync, rows, default_configs)
    assert (desired[STATUS_KEY], desired[NAME_KEY]) == ("active", "beta")


# --- Retries of tag statements -----------------------------------------------------


class _FlakySpark:
    def __init__(self, errors):
        self.errors = list(errors)
        self.statements = []

    def sql(self, statement):
        self.statements.append(statement)
        if self.errors:
            raise self.errors.pop(0)


@pytest.fixture
def sleeps(tag_sync, monkeypatch):
    calls = []
    monkeypatch.setattr(tag_sync, "TAG_SQL_SLEEP", calls.append)
    return calls


def test_a_transient_error_is_retried_with_backoff(tag_sync, sleeps):
    spark = _FlakySpark([RuntimeError("Connection reset"), RuntimeError("503 Unavailable")])

    tag_sync.assign_tag(spark, "TABLE", TABLE, STATUS_KEY, "deprecated")

    assert len(spark.statements) == 3
    assert spark.statements[0] == (
        f"ALTER TABLE {TABLE} SET TAGS ('{STATUS_KEY}' = 'deprecated')")
    assert sleeps == [2.0, 10.0]


def test_a_transient_error_is_raised_after_the_last_attempt(tag_sync, sleeps):
    spark = _FlakySpark([RuntimeError("timeout")] * 3)

    with pytest.raises(RuntimeError, match="timeout"):
        tag_sync.unassign_tag(spark, "TABLE", TABLE, STATUS_KEY)

    assert len(spark.statements) == 3
    assert sleeps == [2.0, 10.0]


@pytest.mark.parametrize("message", [
    "[PERMISSION_DENIED] User does not have APPLY TAG on Table 'main.sales.orders'.",
    "[INSUFFICIENT_PERMISSIONS] Insufficient privileges",
    "[TABLE_OR_VIEW_NOT_FOUND] The table or view `main`.`sales`.`orders` cannot be found.",
    "[SCHEMA_NOT_FOUND] The schema `main`.`sales` cannot be found.",
])
def test_permission_and_missing_table_errors_are_not_retried(tag_sync, sleeps, message):
    spark = _FlakySpark([RuntimeError(message)])

    with pytest.raises(RuntimeError):
        tag_sync.assign_tag(spark, "TABLE", TABLE, STATUS_KEY, "active")

    assert len(spark.statements) == 1
    assert sleeps == []


def test_the_spark_error_class_is_checked_too(tag_sync, sleeps):
    class AnalysisError(Exception):
        def getErrorClass(self):
            return "TABLE_OR_VIEW_NOT_FOUND"

    spark = _FlakySpark([AnalysisError("cannot be found")])

    with pytest.raises(AnalysisError):
        tag_sync.unassign_tag(spark, "TABLE", TABLE, STATUS_KEY)

    assert len(spark.statements) == 1


def test_reconcile_reports_a_tag_that_still_fails(tag_sync, sleeps, monkeypatch):
    monkeypatch.setattr(tag_sync, "get_existing_prefixed_tags", lambda *_a: {})
    monkeypatch.setattr(tag_sync, "ensure_tag_key", lambda *_a: None)
    spark = _FlakySpark([RuntimeError("[PERMISSION_DENIED] no APPLY TAG")])

    updated, removed, errors = tag_sync.reconcile_tags(
        None, spark, "TABLE", TABLE, {STATUS_KEY: "retired"}, "ontos_")

    assert (updated, removed, len(errors)) == (0, 0, 1)
    assert STATUS_KEY in errors[0]
