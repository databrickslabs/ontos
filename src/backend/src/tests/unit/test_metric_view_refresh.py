"""The refresh state of a materialized metric view (#1124, module 6).

Read with the user's client: Unity Catalog's ``pipeline_id`` on the table, then
the pipeline's latest update. Anything unreadable is ``unknown``.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from databricks.sdk.errors import NotFound, PermissionDenied
from databricks.sdk.service.pipelines import (
    GetPipelineResponse, GetPipelineResponseHealth, PipelineState, UpdateStateInfo,
    UpdateStateInfoState,
)

from src.controller.metric_view_refresh import read_refresh_state

MATERIALIZED = {
    'materialization': {'schedule': 'EVERY 6 HOURS', 'mode': 'relaxed',
                        'materialized_views': []},
}
PIPELINE = 'pipe-123'


def _ws(pipeline=None, error=None, host='https://adb-1.example.com/'):
    ws = MagicMock()
    ws.config.host = host
    if error is not None:
        ws.pipelines.get.side_effect = error
    else:
        ws.pipelines.get.return_value = pipeline
    return ws


def _pipeline(*states):
    return GetPipelineResponse(
        pipeline_id=PIPELINE, state=PipelineState.IDLE, health=GetPipelineResponseHealth.HEALTHY,
        latest_updates=[
            UpdateStateInfo(update_id=f'u{i}', state=state,
                            creation_time=f'2026-10-3{i}T06:00:00Z')
            for i, state in enumerate(states)
        ],
    )


def test_a_view_without_materialization_or_pipeline_has_no_refresh_state():
    ws = _ws()

    assert read_refresh_state(ws, SimpleNamespace(pipeline_id=None), {'materialization': None}) \
        is None
    ws.pipelines.get.assert_not_called()


def test_the_latest_update_gives_the_status_time_and_pipeline_link():
    ws = _ws(_pipeline(UpdateStateInfoState.COMPLETED, UpdateStateInfoState.FAILED))

    refresh = read_refresh_state(ws, SimpleNamespace(pipeline_id=PIPELINE), MATERIALIZED)

    ws.pipelines.get.assert_called_once_with(pipeline_id=PIPELINE)
    # Newest update first
    assert refresh.status == 'succeeded'
    assert refresh.latest_update_id == 'u0'
    assert refresh.latest_update_state == 'COMPLETED'
    assert refresh.latest_update_at == '2026-10-30T06:00:00Z'
    assert refresh.schedule == 'EVERY 6 HOURS'
    assert refresh.pipeline_state == 'IDLE' and refresh.health == 'HEALTHY'
    # The link Databricks itself returns for a metric view's refresh
    assert refresh.pipeline_url == f'https://adb-1.example.com/#joblist/pipelines/{PIPELINE}'


def test_the_pipeline_id_of_a_metric_view_is_read_from_its_properties():
    # Seen on a workspace: a materialized metric view has no TableInfo.pipeline_id;
    # Unity Catalog keeps the pipeline id in the view's properties
    ws = _ws(_pipeline(UpdateStateInfoState.COMPLETED))
    table = SimpleNamespace(
        pipeline_id=None,
        properties={'metric_view.materialization.pipelineUuid': PIPELINE},
    )

    refresh = read_refresh_state(ws, table, MATERIALIZED)

    ws.pipelines.get.assert_called_once_with(pipeline_id=PIPELINE)
    assert refresh.pipeline_id == PIPELINE and refresh.status == 'succeeded'


@pytest.mark.parametrize('state, status', [
    (UpdateStateInfoState.FAILED, 'failed'),
    (UpdateStateInfoState.CANCELED, 'canceled'),
    (UpdateStateInfoState.RUNNING, 'running'),
    (UpdateStateInfoState.WAITING_FOR_RESOURCES, 'running'),
])
def test_update_states_map_to_a_status(state, status):
    refresh = read_refresh_state(
        _ws(_pipeline(state)), SimpleNamespace(pipeline_id=PIPELINE), MATERIALIZED,
    )

    assert refresh.status == status


def test_a_pipeline_without_updates_is_unknown():
    refresh = read_refresh_state(
        _ws(_pipeline()), SimpleNamespace(pipeline_id=PIPELINE), MATERIALIZED,
    )

    assert refresh.status == 'unknown' and refresh.latest_update_id is None
    assert refresh.pipeline_state == 'IDLE'


@pytest.mark.parametrize('error', [
    NotFound('no pipeline'), PermissionDenied('no CAN_VIEW'), RuntimeError('boom'),
])
def test_an_unreadable_pipeline_is_unknown_not_an_error(error):
    refresh = read_refresh_state(
        _ws(error=error), SimpleNamespace(pipeline_id=PIPELINE), MATERIALIZED,
    )

    assert refresh.status == 'unknown'
    assert refresh.pipeline_id == PIPELINE and refresh.pipeline_state is None


def test_a_materialized_definition_without_a_pipeline_id_is_unknown():
    ws = _ws()

    refresh = read_refresh_state(ws, SimpleNamespace(), MATERIALIZED)

    assert refresh.status == 'unknown' and refresh.schedule == 'EVERY 6 HOURS'
    assert refresh.pipeline_id is None and refresh.pipeline_url is None
    ws.pipelines.get.assert_not_called()


def test_a_pipeline_reported_by_unity_catalog_counts_without_a_block():
    refresh = read_refresh_state(
        _ws(_pipeline(UpdateStateInfoState.COMPLETED), host=None),
        SimpleNamespace(pipeline_id=PIPELINE), {'materialization': None},
    )

    assert refresh.status == 'succeeded'
    assert refresh.schedule is None and refresh.pipeline_url is None
