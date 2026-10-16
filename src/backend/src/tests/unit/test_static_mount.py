"""The backend starts without a frontend build (#829).

``StaticFiles`` raises when its directory doesn't exist, so mounting
``src/backend/static`` unconditionally made the app crash at import in any
checkout where the frontend wasn't built (Vite serves the UI in local work).
"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.app import _mount_frontend_static


def _mounted(app):
    return [r for r in app.routes if getattr(r, 'name', None) == 'static']


def test_a_missing_build_is_not_mounted(tmp_path):
    app = FastAPI()

    assert _mount_frontend_static(app, tmp_path / 'static', 'LOCAL') is False
    assert _mounted(app) == []


def test_a_missing_build_outside_local_is_not_mounted_either(tmp_path):
    # Deployed apps need the build; the mount is skipped (with an error logged)
    # rather than crashing the whole backend
    app = FastAPI()

    assert _mount_frontend_static(app, tmp_path / 'static', 'PROD') is False
    assert _mounted(app) == []


def test_an_existing_build_is_served(tmp_path):
    static = tmp_path / 'static'
    static.mkdir()
    (static / 'index.html').write_text('<html>ontos</html>')
    app = FastAPI()

    assert _mount_frontend_static(app, static, 'PROD') is True
    assert len(_mounted(app)) == 1
    response = TestClient(app).get('/static/index.html')
    assert response.status_code == 200
    assert 'ontos' in response.text


# --- The SPA catch-all ------------------------------------------------------

import pytest
from fastapi import HTTPException

from src.app import _spa_response


def test_frontend_routes_get_index_html(tmp_path):
    (tmp_path / 'index.html').write_text('<html>ontos</html>')

    response = _spa_response('data-products', tmp_path)

    assert response.status_code == 200
    assert str(response.path).endswith('index.html')


def test_without_a_build_frontend_routes_say_so(tmp_path):
    response = _spa_response('settings', tmp_path / 'static')

    assert response.status_code == 404
    assert b'Frontend not built' in response.body


@pytest.mark.parametrize('path', ['static/js/app.js', 'api/does-not-exist', 'mcp/x', 'docs'])
def test_paths_the_spa_does_not_answer_are_not_found(tmp_path, path):
    # Before: the route returned nothing, i.e. 200 with a `null` body
    (tmp_path / 'index.html').write_text('<html>ontos</html>')

    with pytest.raises(HTTPException) as e:
        _spa_response(path, tmp_path)

    assert e.value.status_code == 404
