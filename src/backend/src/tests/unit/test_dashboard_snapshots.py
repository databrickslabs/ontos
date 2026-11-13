"""Dashboard snapshots (#1312 slice 3): capture, storage on the asset, inheritance into products."""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from src.connectors.base import DashboardSnapshot
from src.connectors.tableau import TableauConnector, TableauConnectorConfig, clear_listing_cache
from src.connectors.tableau_client import GraphQLResult, TableauAPIError
from src.controller.dashboard_snapshot_manager import DashboardSnapshotManager
from src.controller.metadata_manager import MetadataManager
from src.db_models.assets import AssetDb, AssetTypeDb
from src.db_models.data_products import DataProductDb, OutputPortDb
from src.db_models.metadata import DocumentMetadataDb, RichTextMetadataDb

PATH = "p~p1.wb~wb1.v~v1"


class FakeConnector:
    def __init__(self, snapshot=None, risks=None):
        self.snapshot = snapshot or DashboardSnapshot(status="ok", content=b"\x89PNG-1", source="view_image")
        self.risks = risks or []
        self.captures = 0

    def capture_snapshot(self, path):
        self.captures += 1
        return self.snapshot

    def snapshot_risks(self, path):
        return self.risks


@pytest.fixture
def ws(monkeypatch):
    monkeypatch.setattr(MetadataManager, "ensure_volume_path", lambda self, ws, settings, base_dir: "/Volumes/c/s/v")
    return MagicMock()


@pytest.fixture
def manager(ws):
    return DashboardSnapshotManager(workspace_client_provider=lambda: ws, settings_provider=lambda: SimpleNamespace())


@pytest.fixture
def dashboard(db_session):
    dashboard_type = AssetTypeDb(id=uuid4(), name="Dashboard")
    db_session.add(dashboard_type)
    db_session.flush()
    asset = AssetDb(
        id=uuid4(), name="Orders Overview", asset_type_id=dashboard_type.id, platform="tableau", location=PATH,
        properties={"dashboardPlatform": "tableau", "dashboardUrl": "https://t/#/views/OrdersOverview/OrdersOverview",
                    "source_updated_at": "2026-11-05T11:24:28+00:00"},
    )
    db_session.add(asset)
    db_session.flush()
    return asset


def _doc_and_note(db, asset):
    docs = db.query(DocumentMetadataDb).filter_by(entity_type="asset", entity_id=str(asset.id)).all()
    notes = db.query(RichTextMetadataDb).filter_by(entity_type="asset", entity_id=str(asset.id)).all()
    return docs, notes


def test_capture_stores_image_document_and_preview_note(db_session, manager, dashboard, ws):
    state = manager.capture(db_session, asset=dashboard, connector=FakeConnector(), current_user="u@example.com")

    assert state["status"] == "ok" and state["source"] == "view_image"
    [doc], [note] = _doc_and_note(db_session, dashboard)
    assert state["document_id"] == str(doc.id) and state["note_id"] == str(note.id)
    assert doc.content_type == "image/png" and doc.size_bytes == 6 and doc.inheritable and doc.level == 10
    assert doc.storage_path == f"/Volumes/c/s/v/uploads/asset/{dashboard.id}/dashboard-snapshot.png"
    assert f"![Orders Overview](doc:{doc.id})" in note.content_markdown
    assert "[Open the live dashboard](https://t/#/views/OrdersOverview/OrdersOverview)" in note.content_markdown
    assert "row-level security" in note.content_markdown
    ws.files.upload.assert_called_once()
    assert dashboard.properties["snapshot"]["status"] == "ok"


def test_unchanged_dashboard_is_not_rendered_again(db_session, manager, dashboard):
    connector = FakeConnector()
    manager.capture(db_session, asset=dashboard, connector=connector, current_user=None)
    manager.capture(db_session, asset=dashboard, connector=connector, current_user=None)
    assert connector.captures == 1

    dashboard.properties = {**dashboard.properties, "source_updated_at": "2026-11-06T09:00:00+00:00"}
    manager.capture(db_session, asset=dashboard, connector=connector, current_user=None)
    assert connector.captures == 2


def test_forced_capture_updates_the_same_document_and_note(db_session, manager, dashboard):
    first = manager.capture(db_session, asset=dashboard, connector=FakeConnector(), current_user=None)
    second = manager.capture(
        db_session, asset=dashboard, current_user=None, force=True,
        connector=FakeConnector(DashboardSnapshot(status="ok", content=b"\x89PNG-22", source="view_image")),
    )
    assert (first["document_id"], first["note_id"]) == (second["document_id"], second["note_id"])
    [doc], [note] = _doc_and_note(db_session, dashboard)
    assert doc.size_bytes == 7


def test_user_filters_block_automatic_capture_but_not_a_forced_one(db_session, manager, dashboard):
    connector = FakeConnector(risks=["'Region Filter' uses USERNAME()"])

    state = manager.capture(db_session, asset=dashboard, connector=connector, current_user=None)
    assert state["status"] == "skipped_user_filters"
    assert state["risks"] == ["'Region Filter' uses USERNAME()"]
    assert connector.captures == 0 and _doc_and_note(db_session, dashboard) == ([], [])

    forced = manager.capture(db_session, asset=dashboard, connector=connector, current_user=None, force=True)
    assert forced["status"] == "ok" and connector.captures == 1


def test_opted_out_dashboards_are_never_captured(db_session, manager, dashboard):
    manager.set_opt_out(db_session, dashboard, True)
    connector = FakeConnector()
    state = manager.capture(db_session, asset=dashboard, connector=connector, current_user=None, force=True)
    assert state["status"] == "opted_out" and connector.captures == 0


def test_failed_render_keeps_the_thumbnail_with_the_failure_status(db_session, manager, dashboard):
    snapshot = DashboardSnapshot(status="auth_expired", content=b"\x89PNG-thumb", source="preview_image", error="refresh token")
    state = manager.capture(db_session, asset=dashboard, connector=FakeConnector(snapshot), current_user=None)

    assert state["status"] == "auth_expired" and state["error"] == "refresh token"
    [doc], [note] = _doc_and_note(db_session, dashboard)
    assert "Thumbnail from Tableau" in note.content_markdown


def test_no_image_at_all_records_the_status_only(db_session, manager, dashboard, ws):
    state = manager.capture(
        db_session, asset=dashboard, connector=FakeConnector(DashboardSnapshot(status="not_connected", error="x")),
        current_user=None,
    )
    assert state["status"] == "not_connected" and state["document_id"] is None
    ws.files.upload.assert_not_called()


def test_a_product_with_the_dashboard_as_port_inherits_the_snapshot(db_session, manager, dashboard):
    manager.capture(db_session, asset=dashboard, connector=FakeConnector(), current_user=None)
    product = DataProductDb(id=str(uuid4()), name="Orders Analytics", status="draft", max_level_inheritance=99)
    db_session.add(product)
    db_session.flush()
    db_session.add(OutputPortDb(
        id=str(uuid4()), product_id=product.id, name="dashboard", version="1.0.0",
        port_type="dashboard", asset_type="dashboard", asset_identifier=PATH,
    ))
    db_session.flush()

    merged = MetadataManager().get_merged_metadata(db_session, entity_type="data_product", entity_id=product.id)

    assert [d.title for d in merged.documents] == ["Snapshot: Orders Overview"]
    assert [rt.title for rt in merged.rich_texts] == ["Dashboard preview"]
    assert merged.source_names == {f"asset:{dashboard.id}": "Orders Overview"}


# --- Tableau rendering ---------------------------------------------------------


class RenderClient:
    server_url = "https://t"
    site_content_url = "s"
    identity = "pat:test"

    def __init__(self, image=None, preview=b"\x89PNG-thumb", formulas=None):
        self.image = image
        self.preview = preview
        self.formulas = formulas or []

    def get_bytes(self, path, params=None):
        if path.endswith("/image"):
            if isinstance(self.image, Exception):
                raise self.image
            return self.image
        return self.preview

    def graphql(self, query, variables=None):
        if "WorkbookViews" in query:
            return GraphQLResult({"workbooks": [{
                "embeddedDatasources": [{"fields": [{"name": f, "formula": x} for f, x in self.formulas]}],
                "dashboards": [{"luid": "v1", "upstreamDatasources": [{"luid": "ds1"}]}], "sheets": [],
            }]})
        return GraphQLResult({"publishedDatasources": [{"fields": [{"name": "Region Filter", "formula": "[Owner] = USERNAME()"}]}]})


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_listing_cache()
    yield
    clear_listing_cache()


def _tableau(client):
    return TableauConnector(TableauConnectorConfig(server_url="https://t", site_content_url="s"), client=client)


def test_tableau_capture_renders_the_view_in_high_resolution():
    snapshot = _tableau(RenderClient(image=b"\x89PNG-high")).capture_snapshot(PATH)
    assert (snapshot.status, snapshot.source, snapshot.content) == ("ok", "view_image", b"\x89PNG-high")


@pytest.mark.parametrize("error,status", [
    (TableauAPIError("400074 ... needs an unexpired OAuth refresh token ...", 400), "auth_expired"),
    (TableauAPIError("400074 ... Error: data sources not connected", 400), "not_connected"),
    (TableauAPIError("no read", 403), "forbidden"),
    (TableauAPIError("boom", 500), "error"),
])
def test_tableau_render_failures_fall_back_to_the_thumbnail(error, status):
    snapshot = _tableau(RenderClient(image=error)).capture_snapshot(PATH)
    assert snapshot.status == status
    assert (snapshot.source, snapshot.content) == ("preview_image", b"\x89PNG-thumb")


def test_tableau_empty_render_and_empty_thumbnail():
    snapshot = _tableau(RenderClient(image=b"", preview=b"")).capture_snapshot(PATH)
    assert snapshot.status == "empty" and snapshot.content is None


def test_tableau_snapshot_risks_find_user_functions_in_embedded_and_published_formulas():
    risks = _tableau(RenderClient(formulas=[("Mine", "ISMEMBEROF('Sales')"), ("Plain", "SUM([Sales])")])).snapshot_risks(PATH)
    assert risks == ["'Mine' uses ISMEMBEROF()", "'Region Filter' uses USERNAME()"]


def test_only_dashboards_get_snapshots_on_import():
    connector = _tableau(RenderClient())
    from src.models.assets import AssetMetadata, UnifiedAssetType
    def meta(t):
        return AssetMetadata(identifier=PATH, name="x", asset_type=t, connector_type="tableau")
    assert connector.wants_snapshot(meta(UnifiedAssetType.TABLEAU_DASHBOARD)) is True
    assert connector.wants_snapshot(meta(UnifiedAssetType.TABLEAU_SHEET)) is False


def test_opting_out_removes_the_stored_snapshot(db_session, manager, dashboard):
    manager.capture(db_session, asset=dashboard, connector=FakeConnector(), current_user=None)
    state = manager.set_opt_out(db_session, dashboard, True)["snapshot"]
    assert state["status"] == "opted_out" and state["document_id"] is None
    assert _doc_and_note(db_session, dashboard) == ([], [])


def test_user_filters_found_later_remove_the_earlier_snapshot(db_session, manager, dashboard):
    manager.capture(db_session, asset=dashboard, connector=FakeConnector(), current_user=None)
    dashboard.properties = {**dashboard.properties, "source_updated_at": "2026-11-07T00:00:00+00:00"}
    state = manager.capture(db_session, asset=dashboard, connector=FakeConnector(risks=["'X' uses USERNAME()"]), current_user=None)
    assert state["status"] == "skipped_user_filters" and state["document_id"] is None
    assert _doc_and_note(db_session, dashboard) == ([], [])


def test_risk_check_fails_closed_without_the_metadata_api():
    class NoMetadata(RenderClient):
        def graphql(self, query, variables=None):
            raise TableauAPIError("Metadata API disabled", 400)
    risks = _tableau(NoMetadata()).snapshot_risks(PATH)
    assert risks and "Metadata API unavailable" in risks[0]
