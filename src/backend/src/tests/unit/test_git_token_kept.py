"""The Git token is write-only (#75 follow-up).

The settings page never gets the token back, so the Git form sends an empty
field when the user saves without retyping it. That must keep the saved
token; only an explicit `git_password_clear` removes it.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.common.config import Settings
from src.controller.settings_manager import SettingsManager
from src.repositories.app_settings_repository import app_settings_repo


@pytest.fixture
def manager(db_session):
    settings = MagicMock(spec=Settings)
    settings.job_cluster_id = "test-cluster"
    settings.to_dict.return_value = {"job_cluster_id": "test-cluster"}
    return SettingsManager(db=db_session, settings=settings, workspace_client=MagicMock())


def _save_git_form(manager, **payload):
    body = {"git_repo_url": "file:///tmp/repo.git", "git_branch": "main", "git_username": "u"}
    body.update(payload)
    with patch("src.common.git.reinitialize_git_service"):
        manager.update_settings(body)


def _stored_token(db_session):
    return app_settings_repo.get_by_key(db_session, "GIT_PASSWORD")


def test_saving_the_git_form_with_an_empty_token_keeps_the_saved_one(manager, db_session):
    _save_git_form(manager, git_password="secret123")

    _save_git_form(manager, git_password="")

    assert _stored_token(db_session) == "secret123"
    assert manager._settings.GIT_PASSWORD == "secret123"


def test_saving_without_the_token_key_keeps_the_saved_one(manager, db_session):
    _save_git_form(manager, git_password="secret123")

    _save_git_form(manager)

    assert _stored_token(db_session) == "secret123"


def test_a_new_token_replaces_the_saved_one(manager, db_session):
    _save_git_form(manager, git_password="secret123")

    _save_git_form(manager, git_password="newer456")

    assert _stored_token(db_session) == "newer456"
    assert manager._settings.GIT_PASSWORD == "newer456"


def test_the_clear_flag_removes_the_saved_token(manager, db_session):
    _save_git_form(manager, git_password="secret123")

    with patch("src.common.git.reinitialize_git_service"):
        manager.update_settings({"git_password_clear": True})

    assert _stored_token(db_session) is None
    assert manager._settings.GIT_PASSWORD is None


@pytest.mark.parametrize("token, saved", [("secret123", True), (None, False)])
def test_settings_say_whether_a_token_is_saved_without_returning_it(db_session, token, saved):
    settings = MagicMock()
    settings.GIT_PASSWORD = token
    manager = SettingsManager.__new__(SettingsManager)
    manager._settings = settings
    manager._db = db_session
    manager._jobs = None
    manager._available_jobs = []
    manager._installations = {}

    result = manager.get_settings()

    assert result["git_password_set"] is saved
    assert "secret123" not in str(result)
