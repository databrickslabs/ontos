"""Integration tests: compliance templates bound to table and view assets.

Covers the asset host checks on the per-entity template routes (asset must be a
table or view; read and write follow the asset routes' rules) and the
reconcile call on an asset edit.
"""
import json
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from src.app import app
from src.common.authorization import get_user_details_from_sdk
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.compliance_templates import ComplianceTemplateValueDb
from src.db_models.settings import AppRoleDb
from src.models.users import UserInfo

BASE = "/api/compliance-templates"


@pytest.fixture(autouse=True)
def _noop_audit_manager():
    """The asset update route logs through ``app.state.audit_manager``."""

    class _NoopAudit:
        def log_action(self, **kwargs):
            return None

        def log_action_background(self, **kwargs):
            return None

    previous = getattr(app.state, "audit_manager", None)
    app.state.audit_manager = _NoopAudit()
    try:
        yield
    finally:
        if previous is not None:
            app.state.audit_manager = previous
        else:
            try:
                delattr(app.state, "audit_manager")
            except AttributeError:
                pass


def _asset(db: Session, type_name: str) -> AssetDb:
    asset_type = db.query(AssetTypeDb).filter(AssetTypeDb.name == type_name).first()
    if asset_type is None:
        asset_type = AssetTypeDb(id=uuid.uuid4(), name=type_name)
        db.add(asset_type)
        db.flush()
    asset = AssetDb(
        id=uuid.uuid4(),
        name=f"{type_name.lower()}_{uuid.uuid4().hex[:6]}",
        asset_type_id=asset_type.id,
        status="active",
    )
    db.add(asset)
    db.commit()
    return asset


def _active_asset_template(client: TestClient) -> dict:
    # SQLite ignores the partial (active-only) unique index, so drop leftovers.
    for old in client.get(BASE, params={"entity_type": "asset"}).json():
        assert client.delete(f"{BASE}/{old['id']}").status_code == 204
    resp = client.post(BASE, json={
        "name": "Table documentation",
        "entity_type": "asset",
        "fields": [
            {
                "key": "limitations", "label": "Limitations",
                "reference_id": "limitations", "is_mandatory": True,
            },
            {
                "key": "intended_use", "label": "Intended use",
                "reference_id": "intended_use", "default_value": "analytics",
                "field_order": 1,
            },
        ],
    })
    assert resp.status_code == 201, resp.text
    template = resp.json()
    resp = client.post(f"{BASE}/{template['id']}/activate")
    assert resp.status_code == 200, resp.text
    return template


def _field_id(template: dict, reference_id: str) -> str:
    return next(f["id"] for f in template["fields"] if f["reference_id"] == reference_id)


@pytest.fixture
def as_group(client: TestClient, db_session: Session):
    """Switch the request user to a fresh group whose only role grants ``permissions``."""
    previous = app.dependency_overrides.get(get_user_details_from_sdk)

    def _switch(permissions: dict) -> TestClient:
        group = f"ct-assets-{uuid.uuid4().hex[:8]}"
        db_session.add(AppRoleDb(
            id=str(uuid.uuid4()),
            name=f"Compliance asset test {group}",
            description="test role",
            feature_permissions=json.dumps(permissions),
            assigned_groups=json.dumps([group]),
            home_sections="[]",
            approval_privileges="{}",
            is_admin=False,
        ))
        db_session.commit()

        async def _override():
            return UserInfo(
                username=group, email=f"{group}@example.com", user=group,
                ip="127.0.0.1", groups=[group],
            )

        app.dependency_overrides[get_user_details_from_sdk] = _override
        return client

    try:
        yield _switch
    finally:
        if previous is not None:
            app.dependency_overrides[get_user_details_from_sdk] = previous
        else:
            app.dependency_overrides.pop(get_user_details_from_sdk, None)


class TestAssetTemplateRoutes:

    def test_table_asset_fill_and_completeness(self, client: TestClient, db_session: Session):
        template = _active_asset_template(client)
        table = _asset(db_session, "Table")
        entity = f"{BASE}/entities/asset/{table.id}"

        resp = client.get(f"{entity}/completeness")
        assert resp.status_code == 200, resp.text
        assert resp.json()["applicable"] is True
        assert resp.json()["passed"] is False
        assert resp.json()["missing"] == ["Limitations"]

        resp = client.put(f"{entity}/values", json={"values": [
            {"field_id": _field_id(template, "limitations"), "value": "Daily refresh only"},
        ]})
        assert resp.status_code == 200, resp.text
        values = {v["reference_id"]: v["value"] for v in resp.json()["values"]}
        assert values == {"limitations": "Daily refresh only"}

        resp = client.get(f"{entity}/completeness")
        assert resp.json()["passed"] is True

    def test_view_asset_is_supported(self, client: TestClient, db_session: Session):
        _active_asset_template(client)
        view = _asset(db_session, "View")
        resp = client.get(f"{BASE}/entities/asset/{view.id}")
        assert resp.status_code == 200, resp.text
        assert resp.json()["template"]["entity_type"] == "asset"

    def test_other_asset_type_is_refused(self, client: TestClient, db_session: Session):
        template = _active_asset_template(client)
        field_id = _field_id(template, "limitations")
        calls = (
            lambda entity: client.get(entity),
            lambda entity: client.get(f"{entity}/completeness"),
            lambda entity: client.put(f"{entity}/values", json={"values": [
                {"field_id": field_id, "value": "x"},
            ]}),
        )
        for call in calls:
            # An error answer rolls the test session back: one asset per call.
            dashboard_id = str(_asset(db_session, "Dashboard").id)
            resp = call(f"{BASE}/entities/asset/{dashboard_id}")
            assert resp.status_code == 422, resp.text
            detail = resp.json()["detail"]
            assert detail["code"] == "compliance_template_asset_type_unsupported"
            assert detail["params"] == {"assetType": "Dashboard"}

    def test_unknown_asset_is_not_found(self, client: TestClient):
        for asset_id in (str(uuid.uuid4()), "not-a-uuid"):
            resp = client.get(f"{BASE}/entities/asset/{asset_id}/completeness")
            assert resp.status_code == 404, resp.text
            assert resp.json()["detail"]["code"] == "compliance_template_asset_not_found"

    def test_reader_without_asset_access_is_refused(
        self, client: TestClient, db_session: Session, as_group
    ):
        _active_asset_template(client)
        table = _asset(db_session, "Table")
        reader = as_group({"compliance-template-values": "Read-only", "assets": "Read-only"})
        resp = reader.get(f"{BASE}/entities/asset/{table.id}")
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "compliance_template_asset_read_forbidden"

    def test_asset_editor_reads_but_values_reader_cannot_write(
        self, client: TestClient, db_session: Session, as_group
    ):
        template = _active_asset_template(client)
        table = _asset(db_session, "Table")
        user = as_group({"compliance-template-values": "Read-only", "assets": "Read/Write"})
        entity = f"{BASE}/entities/asset/{table.id}"
        assert user.get(entity).status_code == 200
        resp = user.put(f"{entity}/values", json={"values": [
            {"field_id": _field_id(template, "limitations"), "value": "x"},
        ]})
        assert resp.status_code == 403, resp.text

    def test_write_needs_asset_edit_rights(
        self, client: TestClient, db_session: Session, as_group
    ):
        template = _active_asset_template(client)
        table_id = str(_asset(db_session, "Table").id)
        user = as_group({"compliance-template-values": "Read/Write", "assets": "Read-only"})
        resp = user.put(f"{BASE}/entities/asset/{table_id}/values", json={"values": [
            {"field_id": _field_id(template, "limitations"), "value": "x"},
        ]})
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"]["code"] == "compliance_template_asset_write_forbidden"
        stored = db_session.query(ComplianceTemplateValueDb).filter_by(
            entity_type="asset", entity_id=table_id
        ).count()
        assert stored == 0

    def test_data_product_values_unchanged(self, client: TestClient):
        """Non-asset entity types keep #731's behaviour (no host checks)."""
        resp = client.get(f"{BASE}/entities/data_product/{uuid.uuid4()}/completeness")
        assert resp.status_code == 200, resp.text
        assert resp.json()["applicable"] is False

    def test_asset_edit_materializes_defaults(self, client: TestClient, db_session: Session):
        template = _active_asset_template(client)
        table = _asset(db_session, "Table")
        resp = client.put(f"/api/assets/{table.id}", json={"description": "Orders table"})
        assert resp.status_code == 200, resp.text
        rows = db_session.query(ComplianceTemplateValueDb).filter_by(
            entity_type="asset", entity_id=str(table.id)
        ).all()
        # The defaulted field is materialized; the mandatory one stays pending.
        assert [(str(r.field_id), r.value) for r in rows] == [
            (_field_id(template, "intended_use"), "analytics"),
        ]
