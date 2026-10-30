"""Live Unity Catalog round trip for Access Policies (opt-in, real workspace).

Compile → release review → Direct delivery through the real GrantManager → the grants are on
the platform → reconcile is in sync → out-of-band changes are reported as drift → revocation.

Runs only when ``ONTOS_LIVE_UC_PROFILE`` names a Databricks CLI profile. The catalog
(``ONTOS_LIVE_UC_CATALOG``, default ``ontos-odrl-test``) must exist with the schemas ``sales``,
``finance`` and synthetic tables ``sales.orders`` / ``finance.invoices``; grants go to the
built-in ``account users`` group and are revoked again at the end::

    ONTOS_LIVE_UC_PROFILE=e2-demo-field-eng hatch -e dev run pytest -q -p no:cacheprovider --no-cov \\
        backend/src/tests/integration/test_access_policies_live_uc.py
"""
import os
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session

from src.controller.access_policies_manager import KIND_POLICY, KIND_TARGET, AccessPoliciesManager
from src.controller.access_policy_releases_manager import PolicyReleaseManager
from src.controller.delivery_service import DeliveryMode, DeliveryService
from src.models.access_policies import AccessPolicyCreate, TargetCreate

PROFILE = os.environ.get("ONTOS_LIVE_UC_PROFILE")
CATALOG = os.environ.get("ONTOS_LIVE_UC_CATALOG", "ontos-odrl-test")
GROUP = "account users"
AUTHOR, APPROVER = "author@example.com", "approver@example.com"

pytestmark = pytest.mark.skipif(not PROFILE, reason="set ONTOS_LIVE_UC_PROFILE to run against a real workspace")


class Delivery(DeliveryService):
    def __init__(self, grants):
        super().__init__(settings=SimpleNamespace(DELIVERY_DIRECT_DRY_RUN=False), grant_manager=grants)

    def get_active_modes(self):
        return [DeliveryMode.DIRECT]


@pytest.fixture
def ws(monkeypatch):
    from databricks.sdk import WorkspaceClient
    # conftest points DATABRICKS_HOST etc. at a fake workspace; the SDK would prefer it over the profile.
    for name in [n for n in os.environ if n.startswith("DATABRICKS_")]:
        monkeypatch.delenv(name)
    return WorkspaceClient(profile=PROFILE)


CATALOG_T, SCHEMA_T, TABLE_T = "catalog", "schema", "table"  # the grants API takes the plain names


def _securables():
    return [(CATALOG_T, CATALOG), (SCHEMA_T, f"{CATALOG}.sales"), (SCHEMA_T, f"{CATALOG}.finance"),
            (TABLE_T, f"{CATALOG}.finance.invoices"), (TABLE_T, f"{CATALOG}.sales.orders")]


def _privileges(ws, securable_type, name):
    out = set()
    for a in ws.grants.get(securable_type, name).privilege_assignments or []:
        if (a.principal or "").lower() == GROUP:
            out |= {p.value if hasattr(p, "value") else str(p) for p in a.privileges or []}
    return out


def _clean(ws):
    """Revoke whatever the group holds on the test securables (a clean slate before and after)."""
    from databricks.sdk.service.catalog import PermissionsChange, Privilege
    for securable_type, name in _securables():
        held = _privileges(ws, securable_type, name)
        if held:
            ws.grants.update(securable_type, name, changes=[
                PermissionsChange(principal=GROUP, remove=[Privilege(p) for p in sorted(held)])])


def _activate(policies, db, kind, row):
    policies.change_status(db, kind, row.id, "under_review", AUTHOR)
    policies.change_status(db, kind, row.id, "approved", APPROVER)
    return policies.change_status(db, kind, row.id, "active", AUTHOR)


def test_live_direct_delivery_reconcile_and_drift(db_session: Session, ws):
    from databricks.sdk.service.catalog import PermissionsChange, Privilege

    from src.controller.grant_manager import GrantManager

    policies = AccessPoliciesManager(attribute_sources=[])
    rm = PolicyReleaseManager(policies)
    grants = GrantManager(ws_client=ws)
    _clean(ws)
    try:
        rules = {"permission": [
            {"target": f"uc:{CATALOG}.sales", "action": "read", "assignee": f"group:{GROUP}"},
            {"target": f"uc:{CATALOG}.finance.invoices", "action": "modify", "assignee": f"group:{GROUP}",
             "constraint": [{"leftOperand": "dateTime", "operator": "lteq", "rightOperand": "2099-12-31T23:59:59Z"}]},
        ]}
        _activate(policies, db_session, KIND_POLICY, policies.create(
            db_session, KIND_POLICY, AccessPolicyCreate(name="Live UC test", rules=rules), AUTHOR))
        _activate(policies, db_session, KIND_TARGET, policies.create(db_session, KIND_TARGET, TargetCreate(
            name="Live UC", key="uc", scope=[CATALOG], delivery_modes=["direct"]), AUTHOR))

        compiled = rm.compile(db_session, "uc")
        assert not compiled["has_errors"], compiled["issues"]
        release = rm.create_release(db_session, "uc", AUTHOR)
        rm.change_status(db_session, release.id, "under_review", AUTHOR)
        rm.change_status(db_session, release.id, "approved", APPROVER)
        out = rm.deliver(db_session, release.id, AUTHOR, Delivery(grants))
        assert out.status == "applied", (out.status, out.delivery_results)  # Direct confirms the apply

        # What Ontos delivered is on the platform.
        assert "USE_CATALOG" in _privileges(ws, CATALOG_T, CATALOG)
        assert {"SELECT", "USE_SCHEMA"} <= _privileges(ws, SCHEMA_T, f"{CATALOG}.sales")
        assert "MODIFY" in _privileges(ws, TABLE_T, f"{CATALOG}.finance.invoices")
        report = rm.reconcile(db_session, "uc", grants, AUTHOR)
        assert report.status == "in_sync", (report.status, report.counts, report.findings)

        # Out-of-band: someone revokes a tracked grant and adds one Ontos doesn't manage.
        ws.grants.update(SCHEMA_T, f"{CATALOG}.sales",
                         changes=[PermissionsChange(principal=GROUP, remove=[Privilege.SELECT], add=[Privilege.MODIFY])])
        report = rm.reconcile(db_session, "uc", grants, AUTHOR)
        assert report.status == "drift", (report.status, report.counts)
        assert report.counts["missing"] >= 1 and report.counts["unmanaged"] >= 1, report.counts
        # Report only: nothing was changed back.
        assert "SELECT" not in _privileges(ws, SCHEMA_T, f"{CATALOG}.sales")
    finally:
        _clean(ws)
