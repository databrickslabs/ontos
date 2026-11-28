"""HTTP surface of staged model imports (PRD #1718)."""
import functools
import json
from pathlib import Path

import pytest

from src.app import app
from src.controller.model_import_manager import ModelImportManager
from src.routes import model_import_routes
from src.tests.integration.test_model_import_concepts import semantic  # noqa: F401  (fixture)

FIXTURE = Path(__file__).resolve().parents[1] / "data" / "erwin" / "sales_dw_standard.xml"


class _NoopAudit:
    async def log_action_background(self, **_kwargs):
        return None

    def log_action(self, *_a, **_k):
        return None

    def log_event(self, *_a, **_k):
        return None


@pytest.fixture
def api(client, semantic):  # noqa: F811
    manager = ModelImportManager(semantic_models_manager=semantic, data_contracts_manager=None)
    # Run confirmed imports inline: the test DB session is not shared with threads.
    manager.confirm_run = functools.partial(manager.confirm_run, run_inline=True)
    app.state.model_import_manager = manager
    app.state.audit_manager = _NoopAudit()
    yield client
    if hasattr(app.state, "model_import_manager"):
        delattr(app.state, "model_import_manager")


def _upload(api, content: bytes, options=None, name="sales_dw.xml"):
    data = {"options": json.dumps(options)} if options is not None else {}
    return api.post("/api/model-import/runs", files={"file": (name, content, "application/xml")}, data=data)


def test_upload_returns_preview_and_token(api):
    resp = _upload(api, FIXTURE.read_bytes(), {"import_physical": False})
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "previewed"
    assert body["confirm_token"]
    assert body["source_model_name"] == "Sales DW"
    assert len(body["source_sha256"]) == 64
    assert body["preview"]["logical"]["counts"]["classes"] == 7
    assert "model_ir" not in body


def test_not_an_erwin_file_is_422(api):
    resp = _upload(api, b"<html/>", name="x.xml")
    assert resp.status_code == 422
    assert "erwin" in resp.json()["detail"]


def test_empty_file_is_422(api):
    assert _upload(api, b"").status_code == 422


def test_invalid_options_are_422(api):
    resp = _upload(api, FIXTURE.read_bytes(), {"contract_grouping": "nope"})
    assert resp.status_code == 422


def test_nothing_selected_is_422(api):
    resp = _upload(api, FIXTURE.read_bytes(), {"import_logical": False, "import_physical": False})
    assert resp.status_code == 422


def test_size_cap(api, monkeypatch):
    monkeypatch.setattr(model_import_routes, "MODEL_IMPORT_MAX_BYTES", 100)
    resp = _upload(api, FIXTURE.read_bytes())
    assert resp.status_code == 413


def test_patch_confirm_and_get(api):
    run = _upload(api, FIXTURE.read_bytes(), {"import_physical": False}).json()
    party = next(s["id"] for s in run["preview"]["model"]["subject_areas"] if s["name"] == "Party")

    patched = api.patch(f"/api/model-import/runs/{run['id']}",
                        json={"import_physical": False, "subject_area_ids": [party]})
    assert patched.status_code == 200, patched.text
    assert patched.json()["confirm_token"] != run["confirm_token"]

    ok = api.post(f"/api/model-import/runs/{run['id']}/confirm",
                  json={"confirm_token": patched.json()["confirm_token"]})
    assert ok.status_code == 202, ok.text
    assert ok.json()["status"] == "completed"
    assert ok.json()["confirm_token"] is None

    got = api.get(f"/api/model-import/runs/{run['id']}")
    assert got.status_code == 200
    assert got.json()["result"]["logical"]["collection_iri"] == "urn:ontology:sales-dw"

    listed = api.get("/api/model-import/runs").json()
    assert any(r["id"] == run["id"] for r in listed)


def test_stale_token_is_409(api):
    # Separate test: an error response rolls back the shared test session.
    run = _upload(api, FIXTURE.read_bytes(), {"import_physical": False}).json()
    api.patch(f"/api/model-import/runs/{run['id']}", json={"import_physical": False, "contract_grouping": "table"})
    stale = api.post(f"/api/model-import/runs/{run['id']}/confirm", json={"confirm_token": run["confirm_token"]})
    assert stale.status_code == 409


def test_unknown_run_is_404(api):
    assert api.get("/api/model-import/runs/nope").status_code == 404


def test_cancel(api):
    run = _upload(api, FIXTURE.read_bytes(), {"import_physical": False}).json()
    resp = api.post(f"/api/model-import/runs/{run['id']}/cancel")
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"
    assert api.post(f"/api/model-import/runs/{run['id']}/cancel").status_code == 409
