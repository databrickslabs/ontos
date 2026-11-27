"""erwin physical model → ODCS drafts, UC resolution and drift (PRD #1718, slice 3 #1721)."""
from pathlib import Path

import pytest

from src.common.odcs_validation import ODCSValidationError, validate_odcs_contract
from src.model_import.erwin.map_contracts import (
    CP_FINGERPRINT,
    CP_GROUP_KEY,
    SEMANTIC_ASSIGNMENT_TYPE,
    group_entities,
    map_contracts,
)
from src.model_import.erwin.match_uc import UcColumn, candidate_fqn, table_drift
from src.model_import.erwin.parse import parse_erwin
from src.model_import.erwin.types import (
    databricks_type,
    databricks_type_for,
    normalize_dbms,
    odcs_logical_type,
    same_type,
    type_family,
)
from src.models.model_import import CatalogMapping, ModelImportOptions, UdpMapping

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "erwin" / "sales_dw_standard.xml"


def _id(name):
    return "{" + name + "}+00000000"


@pytest.fixture(scope="module")
def model():
    with FIXTURE.open("rb") as f:
        return parse_erwin(f)


def _cp(obj, name):
    return next((c["value"] for c in obj.get("customProperties", []) if c["property"] == name), None)


def _contract(drafts, label):
    return next(d for d in drafts if d.group_label == label)


def _table(draft, name):
    return next(o for o in draft.odcs["schema"] if o["name"] == name)


def _col(table, name):
    return next(p for p in table["properties"] if p["name"] == name)


class TestTypes:
    @pytest.mark.parametrize("t,fam", [
        ("NUMBER(10)", "integer"), ("NUMBER(12,2)", "decimal"), ("NUMBER", "decimal"),
        ("NUMBER(12,0)", "integer"), ("VARCHAR2(100)", "string"), ("DATE", "date"),
        ("TIMESTAMP(6) WITH TIME ZONE", "timestamp"), ("BIT", "boolean"), ("RAW(16)", "binary"),
        ("FOO", None), (None, None),
    ])
    def test_family(self, t, fam):
        assert type_family(t) == fam

    @pytest.mark.parametrize("t,dbx", [
        ("NUMBER(4)", "SMALLINT"), ("NUMBER(9)", "INT"), ("NUMBER(10)", "BIGINT"), ("NUMBER(20)", "DECIMAL(20,0)"),
        ("NUMBER(12,2)", "DECIMAL(12,2)"), ("VARCHAR2(100)", "STRING"), ("DATETIME2", "TIMESTAMP_NTZ"),
        ("MONEY", "DECIMAL(19,4)"), ("FLOAT", "DOUBLE"), ("REAL", "FLOAT"), ("BLOB", "BINARY"),
    ])
    def test_databricks_type(self, t, dbx):
        assert databricks_type(t) == dbx

    def test_oracle_date_is_a_timestamp(self):
        assert databricks_type_for("DATE", "oracle") == "TIMESTAMP"
        assert databricks_type_for("DATE", "sqlserver") == "DATE"

    def test_odcs_logical_type(self):
        assert odcs_logical_type("DECIMAL(12,2)") == "number"
        assert odcs_logical_type(None, "NUMBER(10)") == "integer"
        assert odcs_logical_type("XYZ") == "string"

    @pytest.mark.parametrize("modeled,actual,dbms,same", [
        ("NUMBER(10)", "bigint", "oracle", True), ("NUMBER(10)", "int", "oracle", True),
        ("VARCHAR2(100)", "string", "oracle", True), ("NUMBER(12,2)", "decimal(12,2)", "oracle", True),
        ("NUMBER(12,2)", "decimal(10,2)", "oracle", False), ("DATE", "timestamp", "oracle", True),
        ("VARCHAR2(10)", "int", "oracle", False), ("DATE", "date", "oracle", False),
    ])
    def test_same_type(self, modeled, actual, dbms, same):
        assert same_type(modeled, actual, dbms) is same

    @pytest.mark.parametrize("name,key", [
        ("Oracle", "oracle"), ("SQL Server 2019", "sqlserver"), ("Databricks", "databricks"),
        ("1075859016", "other"), (None, "other"),
    ])
    def test_normalize_dbms(self, name, key):
        assert normalize_dbms(name) == key


class TestGrouping:
    def test_subject_area_first_wins(self, model):
        groups = {label: [e.name for e in ents] for _, label, ents in group_entities(model, ModelImportOptions())}
        assert "Customer" in groups["Sales"] and "Customer" not in groups["Party"]
        assert "v_customer_orders" in groups["Sales"]

    def test_subject_area_order_follows_selection(self, model):
        opts = ModelImportOptions(subject_area_ids=[_id("SA-PARTY"), _id("SA-SALES")])
        groups = {label: [e.name for e in ents] for _, label, ents in group_entities(model, opts)}
        assert "Customer" in groups["Party"]

    def test_schema_table_and_model_grouping(self, model):
        by_schema = {label for _, label, _ in group_entities(model, ModelImportOptions(contract_grouping="schema"))}
        assert by_schema == {"SALES", "MDM"}
        per_table = group_entities(model, ModelImportOptions(contract_grouping="table"))
        assert len(per_table) == 8
        [(key, _, ents)] = group_entities(model, ModelImportOptions(contract_grouping="model"))
        assert key == "model" and len(ents) == 8


class TestContracts:
    @pytest.fixture
    def drafts(self, model):
        iris = {_id("E-CUST"): "urn:x/customer", _id("A-CUST-ID"): "urn:x/customer.customer-id",
                _id("A-CUST-EMAIL"): "urn:x/customer.email-address"}
        return map_contracts(model, ModelImportOptions(), iris, {_id("E-CUST"): "main.sales.customer"})

    def test_contract_level(self, drafts):
        sales = _contract(drafts, "Sales")
        assert sales.name == "Sales DW – Sales"
        assert sales.odcs["status"] == "draft"
        assert sales.odcs["apiVersion"] == "v3.1.0"
        assert sales.odcs["description"]["purpose"].startswith("Orders, order lines")
        assert _cp(sales.odcs, CP_GROUP_KEY) == f"sa:{_id('SA-SALES')}"
        assert _cp(sales.odcs, CP_FINGERPRINT) == sales.fingerprint

    def test_valid_odcs(self, drafts):
        for d in drafts:
            try:
                validate_odcs_contract(d.odcs, strict=True)
            except ODCSValidationError as e:  # pragma: no cover - shows the errors
                pytest.fail(f"{d.name}: {e.message} {e.validation_errors[:5]}")

    def test_table_and_columns(self, drafts):
        cust = _table(_contract(drafts, "Sales"), "CUSTOMER")
        assert cust["physicalName"] == "main.sales.customer"
        assert cust["businessName"] == "Customer"
        assert cust["physicalType"] == "table"
        assert cust["authoritativeDefinitions"] == [{"type": SEMANTIC_ASSIGNMENT_TYPE, "url": "urn:x/customer"}]
        cid = _col(cust, "CUSTOMER_ID")
        assert cid["primaryKey"] is True and cid["primaryKeyPosition"] == 1 and cid["required"] is True
        assert cid["logicalType"] == "integer" and cid["physicalType"] == "NUMBER(10)"
        email = _col(cust, "EMAIL_ADDRESS")
        assert email["unique"] is True and email["required"] is False
        assert _cp(email, "erwin.udp.Classification") == "PII"
        assert _cp(cust, "erwin.udp.Data Owner") == "Sales Operations"
        assert _cp(_col(cust, "CUSTOMER_SINCE"), "erwin.default") == "SYSDATE"

    def test_unresolved_table_has_no_physical_name(self, drafts):
        assert "physicalName" not in _table(_contract(drafts, "Sales"), "ORDERS")

    def test_fk_column_links_to_parent_concept(self, drafts):
        orders = _table(_contract(drafts, "Sales"), "ORDERS")
        assert _col(orders, "CUSTOMER_ID")["authoritativeDefinitions"][0]["url"] == "urn:x/customer.customer-id"

    def test_composite_primary_key_and_fks(self, drafts):
        line = _table(_contract(drafts, "Sales"), "ORDER_LINE")
        assert [(p["name"], p.get("primaryKeyPosition")) for p in line["properties"] if p.get("primaryKey")] == [
            ("ORDER_ID", 1), ("LINE_NUMBER", 2),
        ]
        rels = {r["from"]: r for r in line["relationships"]}
        assert rels["ORDER_LINE.ORDER_ID"]["to"] == "ORDERS.ORDER_ID"
        assert rels["ORDER_LINE.PRODUCT_ID"]["to"] == "PRODUCT.PRODUCT_ID"
        # logical-only attribute is not a column
        assert all(p["name"] != "pricing_rationale" for p in line["properties"])

    def test_cross_contract_fk_is_kept_and_warned(self, drafts):
        sales = _contract(drafts, "Sales")
        cust = _table(sales, "CUSTOMER")
        assert cust["relationships"][0]["to"] == "PARTY.PARTY_ID"
        assert any("another contract" in w for w in sales.warnings)

    def test_view(self, drafts):
        view = _table(_contract(drafts, "Sales"), "V_CUSTOMER_ORDERS")
        assert view["physicalType"] == "view"
        assert _cp(view, "erwin.viewSql").startswith("SELECT")

    def test_domain_values(self, drafts):
        status = _col(_table(_contract(drafts, "Sales"), "ORDERS"), "ORDER_STATUS")
        assert _cp(status, "erwin.domain") == "Order Status"
        assert _cp(status, "erwin.validValues") == ["NEW", "SHIPPED", "CANCELLED"]

    def test_udp_mapping(self, model):
        opts = ModelImportOptions(udp_mappings=[
            UdpMapping(udp="classification", target="classification"),
            UdpMapping(udp="Critical Data Element", target="critical_data_element"),
            UdpMapping(udp="Data Owner", target="tag"),
        ])
        sales = _contract(map_contracts(model, opts, {}, {}), "Sales")
        cust = _table(sales, "CUSTOMER")
        email = _col(cust, "EMAIL_ADDRESS")
        assert email["classification"] == "PII"
        assert email["criticalDataElement"] is True
        assert cust["tags"] == ["Data Owner:Sales Operations"]

    def test_migration_mode(self, model):
        sales = _contract(map_contracts(model, ModelImportOptions(migration_mode=True), {}, {}), "Sales")
        orders = _table(sales, "ORDERS")
        assert _col(orders, "TOTAL_AMOUNT")["physicalType"] == "DECIMAL(12,2)"
        assert _col(orders, "ORDER_DATE")["physicalType"] == "TIMESTAMP"
        assert _cp(_col(orders, "ORDER_DATE"), "erwin.sourcePhysicalType") == "DATE"
        assert any("Oracle DATE" in w for w in sales.warnings)

    def test_fingerprint_ignores_run_id(self, model):
        a = map_contracts(model, ModelImportOptions(), {}, {}, run_id="r1")
        b = map_contracts(model, ModelImportOptions(), {}, {}, run_id="r2")
        assert [d.fingerprint for d in a] == [d.fingerprint for d in b]

    def test_domain_assignment(self, model):
        opts = ModelImportOptions(domain_by_group={f"sa:{_id('SA-SALES')}": "dom-1"})
        assert _cp(_contract(map_contracts(model, opts, {}, {}), "Sales").odcs, "ontosDomainId") == ["dom-1"]


class TestUcMatching:
    def test_candidate_fqn(self, model):
        cust = model.entity(_id("E-CUST"))
        party = model.entity(_id("E-PARTY"))
        opts = ModelImportOptions(catalog_mappings=[
            CatalogMapping(source="sales", target="Main.Sales"), CatalogMapping(source="*", target="main.other"),
        ])
        assert candidate_fqn(cust, opts) == "main.sales.customer"
        assert candidate_fqn(party, opts) == "main.other.party"
        assert candidate_fqn(cust, ModelImportOptions()) is None
        override = ModelImportOptions(table_overrides={_id("E-CUST"): "x.y.clients"})
        assert candidate_fqn(cust, override) == "x.y.clients"

    def test_drift(self, model):
        cust = model.entity(_id("E-CUST"))
        uc = [
            UcColumn("customer_id", "bigint", False),
            UcColumn("customer_name", "int", False),
            UcColumn("email_address", "string", False),
            UcColumn("loyalty_tier", "string", True),
        ]
        d = table_drift(cust, uc, "oracle")
        assert set(d.missing_in_uc) == {"CUSTOMER_SINCE", "PARTY_ID"}
        assert d.extra_in_uc == ["loyalty_tier"]
        assert [m["column"] for m in d.type_mismatches] == ["CUSTOMER_NAME"]
        assert d.nullability_mismatches == [
            {"column": "EMAIL_ADDRESS", "modeled_required": False, "uc_nullable": False},
        ]

    def test_clean_drift(self, model):
        prod = model.entity(_id("E-PROD"))
        d = table_drift(prod, [UcColumn("PRODUCT_ID", "bigint", False), UcColumn("PRODUCT_NAME", "string", False)],
                        "oracle")
        assert d.is_clean()
