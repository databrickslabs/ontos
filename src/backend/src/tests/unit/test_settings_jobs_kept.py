"""Saving one settings form must not uninstall the Databricks jobs.

Each settings form (Git, General, UI customization, Delivery) sends only its
own keys. A payload without `enabled_jobs` used to be read as "no jobs
enabled", so every installed job was removed and the job cluster and sync
settings were cleared. Only the Jobs screen, which sends `enabled_jobs`,
changes the installed jobs.
"""
from unittest.mock import MagicMock, patch

import pytest

from src.common.config import Settings
from src.controller.settings_manager import SettingsManager
from src.db_models.workflow_installations import WorkflowInstallationDb

WORKFLOW_ID = "data_quality_checks"
JOB_ID = 4242


@pytest.fixture
def manager(db_session):
    settings = MagicMock(spec=Settings)
    settings.job_cluster_id = "cl-1234"
    settings.enabled_jobs = [WORKFLOW_ID]
    settings.sync_enabled = True
    settings.sync_repository = "https://example.com/org/sync.git"
    settings.to_dict.return_value = {}
    manager = SettingsManager(db=db_session, settings=settings, workspace_client=MagicMock())
    jobs = MagicMock()
    jobs.list_available_workflows.return_value = [{"id": WORKFLOW_ID}]
    jobs.get_workflow_statuses.return_value = {}
    manager._jobs = jobs
    db_session.add(WorkflowInstallationDb(workflow_id=WORKFLOW_ID, name="DQ checks", job_id=JOB_ID))
    db_session.flush()
    return manager


def _save(manager, payload):
    with patch("src.common.git.reinitialize_git_service"):
        manager.update_settings(payload)


def _assert_jobs_untouched(manager):
    manager._jobs.remove_workflow.assert_not_called()
    manager._jobs.install_workflow.assert_not_called()
    assert manager._settings.job_cluster_id == "cl-1234"
    assert manager._settings.enabled_jobs == [WORKFLOW_ID]
    assert manager._settings.sync_enabled is True
    assert manager._settings.sync_repository == "https://example.com/org/sync.git"


def test_saving_the_git_form_keeps_the_installed_jobs(manager):
    _save(manager, {
        "git_repo_url": "https://example.com/org/repo.git",
        "git_branch": "main",
        "git_username": "",
    })

    _assert_jobs_untouched(manager)


def test_removing_the_saved_token_keeps_the_installed_jobs(manager):
    _save(manager, {"git_password_clear": True})

    _assert_jobs_untouched(manager)


def test_saving_the_general_form_keeps_the_installed_jobs(manager):
    _save(manager, {
        "databricks_catalog": "app_data",
        "databricks_schema": "app_ontos",
        "databricks_volume": "app_files",
        "llm_enabled": False,
        "allow_job_enablement_requests": False,
    })

    _assert_jobs_untouched(manager)


def test_the_jobs_screen_with_no_job_enabled_removes_them(manager):
    _save(manager, {"job_cluster_id": None, "enabled_jobs": []})

    manager._jobs.remove_workflow.assert_called_once_with(JOB_ID)
    assert manager._settings.enabled_jobs == []
    assert manager._settings.job_cluster_id is None


def test_a_new_token_wins_over_a_clear_in_the_same_payload(manager):
    _save(manager, {"git_password": "fresh-token", "git_password_clear": True})

    assert manager._settings.GIT_PASSWORD == "fresh-token"


@pytest.mark.parametrize("payload, recorded", [
    ({"git_password": "s3cret-value"}, "set"),
    ({"git_password_clear": True}, "cleared"),
    ({"git_password": ""}, None),
])
def test_the_audit_records_what_happened_to_the_token_but_never_its_value(payload, recorded):
    import asyncio
    from src.routes.settings_routes import update_settings

    background_tasks = MagicMock()
    settings_manager = MagicMock()
    asyncio.run(update_settings(
        request=MagicMock(),
        background_tasks=background_tasks,
        db=MagicMock(),
        audit_manager=MagicMock(),
        current_user=MagicMock(username="admin@example.com"),
        settings_payload=payload,
        manager=settings_manager,
        _=True,
    ))

    details = background_tasks.add_task.call_args.kwargs["details"]
    assert details.get("git_password") == recorded
    assert "s3cret-value" not in repr(details)
