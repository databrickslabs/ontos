"""Application config for Databricks workflow jobs (shared by the workflows that run the app's code).

A workflow runs outside the app process: it has to set the host, the warehouse and a few
environment defaults, then call :func:`src.common.config.init_config` before any code that
reads the settings (the managers, the ADM reader). The helper is the one place that does it.
"""
import os
import tempfile
from typing import Optional

from databricks.sdk import WorkspaceClient


def initialize_application_config(ws_client: WorkspaceClient, warehouse_id: Optional[str] = None) -> None:
    """Set the workspace host and the warehouse, then initialise the global settings.

    ``warehouse_id`` (the job's SQL warehouse) wins when given. Otherwise an existing
    ``DATABRICKS_WAREHOUSE_ID`` is kept, and the default is empty (a job that doesn't read
    through SQL needs none).
    """
    from src.common.config import init_config

    # Preserve an explicitly configured host; use the ambient client's resolved host
    # only as fallback.
    workspace_host = os.getenv("DATABRICKS_HOST") or ws_client.config.host
    if not workspace_host:
        raise RuntimeError("Databricks workspace host is unavailable")

    os.environ["DATABRICKS_HOST"] = workspace_host
    if warehouse_id:
        os.environ["DATABRICKS_WAREHOUSE_ID"] = warehouse_id
    else:
        # setdefault preserves an environment-provided value.
        os.environ.setdefault("DATABRICKS_WAREHOUSE_ID", "")
    os.environ.setdefault("APP_AUDIT_LOG_DIR", tempfile.gettempdir())
    init_config()
