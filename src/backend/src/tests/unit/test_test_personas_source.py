"""Unit tests for test-persona list resolution (volume override vs bundled).

Covers the source-resolution logic added so that DABs-from-git deployers can
override the persona list at runtime by dropping a file on the Unity Catalog
Volume, without editing the repo or restarting the app:

    volume file present  -> use volume list (exclusively)
    volume file absent   -> fall back to the repo-bundled list

/Volumes/... reads must go through the SDK Files API (that path is not a real
filesystem mount in the Databricks Apps runtime), while a local/dotted
DATABRICKS_VOLUME is treated as a plain filesystem path (dev only).
"""
from __future__ import annotations

from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.routes import test_personas_routes as tpr

VOLUME_YAML = """
personas:
  - id: custom
    label: "Custom Persona"
    email: custom@volume.local
    groups: ["custom-group"]
    description: "Defined on the volume"
"""

MALFORMED_MIX_YAML = """
personas:
  - id: ok
    label: "OK"
    email: ok@test.local
  - label: "Missing id and email"
"""


@pytest.fixture(autouse=True)
def _clear_cache():
    """Persona resolution is cached with a TTL; reset it around every test."""
    tpr._invalidate_persona_cache()
    yield
    tpr._invalidate_persona_cache()


def _settings(
    volume: str | None,
    *,
    catalog: str | None = None,
    schema: str | None = None,
) -> SimpleNamespace:
    """Minimal stand-in exposing only the attributes _load_personas reads."""
    return SimpleNamespace(
        DATABRICKS_VOLUME=volume,
        DATABRICKS_CATALOG=catalog,
        DATABRICKS_SCHEMA=schema,
        TEST_USER_TOKEN="tok",
    )


class TestVolumeOverride:
    def test_volume_path_uses_files_api_and_overrides_bundled(self):
        """A /Volumes/... override is read via the SDK and used exclusively."""
        mock_resp = MagicMock()
        mock_resp.contents = BytesIO(VOLUME_YAML.encode("utf-8"))
        mock_ws = MagicMock()
        mock_ws.files.download = MagicMock(return_value=mock_resp)

        with patch(
            "src.common.workspace_client.get_workspace_client",
            return_value=mock_ws,
        ):
            personas = tpr._load_personas(_settings("/Volumes/cat/sch/vol"))

        mock_ws.files.download.assert_called_once_with(
            file_path="/Volumes/cat/sch/vol/config/test_personas.yaml"
        )
        assert [p.id for p in personas] == ["custom"]
        assert personas[0].email == "custom@volume.local"

    def test_volume_download_failure_falls_back_to_bundled(self):
        """If the SDK download raises, we fall back to the repo-bundled list."""
        mock_ws = MagicMock()
        mock_ws.files.download = MagicMock(side_effect=Exception("not found"))

        with patch(
            "src.common.workspace_client.get_workspace_client",
            return_value=mock_ws,
        ):
            personas = tpr._load_personas(_settings("/Volumes/cat/sch/vol"))

        # Bundled file ships the seeded personas, including the admin persona.
        assert any(p.id == "admin" for p in personas)

    def test_local_volume_override_file(self, tmp_path):
        """A local filesystem DATABRICKS_VOLUME is read as a filesystem path."""
        override = tmp_path / "config" / "test_personas.yaml"
        override.parent.mkdir(parents=True)
        override.write_text(VOLUME_YAML)

        personas = tpr._load_personas(_settings(str(tmp_path)))

        assert [p.id for p in personas] == ["custom"]

    def test_dotted_volume_name_resolved_to_mount_path(self):
        """A dotted catalog.schema.volume is normalized to a /Volumes/ path."""
        mock_resp = MagicMock()
        mock_resp.contents = BytesIO(VOLUME_YAML.encode("utf-8"))
        mock_ws = MagicMock()
        mock_ws.files.download = MagicMock(return_value=mock_resp)

        with patch(
            "src.common.workspace_client.get_workspace_client",
            return_value=mock_ws,
        ):
            personas = tpr._load_personas(_settings("cat.sch.vol"))

        mock_ws.files.download.assert_called_once_with(
            file_path="/Volumes/cat/sch/vol/config/test_personas.yaml"
        )
        assert [p.id for p in personas] == ["custom"]

    def test_bare_volume_name_resolved_with_catalog_and_schema(self):
        """A bare volume name is combined with DATABRICKS_CATALOG/SCHEMA."""
        mock_resp = MagicMock()
        mock_resp.contents = BytesIO(VOLUME_YAML.encode("utf-8"))
        mock_ws = MagicMock()
        mock_ws.files.download = MagicMock(return_value=mock_resp)

        with patch(
            "src.common.workspace_client.get_workspace_client",
            return_value=mock_ws,
        ):
            personas = tpr._load_personas(
                _settings("app_files", catalog="ayoub_catalog", schema="ontos_app")
            )

        mock_ws.files.download.assert_called_once_with(
            file_path="/Volumes/ayoub_catalog/ontos_app/app_files/config/test_personas.yaml"
        )
        assert [p.id for p in personas] == ["custom"]

    def test_bare_volume_name_without_catalog_schema_stays_local(self):
        """A bare name with no catalog/schema is treated as a local path (no SDK)."""
        mock_ws = MagicMock()
        with patch(
            "src.common.workspace_client.get_workspace_client",
            return_value=mock_ws,
        ):
            personas = tpr._load_personas(_settings("app_files"))

        # No /Volumes/ path could be synthesized → local read (miss) → bundled.
        mock_ws.files.download.assert_not_called()
        assert any(p.id == "admin" for p in personas)


class TestBundledFallback:
    def test_no_volume_uses_bundled(self):
        personas = tpr._load_personas(_settings(None))
        assert any(p.id == "admin" for p in personas)

    def test_local_volume_without_override_uses_bundled(self, tmp_path):
        # tmp_path has no config/test_personas.yaml under it.
        personas = tpr._load_personas(_settings(str(tmp_path)))
        assert any(p.id == "admin" for p in personas)


class TestParsing:
    def test_malformed_entries_are_skipped(self):
        personas = tpr._parse_personas(MALFORMED_MIX_YAML, "test")
        assert [p.id for p in personas] == ["ok"]

    def test_invalid_yaml_returns_empty(self):
        assert tpr._parse_personas("personas: [unclosed", "test") == []

    def test_empty_text_returns_empty(self):
        assert tpr._parse_personas(None, "test") == []


class TestCaching:
    def test_cache_ttl_reload_surfaces_volume_edits(self, tmp_path, monkeypatch):
        """After the TTL expires, an edited override is re-read (no restart)."""
        override = tmp_path / "config" / "test_personas.yaml"
        override.parent.mkdir(parents=True)
        override.write_text(VOLUME_YAML)
        settings = _settings(str(tmp_path))

        # Freeze "now" so we control cache expiry deterministically.
        clock = {"t": 1000.0}
        monkeypatch.setattr(tpr.time, "monotonic", lambda: clock["t"])

        first = tpr._load_personas(settings)
        assert [p.id for p in first] == ["custom"]

        # Edit the file, then advance past the TTL.
        override.write_text(
            "personas:\n  - id: edited\n    label: E\n    email: e@x.local\n"
        )
        clock["t"] += tpr._CACHE_TTL_SECONDS + 1

        second = tpr._load_personas(settings)
        assert [p.id for p in second] == ["edited"]
