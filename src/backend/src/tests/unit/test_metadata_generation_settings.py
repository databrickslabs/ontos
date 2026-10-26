"""Unit tests for the Metadata Generation hardening: admin settings and pre-flight checks.

Runs against the in-memory ``db_session``; Jobs API and UC are mocked. Covers:
persisted settings, the serving-endpoint allow-list, the data-sampling gate,
the per-user active-run and per-run table limits, and the pre-flight check
that marks suggestions of tables the app may not change as Not applicable.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.service.catalog import Privilege, TableType
from databricks.sdk.service.sql import StatementState
from pydantic import ValidationError

from src.common.errors import ConflictError
from src.controller.metadata_generation_manager import (
    JOB_PARAMETERS,
    SETTINGS_KEY,
    WORKFLOW_ID,
    ActiveRunLimitError,
    MetadataGenerationManager,
)
from src.db_models.workflow_installations import WorkflowInstallationDb
from src.models.metadata_generation import (
    MetadataGenerationSettings,
    SelectionItem,
    StartRunRequest,
)
from src.repositories.app_settings_repository import app_settings_repo
from src.routes import metadata_generation_routes as routes

RESULT_COLUMNS = ["object_type", "table_fqn", "column_name", "base_text", "proposed_text"]
SP = "8f1c-app-sp"


def _settings():
    return SimpleNamespace(
        LLM_ENDPOINT="my-endpoint",
        DATABRICKS_CATALOG="app_ontos",
        DATABRICKS_SCHEMA="app_ontos",
        DATABRICKS_WAREHOUSE_ID="wh-1",
        DATABRICKS_VOLUME=None,
    )


def _jobs():
    jobs = MagicMock()
    jobs.run_job.return_value = 111
    jobs.get_job_parameter_names.return_value = None
    return jobs


def _uc(*, tables=None, schemas=None, rows=None, owners=None, views=(), privileges=None, groups=()):
    """A workspace client over a fake UC.

    ``tables``: schema "cat.sch" -> table names; ``owners``: table -> owner;
    ``privileges``: table -> the SP's effective privileges.
    """
    tables, owners, privileges = tables or {}, owners or {}, privileges or {}
    ws = MagicMock()
    ws.schemas.list.side_effect = lambda catalog_name: [
        SimpleNamespace(name=s) for s in (schemas or {}).get(catalog_name, [])
    ]
    ws.tables.list.side_effect = lambda catalog_name, schema_name: [
        SimpleNamespace(name=t) for t in tables.get(f"{catalog_name}.{schema_name}", [])
    ]
    ws.tables.get.side_effect = lambda full_name: SimpleNamespace(
        owner=owners.get(full_name, "someone@x.com"),
        table_type=TableType.VIEW if full_name in views else TableType.MANAGED,
    )
    ws.grants.get_effective.side_effect = lambda securable_type, full_name, principal, page_token=None: SimpleNamespace(
        privilege_assignments=[SimpleNamespace(
            principal=principal,
            privileges=[SimpleNamespace(privilege=p) for p in privileges.get(full_name, [])],
        )],
        next_page_token=None,
    )
    ws.current_user.me.return_value = SimpleNamespace(
        user_name=SP, groups=[SimpleNamespace(display=g) for g in groups],
    )
    ws.statement_execution.execute_statement.return_value = SimpleNamespace(
        statement_id="st-1",
        status=SimpleNamespace(state=StatementState.SUCCEEDED, error=None),
        manifest=SimpleNamespace(
            schema=SimpleNamespace(columns=[SimpleNamespace(name=c) for c in RESULT_COLUMNS]),
            total_chunk_count=1,
        ),
        result=SimpleNamespace(data_array=rows or []),
    )
    return ws


class SyncExecutor:
    def submit(self, fn, *args, **kwargs):
        fn(*args, **kwargs)


def _manager(ws=None, jobs=None):
    return MetadataGenerationManager(
        settings=_settings(),
        jobs_manager=jobs or _jobs(),
        workspace_client_factory=lambda: ws if ws is not None else _uc(),
        ingest_executor=SyncExecutor(),
    )


def _request(fqn="main.sales", type_="schema", **kwargs):
    return StartRunRequest(selection=[SelectionItem(type=type_, fqn=fqn)], **kwargs)


def _save(db_session, **values):
    app_settings_repo.set(db_session, SETTINGS_KEY, MetadataGenerationSettings(**values).model_dump_json())


@pytest.fixture(autouse=True)
def rollback_keeps_fixture_data(db_session, monkeypatch):
    monkeypatch.setattr(db_session, "rollback", MagicMock())


@pytest.fixture
def installation(db_session):
    inst = WorkflowInstallationDb(workflow_id=WORKFLOW_ID, name="Metadata Generation", job_id=42)
    db_session.add(inst)
    db_session.flush()
    return inst


# ---------------------------------------------------------------- settings

def test_settings_default_when_unset_or_invalid(db_session):
    manager = _manager()
    assert manager.get_feature_settings(db_session) == MetadataGenerationSettings()
    app_settings_repo.set(db_session, SETTINGS_KEY, "{not json")
    defaults = manager.get_feature_settings(db_session)
    assert (defaults.max_tables_per_run, defaults.max_active_runs_per_user) == (500, 1)
    assert defaults.allow_data_sampling is False and defaults.send_column_metadata is True


def test_settings_round_trip_and_endpoints_list_the_default_first(db_session):
    manager = _manager()
    saved = manager.update_feature_settings(db_session, MetadataGenerationSettings(
        max_tables_per_run=20, allowed_endpoints=["other-endpoint", "my-endpoint", " other-endpoint "],
    ))
    assert saved.default_endpoint == "my-endpoint"
    assert saved.endpoints == ["my-endpoint", "other-endpoint"]
    assert manager.get_feature_settings(db_session).max_tables_per_run == 20


@pytest.mark.parametrize("name", ["bad name", "x;drop", "-leading"])
def test_settings_reject_invalid_endpoint_names(name):
    with pytest.raises(ValidationError):
        MetadataGenerationSettings(allowed_endpoints=[name])


# ---------------------------------------------------------------- start-run gates

def test_start_run_rejects_endpoints_outside_the_allow_list(db_session, installation):
    manager = _manager()
    with pytest.raises(ValueError, match="not allowed"):
        manager.start_run(db_session, user_id="a@x.com", request=_request(model="rogue-endpoint"))
    _save(db_session, allowed_endpoints=["rogue-endpoint"])
    run = manager.start_run(db_session, user_id="a@x.com", request=_request(model="rogue-endpoint"))
    assert run.options["model"] == "rogue-endpoint"


def test_data_sampling_needs_the_admin_setting(db_session, installation):
    jobs = _jobs()
    manager = _manager(jobs=jobs)
    with pytest.raises(ValueError, match="sample data"):
        manager.start_run(db_session, user_id="a@x.com", request=_request(allow_data=True))
    jobs.run_job.assert_not_called()

    _save(db_session, allow_data_sampling=True, sample_size=7, send_column_metadata=False, max_tables_per_run=30)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request(allow_data=True))
    params = jobs.run_job.call_args.kwargs["job_parameters"]
    assert (params["allow_data"], params["sample_size"]) == ("true", "7")
    assert (params["add_metadata"], params["max_tables"]) == ("false", "30")
    assert run.options["allow_data"] is True and run.options["sample_size"] == 7
    assert run.options["send_column_metadata"] is False


def test_runs_without_sampling_send_no_samples_even_when_permitted(db_session, installation):
    jobs = _jobs()
    _save(db_session, allow_data_sampling=True, sample_size=7)
    _manager(jobs=jobs).start_run(db_session, user_id="a@x.com", request=_request())
    params = jobs.run_job.call_args.kwargs["job_parameters"]
    assert (params["allow_data"], params["sample_size"], params["add_metadata"]) == ("false", "0", "true")


def test_active_run_limit_comes_from_the_settings(db_session, installation):
    _save(db_session, max_active_runs_per_user=2)
    manager = _manager()
    manager.start_run(db_session, user_id="a@x.com", request=_request("main.a"))
    manager.start_run(db_session, user_id="a@x.com", request=_request("main.b"))
    with pytest.raises(ActiveRunLimitError, match="2 Generation Runs"):
        manager.start_run(db_session, user_id="a@x.com", request=_request("main.c"))


def test_table_limit_counts_schemas_catalogs_and_tables(db_session, installation):
    ws = _uc(
        schemas={"main": ["sales", "hr", "information_schema"]},
        tables={"main.sales": ["orders", "customers"], "main.hr": ["people"], "main.information_schema": ["t1", "t2"]},
    )
    manager = _manager(ws=ws)
    # information_schema is skipped and a table inside a picked schema counts once
    assert manager._count_tables(ws, ["main", "main.sales.orders"], stop_after=100) == 3
    assert manager._count_tables(ws, ["main.sales", "main.sales.orders", "x.y.z"], stop_after=100) == 3

    _save(db_session, max_tables_per_run=3)
    selection = [SelectionItem(type="catalog", fqn="main"), SelectionItem(type="table", fqn="main.sales.orders")]
    run = manager.start_run(db_session, user_id="a@x.com", request=StartRunRequest(selection=selection))
    assert run.status == "running"
    with pytest.raises(ValueError, match="more than 2 tables"):
        manager._check_table_limit(["main"], 2)


def test_table_limit_rejects_before_creating_a_run(db_session, installation):
    ws = _uc(tables={"main.sales": ["a", "b", "c"]})
    _save(db_session, max_tables_per_run=2)
    jobs = _jobs()
    manager = _manager(ws=ws, jobs=jobs)
    with pytest.raises(ValueError, match="more than 2 tables"):
        manager.start_run(db_session, user_id="a@x.com", request=_request())
    jobs.run_job.assert_not_called()
    assert manager.list_runs(db_session, "a@x.com") == []


def test_table_limit_leaves_it_to_the_job_when_uc_cant_be_listed(db_session, installation):
    ws = _uc()
    ws.tables.list.side_effect = RuntimeError("UC down")
    _save(db_session, max_tables_per_run=2)
    run = _manager(ws=ws).start_run(db_session, user_id="a@x.com", request=_request())
    assert run.status == "running"


def test_start_run_refuses_a_job_installed_from_an_older_definition(db_session, installation):
    jobs = _jobs()
    jobs.get_job_parameter_names.return_value = {
        "ontos_run_id", "table_names", "output_catalog", "output_schema", "model",
        "comment_style", "allow_data", "sample_size", "regenerate_existing",
    }
    manager = _manager(jobs=jobs)
    with pytest.raises(ConflictError, match="outdated"):
        manager.start_run(db_session, user_id="a@x.com", request=_request())
    jobs.run_job.assert_not_called()
    jobs.get_job_parameter_names.assert_called_once_with(42)
    assert manager.list_runs(db_session, "a@x.com") == []  # no run left behind

    jobs.get_job_parameter_names.return_value |= {"add_metadata", "max_tables"}
    assert manager.start_run(db_session, user_id="a@x.com", request=_request("main.hr")).status == "running"
    # The list matches what is actually passed
    assert set(jobs.run_job.call_args.kwargs["job_parameters"]) == set(JOB_PARAMETERS)


def test_jobs_manager_reads_the_installed_parameter_names():
    from src.controller.jobs_manager import JobsManager

    jobs_manager = JobsManager.__new__(JobsManager)
    jobs_manager._client = MagicMock()
    jobs_manager._client.jobs.get.return_value = SimpleNamespace(
        settings=SimpleNamespace(parameters=[SimpleNamespace(name="a"), SimpleNamespace(name="b")])
    )
    assert jobs_manager.get_job_parameter_names(7) == {"a", "b"}
    jobs_manager._client.jobs.get.side_effect = RuntimeError("gone")
    assert jobs_manager.get_job_parameter_names(7) is None


# ---------------------------------------------------------------- pre-flight writability

def test_unwritable_tables_by_ownership_and_privileges():
    ws = _uc(
        owners={"main.s.mine": SP, "main.s.team": "stewards", "main.s.v_mine": SP},
        views=("main.s.v_other", "main.s.v_mine"),
        privileges={"main.s.modify": [Privilege.MODIFY], "main.s.all": [Privilege.ALL_PRIVILEGES],
                    "main.s.select": [Privilege.SELECT]},
        groups=("stewards",),
    )
    result = _manager(ws=ws)._unwritable_tables({
        "main.s.mine", "main.s.team", "main.s.v_mine", "main.s.v_other",
        "main.s.modify", "main.s.all", "main.s.select", "main.s.none",
    })
    assert set(result) == {"main.s.v_other", "main.s.select", "main.s.none"}
    assert "own this view" in result["main.s.v_other"]
    assert "MODIFY" in result["main.s.select"]


def test_write_privilege_is_found_on_a_later_page_of_effective_grants():
    ws = _uc()
    pages = {
        None: SimpleNamespace(privilege_assignments=[SimpleNamespace(
            principal=SP, privileges=[SimpleNamespace(privilege=Privilege.SELECT)])], next_page_token="p2"),
        "p2": SimpleNamespace(privilege_assignments=[SimpleNamespace(
            principal=SP, privileges=[SimpleNamespace(privilege=Privilege.MODIFY)])], next_page_token=None),
    }
    ws.grants.get_effective.side_effect = lambda securable_type, full_name, principal, page_token=None: pages[page_token]

    assert _manager(ws=ws)._unwritable_tables({"main.s.t"}) == {}
    assert [c.kwargs["page_token"] for c in ws.grants.get_effective.call_args_list] == [None, "p2"]


def test_unwritable_tables_leaves_out_what_it_cant_check():
    ws = _uc()
    ws.tables.get.side_effect = RuntimeError("boom")
    assert _manager(ws=ws)._unwritable_tables({"main.s.t"}) == {}
    ws = _uc()
    ws.current_user.me.side_effect = RuntimeError("no identity")
    assert _manager(ws=ws)._unwritable_tables({"main.s.t"}) == {}


def test_ingest_marks_suggestions_of_unwritable_tables_not_applicable(db_session, installation):
    ws = _uc(
        rows=[
            ["table", "main.sales.orders", None, None, "Orders."],
            ["column", "main.sales.orders", "id", None, "Order id."],
            ["view", "main.sales.revenue", None, None, "Revenue."],
        ],
        privileges={"main.sales.orders": [Privilege.MODIFY]},
        views=("main.sales.revenue",),
    )
    manager = _manager(ws=ws)
    run = manager.start_run(db_session, user_id="a@x.com", request=_request())
    manager.ingest_results(db_session, run)

    by_table = {(s.table_fqn, s.column_name): s for s in manager.list_suggestions(db_session, run.id)}
    assert by_table[("main.sales.orders", None)].status == "pending"
    assert by_table[("main.sales.orders", "id")].status == "pending"
    revenue = by_table[("main.sales.revenue", None)]
    assert revenue.status == "not_applicable"
    assert "own this view" in revenue.error
    # Only reviewable suggestions are offered for review
    assert manager.review_summary(db_session, run.id)[0] == 2


# ---------------------------------------------------------------- routes

def _route_request(manager):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(metadata_generation_manager=manager)),
                           client=SimpleNamespace(host="127.0.0.1"))


def test_settings_routes(db_session):
    manager = _manager()
    request = _route_request(manager)
    assert routes.get_settings(request, db=db_session).endpoints == ["my-endpoint"]

    audit = MagicMock()
    user = SimpleNamespace(username="admin", email="admin@x.com", groups=[])
    body = MetadataGenerationSettings(allow_data_sampling=True, allowed_endpoints=["e2"])
    saved = routes.update_settings(request, body, db=db_session, audit_manager=audit, current_user=user)
    assert saved.endpoints == ["my-endpoint", "e2"]
    kwargs = audit.log_action.call_args.kwargs
    assert kwargs["action"] == "UPDATE_METADATA_GENERATION_SETTINGS" and kwargs["success"] is True
    assert kwargs["details"]["allow_data_sampling"] is True
