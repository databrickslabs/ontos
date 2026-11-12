"""The compliance job gets the app's effective LLM settings (#1479).

The job runs on Databricks with its own environment: the LLM settings saved
in Settings > LLM (the database, over the app's env) never reached it, so
scheduled LLM_CHECK rules failed with llm_check_disabled. The app passes them
as job parameters, like the database parameters, and the job sets them as
environment variables before it reads its config.
"""
import argparse
import os
import re
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

import src.workflows.compliance_checks.compliance_checks as job
from src.common.config import Settings
from src.controller.jobs_manager import LLM_TASK_ARGUMENTS, JobsManager
from src.controller.settings_manager import SettingsManager
from src.repositories.workflow_installations_repository import workflow_installation_repo

WORKFLOW = 'compliance_checks'
LLM_PARAMS = ('llm_enabled', 'llm_endpoint', 'llm_check_max_calls_per_run')


@pytest.fixture
def llm_settings(test_settings):
    return test_settings.model_copy(update={
        'LLM_ENABLED': True, 'LLM_ENDPOINT': 'db-endpoint',
        'COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_RUN': 50,
    })


def _manager(db_session, settings):
    manager = JobsManager(db=db_session, ws_client=MagicMock(), settings=settings)
    manager.get_workflow_configuration = MagicMock(return_value=None)
    return manager


def test_manual_runs_get_the_effective_llm_settings(db_session, llm_settings):
    merged = _manager(db_session, llm_settings).get_merged_job_parameters(WORKFLOW)

    assert {k: merged.get(k) for k in LLM_PARAMS} == {
        'llm_enabled': 'true', 'llm_endpoint': 'db-endpoint',
        'llm_check_max_calls_per_run': '50',
    }


def test_scheduled_runs_get_them_in_the_job_defaults(db_session, llm_settings):
    manager = _manager(db_session, llm_settings)
    wf_def = manager._get_workflow_definition(WORKFLOW, job_cluster_id=None)

    defaults = {
        p.name: p.default for p in manager._build_persisted_job_parameters(WORKFLOW, wf_def)
    }

    assert defaults['llm_enabled'] == 'true'
    assert defaults['llm_endpoint'] == 'db-endpoint'
    assert defaults['llm_check_max_calls_per_run'] == '50'


def test_llm_disabled_is_passed_as_false(db_session, test_settings):
    merged = _manager(db_session, test_settings).get_merged_job_parameters(WORKFLOW)

    assert (merged['llm_enabled'], merged['llm_endpoint']) == ('false', '')


def test_the_task_passes_every_llm_parameter():
    definition = yaml.safe_load(open(os.path.join(os.path.dirname(job.__file__),
                                                  'compliance_checks.yaml')))
    [task] = definition['tasks']
    args = task['spark_python_task']['parameters']

    for name in LLM_PARAMS:
        assert name in definition['parameters']
        flag = args.index(f'--{name}')
        assert re.fullmatch(r'\{\{job\.parameters\.(\w+)\}\}', args[flag + 1]).group(1) == name


def test_the_job_sets_the_parameters_as_settings(monkeypatch):
    for name in ('LLM_ENABLED', 'LLM_ENDPOINT', 'COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_RUN'):
        # Set first, so monkeypatch restores what the job sets
        monkeypatch.setenv(name, 'x')
        monkeypatch.delenv(name)

    job._apply_llm_parameters(argparse.Namespace(
        llm_enabled='true', llm_endpoint='db-endpoint', llm_check_max_calls_per_run='50',
    ))

    settings = Settings(
        DATABRICKS_HOST='https://x', DATABRICKS_WAREHOUSE_ID='w', APP_AUDIT_LOG_DIR='/tmp',
    )
    assert (settings.LLM_ENABLED, settings.LLM_ENDPOINT) == (True, 'db-endpoint')
    assert settings.COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_RUN == 50


def test_empty_parameters_keep_the_job_environment(monkeypatch):
    monkeypatch.setenv('LLM_ENDPOINT', 'env-endpoint')
    for name in ('LLM_ENABLED', 'COMPLIANCE_LLM_CHECK_MAX_CALLS_PER_RUN'):
        monkeypatch.setenv(name, 'x')
        monkeypatch.delenv(name)

    job._apply_llm_parameters(argparse.Namespace(
        llm_enabled='', llm_endpoint='', llm_check_max_calls_per_run=None,
    ))

    assert os.environ['LLM_ENDPOINT'] == 'env-endpoint'
    assert 'LLM_ENABLED' not in os.environ


def _settings_manager(db_session, cluster_id='test-cluster'):
    settings = MagicMock(spec=Settings)
    settings.job_cluster_id = cluster_id
    settings.to_dict.return_value = {'job_cluster_id': cluster_id}
    manager = SettingsManager(db=db_session, settings=settings, workspace_client=MagicMock())
    manager._jobs = MagicMock()
    return manager


def test_changing_the_llm_settings_syncs_the_installed_job(db_session):
    manager = _settings_manager(db_session)

    manager.update_settings({'llm_endpoint': 'new-endpoint'})

    manager._jobs.sync_installed_workflow.assert_called_once_with(
        WORKFLOW, required_arguments=LLM_TASK_ARGUMENTS,
    )


def test_a_failed_job_update_still_saves_the_settings(db_session):
    manager = _settings_manager(db_session)
    manager._jobs.sync_installed_workflow.side_effect = RuntimeError('job deleted')

    manager.update_settings({'llm_endpoint': 'new-endpoint'})

    assert manager._settings.LLM_ENDPOINT == 'new-endpoint'


def _installed(monkeypatch, job_id=789):
    monkeypatch.setattr(
        workflow_installation_repo, 'get_by_workflow_id',
        MagicMock(return_value=SimpleNamespace(job_id=job_id)),
    )


def _installed_job_with(manager, arguments, cluster_id=None):
    task = SimpleNamespace(
        spark_python_task=SimpleNamespace(parameters=arguments), existing_cluster_id=cluster_id,
    )
    manager._client.jobs.get.return_value = SimpleNamespace(
        settings=SimpleNamespace(tasks=[task]),
    )


def test_a_current_job_gets_only_its_parameters(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    manager._workspace_deployer = MagicMock()
    _installed(monkeypatch)
    _installed_job_with(manager, ['--policy_filter', 'active', *LLM_TASK_ARGUMENTS])

    assert manager.sync_installed_workflow(WORKFLOW, required_arguments=LLM_TASK_ARGUMENTS)

    new_settings = manager._client.jobs.update.call_args.kwargs['new_settings']
    assert new_settings.tasks is None
    assert {p.name: p.default for p in new_settings.parameters}['llm_endpoint'] == 'db-endpoint'
    manager._workspace_deployer.deploy_workflow.assert_not_called()


def test_an_older_job_gets_its_code_and_tasks_again(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    manager._workspace_deployer = MagicMock()
    _installed(monkeypatch)
    _installed_job_with(manager, ['--policy_filter', 'active'], cluster_id='cluster-1')

    assert manager.sync_installed_workflow(WORKFLOW, required_arguments=LLM_TASK_ARGUMENTS)

    manager._workspace_deployer.deploy_workflow.assert_called_once()
    assert manager._workspace_deployer.deploy_workflow.call_args.args[0] == WORKFLOW
    new_settings = manager._client.jobs.update.call_args.kwargs['new_settings']
    [task] = new_settings.tasks
    assert task.existing_cluster_id == 'cluster-1'
    args = task.spark_python_task.parameters
    assert args[args.index('--llm_endpoint') + 1] == '{{job.parameters.llm_endpoint}}'
    # The schedule (and its pause status) is not rewritten
    assert new_settings.schedule is None


def test_an_older_serverless_job_stays_serverless(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    _installed(monkeypatch)
    _installed_job_with(manager, ['--policy_filter', 'active'])

    assert manager.sync_installed_workflow(WORKFLOW, required_arguments=LLM_TASK_ARGUMENTS)

    [task] = manager._client.jobs.update.call_args.kwargs['new_settings'].tasks
    assert task.existing_cluster_id is None


def test_nothing_to_update_when_the_job_is_not_installed(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    monkeypatch.setattr(
        workflow_installation_repo, 'get_by_workflow_id', MagicMock(return_value=None),
    )

    assert not manager.sync_installed_workflow(WORKFLOW, required_arguments=LLM_TASK_ARGUMENTS)
    assert manager.update_installed_workflow(WORKFLOW) is False
    manager._client.jobs.update.assert_not_called()


def test_refresh_updates_the_installed_job_defaults(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    monkeypatch.setattr(
        workflow_installation_repo, 'get_by_workflow_id',
        MagicMock(return_value=SimpleNamespace(job_id=789)),
    )

    assert manager.refresh_installed_job_parameters(WORKFLOW) is True

    update = manager._client.jobs.update.call_args.kwargs
    assert update['job_id'] == 789
    defaults = {p.name: p.default for p in update['new_settings'].parameters}
    assert defaults['llm_endpoint'] == 'db-endpoint'
