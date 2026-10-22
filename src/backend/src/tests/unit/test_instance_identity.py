"""Unit tests for Ontos instance identity (ONTOS_INSTANCE_ID / ONTOS_INSTANCE_NAME).

Covers the derived defaults, env overrides, the missing-env cases (local dev) and the
SettingsManager read/update/persist path. No ``client`` fixture is used.
"""
import pytest

from src.common.config import Settings
from src.common.instance_identity import InstanceIdInvalidError, InstanceNameInvalidError
from src.controller.settings_manager import SettingsManager
from src.repositories.app_settings_repository import app_settings_repo


def make_settings(tmp_path, **overrides) -> Settings:
    # _env_file=None keeps a developer's local .env out of the test.
    values = dict(
        DATABRICKS_HOST="https://test.example.com",
        DATABRICKS_WAREHOUSE_ID="wh",
        APP_AUDIT_LOG_DIR=str(tmp_path),
        ENV="TEST",
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in (
        "DATABRICKS_WORKSPACE_ID",
        "DATABRICKS_APP_NAME",
        "ONTOS_INSTANCE_ID",
        "ONTOS_INSTANCE_NAME",
    ):
        monkeypatch.delenv(key, raising=False)


class TestDefaults:
    def test_derived_from_workspace_id_and_app_name(self, tmp_path):
        s = make_settings(
            tmp_path, DATABRICKS_WORKSPACE_ID="123456", DATABRICKS_APP_NAME="ontos-prod"
        )
        assert s.ONTOS_INSTANCE_ID == "123456-ontos-prod"
        assert s.ONTOS_INSTANCE_NAME == "ontos-prod"

    def test_derivation_is_stable_across_instances(self, tmp_path):
        a = make_settings(tmp_path, DATABRICKS_WORKSPACE_ID="42", DATABRICKS_APP_NAME="x")
        b = make_settings(tmp_path, DATABRICKS_WORKSPACE_ID="42", DATABRICKS_APP_NAME="x")
        assert a.ONTOS_INSTANCE_ID == b.ONTOS_INSTANCE_ID
        assert a.ONTOS_INSTANCE_NAME == b.ONTOS_INSTANCE_NAME

    def test_missing_workspace_id_falls_back_to_app_name(self, tmp_path):
        s = make_settings(tmp_path, DATABRICKS_APP_NAME="my-app")
        assert s.ONTOS_INSTANCE_ID == "my-app"
        assert s.ONTOS_INSTANCE_NAME == "my-app"

    def test_missing_both_uses_default_app_name(self, tmp_path):
        s = make_settings(tmp_path)
        assert s.ONTOS_INSTANCE_ID == "ontos"
        assert s.ONTOS_INSTANCE_NAME == "ontos"

    def test_blank_workspace_id_is_treated_as_missing(self, tmp_path):
        s = make_settings(tmp_path, DATABRICKS_WORKSPACE_ID="   ", DATABRICKS_APP_NAME="a")
        assert s.ONTOS_INSTANCE_ID == "a"

    def test_explicit_values_win_over_derived(self, tmp_path):
        s = make_settings(
            tmp_path,
            DATABRICKS_WORKSPACE_ID="1",
            DATABRICKS_APP_NAME="a",
            ONTOS_INSTANCE_ID="custom-id",
            ONTOS_INSTANCE_NAME="Custom Name",
        )
        assert s.ONTOS_INSTANCE_ID == "custom-id"
        assert s.ONTOS_INSTANCE_NAME == "Custom Name"

    def test_env_vars_are_read(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ONTOS_INSTANCE_ID", "from-env")
        monkeypatch.setenv("DATABRICKS_WORKSPACE_ID", "99")
        s = make_settings(tmp_path)
        assert s.ONTOS_INSTANCE_ID == "from-env"
        assert s.ONTOS_INSTANCE_NAME == "ontos"


class TestManagerReadUpdate:
    @pytest.fixture
    def settings(self, tmp_path):
        return make_settings(tmp_path, DATABRICKS_WORKSPACE_ID="7", DATABRICKS_APP_NAME="app")

    @pytest.fixture
    def manager(self, db_session, settings):
        return SettingsManager(db=db_session, settings=settings, workspace_client=None)

    def test_get_settings_exposes_values_and_defaults(self, manager):
        data = manager.get_settings()
        assert data["ontos_instance_id"] == "7-app"
        assert data["ontos_instance_name"] == "app"
        assert data["ontos_instance_id_default"] == "7-app"
        assert data["ontos_instance_name_default"] == "app"

    def test_update_persists_and_applies(self, manager, db_session, settings):
        manager.update_settings(
            {"ontos_instance_id": " my.id-1 ", "ontos_instance_name": "My Ontos"}
        )
        assert settings.ONTOS_INSTANCE_ID == "my.id-1"
        assert settings.ONTOS_INSTANCE_NAME == "My Ontos"
        assert app_settings_repo.get_by_key(db_session, "ONTOS_INSTANCE_ID") == "my.id-1"
        assert app_settings_repo.get_by_key(db_session, "ONTOS_INSTANCE_NAME") == "My Ontos"
        data = manager.get_settings()
        assert data["ontos_instance_id"] == "my.id-1"
        # defaults stay available so the UI can show them
        assert data["ontos_instance_id_default"] == "7-app"

    def test_override_survives_restart(self, manager, db_session, tmp_path):
        manager.update_settings({"ontos_instance_id": "kept", "ontos_instance_name": "Kept"})
        fresh = make_settings(tmp_path, DATABRICKS_WORKSPACE_ID="7", DATABRICKS_APP_NAME="app")
        assert fresh.ONTOS_INSTANCE_ID == "7-app"
        SettingsManager(db=db_session, settings=fresh, workspace_client=None)
        assert fresh.ONTOS_INSTANCE_ID == "kept"
        assert fresh.ONTOS_INSTANCE_NAME == "Kept"

    def test_blank_clears_override_and_restores_default(self, manager, db_session, settings):
        manager.update_settings({"ontos_instance_id": "x", "ontos_instance_name": "X"})
        manager.update_settings({"ontos_instance_id": "", "ontos_instance_name": "  "})
        assert settings.ONTOS_INSTANCE_ID == "7-app"
        assert settings.ONTOS_INSTANCE_NAME == "app"
        assert app_settings_repo.get_by_key(db_session, "ONTOS_INSTANCE_ID") is None
        assert app_settings_repo.get_by_key(db_session, "ONTOS_INSTANCE_NAME") is None

    def test_clear_restores_env_value_not_derived(self, db_session, tmp_path):
        s = make_settings(tmp_path, DATABRICKS_WORKSPACE_ID="7", ONTOS_INSTANCE_ID="env-id")
        m = SettingsManager(db=db_session, settings=s, workspace_client=None)
        m.update_settings({"ontos_instance_id": "override"})
        m.update_settings({"ontos_instance_id": ""})
        assert s.ONTOS_INSTANCE_ID == "env-id"

    def test_unrelated_update_does_not_touch_identity(self, manager, settings, db_session):
        manager.update_settings({"schema_import_child_limit": 10})
        assert settings.ONTOS_INSTANCE_ID == "7-app"
        assert app_settings_repo.get_by_key(db_session, "ONTOS_INSTANCE_ID") is None

    @pytest.mark.parametrize("bad", ["has space", "-leading", "a/b", "x" * 129, "ünï"])
    def test_invalid_id_rejected(self, manager, settings, bad):
        with pytest.raises(ValueError):
            manager.update_settings({"ontos_instance_id": bad})
        assert settings.ONTOS_INSTANCE_ID == "7-app"

    @pytest.mark.parametrize("bad", ["x" * 129, "line\nbreak"])
    def test_invalid_name_rejected(self, manager, settings, bad):
        with pytest.raises(ValueError):
            manager.update_settings({"ontos_instance_name": bad})
        assert settings.ONTOS_INSTANCE_NAME == "app"


class TestCodedErrors:
    """Invalid values raise coded errors that the PUT answers as {code, message, params}."""

    @pytest.fixture
    def client(self, db_session, tmp_path):
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient
        from starlette.exceptions import HTTPException as StarletteHTTPException

        from src.common.api_errors import coded_http_exception_handler

        manager = SettingsManager(
            db=db_session, settings=make_settings(tmp_path), workspace_client=None
        )
        app = FastAPI()
        app.add_exception_handler(StarletteHTTPException, coded_http_exception_handler)

        @app.put("/api/settings")
        def put(payload: dict):  # mirrors the real route's ValueError handling
            try:
                manager.update_settings(payload)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {}

        return TestClient(app)

    def test_invalid_id_detail_has_code_and_params(self, client):
        r = client.put("/api/settings", json={"ontos_instance_id": "bad id!"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail["code"] == "instance_id_invalid"
        assert detail["params"] == {"max_length": 128}
        assert "ontos_instance_id" in detail["message"]

    def test_invalid_name_detail_has_code_and_params(self, client):
        r = client.put("/api/settings", json={"ontos_instance_name": "x" * 129})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail["code"] == "instance_name_invalid"
        assert detail["params"] == {"max_length": 128}

    def test_control_characters_in_name_use_the_same_coded_detail(self, client):
        r = client.put("/api/settings", json={"ontos_instance_name": "bad\x07name"})
        assert r.status_code == 400
        detail = r.json()["detail"]
        assert detail["code"] == "instance_name_invalid"
        assert detail["params"] == {"max_length": 128}
        assert "control characters" in detail["message"]


class TestEnvironmentSourcesAreValidated:
    """The environment (and derived) values go through the validator the Settings PUT uses."""

    @pytest.mark.parametrize(
        "bad",
        [
            "has space", "-leading", ".dot", "a/b", "x" * 129, "ünï", "tab\tid", "new\nline",
            "mid\nend",
        ],
    )
    def test_invalid_env_id_stops_startup_with_a_coded_error(self, tmp_path, monkeypatch, bad):
        from pydantic import ValidationError

        monkeypatch.setenv("ONTOS_INSTANCE_ID", bad)
        with pytest.raises(ValidationError) as raised:
            make_settings(tmp_path)
        error = raised.value.errors()[0]["ctx"]["error"]
        assert isinstance(error, InstanceIdInvalidError)
        assert error.code == "instance_id_invalid"
        assert error.params == {"max_length": 128}
        assert "ONTOS_INSTANCE_ID (environment variable)" in str(error)

    @pytest.mark.parametrize("bad", ["bad id", "a\x00b"])
    def test_invalid_env_id_passed_as_init_value_is_rejected_too(self, tmp_path, bad):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            make_settings(tmp_path, ONTOS_INSTANCE_ID=bad)

    @pytest.mark.parametrize("bad", ["x" * 129, "line\nbreak", "bell\x07"])
    def test_invalid_env_name_stops_startup_with_a_coded_error(self, tmp_path, monkeypatch, bad):
        from pydantic import ValidationError

        monkeypatch.setenv("ONTOS_INSTANCE_NAME", bad)
        with pytest.raises(ValidationError) as raised:
            make_settings(tmp_path)
        error = raised.value.errors()[0]["ctx"]["error"]
        assert isinstance(error, InstanceNameInvalidError)
        assert error.code == "instance_name_invalid"
        assert error.params == {"max_length": 128}
        assert "ONTOS_INSTANCE_NAME (environment variable)" in str(error)

    @pytest.mark.parametrize("empty", ["", "   "])
    def test_empty_env_values_mean_unset(self, tmp_path, monkeypatch, empty):
        monkeypatch.setenv("ONTOS_INSTANCE_ID", empty)
        monkeypatch.setenv("ONTOS_INSTANCE_NAME", empty)
        monkeypatch.setenv("DATABRICKS_WORKSPACE_ID", "5")
        s = make_settings(tmp_path)
        assert s.ONTOS_INSTANCE_ID == "5-ontos"
        assert s.ONTOS_INSTANCE_NAME == "ontos"

    def test_valid_env_values_are_stripped_and_used(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ONTOS_INSTANCE_ID", "  Prod.eu:1_a-b  ")
        monkeypatch.setenv("ONTOS_INSTANCE_NAME", "  Ontos EU  ")
        s = make_settings(tmp_path)
        assert s.ONTOS_INSTANCE_ID == "Prod.eu:1_a-b"
        assert s.ONTOS_INSTANCE_NAME == "Ontos EU"

    def test_invalid_derived_id_is_rejected_with_its_source(self, tmp_path):
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as raised:
            make_settings(tmp_path, DATABRICKS_WORKSPACE_ID="1", DATABRICKS_APP_NAME="my app")
        error = raised.value.errors()[0]["ctx"]["error"]
        assert isinstance(error, InstanceIdInvalidError)
        assert "DATABRICKS_APP_NAME" in str(error)

    def test_stored_override_still_wins_over_a_valid_env_value(self, db_session, tmp_path):
        s = make_settings(tmp_path, ONTOS_INSTANCE_ID="env-id", ONTOS_INSTANCE_NAME="Env")
        m = SettingsManager(db=db_session, settings=s, workspace_client=None)
        m.update_settings({"ontos_instance_id": "stored-id", "ontos_instance_name": "Stored"})
        fresh = make_settings(tmp_path, ONTOS_INSTANCE_ID="env-id", ONTOS_INSTANCE_NAME="Env")
        SettingsManager(db=db_session, settings=fresh, workspace_client=None)
        assert fresh.ONTOS_INSTANCE_ID == "stored-id"
        assert fresh.ONTOS_INSTANCE_NAME == "Stored"

    def test_invalid_stored_values_are_ignored_and_the_default_stays(self, db_session, tmp_path):
        app_settings_repo.set(db_session, "ONTOS_INSTANCE_ID", "bad id!")
        app_settings_repo.set(db_session, "ONTOS_INSTANCE_NAME", "x" * 200)
        s = make_settings(tmp_path, ONTOS_INSTANCE_ID="env-id")
        SettingsManager(db=db_session, settings=s, workspace_client=None)
        assert s.ONTOS_INSTANCE_ID == "env-id"
        assert s.ONTOS_INSTANCE_NAME == "ontos"
