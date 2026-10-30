"""The Access Policies demo example end to end: audiences + asset collections + policies + target →
check access per persona → compile → release review → delivery (Manual only, as the target allows)."""
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from src.controller.access_policies_manager import AccessPoliciesManager, AccessPolicyError
from src.controller.access_policy_releases_manager import PolicyReleaseManager
from src.controller.delivery_service import DeliveryMode, DeliveryService
from src.db_models.access_policies import (
    AccessAssetCollectionDb,
    AccessAudienceDb,
    AccessPolicyDb,
    AccessPolicyIndexDb,
    AccessTargetDb,
)
from src.models.access_policies import CheckAccessRequest
from src.utils import demo_access_policies as demo

MODELS = {"access_audiences": AccessAudienceDb, "access_asset_collections": AccessAssetCollectionDb,
          "access_policies": AccessPolicyDb, "access_policy_index": AccessPolicyIndexDb,
          "access_targets": AccessTargetDb}


class Delivery(DeliveryService):
    def __init__(self, modes):
        super().__init__(settings=SimpleNamespace(DELIVERY_DIRECT_DRY_RUN=False), grant_manager=None)
        self.modes = modes

    def get_active_modes(self):
        return list(self.modes)


@pytest.fixture
def demo_db(db_session: Session):
    for table, row in demo.rows():
        db_session.add(MODELS[table](**row))
    db_session.flush()
    return db_session


@pytest.fixture
def policies():
    return AccessPoliciesManager(attribute_sources=[])


def _check(policies, db, principal, action, asset, groups=(), attributes=None):
    return policies.check_access(db, CheckAccessRequest(
        principal=principal, action=action, asset=asset, principal_groups=list(groups),
        principal_attributes=attributes or {}, resolve_business_roles=False))["verdict"]


def test_pack_block_is_generated_from_the_yaml():
    assert demo.pack_block() == demo.render_sql(), "run: python -m src.utils.demo_access_policies --write"


def test_generated_block_is_cleared_with_the_pack():
    from src.utils.demo_data_sql import parse_demo_inserts
    tables = {i.table for i in parse_demo_inserts(demo.render_sql())}
    assert tables == set(MODELS)


def test_every_example_policy_validates(demo_db: Session, policies):
    for p in demo_db.query(AccessPolicyDb).all():
        assert policies.activation_problems(demo_db, "policy", p) == [], p.name


def test_personas_get_what_their_audience_allows(demo_db: Session, policies):
    sales = "uc:demo_enterprise.sales.orders"
    assert _check(policies, demo_db, "alice.chen@example.com", "read", sales) == "allow"
    assert _check(policies, demo_db, "bob@example.com", "read", sales, ["group:sales-analysts"]) == "allow"
    # Sales analysts never read HR records (prohibition wins).
    assert _check(policies, demo_db, "alice.chen@example.com", "read", "uc:demo_enterprise.hr.employees") == "deny"
    assert _check(policies, demo_db, "fin@example.com", "modify", "uc:demo_enterprise.finance.invoices",
                  ["group:finance"]) == "allow"
    # HR read waits for the HR terms to be accepted (duty).
    assert _check(policies, demo_db, "hr@example.com", "read", "uc:demo_enterprise.hr.employees",
                  ["group:hr-partners"]) == "conditional"
    # Dynamic audience: whoever holds the Data Steward business role.
    assert _check(policies, demo_db, "iris.steward@example.com", "ontos:browse", "uc:demo_enterprise.finance",
                  attributes={"ontos:businessRole": ["Data Steward"]}) == "allow"
    # The draft policy grants nothing yet.
    assert _check(policies, demo_db, "ds@example.com", "read", "uc:demo_analytics.data_science.v_customer_features",
                  ["group:data-science"]) != "allow"


def test_compile_release_and_deliver_through_the_demo_target(demo_db: Session, policies):
    rm = PolicyReleaseManager(policies)
    assert [t.key for t in rm.targets(demo_db)] == ["uc"] and rm.resolve(demo_db, "uc").entity_id
    compiled = rm.compile(demo_db, "uc")
    assert not compiled["has_errors"], [i for i in compiled["issues"] if i["severity"] == "error"]
    grants = {(g["principal"], g["securable_name"], g["privilege"]) for g in compiled["plan"]["grants"]}
    assert ("sales-analysts", "demo_enterprise.sales", "SELECT") in grants
    assert ("alice.chen@example.com", "demo_analytics.reporting.v_sales_summary", "SELECT") in grants
    assert ("finance", "demo_enterprise.finance", "MODIFY") in grants
    assert not any(n.startswith("demo_enterprise.hr") for _, n, _ in grants)  # gated by the duty
    finance = [g for g in compiled["plan"]["grants"] if g["principal"] == "finance" and g["privilege"] == "MODIFY"]
    assert finance[0]["expires_at"].startswith("2027-12-31")
    gated = {g["source"]["policy_name"] for g in compiled["plan"]["gated"] if g.get("source")}
    assert {"HR records read", "Prepared sales — terms of use"} <= gated

    release = rm.create_release(demo_db, "uc", "author@demo")
    rm.change_status(demo_db, release.id, "under_review", "author@demo")
    rm.change_status(demo_db, release.id, "approved", "approver@demo")
    with pytest.raises(AccessPolicyError):  # the demo target only allows Manual / Indirect
        rm.deliver(demo_db, release.id, "admin@demo", Delivery([DeliveryMode.DIRECT]), modes=["direct"])
    out = rm.deliver(demo_db, release.id, "admin@demo", Delivery([DeliveryMode.DIRECT, DeliveryMode.MANUAL]))
    assert out.delivery_modes == ["manual"]
    sales = [s for s in out.changes["sql"] if s.startswith("GRANT ") and " ON SCHEMA `demo_enterprise`.`sales` TO `sales-analysts`" in s]
    assert sales and "SELECT" in sales[0], out.changes["sql"]
