"""Admin-set ``schedule_cron`` for workflows (#1059).

The saved workflow configuration key ``schedule_cron`` (Settings -> Jobs)
overrides the workflow YAML's schedule on install and update, is applied to an
already-installed job when saved, and is never passed as a job parameter.
"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service import jobs

from src.controller import jobs_manager as jm
from src.controller.jobs_manager import JobsManager, validate_quartz_cron

WORKFLOWS = Path(__file__).resolve().parents[2] / "workflows"
WF = "search_index_reindex"


@pytest.fixture()
def saved(monkeypatch):
    """In-memory stand-in for the workflow_configurations table."""
    store = {}
    monkeypatch.setattr(jm.workflow_configuration_repo, "get_configuration_dict",
                        lambda db, workflow_id: store.get(workflow_id))
    monkeypatch.setattr(jm.workflow_configuration_repo, "upsert",
                        lambda db, workflow_id, configuration: store.__setitem__(workflow_id, dict(configuration)))
    return store


@pytest.fixture()
def installed(monkeypatch):
    inst = {}
    monkeypatch.setattr(jm.workflow_installation_repo, "get_by_workflow_id",
                        lambda db, workflow_id: inst.get(workflow_id))
    return inst


@pytest.fixture()
def mgr():
    client = MagicMock()
    client.jobs.create.return_value = SimpleNamespace(job_id=42)
    return JobsManager(db=MagicMock(), ws_client=client, workflows_root=WORKFLOWS)


def _wf_def(mgr):
    return mgr._get_workflow_definition(WF, job_cluster_id=None)


@pytest.mark.parametrize("expr", ["0 30 2 * * ?", "0 0 */6 * * ? *", "  0 15 3 ? * MON  "])
def test_valid_quartz_expressions(expr):
    assert validate_quartz_cron(expr) == " ".join(expr.split())


@pytest.mark.parametrize("expr", ["", "30 2 * * *", "daily", "0 30 2 * * ? * extra"])
def test_invalid_expressions_are_rejected(expr):
    with pytest.raises(ValueError, match="Quartz"):
        validate_quartz_cron(expr)


def test_yaml_schedule_is_the_default(mgr, saved):
    sched = mgr._resolve_schedule(WF, _wf_def(mgr))
    assert sched.quartz_cron_expression == "0 30 2 * * ?"
    assert sched.pause_status == jobs.PauseStatus.UNPAUSED  # keeps BM25 statistics current


def test_saved_schedule_cron_overrides_yaml_and_unpauses(mgr, saved):
    saved[WF] = {"schedule_cron": "0 0 */6 * * ?", "schedule_timezone": "Europe/Berlin"}
    sched = mgr._resolve_schedule(WF, _wf_def(mgr))
    assert sched.quartz_cron_expression == "0 0 */6 * * ?"
    assert sched.timezone_id == "Europe/Berlin"
    assert sched.pause_status == jobs.PauseStatus.UNPAUSED


def test_empty_schedule_cron_falls_back_to_yaml(mgr, saved):
    saved[WF] = {"schedule_cron": "  "}
    assert mgr._resolve_schedule(WF, _wf_def(mgr)).quartz_cron_expression == "0 30 2 * * ?"


def test_install_uses_the_saved_schedule(mgr, saved):
    saved[WF] = {"schedule_cron": "0 0 4 * * ?"}
    assert mgr.install_workflow(WF) == 42
    kwargs = mgr._client.jobs.create.call_args.kwargs
    assert kwargs["schedule"].quartz_cron_expression == "0 0 4 * * ?"


def test_update_workflow_uses_the_saved_schedule(mgr, saved):
    saved[WF] = {"schedule_cron": "0 0 5 * * ?"}
    mgr.update_workflow(WF, 7)
    new_settings = mgr._client.jobs.update.call_args.kwargs["new_settings"]
    assert new_settings.schedule.quartz_cron_expression == "0 0 5 * * ?"


def test_saving_schedule_cron_applies_it_to_the_installed_job(mgr, saved, installed):
    installed[WF] = SimpleNamespace(job_id="99")
    mgr.update_workflow_configuration(WF, {"schedule_cron": "0  0 1 * * ?", "reindex_all": True})
    call = mgr._client.jobs.update.call_args.kwargs
    assert call["job_id"] == 99
    assert call["new_settings"].schedule.quartz_cron_expression == "0 0 1 * * ?"  # normalised
    assert saved[WF]["schedule_cron"] == "0 0 1 * * ?"


def test_clearing_schedule_cron_restores_the_yaml_schedule(mgr, saved, installed):
    installed[WF] = SimpleNamespace(job_id="99")
    saved[WF] = {"schedule_cron": "0 0 1 * * ?"}
    mgr.update_workflow_configuration(WF, {"schedule_cron": ""})
    assert mgr._client.jobs.update.call_args.kwargs["new_settings"].schedule.quartz_cron_expression == "0 30 2 * * ?"


def test_no_schedule_at_all_removes_it_from_the_job(mgr, saved, installed, monkeypatch):
    installed[WF] = SimpleNamespace(job_id="99")
    real = mgr._get_workflow_definition
    monkeypatch.setattr(mgr, "_get_workflow_definition",
                        lambda wid, job_cluster_id=None: {k: v for k, v in real(wid, job_cluster_id=None).items() if k != "schedule"})
    saved[WF] = {"schedule_cron": "0 0 1 * * ?"}
    mgr.update_workflow_configuration(WF, {"schedule_cron": ""})
    assert mgr._client.jobs.update.call_args.kwargs["fields_to_remove"] == ["schedule"]


def test_not_installed_saves_without_touching_jobs(mgr, saved, installed):
    mgr.update_workflow_configuration(WF, {"schedule_cron": "0 0 1 * * ?"})
    mgr._client.jobs.update.assert_not_called()


def test_invalid_schedule_cron_is_rejected_before_saving(mgr, saved, installed):
    with pytest.raises(ValueError):
        mgr.update_workflow_configuration(WF, {"schedule_cron": "every night"})
    assert WF not in saved


def test_other_config_changes_update_parameters_but_not_the_schedule(mgr, saved, installed):
    installed[WF] = SimpleNamespace(job_id="99")
    saved[WF] = {"schedule_cron": "0 0 1 * * ?"}
    mgr.update_workflow_configuration(WF, {"schedule_cron": "0 0 1 * * ?", "reindex_all": True})
    new_settings = mgr._client.jobs.update.call_args.kwargs["new_settings"]
    assert new_settings.schedule is None                     # unchanged: not re-pushed
    assert {p.name: p.default for p in new_settings.parameters}["reindex_all"] == "True"


def test_an_unchanged_save_doesnt_touch_the_job(mgr, saved, installed):
    installed[WF] = SimpleNamespace(job_id="99")
    saved[WF] = {"schedule_cron": "0 0 1 * * ?", "reindex_all": True}
    mgr.update_workflow_configuration(WF, {"schedule_cron": "0  0 1 * * ?", "reindex_all": True})
    mgr._client.jobs.update.assert_not_called()


def test_a_failed_push_leaves_the_saved_configuration_alone(mgr, saved, installed):
    installed[WF] = SimpleNamespace(job_id="99")
    saved[WF] = {"schedule_cron": "0 0 1 * * ?"}
    mgr._client.jobs.update.side_effect = RuntimeError("jobs API down")
    with pytest.raises(RuntimeError):
        mgr.update_workflow_configuration(WF, {"schedule_cron": "0 0 2 * * ?"})
    assert saved[WF] == {"schedule_cron": "0 0 1 * * ?"}


def test_scheduled_runs_get_the_app_database_as_parameter_defaults(mgr, saved, monkeypatch):
    """Scheduled runs only see the job's parameter defaults, not the merged
    parameters a manual run passes, so install bakes those in."""
    monkeypatch.setattr(mgr, "get_merged_job_parameters", lambda wid, ad_hoc_params=None, saved_config=None: {
        "postgres_host": "ep-x.database.cloud", "postgres_schema": "app_schema", "reindex_all": "false",
    })
    mgr.install_workflow(WF)
    params = {p.name: p.default for p in mgr._client.jobs.create.call_args.kwargs["parameters"]}
    assert params["postgres_host"] == "ep-x.database.cloud" and params["postgres_schema"] == "app_schema"
    assert params["postgres_port"] == "5432"                # YAML default where nothing is resolved


def test_schedule_keys_are_not_job_parameters(mgr, saved):
    saved[WF] = {"schedule_cron": "0 0 1 * * ?", "schedule_timezone": "UTC", "reindex_all": True}
    params = mgr.get_merged_job_parameters(WF)
    assert "schedule_cron" not in params and "schedule_timezone" not in params
    assert params["reindex_all"] == "True"


def test_reindex_workflow_is_listed_with_its_parameters(mgr):
    assert WF in {w["id"] for w in mgr.list_available_workflows()}
    names = {d.name for d in mgr.get_workflow_parameter_definitions(WF)}
    assert names == {"schedule_cron", "reindex_all"}
