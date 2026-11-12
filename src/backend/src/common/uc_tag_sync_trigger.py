"""Request a ``uc_tag_sync`` run after a lifecycle transition.

The job writes each table's ``ontos_lifecycle_status`` tag. A transition into or out of
``deprecated`` / ``retired`` asks for a run right away; other status changes reach
Unity Catalog with the next scheduled run. Without the job installed, nothing is
requested.
"""

from typing import Optional

from src.common.app_state import get_app_state_manager
from src.common.logging import get_logger

logger = get_logger(__name__)

UC_TAG_SYNC_WORKFLOW_ID = "uc_tag_sync"
_ON_DEMAND_STATUSES = frozenset({"deprecated", "retired"})


def request_uc_tag_sync_after_transition(
    entity_type: str,
    entity_id: str,
    from_status: Optional[str],
    to_status: Optional[str],
) -> Optional[int]:
    """Request one run of the installed ``uc_tag_sync`` job; call after the commit.

    Returns the run id, or None when no run was requested. Never raises.
    """
    old, new = (from_status or "").lower(), (to_status or "").lower()
    if old == new or not ({old, new} & _ON_DEMAND_STATUSES):
        return None
    try:
        jobs_manager = get_app_state_manager("jobs_manager")
        if jobs_manager is None:
            return None
        run_id = jobs_manager.run_workflow_unless_pending(UC_TAG_SYNC_WORKFLOW_ID)
        if run_id is not None:
            logger.info(
                "Requested uc_tag_sync run %s after %s %s moved from %s to %s",
                run_id, entity_type, entity_id, old, new,
            )
        return run_id
    except Exception:
        # The status change is already committed and must stand whatever happens here
        # (Databricks API, job lookup), so every error is caught. The next scheduled run
        # updates the tag instead.
        logger.warning(
            "Could not request a uc_tag_sync run after %s %s moved from %s to %s",
            entity_type, entity_id, old, new, exc_info=True,
        )
        return None
