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
from databricks.sdk.service import compute, jobs

from src.controller.jobs_manager import JOB_SHAPE_UNEXPECTED, LLM_TASK_ARGUMENTS, JobsManager
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
    manager._jobs.sync_installed_workflow.return_value = None

    manager.update_settings({'llm_endpoint': 'new-endpoint'})

    manager._jobs.sync_installed_workflow.assert_called_once_with(
        WORKFLOW, required_arguments=LLM_TASK_ARGUMENTS,
    )
    assert manager.update_warnings == []


def test_a_job_the_app_cannot_update_is_a_coded_warning(db_session):
    from databricks.sdk.errors import PermissionDenied

    manager = _settings_manager(db_session)
    manager._jobs.sync_installed_workflow.side_effect = PermissionDenied('no CAN_MANAGE')

    manager.update_settings({'llm_endpoint': 'new-endpoint'})

    # The settings are saved; the warning says the job kept the old ones
    assert manager._settings.LLM_ENDPOINT == 'new-endpoint'
    assert [w['code'] for w in manager.update_warnings] == ['compliance_job_not_updated']


def test_a_job_of_another_shape_is_a_coded_warning(db_session):
    manager = _settings_manager(db_session)
    manager._jobs.sync_installed_workflow.return_value = JOB_SHAPE_UNEXPECTED

    manager.update_settings({'llm_enabled': True})

    assert [w['code'] for w in manager.update_warnings] == ['compliance_job_shape_unexpected']


def _installed(monkeypatch, job_id=789):
    monkeypatch.setattr(
        workflow_installation_repo, 'get_by_workflow_id',
        MagicMock(return_value=SimpleNamespace(job_id=job_id)),
    )


OLD_ARGS = ['--policy_filter', '{{job.parameters.policy_filter}}']


def _job(manager, *tasks):
    manager._client.jobs.get.return_value = jobs.Job(
        job_id=789, settings=jobs.JobSettings(tasks=list(tasks)),
    )


def _compliance_task(arguments=None, **fields):
    return jobs.Task(
        task_key=WORKFLOW,
        spark_python_task=jobs.SparkPythonTask(
            python_file='/Workspace/app/compliance_checks/compliance_checks.py',
            parameters=list(OLD_ARGS if arguments is None else arguments),
        ),
        **fields,
    )


def _sync(manager):
    return manager.sync_installed_workflow(WORKFLOW, required_arguments=LLM_TASK_ARGUMENTS)


def _updated(manager):
    return manager._client.jobs.update.call_args.kwargs['new_settings']


def test_a_current_job_gets_only_its_parameters(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    manager._workspace_deployer = MagicMock()
    _installed(monkeypatch)
    current = OLD_ARGS + [
        a for flag in LLM_TASK_ARGUMENTS for a in (flag, f'{{{{job.parameters.{flag[2:]}}}}}')
    ]
    _job(manager, _compliance_task(current))

    assert _sync(manager) is None

    new_settings = _updated(manager)
    assert new_settings.tasks is None
    assert {p.name: p.default for p in new_settings.parameters}['llm_endpoint'] == 'db-endpoint'
    manager._workspace_deployer.deploy_workflow.assert_not_called()


def _llm_args(task):
    args = task.spark_python_task.parameters
    return {args[i]: args[i + 1] for i in range(len(args) - 1) if args[i] in LLM_TASK_ARGUMENTS}


EXPECTED_LLM_ARGS = {
    '--llm_enabled': '{{job.parameters.llm_enabled}}',
    '--llm_endpoint': '{{job.parameters.llm_endpoint}}',
    '--llm_check_max_calls_per_run': '{{job.parameters.llm_check_max_calls_per_run}}',
}


def test_an_older_job_on_a_new_cluster_keeps_it(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    manager._workspace_deployer = MagicMock()
    _installed(monkeypatch)
    cluster = compute.ClusterSpec(spark_version='15.4.x-scala2.12', num_workers=2)
    _job(manager, _compliance_task(new_cluster=cluster, max_retries=3, timeout_seconds=900))

    assert _sync(manager) is None

    manager._workspace_deployer.deploy_workflow.assert_called_once()
    [task] = _updated(manager).tasks
    assert task.new_cluster == cluster
    assert task.environment_key is None and task.existing_cluster_id is None
    assert (task.max_retries, task.timeout_seconds) == (3, 900)
    assert task.spark_python_task.parameters[:2] == OLD_ARGS
    assert _llm_args(task) == EXPECTED_LLM_ARGS
    # The schedule (and its pause status) is not rewritten
    assert _updated(manager).schedule is None


def test_an_older_job_on_a_job_cluster_keeps_it(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    _installed(monkeypatch)
    _job(manager, _compliance_task(job_cluster_key='shared'))

    assert _sync(manager) is None

    new_settings = _updated(manager)
    [task] = new_settings.tasks
    assert task.job_cluster_key == 'shared'
    # job_clusters is not sent, so the job keeps it
    assert new_settings.job_clusters is None
    assert _llm_args(task) == EXPECTED_LLM_ARGS


def test_a_task_the_user_added_is_kept(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    _installed(monkeypatch)
    extra = jobs.Task(
        task_key='notify_owners', depends_on=[jobs.TaskDependency(task_key=WORKFLOW)],
        notebook_task=jobs.NotebookTask(notebook_path='/Workspace/Shared/notify'), max_retries=2,
    )
    _job(manager, _compliance_task(existing_cluster_id='cluster-1'), extra)

    assert _sync(manager) is None

    compliance, kept = _updated(manager).tasks
    assert compliance.existing_cluster_id == 'cluster-1'
    assert _llm_args(compliance) == EXPECTED_LLM_ARGS
    assert kept is extra and kept.max_retries == 2


def test_a_job_without_its_task_only_gets_parameters(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    manager._workspace_deployer = MagicMock()
    _installed(monkeypatch)
    renamed = jobs.Task(task_key='renamed', notebook_task=jobs.NotebookTask(notebook_path='/x'))
    _job(manager, renamed)

    assert _sync(manager) == JOB_SHAPE_UNEXPECTED

    new_settings = _updated(manager)
    assert new_settings.tasks is None
    assert {p.name: p.default for p in new_settings.parameters}['llm_endpoint'] == 'db-endpoint'
    manager._workspace_deployer.deploy_workflow.assert_not_called()


def test_a_permission_error_is_raised_to_the_caller(db_session, llm_settings, monkeypatch):
    from databricks.sdk.errors import PermissionDenied

    manager = _manager(db_session, llm_settings)
    _installed(monkeypatch)
    manager._client.jobs.get.side_effect = PermissionDenied('no CAN_VIEW')

    with pytest.raises(PermissionDenied):
        _sync(manager)
    manager._client.jobs.update.assert_not_called()


def test_nothing_to_update_when_the_job_is_not_installed(db_session, llm_settings, monkeypatch):
    manager = _manager(db_session, llm_settings)
    monkeypatch.setattr(
        workflow_installation_repo, 'get_by_workflow_id', MagicMock(return_value=None),
    )

    assert _sync(manager) is None
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
