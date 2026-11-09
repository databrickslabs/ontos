"""Unit tests for the SPA catch-all's path-exclusion helper.

The catch-all is only registered when ``settings.TESTING`` is false, so an
end-to-end TestClient check doesn't exercise the exclusion — any unmatched
GET would 404 regardless. These tests cover the helper directly so the
regression guard (#937 reviewer: 404 under ``/mcp/*`` must not fall into the
SPA) can't drift silently.
"""
import pytest

from src.app import _is_spa_fallback_path


class TestSpaFallbackPath:
    @pytest.mark.parametrize("path", [
        "",                 # root
        "settings",
        "settings/mcp",     # the frontend MCP settings route (not /mcp/*)
        "mcpfoo",           # looks like mcp but is not under /mcp — SPA is fine
        "data-products",
        "some/deep/route",
    ])
    def test_frontend_routes_fall_through_to_spa(self, path):
        assert _is_spa_fallback_path(path) is True

    @pytest.mark.parametrize("path", [
        "mcp",
        "mcp/tools/list",
        "mcp/does-not-exist",
        "mcp/health",
    ])
    def test_mcp_paths_never_fall_to_spa(self, path):
        """The whole point of the exclusion — otherwise MCP clients get HTML
        when they hit an unknown endpoint under /mcp."""
        assert _is_spa_fallback_path(path) is False

    @pytest.mark.parametrize("path", [
        "api/data-products",
        "static/js/app.js",
        "docs",
        "redoc",
        "openapi.json",
    ])
    def test_api_and_static_and_docs_do_not_fall_to_spa(self, path):
        assert _is_spa_fallback_path(path) is False

    def test_mcp_prefix_is_tight(self):
        """Reviewer-note: ``startswith('mcp')`` would also swallow ``mcpfoo``.
        The helper matches only the literal ``mcp`` or the ``mcp/`` prefix."""
        assert _is_spa_fallback_path("mcpfoo") is True   # not under /mcp
        assert _is_spa_fallback_path("mcp") is False
        assert _is_spa_fallback_path("mcp/x") is False
