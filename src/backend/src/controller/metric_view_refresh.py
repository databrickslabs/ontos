"""The refresh state of a materialized Unity Catalog metric view (#1124, module 6). Read-only.

Materialization is backed by a managed Lakeflow pipeline; Databricks shows its
refresh status and a pipeline link in ``DESCRIBE EXTENDED`` ("Refresh
Information") and in Catalog Explorer
(https://docs.databricks.com/aws/en/metric-views/materialization).

For the SDK the state is read in two steps:

1. ``tables.get``: on a workspace, a materialized metric view has no
   ``TableInfo.pipeline_id``; Unity Catalog keeps the pipeline id in the view's
   ``properties`` (``metric_view.materialization.pipelineUuid``).
   ``pipeline_id`` ("the pipeline ID of the table, applicable for tables created
   by pipelines", https://docs.databricks.com/api/workspace/tables/get) is
   still read first.
2. ``pipelines.get(pipeline_id)`` returns ``state``, ``health`` and
   ``latest_updates`` ("ordered with the newest update first"), each with
   ``update_id``, ``state`` and ``creation_time``
   (https://docs.databricks.com/api/workspace/pipelines/get). ``creation_time``
   is when the update started (seen on a workspace: before the refresh's end).

The pipeline link has the form Databricks returns for a metric view's refresh
(``<host>/#joblist/pipelines/<id>``).

Both are read with the user's client, so the user sees what Unity Catalog and
the pipeline's permissions let them see. Anything not readable is ``unknown``,
never an error.
"""
from enum import Enum
from typing import Any, Dict, Optional

from databricks.sdk import WorkspaceClient

from src.common.logging import get_logger
from src.models.metric_views import MetricViewRefresh, RefreshStatus

logger = get_logger(__name__)

# UpdateStateInfoState values (databricks-sdk) by the status shown
_UPDATE_STATUS: Dict[str, RefreshStatus] = {
    'COMPLETED': 'succeeded',
    'FAILED': 'failed',
    'CANCELED': 'canceled',
    **{state: 'running' for state in (
        'CREATED', 'QUEUED', 'INITIALIZING', 'RESETTING', 'SETTING_UP_TABLES',
        'WAITING_FOR_RESOURCES', 'RUNNING', 'STOPPING',
    )},
}


def _value(value: Any) -> Optional[str]:
    """An SDK enum's value, or a plain string; None otherwise."""
    if isinstance(value, Enum):
        value = value.value
    return value if isinstance(value, str) and value else None


# Where Unity Catalog keeps a materialized metric view's pipeline id
PIPELINE_ID_PROPERTY = 'metric_view.materialization.pipelineUuid'


def _pipeline_id(table: Any) -> Optional[str]:
    """``TableInfo.pipeline_id``, else the pipeline id in the view's properties."""
    properties = getattr(table, 'properties', None)
    from_properties = (
        properties.get(PIPELINE_ID_PROPERTY) if isinstance(properties, dict) else None
    )
    return _value(getattr(table, 'pipeline_id', None)) or _value(from_properties)


def _pipeline_url(ws_client: WorkspaceClient, pipeline_id: str) -> Optional[str]:
    """The pipeline's page in the workspace, or None without a host."""
    host = getattr(getattr(ws_client, 'config', None), 'host', None)
    if not isinstance(host, str) or not host.startswith('https://'):
        return None
    return f"{host.rstrip('/')}/#joblist/pipelines/{pipeline_id}"


def read_refresh_state(
    ws_client: WorkspaceClient, table: Any, spec: Optional[Dict[str, Any]],
) -> Optional[MetricViewRefresh]:
    """The refresh state of a metric view, or None when it isn't materialized.

    A metric view counts as materialized when its definition has a
    ``materialization`` block or Unity Catalog reports a pipeline for it.
    """
    materialization = (spec or {}).get('materialization')
    pipeline_id = _pipeline_id(table)
    if materialization is None and pipeline_id is None:
        return None
    refresh = MetricViewRefresh(
        schedule=_value((materialization or {}).get('schedule')),
        pipeline_id=pipeline_id,
    )
    if pipeline_id is None:
        return refresh
    refresh.pipeline_url = _pipeline_url(ws_client, pipeline_id)
    try:
        pipeline = ws_client.pipelines.get(pipeline_id=pipeline_id)
    except Exception:
        # Not found, no permission on the pipeline, or the API failed: unknown
        logger.info("Refresh state of pipeline %s not readable", pipeline_id, exc_info=True)
        return refresh
    refresh.pipeline_state = _value(getattr(pipeline, 'state', None))
    refresh.health = _value(getattr(pipeline, 'health', None))
    updates = getattr(pipeline, 'latest_updates', None) or []
    latest = updates[0] if isinstance(updates, list) and updates else None
    if latest is not None:
        refresh.latest_update_id = _value(getattr(latest, 'update_id', None))
        refresh.latest_update_state = _value(getattr(latest, 'state', None))
        refresh.latest_update_at = _value(getattr(latest, 'creation_time', None))
        refresh.status = _UPDATE_STATUS.get(refresh.latest_update_state or '', 'unknown')
    return refresh
