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

from databricks.sdk.errors import NotFound, PermissionDenied

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

    @pytest.mark.parametrize(
        "error", [NotFound("missing"), PermissionDenied("denied"), Exception("boom")]
    )
    def test_volume_download_failure_falls_back_to_bundled(self, error):
        """If the SDK download raises, we fall back to the repo-bundled list."""
        mock_ws = MagicMock()
        mock_ws.files.download = MagicMock(side_effect=error)

        with patch(
            "src.common.workspace_client.get_workspace_client",
            return_value=mock_ws,
        ):
            personas = tpr._load_personas(_settings("/Volumes/cat/sch/vol"))

        # Bundled file ships the seeded personas, including the admin persona.
        assert any(p.id == "admin" for p in personas)

    def test_missing_override_logs_debug_but_denied_read_logs_warning(self):
        """Operators can tell a missing override from a denied read in the logs."""
        mock_ws = MagicMock()
        with patch(
            "src.common.workspace_client.get_workspace_client",
            return_value=mock_ws,
        ), patch.object(tpr, "logger") as mock_logger:
            mock_ws.files.download = MagicMock(side_effect=NotFound("missing"))
            tpr._read_volume_override(_settings("/Volumes/cat/sch/vol"))
            mock_logger.warning.assert_not_called()

            mock_ws.files.download = MagicMock(side_effect=PermissionDenied("denied"))
            tpr._read_volume_override(_settings("/Volumes/cat/sch/vol"))
            mock_logger.warning.assert_called_once()

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

    @pytest.mark.parametrize(
        "text",
        [
            "- id: a\n  label: A\n  email: a@x.local\n",  # top-level list
            "just a string",  # top-level scalar
            "personas: not-a-list",  # 'personas' is not a list
        ],
    )
    def test_non_mapping_or_non_list_returns_empty(self, text):
        assert tpr._parse_personas(text, "test") == []


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


PRESENTATION_YAML = """
personas:
  - id: priya
    label: "Priya Raman — Data Steward, Finance"
    email: priya@test.local
    display_name: "Priya Raman"
    title: "Data Steward, Finance"
    color: "#0f7b3f"
    avatar: priya.svg
  - id: joost
    label: "Joost"
    email: joost@test.local
    color: "red; background: url(x)"
    avatar: "../../etc/passwd"
  - id: inline
    label: "Inline"
    email: inline@test.local
    avatar: "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg'/>"
"""

SVG = b"<svg xmlns='http://www.w3.org/2000/svg'><circle r='4'/></svg>"


def _volume_with(tmp_path, yaml_text=PRESENTATION_YAML, avatars=None):
    cfg = tmp_path / "config"
    cfg.mkdir(parents=True)
    (cfg / "test_personas.yaml").write_text(yaml_text)
    if avatars:
        (cfg / "avatars").mkdir()
        for name, data in avatars.items():
            (cfg / "avatars" / name).write_bytes(data)
    return _settings(str(tmp_path))


class TestPresentationFields:
    def test_fields_parse_and_avatar_file_maps_to_route(self, tmp_path):
        personas = {p.id: p for p in tpr._load_personas(_volume_with(tmp_path))}
        priya = personas["priya"]
        assert (priya.display_name, priya.title, priya.color) == ("Priya Raman", "Data Steward, Finance", "#0f7b3f")
        assert priya.avatar_url == "/api/test/personas/priya/avatar"
        assert priya.model_dump()["avatar_url"] == "/api/test/personas/priya/avatar"

    def test_invalid_color_and_avatar_are_dropped_not_the_persona(self, tmp_path):
        joost = {p.id: p for p in tpr._load_personas(_volume_with(tmp_path))}["joost"]
        assert joost.color is None
        assert joost.avatar is None and joost.avatar_url is None

    def test_inline_and_https_avatars_pass_through(self, tmp_path):
        inline = {p.id: p for p in tpr._load_personas(_volume_with(tmp_path))}["inline"]
        assert inline.avatar_url.startswith("data:image/svg+xml")
        remote = tpr.TestPersona(id="r", label="R", email="r@x", avatar="https://example.com/r.png")
        assert remote.avatar_url == "https://example.com/r.png"

    @pytest.mark.parametrize("avatar", ["javascript:alert(1)", "data:text/html,<b>", "a/b.svg", "notes.txt", "http://x/a.png"])
    def test_unsafe_avatar_values_rejected(self, avatar):
        assert tpr.TestPersona(id="x", label="X", email="x@x", avatar=avatar).avatar is None

    def test_persona_id_is_url_encoded(self):
        p = tpr.TestPersona(id="a/b c", label="X", email="x@x", avatar="a.png")
        assert p.avatar_url == "/api/test/personas/a%2Fb%20c/avatar"


class TestAvatarRoute:
    def test_serves_local_file_with_safe_headers(self, tmp_path):
        settings = _volume_with(tmp_path, avatars={"priya.svg": SVG})
        resp = tpr.get_test_persona_avatar("priya", settings=settings)
        assert resp.body == SVG
        assert resp.media_type == "image/svg+xml"
        assert "sandbox" in resp.headers["content-security-policy"]
        assert resp.headers["x-content-type-options"] == "nosniff"

    def test_disabled_without_token(self, tmp_path):
        settings = _volume_with(tmp_path, avatars={"priya.svg": SVG})
        settings.TEST_USER_TOKEN = None
        with pytest.raises(tpr.HTTPException) as exc:
            tpr.get_test_persona_avatar("priya", settings=settings)
        assert exc.value.status_code == 404

    @pytest.mark.parametrize("persona_id", ["nobody", "inline", "joost"])
    def test_404_for_unknown_persona_or_non_file_avatar(self, tmp_path, persona_id):
        settings = _volume_with(tmp_path, avatars={"priya.svg": SVG})
        with pytest.raises(tpr.HTTPException) as exc:
            tpr.get_test_persona_avatar(persona_id, settings=settings)
        assert exc.value.status_code == 404

    def test_404_when_file_missing(self, tmp_path):
        with pytest.raises(tpr.HTTPException) as exc:
            tpr.get_test_persona_avatar("priya", settings=_volume_with(tmp_path))
        assert exc.value.status_code == 404

    def test_oversized_file_not_served(self, tmp_path, monkeypatch):
        monkeypatch.setattr(tpr, "_AVATAR_MAX_BYTES", 10)
        settings = _volume_with(tmp_path, avatars={"priya.svg": SVG})
        with pytest.raises(tpr.HTTPException):
            tpr.get_test_persona_avatar("priya", settings=settings)

    def test_volume_avatar_read_via_files_api_and_cached(self):
        mock_ws = MagicMock()
        mock_ws.files.download.return_value = SimpleNamespace(contents=BytesIO(SVG))
        with patch("src.common.workspace_client.get_workspace_client", return_value=mock_ws):
            settings = _settings("/Volumes/cat/sch/vol")
            assert tpr._read_avatar(settings, "priya.svg") == SVG
            assert tpr._read_avatar(settings, "priya.svg") == SVG
        mock_ws.files.download.assert_called_once_with(
            file_path="/Volumes/cat/sch/vol/config/avatars/priya.svg"
        )

    def test_volume_avatar_missing_is_none(self):
        mock_ws = MagicMock()
        mock_ws.files.download.side_effect = NotFound("missing")
        with patch("src.common.workspace_client.get_workspace_client", return_value=mock_ws):
            assert tpr._read_avatar(_settings("/Volumes/cat/sch/vol"), "priya.svg") is None


class TestPresentationEdgeCases:
    def test_empty_color_and_avatar_mean_unset_without_warning(self):
        with patch.object(tpr, "logger") as mock_logger:
            p = tpr.TestPersona(id="x", label="X", email="x@x", color="", avatar="  ")
        assert p.color is None and p.avatar is None
        mock_logger.warning.assert_not_called()

    def test_gif_files_and_data_uris_are_both_accepted(self):
        assert tpr.TestPersona(id="x", label="X", email="x@x", avatar="x.gif").avatar_url == "/api/test/personas/x/avatar"
        assert tpr.TestPersona(id="x", label="X", email="x@x", avatar="data:image/gif;base64,R0lG").avatar
