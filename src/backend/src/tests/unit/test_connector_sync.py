"""Connector syncs (#1312 slice 5): incremental re-import and retirement of what the source dropped.

A sync walks its selection completely in sync mode. Items whose listing shows no
change since the last import are not fetched again; changed ones are refreshed.
Assets a complete walk did not see count a miss and are retired after N misses.
"""
import os

os.environ['TESTING'] = 'true'
os.environ['SKIP_STARTUP_TASKS'] = 'true'

import copy
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm.attributes import flag_modified

from src.connectors.tableau import TableauConnector, TableauConnectorConfig, clear_listing_cache
from src.connectors.tableau_client import GraphQLResult, TableauAPIError
from src.controller.assets_manager import AssetsManager
from src.controller.connector_sync_manager import (
    MISSED_PROPERTY,
    RETIRED_BY_SYNC_PROPERTY,
    STATUS_COMPLETED,
    STATUS_INCOMPLETE,
    ConnectorSyncManager,
)
from src.controller.schema_import_manager import SchemaImportManager
from src.db_models.assets import AssetDb
from src.db_models.connections import ConnectionDb
from src.db_models.schema_import_runs import SchemaImportRunDb
from src.models.assets import IMPORTED_KEYS_PROPERTY, public_properties
from src.models.schema_import import ImportMode, ImportRequest
from src.tests.unit.test_tableau_import import (  # noqa: F401 (fixtures)
    FIELDS,
    ORDERS,
    RecordingSnapshots,
    _fresh_cache,
    asset_types,
    osm,
    uc_orders,
)

T0 = "2026-11-01T10:00:00Z"
T1 = "2026-11-06T09:00:00Z"
DS = "p~p1.p~p2.ds~ds1"
WB = "p~p1.wb~wb1"


class SourceClient:
    """A Tableau site whose content and change times the test edits between syncs."""
    server_url = "https://10xx.online.tableau.com"
    site_content_url = "s"
    identity = "pat:test"

    def __init__(self):
        self.projects = [{"id": "p1", "name": "Finance", "updatedAt": T0},
                         {"id": "p2", "name": "Shared", "parentProjectId": "p1", "updatedAt": T0}]
        self.workbooks = [{"id": "wb1", "name": "Orders Overview", "project": {"id": "p1"}, "updatedAt": T0}]
        self.datasources = [{"id": "ds1", "name": "TPCH Orders", "project": {"id": "p2"}, "updatedAt": T0}]
        self.views = [{"id": "v1", "name": "Orders Overview", "contentUrl": "OrdersOverview/sheets/OrdersOverview",
                       "workbook": {"id": "wb1"}, "updatedAt": T0}]
        self.fields = copy.deepcopy(FIELDS)
        self.graphql_error = None
        self.calls = []

    def paginate(self, path, collection, item, params=None):
        return copy.deepcopy({"/projects": self.projects, "/workbooks": self.workbooks, "/datasources": self.datasources,
                              "/workbooks/wb1/views": self.views}.get(path, []))

    def get_json(self, path, params=None):
        self.calls.append(path)
        by_path = {f"/workbooks/{w['id']}": {"workbook": w} for w in self.workbooks}
        by_path.update({f"/views/{v['id']}": {"view": v} for v in self.views})
        by_path.update({f"/datasources/{d['id']}": {"datasource": {**d, "type": "databricks"}} for d in self.datasources})
        if path not in by_path:
            raise TableauAPIError("not found", 404)
        return copy.deepcopy(by_path[path])

    def graphql(self, query, variables=None):
        self.calls.append("graphql")
        if self.graphql_error:
            raise self.graphql_error
        if "WorkbookViews" in query:
            return GraphQLResult({"workbooks": [{
                "upstreamTables": [ORDERS],
                "dashboards": [{"luid": "v1", "upstreamDatasources": [{"luid": "ds1"}]}], "sheets": [],
            }]})
        return GraphQLResult({"publishedDatasources": [{
            "luid": "ds1", "upstreamTables": [{"name": "orders", "schema": "tpch", **ORDERS}], "fields": self.fields,
        }]})


@pytest.fixture
def source():
    return SourceClient()


@pytest.fixture
def importer(source):
    connector = TableauConnector(TableauConnectorConfig(server_url=source.server_url, site_content_url="s"), client=source)
    connections = MagicMock()
    connections.get_connector_for_connection.return_value = connector
    return SchemaImportManager(connections, AssetsManager(), snapshot_manager=RecordingSnapshots())


@pytest.fixture
def sync(db_session, asset_types, uc_orders):
    connection = ConnectionDb(id=uuid4(), name=f"tableau-{uuid4().hex[:6]}", connector_type="tableau", config={})
    db_session.add(connection)
    db_session.flush()
    return ConnectorSyncManager().create(
        db_session, name="Finance", connection_id=connection.id, request={"selected_paths": ["p~p1"]},
        interval_minutes=60, retire_after_misses=3, enabled=True, created_by="u@example.com",
    )


def _run(db, sync, importer):
    clear_listing_cache()
    return ConnectorSyncManager().run(db, sync, importer)


def _asset(db, location):
    return db.query(AssetDb).filter(AssetDb.location == location, AssetDb.platform == "tableau").one()


def test_the_first_sync_imports_the_selection_and_records_the_run(db_session, sync, importer):
    summary = _run(db_session, sync, importer)

    assert summary["status"] == STATUS_COMPLETED and summary["created"] > 0
    model = _asset(db_session, DS)
    assert model.properties["source_updated_at"].startswith("2026-11-01T10:00:00")
    assert model.properties[IMPORTED_KEYS_PROPERTY] and IMPORTED_KEYS_PROPERTY not in public_properties(model.properties)
    run = db_session.get(SchemaImportRunDb, summary["run_id"])
    assert (run.status, run.sync_id, run.trigger) == ("completed", sync.id, "schedule")
    assert sync.last_status == STATUS_COMPLETED and sync.next_due_at > sync.last_run_at


def test_an_unchanged_source_is_not_fetched_again(db_session, sync, importer, source):
    _run(db_session, sync, importer)
    source.calls.clear()

    summary = _run(db_session, sync, importer)

    assert summary["status"] == STATUS_COMPLETED
    assert (summary["created"], summary["refreshed"], summary["missed"]) == (0, 0, 0)
    # Projects are listed; the unchanged workbook and data source are neither fetched nor queried
    assert "graphql" not in source.calls and "/workbooks/wb1" not in source.calls and "/datasources/ds1" not in source.calls


def test_a_changed_data_source_is_refreshed_keeping_what_ontos_and_users_added(db_session, sync, importer, source):
    _run(db_session, sync, importer)
    aov = _asset(db_session, f"{DS}.Avg Order Value")
    aov.properties = {**aov.properties, "steward_note": "kept", "snapshot_opt_out": True}
    flag_modified(aov, "properties")
    db_session.flush()

    source.datasources[0]["updatedAt"] = T1
    source.datasources[0]["description"] = "Orders, cleaned"
    # Avg Order Value is now a plain column: its formula must go
    source.fields[2] = {"__typename": "ColumnField", "name": "Avg Order Value", "role": "MEASURE", "dataType": "REAL",
                        "columns": [{"name": "o_avg", "remoteType": "NUMERIC", "table": ORDERS}]}
    summary = _run(db_session, sync, importer)

    assert summary["refreshed"] >= 2
    model = _asset(db_session, DS)
    assert model.description == "Orders, cleaned" and model.properties["source_updated_at"].startswith("2026-11-06")
    aov = _asset(db_session, f"{DS}.Avg Order Value")
    assert "formula" not in aov.properties and aov.properties["is_calculated"] is False
    assert aov.properties["steward_note"] == "kept" and aov.properties["snapshot_opt_out"] is True


def test_items_missing_from_three_complete_syncs_are_retired_and_come_back(db_session, sync, importer, source):
    _run(db_session, sync, importer)
    workbook, view = _asset(db_session, WB), _asset(db_session, f"{WB}.v~v1")
    removed = source.workbooks.pop()

    for expected in (1, 2):
        summary = _run(db_session, sync, importer)
        assert summary["status"] == STATUS_COMPLETED and summary["retired"] == 0
        assert workbook.properties[MISSED_PROPERTY] == expected and workbook.status == "active"

    summary = _run(db_session, sync, importer)
    assert summary["retired"] == 2  # the workbook and its dashboard
    assert (workbook.status, view.status) == ("retired", "retired") and view.properties[RETIRED_BY_SYNC_PROPERTY]
    assert _asset(db_session, DS).status == "active"

    source.workbooks.append(removed)
    summary = _run(db_session, sync, importer)
    assert summary["reactivated"] == 2
    assert workbook.status == "active" and MISSED_PROPERTY not in workbook.properties
    assert RETIRED_BY_SYNC_PROPERTY not in view.properties


def test_a_field_dropped_from_a_changed_data_source_counts_a_miss(db_session, sync, importer, source):
    _run(db_session, sync, importer)
    source.datasources[0]["updatedAt"] = T1
    source.fields = [f for f in source.fields if f["name"] != "Order Key"]

    _run(db_session, sync, importer)

    assert _asset(db_session, f"{DS}.Order Key").properties[MISSED_PROPERTY] == 1
    assert MISSED_PROPERTY not in _asset(db_session, f"{DS}.Total Price").properties


def test_an_incomplete_walk_counts_no_misses(db_session, sync, importer, source):
    _run(db_session, sync, importer)
    source.workbooks.pop()
    source.datasources[0]["updatedAt"] = T1
    source.graphql_error = TableauAPIError("Metadata API disabled", 400)

    summary = _run(db_session, sync, importer)

    assert summary["status"] == STATUS_INCOMPLETE and summary["incomplete_reasons"]
    assert summary["missed"] == 0 and MISSED_PROPERTY not in _asset(db_session, WB).properties
    assert sync.last_status == STATUS_INCOMPLETE and sync.last_complete_sync_at < sync.last_run_at


def test_retired_by_hand_stays_retired_and_excluded_paths_are_out_of_scope(db_session, sync, importer, source):
    _run(db_session, sync, importer)
    manual = _asset(db_session, f"{WB}.v~v1")
    manual.status = "retired"
    ConnectorSyncManager().update(db_session, sync, request={"selected_paths": ["p~p1"], "excluded_paths": [DS]})
    source.datasources.pop()

    for _ in range(3):
        _run(db_session, sync, importer)

    assert manual.status == "retired" and RETIRED_BY_SYNC_PROPERTY not in manual.properties
    model = _asset(db_session, DS)
    assert model.status == "active" and MISSED_PROPERTY not in model.properties


def test_only_enabled_syncs_that_are_due_run(db_session, sync):
    manager = ConnectorSyncManager()
    assert manager.due(db_session) == [sync]

    sync.next_due_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    db_session.flush()
    assert manager.due(db_session) == []

    manager.update(db_session, sync, enabled=False)
    assert sync.next_due_at is None and manager.due(db_session) == []
    manager.update(db_session, sync, enabled=True)
    assert manager.due(db_session) == [sync]


def test_a_failing_sync_is_recorded_and_notifies_its_owner(db_session, sync):
    broken = MagicMock()
    broken.execute_import.side_effect = RuntimeError("boom")

    summary = ConnectorSyncManager().run(db_session, sync, broken)

    assert summary["status"] == "failed"
    run = db_session.get(SchemaImportRunDb, summary["run_id"])
    assert run.status == "failed" and "boom" in run.error
    assert sync.last_status == "failed" and sync.next_due_at is not None


def test_create_mode_still_leaves_existing_assets_alone(db_session, sync, importer, source):
    _run(db_session, sync, importer)
    source.datasources[0]["updatedAt"] = T1
    source.datasources[0]["description"] = "changed"
    clear_listing_cache()

    result = importer.execute_import(
        db_session, ImportRequest(connection_id=sync.connection_id, selected_paths=["p~p1"], mode=ImportMode.CREATE),
        current_user_id="u@example.com",
    )

    assert result.refreshed == 0 and _asset(db_session, DS).description != "changed"


# --- The connector_sync job ------------------------------------------------------


def test_the_job_runs_due_syncs_and_fails_when_one_fails(db_session, sync, importer, monkeypatch):
    from src.workflows.connector_sync.connector_sync import run_syncs
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    clear_listing_cache()

    assert run_syncs(db_session, ws=None, importer=importer) == 0
    assert sync.last_status == STATUS_COMPLETED
    # Not due again until its interval passed
    assert run_syncs(db_session, ws=None, importer=importer) == 0
    assert db_session.query(SchemaImportRunDb).filter_by(sync_id=sync.id).count() == 1

    broken = MagicMock()
    broken.execute_import.side_effect = RuntimeError("boom")
    assert run_syncs(db_session, ws=None, sync_id=sync.id, importer=broken) == 1
    assert run_syncs(db_session, ws=None, sync_id=str(uuid4()), importer=importer) == 1
