"""Baselines of Unity Catalog metric views and their drift (#1124, module 3).

A metric view's baseline is the definition its drift is checked against, kept
normalized (``common/metric_view_normalization.py``) with its digest.

- **When a baseline is recorded.** The PRD keeps "the last approved
  definition"; approvals arrive with change requests (phase 3). Until then the
  first definition Ontos parses for the metric view becomes its baseline,
  without ``approved_at`` or ``request_id``, so it is never shown as approved.
  A delivered change request replaces it, with its decision time and id,
  once Unity Catalog is read back with its definition (``_adopt_applied_request``).
- **When drift is checked.** Each time the metric view behind an asset is read
  (``GET /api/assets/{id}/metric-view``): the definition just read is
  normalized and its digest compared with the baseline's.
- **States.** ``in_sync`` (same digest), ``drifted`` (another digest),
  ``unknown`` (the definition can't be parsed, or the check itself failed).
  The check never fails the read: errors are logged and reported as unknown.
- **Notification.** The asset's owners get one notification per detected
  change: when a drifted digest differs from the one observed last.
"""
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from src.common.logging import get_logger
from src.common.metric_view_normalization import definition_digest, normalize_metric_view
from src.common.metric_views import metric_view_entity_id
from src.common.notification_i18n import notification_i18n_data
from src.db_models.metric_view_baselines import MetricViewBaselineDb
from src.models.metric_views import MetricViewBaseline, MetricViewDrift
from src.models.notifications import Notification, NotificationType
from src.repositories.entity_owners_repository import resolve_owner_emails
from src.repositories.metric_view_baselines_repository import metric_view_baselines_repo
from src.repositories.notification_repository import notification_repo

logger = get_logger(__name__)

DRIFT_TITLE_KEY = 'notifications:metricViewDrift.title'
DRIFT_DESCRIPTION_KEY = 'notifications:metricViewDrift.description'


def _baseline(row: Optional[MetricViewBaselineDb]) -> Optional[MetricViewBaseline]:
    if row is None:
        return None
    return MetricViewBaseline(
        digest=row.digest, approved_at=row.approved_at, request_id=row.request_id,
        recorded_at=row.created_at,
    )


class MetricViewBaselinesManager:
    def __init__(self, db: Session):
        self._db = db
        self._repo = metric_view_baselines_repo

    def check(
        self, fqn: str, spec: Optional[Dict[str, Any]], *, asset_id: UUID,
        user_email: Optional[str] = None,
    ) -> Tuple[Optional[MetricViewBaseline], MetricViewDrift]:
        """The baseline of the metric view ``fqn`` and its drift state for ``spec``.

        ``spec`` is the definition just read, parsed (None when it couldn't be).
        Records the baseline when there is none, stores the check's result, and
        notifies the owners of ``asset_id`` of a newly detected change. Never
        raises: a failed check is logged and reported as ``unknown``.
        """
        try:
            with self._db.begin_nested():
                return self._check(metric_view_entity_id(fqn), spec, asset_id, user_email)
        except Exception:
            # The drift state is extra information: it never fails the read
            logger.warning("Drift check of metric view %s failed", fqn, exc_info=True)
            return None, MetricViewDrift(state='unknown')

    def _check(
        self, key: str, spec: Optional[Dict[str, Any]], asset_id: UUID,
        user_email: Optional[str],
    ) -> Tuple[Optional[MetricViewBaseline], MetricViewDrift]:
        now = datetime.now(timezone.utc)
        baseline = self._repo.get_by_fqn(self._db, key)
        if spec is None:
            if baseline is not None:
                self._repo.record_unknown(self._db, baseline, checked_at=now)
            return _baseline(baseline), MetricViewDrift(
                state='unknown', last_checked_at=now if baseline is not None else None,
            )

        normalized = normalize_metric_view(spec)
        digest = definition_digest(normalized)
        if baseline is None:
            baseline = self._repo.create_if_absent(
                self._db, fqn=key, definition=normalized, digest=digest, checked_at=now,
                created_by=user_email,
            )
        self._adopt_applied_request(key, normalized, digest, baseline)
        state ='in_sync' if digest == baseline.digest else 'drifted'
        changed = self._repo.record_observation(
            self._db, baseline, observed_digest=digest, drift_state=state, checked_at=now,
        )
        if changed and state == 'drifted':
            self._notify_owners(key, asset_id)
        return _baseline(baseline), MetricViewDrift(
            state=state, current_digest=digest, last_checked_at=now,
        )

    def _adopt_applied_request(
        self, key: str, normalized: Dict[str, Any], digest: str,
        baseline: MetricViewBaselineDb,
    ) -> None:
        """Make the definition just read the baseline when it is a delivered request's.

        Ontos doesn't apply change requests (Indirect and Manual delivery), so
        an approval alone doesn't move the baseline: it moves when Unity Catalog
        is read back with exactly the approved definition.
        """
        from src.controller.metric_view_change_requests_manager import adopt_applied_request

        applied = adopt_applied_request(self._db, key, digest)
        if applied is None:
            return
        request, _ = applied
        baseline.definition = normalized
        baseline.digest = digest
        baseline.approved_at = request.decided_at
        baseline.request_id = str(request.id)
        self._db.flush()
        logger.info("Metric view %s: the definition of change request %s is the new baseline",
                    key, request.id)

    def _notify_owners(self, fqn: str, asset_id: UUID) -> None:
        """One notification to each owner of the asset that the definition changed."""
        owners = resolve_owner_emails(self._db, 'asset', str(asset_id))
        if not owners:
            logger.info("Metric view %s drifted; asset %s has no owner to notify",
                        fqn, asset_id)
            return
        data = notification_i18n_data(DRIFT_TITLE_KEY, DRIFT_DESCRIPTION_KEY, fqn=fqn)
        now = datetime.now(timezone.utc)
        for owner in owners:
            notification_repo.create(self._db, obj_in=Notification(
                id=str(uuid4()),
                type=NotificationType.WARNING,
                title='Metric view definition changed',
                description=(
                    f"The definition of the metric view {fqn} in Unity Catalog no longer "
                    "matches its baseline in Ontos."
                ),
                link=f'/assets/{asset_id}',
                recipient=owner,
                created_at=now,
                data=data,
            ))
        logger.info("Metric view %s drifted; notified %d owner(s) of asset %s",
                    fqn, len(owners), asset_id)
