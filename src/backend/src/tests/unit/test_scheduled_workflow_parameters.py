"""Scheduled jobs persist the parameters Ontos injects into manual runs (#1301)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from src.controller.jobs_manager import JobsManager
from src.repositories.workflow_configurations_repository import workflow_configuration_repo
from src.repositories.workflow_installations_repository import workflow_installation_repo


def _defaults(parameters):
    return {parameter.name: parameter.default for parameter in parameters}


def test_persisted_defaults_merge_yaml_saved_config_and_database_parameters():
    manager = JobsManager(db=MagicMock(), ws_client=MagicMock())
    manager.get_merged_job_parameters = MagicMock(return_value={
        'tag_sync_configs': '[{"entity_type":"semantic_assignment"}]',
        'lakebase_instance_name': 'projects/app/branches/production/endpoints/primary',
    })
    workflow = {
        'parameters': {
            'tag_sync_configs': '[]',
            'lakebase_instance_name': '',
            'dry_run': 'false',
        }
    }

    persisted = _defaults(
        manager._build_persisted_job_parameters('uc_tag_sync', workflow)
    )

    assert persisted == {
        'tag_sync_configs': '[{"entity_type":"semantic_assignment"}]',
        'lakebase_instance_name': 'projects/app/branches/production/endpoints/primary',
        'dry_run': 'false',
    }


def test_install_uses_effective_parameters_as_job_defaults(monkeypatch):
    db = MagicMock()
    client = MagicMock()
    client.jobs.create.return_value = SimpleNamespace(job_id=123)
    manager = JobsManager(db=db, ws_client=client)
    workflow = {'name': 'Scheduled', 'tasks': [], 'parameters': {'database': ''}}
    manager._get_workflow_definition = MagicMock(return_value=workflow)
    manager._build_tasks_from_definition = MagicMock(return_value=[])
    manager._build_persisted_job_parameters = MagicMock(return_value=['effective'])
    monkeypatch.setattr(workflow_installation_repo, 'create', MagicMock())

    assert manager.install_workflow('scheduled') == 123

    assert client.jobs.create.call_args.kwargs['parameters'] == ['effective']
    manager._build_persisted_job_parameters.assert_called_once_with(
        'scheduled', workflow
    )


def test_saving_configuration_refreshes_installed_job_defaults(monkeypatch):
    db = MagicMock()
    client = MagicMock()
    manager = JobsManager(db=db, ws_client=client)
    workflow = {'parameters': {'tag_sync_configs': '[]'}}
    manager._get_workflow_definition = MagicMock(return_value=workflow)
    manager._build_persisted_job_parameters = MagicMock(return_value=['effective'])
    monkeypatch.setattr(workflow_configuration_repo, 'upsert', MagicMock())
    monkeypatch.setattr(
        workflow_configuration_repo,
        'get_configuration_dict',
        MagicMock(return_value={'tag_sync_configs': []}),
    )
    monkeypatch.setattr(
        workflow_installation_repo,
        'get_by_workflow_id',
        MagicMock(return_value=SimpleNamespace(job_id=456)),
    )

    manager.update_workflow_configuration(
        'uc_tag_sync', {'tag_sync_configs': []}
    )

    update = client.jobs.update.call_args.kwargs
    assert update['job_id'] == 456
    assert update['new_settings'].parameters == ['effective']


def test_manual_ad_hoc_parameters_still_win():
    manager = JobsManager(db=MagicMock(), ws_client=MagicMock())
    manager.get_workflow_configuration = MagicMock(
        return_value={'dry_run': 'false', 'limit': '100'}
    )

    merged = manager.get_merged_job_parameters(
        'uc_tag_sync', ad_hoc_params={'dry_run': 'true'}
    )

    assert merged == {'dry_run': 'true', 'limit': '100'}
