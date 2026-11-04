"""Definition change requests of Unity Catalog metric views (#1124 phase 3).

A change request proposes a new YAML definition for the metric view behind an
asset. Ontos proposes; it never applies a definition itself in this phase.

- **Draft.** The proposed YAML must parse; the definition read from Unity
  Catalog (as the user) at that moment is kept as the request's base, with
  the digest of its normalized form and the view's owner.
- **Pre-checks** (on the draft and again on submit, coded errors): the YAML
  parses, has a ``source``, no ``$$`` (it is delivered between ``$$``), unique
  field names and differs from the base; on submit also: the base still matches
  Unity Catalog, and the materialization constraints Unity Catalog documents
  (owner unchanged, no group owner, no row filter, column mask or ABAC policy
  on a source the user can see). A field with concept links that the proposal
  removes is a warning, kept on the request for the review.
- **Review.** Submit fires ``on_request_definition_change`` for the
  ``metric_view`` entity (the asset); the default workflow's approval step goes
  to the asset's owners other than the requester, else to the Data Stewards
  and admins. The requester can't decide it (``handle-approval`` refuses it,
  and the decision is checked again here). Without an approval step paused,
  the submission is refused and nothing is delivered.
- **Delivery** after an approval, through the active delivery modes:
  Indirect writes the YAML and its ``ALTER VIEW`` DDL to the Git working copy
  (``DeliveryService``, change type ``METRIC_VIEW_UPDATE``; the pull request
  is #1106's); Manual notifies the owners with the DDL. Direct is phase 4: it
  is not used here, and when it is the only active mode the owners get the
  Manual notification. A failed delivery leaves the request ``failed`` with a
  coded error and the baseline untouched.
- **Baseline.** Ontos applies nothing, so an approval doesn't move the
  baseline: the proposed definition becomes the baseline when Unity Catalog
  is read back with it (``MetricViewBaselinesManager.check``, see
  ``adopt_applied_request``). Until then the view is reported as it is.
- **Audit.** Every step is written to the audit log with the request id, the
  view's FQN and the digests of the base and proposed definitions.
"""
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID, uuid4

import yaml
from databricks.sdk import WorkspaceClient
from databricks.sdk.errors import BadRequest, NotFound, PermissionDenied, Unauthenticated
from databricks.sdk.service.catalog import TableType
from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.common.metric_view_normalization import definition_digest, normalize_metric_view
from src.common.metric_views import (
    MAX_DEFINITION_LENGTH, metric_view_entity_id, parse_metric_view_definition,
)
from src.common.notification_i18n import notification_i18n_data
from src.controller.metric_views_manager import (
    MetricViewNotFoundError, UserTokenRequiredError, _uc_fqn,
)
from src.db_models.metric_view_change_requests import MetricViewChangeRequestDb
from src.models.metric_view_change_requests import (
    CodedNote, MetricViewChangeRequestCreate, MetricViewChangeRequestDetail,
    MetricViewChangeRequestRead,
)
from src.models.notifications import Notification, NotificationType
from src.repositories.assets_repository import asset_repo
from src.repositories.entity_owners_repository import resolve_owner_emails
from src.repositories.metric_view_change_requests_repository import (
    metric_view_change_requests_repo,
)
from src.repositories.notification_repository import notification_repo

logger = get_logger(__name__)

AUDIT_FEATURE = 'assets'
DELIVERY_SUBDIR = 'metric_views'
MANUAL_TITLE_KEY = 'notifications:metricViewChangeManual.title'
MANUAL_DESCRIPTION_KEY = 'notifications:metricViewChangeManual.description'
FAILED_TITLE_KEY = 'notifications:metricViewChangeFailed.title'
FAILED_DESCRIPTION_KEY = 'notifications:metricViewChangeFailed.description'

_UUID = re.compile(r'^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$')
# A three-part table name (possibly backquoted), as opposed to a SQL query
_TABLE_NAME = re.compile(r'^(`[^`]+`|[\w-]+)(\.(`[^`]+`|[\w-]+)){2}$')


class ChangeRequestError(CodedValueError):
    """A refused change request action; ``http_status`` is the HTTP status of the answer."""

    def __init__(self, code: str, message: str, http_status: int = 400, **params: Any):
        super().__init__(message, **params)
        self.code = code
        self.http_status = http_status


class _DeliveryError(Exception):
    def __init__(self, code: str, message: str, **params: Any):
        super().__init__(message)
        self.code = code
        self.message = message
        self.params = params


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _note(code: str, message: str, **params: Any) -> Dict[str, Any]:
    return {'code': code, 'message': message, 'params': params}


def _quote_identifier(part: str) -> str:
    return '`' + part.replace('`', '``') + '`'


def build_ddl(fqn: str, definition: str) -> str:
    """The statement that replaces the definition of the metric view ``fqn``.

    ``ALTER VIEW`` replaces the whole definition, so the full proposed YAML is
    sent between ``$$`` (the pre-checks refuse a YAML containing ``$$``).
    """
    name = '.'.join(_quote_identifier(p) for p in fqn.split('.'))
    return f"ALTER VIEW {name} AS $$\n{definition.rstrip()}\n$$"


def delivery_filename(fqn: str, extension: str) -> str:
    """The file a metric view's definition is delivered to: one per view, named by its FQN."""
    safe = re.sub(r'[^A-Za-z0-9._-]', '_', fqn.lower()).strip('.') or 'metric_view'
    return f"{safe}.{extension}"


def is_group_principal(owner: Optional[str]) -> bool:
    """Whether a Unity Catalog owner names a group.

    Unity Catalog gives users as their email and service principals as their
    application id (a UUID); any other principal is read as a group.
    """
    value = (owner or '').strip()
    return bool(value) and '@' not in value and not _UUID.match(value)


def _field_names(spec: Dict[str, Any]) -> List[str]:
    return [f['name'] for kind in ('dimensions', 'measures') for f in spec.get(kind) or []]


def validate_proposal(definition: str) -> Dict[str, Any]:
    """The parsed proposal, or a coded ``ChangeRequestError`` (422) saying why it can't be."""
    if not definition or not definition.strip():
        raise ChangeRequestError('metric_view_definition_invalid',
                                 'The proposed definition is empty.', 422, reason='empty')
    if len(definition) > MAX_DEFINITION_LENGTH:
        raise ChangeRequestError(
            'metric_view_definition_invalid', 'The proposed definition is too long.', 422,
            reason='too_long', limit=MAX_DEFINITION_LENGTH,
        )
    try:
        yaml.safe_load(definition)
    except yaml.MarkedYAMLError as e:
        mark = e.problem_mark or e.context_mark
        params = {'line': mark.line + 1, 'column': mark.column + 1} if mark else {}
        raise ChangeRequestError(
            'metric_view_definition_invalid_yaml', 'The proposed definition is not valid YAML.',
            422, **params,
        )
    except yaml.YAMLError:
        raise ChangeRequestError('metric_view_definition_invalid_yaml',
                                 'The proposed definition is not valid YAML.', 422)
    except RecursionError:
        raise ChangeRequestError('metric_view_definition_invalid',
                                 'The proposed definition is nested too deeply.', 422,
                                 reason='too_deep')
    spec = parse_metric_view_definition(definition)
    if spec is None:
        raise ChangeRequestError(
            'metric_view_definition_invalid',
            'The proposed definition is not a metric view definition (a YAML mapping).', 422,
            reason='not_mapping',
        )
    if not spec.get('source'):
        raise ChangeRequestError('metric_view_definition_source_missing',
                                 'The proposed definition has no source.', 422)
    if '$$' in definition:
        raise ChangeRequestError(
            'metric_view_definition_dollar_quote',
            "The proposed definition can't contain '$$': it is delivered between '$$'.", 422,
        )
    seen = set()
    for name in _field_names(spec):
        key = name.casefold()
        if key in seen:
            raise ChangeRequestError(
                'metric_view_duplicate_field',
                f"The field name '{name}' is used more than once.", 422, field=name,
            )
        seen.add(key)
    return spec


def _digest(spec: Dict[str, Any]) -> str:
    return definition_digest(normalize_metric_view(spec))


def _audit(action: str, request: MetricViewChangeRequestDb, username: Optional[str],
           success: bool = True, **details: Any) -> None:
    """Audit a step of a request, with its id, the view's FQN and both digests."""
    try:
        from src.controller.audit_manager import log_system_action
        log_system_action(
            username=username or 'system', feature=AUDIT_FEATURE, action=action,
            success=success,
            details={
                'request_id': str(request.id),
                'asset_id': str(request.asset_id),
                'metric_view_fqn': request.metric_view_fqn,
                'base_digest': request.base_digest,
                'proposed_digest': request.proposed_digest,
                **details,
            },
        )
    except Exception:  # The audit never changes the outcome of the request
        logger.error("Could not audit %s of metric view change request %s", action,
                     request.id, exc_info=True)


def to_read(row: MetricViewChangeRequestDb) -> MetricViewChangeRequestRead:
    return MetricViewChangeRequestRead(**_read_fields(row))


def _read_fields(row: MetricViewChangeRequestDb) -> Dict[str, Any]:
    error = None
    if row.error_code:
        params = dict(row.error_params or {})
        message = params.pop('message', None) or row.error_code
        error = CodedNote(code=row.error_code, message=message, params=params)
    return dict(
        id=row.id, asset_id=row.asset_id, metric_view_fqn=row.metric_view_fqn,
        status=row.status, justification=row.justification, base_digest=row.base_digest,
        proposed_digest=row.proposed_digest, proposed_definition=row.proposed_definition,
        warnings=[CodedNote(**w) for w in row.warnings or []], error=error,
        delivery_mode=row.delivery_mode, delivery_reference=row.delivery_reference,
        workflow_execution_id=row.workflow_execution_id, requested_by=row.requested_by,
        decided_by=row.decided_by, decision_message=row.decision_message,
        created_at=row.created_at, submitted_at=row.submitted_at, decided_at=row.decided_at,
        delivered_at=row.delivered_at, applied_at=row.applied_at,
        ddl=build_ddl(row.metric_view_fqn, row.proposed_definition),
    )


class MetricViewChangeRequestsManager:
    def __init__(self, db: Session, links_manager: Any = None):
        self._db = db
        self._repo = metric_view_change_requests_repo
        self._links = links_manager

    # ------------------------------------------------------------------ reads

    def list_for_asset(self, asset_id: UUID) -> List[MetricViewChangeRequestRead]:
        return [to_read(row) for row in self._repo.list_for_asset(self._db, asset_id)]

    def get(self, asset_id: UUID, request_id: UUID) -> MetricViewChangeRequestDetail:
        row = self._get_row(asset_id, request_id)
        return MetricViewChangeRequestDetail(
            **_read_fields(row),
            base_definition=row.base_definition,
            base_metric_view=parse_metric_view_definition(row.base_definition),
            proposed_metric_view=parse_metric_view_definition(row.proposed_definition),
        )

    def _get_row(self, asset_id: UUID, request_id: UUID) -> MetricViewChangeRequestDb:
        row = self._repo.get_for_asset(self._db, asset_id, request_id)
        if row is None:
            raise ChangeRequestError('metric_view_change_request_not_found',
                                     'The change request was not found.', 404,
                                     requestId=str(request_id))
        return row

    def read_metric_view(self, asset_id: UUID, ws_client: Optional[WorkspaceClient]):
        """The asset's metric view as Unity Catalog returns it to the user: (fqn, table)."""
        asset = asset_repo.get(self._db, id=asset_id)
        fqn = _uc_fqn(asset.location) if asset is not None else None
        if asset is None or fqn is None or (asset.platform or '').lower() != 'databricks' \
                or ws_client is None:
            raise MetricViewNotFoundError(
                'This asset is not a Unity Catalog metric view.', assetId=str(asset_id)
            )
        try:
            table = ws_client.tables.get(full_name=fqn)
        except Unauthenticated:
            raise UserTokenRequiredError(
                "Unity Catalog didn't accept the user's Databricks token. Sign in again."
            )
        except (NotFound, PermissionDenied, BadRequest):
            raise MetricViewNotFoundError(
                'The metric view was not found in Unity Catalog, or access was denied.',
                assetId=str(asset_id),
            )
        if getattr(table, 'table_type', None) != TableType.METRIC_VIEW:
            raise MetricViewNotFoundError(
                'This asset is not a Unity Catalog metric view.', assetId=str(asset_id)
            )
        return fqn, table

    # ------------------------------------------------------------------ draft

    def create_draft(
        self, asset_id: UUID, ws_client: Optional[WorkspaceClient],
        body: MetricViewChangeRequestCreate, user_email: str,
    ) -> MetricViewChangeRequestDetail:
        """A draft against the definition Unity Catalog returns to the user now."""
        spec = validate_proposal(body.definition)
        fqn, table = self.read_metric_view(asset_id, ws_client)
        base_definition = getattr(table, 'view_definition', None) or ''
        base_spec = parse_metric_view_definition(base_definition)
        if base_spec is None:
            raise ChangeRequestError(
                'metric_view_base_unreadable',
                "The metric view's current definition can't be parsed, so a change can't be "
                "proposed against it.", 409,
            )
        base_digest, proposed_digest = _digest(base_spec), _digest(spec)
        if base_digest == proposed_digest:
            raise ChangeRequestError(
                'metric_view_definition_unchanged',
                'The proposed definition is the same as the current one.', 422,
            )
        row = MetricViewChangeRequestDb(
            id=uuid4(), asset_id=asset_id, metric_view_fqn=metric_view_entity_id(fqn),
            base_definition=base_definition, base_digest=base_digest,
            base_owner=getattr(table, 'owner', None),
            proposed_definition=body.definition, proposed_digest=proposed_digest,
            justification=(body.justification or '').strip() or None, status='draft',
            warnings=self._removed_linked_fields(fqn, base_spec, spec),
            requested_by=user_email,
        )
        self._db.add(row)
        self._db.flush()
        self._db.commit()
        _audit('METRIC_VIEW_CHANGE_REQUEST_CREATED', row, user_email)
        return self.get(asset_id, row.id)

    def _removed_linked_fields(
        self, fqn: str, base_spec: Dict[str, Any], spec: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """A warning for each field with concept links that is in the base but not proposed."""
        if self._links is None:
            return []
        try:
            removed = self._links.list_for_metric_view(fqn, spec).removed_fields
        except Exception:
            logger.warning("Could not list the concept links of %s", fqn, exc_info=True)
            return []
        in_base = {name.casefold() for name in _field_names(base_spec)}
        return [
            _note('metric_view_linked_field_removed',
                  f"The field '{field.name}' has concept links and is removed.",
                  field=field.name, links=len(field.links))
            for field in removed if field.name.casefold() in in_base
        ]

    # ----------------------------------------------------------------- submit

    def submit(
        self, asset_id: UUID, request_id: UUID, ws_client: Optional[WorkspaceClient],
        user_email: str,
    ) -> MetricViewChangeRequestRead:
        """Run the pre-checks as the user and start the review workflow."""
        row = self._get_row(asset_id, request_id)
        if row.requested_by.lower() != (user_email or '').lower():
            raise ChangeRequestError('metric_view_change_request_not_requester',
                                     'Only the requester can submit this change request.', 403)
        if row.status != 'draft':
            raise ChangeRequestError('metric_view_change_request_not_draft',
                                     'Only a draft can be submitted.', 409, status=row.status)
        spec = validate_proposal(row.proposed_definition)
        fqn, table = self.read_metric_view(asset_id, ws_client)
        current = parse_metric_view_definition(getattr(table, 'view_definition', None) or '')
        if current is None or _digest(current) != row.base_digest:
            raise ChangeRequestError(
                'metric_view_base_stale',
                'The metric view changed in Unity Catalog since this draft was written. '
                'Write a new draft against the current definition.', 409,
            )
        warnings = self._check_materialization(ws_client, table, row, current, spec)
        warnings += self._removed_linked_fields(fqn, current, spec)

        now = _now()
        row.warnings = warnings
        row.status = 'in_review'
        row.submitted_at = now
        self._db.flush()
        self._db.commit()
        _audit('METRIC_VIEW_CHANGE_REQUEST_SUBMITTED', row, user_email,
               warnings=[w['code'] for w in warnings])

        execution_id = self._start_review(row, fqn, spec, user_email)
        if execution_id is None:
            row.status = 'draft'
            row.submitted_at = None
            self._db.commit()
            _audit('METRIC_VIEW_CHANGE_REQUEST_SUBMITTED', row, user_email, success=False,
                   error_code='metric_view_change_no_approval')
            raise ChangeRequestError(
                'metric_view_change_no_approval',
                'No active workflow asks for an approval of metric view change requests, so '
                'the request stays a draft. An admin can activate one in Workflows.', 409,
            )
        row.workflow_execution_id = execution_id
        self._db.commit()
        return to_read(row)

    def _check_materialization(
        self, ws_client: WorkspaceClient, table: Any, row: MetricViewChangeRequestDb,
        current: Dict[str, Any], spec: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """The documented constraints of materialized metric views.

        Returns warnings for what the user can't see.
        """
        owner = getattr(table, 'owner', None)
        if (current.get('materialization') or spec.get('materialization')) \
                and row.base_owner and owner and owner != row.base_owner:
            raise ChangeRequestError(
                'metric_view_owner_changed',
                "The owner of this materialized metric view changed since the draft was "
                "written. Write a new draft.", 409, owner=owner,
            )
        if not spec.get('materialization'):
            return []
        if is_group_principal(owner):
            raise ChangeRequestError(
                'metric_view_materialized_group_owner',
                'A materialized metric view cannot be owned by a group.', 422, owner=owner,
            )
        sources = [spec.get('source')] + [j.get('source') for j in spec.get('joins') or []]
        warnings: List[Dict[str, Any]] = []
        for source in dict.fromkeys(s.strip() for s in sources if isinstance(s, str)):
            warnings += self._check_materialized_source(ws_client, source)
        return warnings

    def _check_materialized_source(self, ws_client: WorkspaceClient,
                                   source: str) -> List[Dict[str, Any]]:
        not_checked = [_note(
            'metric_view_source_not_checked',
            f"The source '{source}' could not be checked for row filters, column masks and "
            "ABAC policies.", source=source,
        )]
        if not _TABLE_NAME.match(source):
            return not_checked
        name = source.replace('`', '')
        try:
            info = ws_client.tables.get(full_name=name)
        except (NotFound, PermissionDenied, BadRequest, Unauthenticated):
            return not_checked
        secured = None
        if getattr(info, 'row_filter', None) is not None:
            secured = 'row_filter'
        elif any(getattr(c, 'mask', None) is not None
                 for c in getattr(info, 'columns', None) or []):
            secured = 'column_mask'
        else:
            try:
                policies = ws_client.policies.list_policies(
                    on_securable_type='TABLE', on_securable_fullname=name, include_inherited=True,
                )
                if next(iter(policies), None) is not None:
                    secured = 'abac_policy'
            except Exception:
                logger.info("ABAC policies of %s could not be listed", name, exc_info=True)
                return not_checked
        if secured:
            raise ChangeRequestError(
                'metric_view_materialized_source_secured',
                f"A materialized metric view can't use the source '{source}': it has a "
                f"{secured.replace('_', ' ')}.", 422, source=source, kind=secured,
            )
        return []

    def _start_review(self, row: MetricViewChangeRequestDb, fqn: str, spec: Dict[str, Any],
                      user_email: str) -> Optional[str]:
        """Fire the review trigger; the id of the execution paused for approval, else None."""
        from src.common.workflow_triggers import get_trigger_registry
        from src.models.process_workflows import EntityType, ExecutionStatus

        entity_data = {
            'request_id': str(row.id),
            'asset_id': str(row.asset_id),
            'metric_view_fqn': row.metric_view_fqn,
            'justification': row.justification,
            'base_digest': row.base_digest,
            'proposed_digest': row.proposed_digest,
            'proposed_definition': row.proposed_definition,
            'dimensions': len(spec.get('dimensions') or []),
            'measures': len(spec.get('measures') or []),
            'warnings': [w['code'] for w in row.warnings or []],
            'requester_email': user_email,
        }
        try:
            executions = get_trigger_registry(self._db).on_request_definition_change(
                entity_type=EntityType.METRIC_VIEW, entity_id=str(row.asset_id),
                entity_name=fqn, entity_data=entity_data, user_email=user_email,
                blocking=True,
            )
        except Exception:
            logger.error("The review of metric view change request %s could not start",
                         row.id, exc_info=True)
            if not self._db.is_active:
                self._db.rollback()
            return None
        paused = [e for e in executions if e.status == ExecutionStatus.PAUSED]
        return paused[0].id if paused else None

    # ----------------------------------------------------------------- cancel

    def cancel(self, asset_id: UUID, request_id: UUID, user_email: str,
               is_admin: bool = False) -> MetricViewChangeRequestRead:
        """End a draft or a request in review; its paused workflow is cancelled."""
        row = self._get_row(asset_id, request_id)
        if not is_admin and row.requested_by.lower() != (user_email or '').lower():
            raise ChangeRequestError('metric_view_change_request_not_requester',
                                     'Only the requester can cancel this change request.', 403)
        previous = row.status
        if previous not in ('draft', 'in_review') or not self._repo.set_status_if(
            self._db, row, previous, {'status': 'cancelled', 'decided_at': _now()},
        ):
            raise ChangeRequestError('metric_view_change_request_not_cancellable',
                                     'This change request can no longer be cancelled.', 409,
                                     status=row.status)
        if previous == 'in_review' and row.workflow_execution_id:
            self._cancel_execution(row.workflow_execution_id, user_email)
        self._db.commit()
        _audit('METRIC_VIEW_CHANGE_REQUEST_CANCELLED', row, user_email, previous_status=previous)
        return to_read(row)

    def _cancel_execution(self, execution_id: str, user_email: str) -> None:
        """Cancel the paused review and close its approval notifications."""
        import json
        from src.db_models.notifications import NotificationDb
        from src.db_models.process_workflows import WorkflowExecutionDb

        execution = self._db.get(WorkflowExecutionDb, execution_id)
        if execution is not None and execution.status == 'paused':
            execution.status = 'cancelled'
            execution.finished_at = _now()
        for notification in self._db.query(NotificationDb).filter(
            NotificationDb.action_type == 'workflow_approval', NotificationDb.read.is_(False),
        ).all():
            try:
                payload = notification.action_payload
                payload = json.loads(payload) if isinstance(payload, str) else (payload or {})
            except (TypeError, ValueError):
                continue
            if payload.get('execution_id') == execution_id:
                payload.update({'handled': True, 'decision': 'cancelled',
                                'handled_by': user_email})
                notification.action_payload = json.dumps(payload)
                notification.read = True
        self._db.flush()

    # --------------------------------------------------------------- decision

    def on_workflow_completed(
        self, request_id: Optional[str], *, approved: Optional[bool],
        responded_by: Optional[str], execution_id: Optional[str] = None,
    ) -> None:
        """Record the review's decision and deliver an approved request.

        Called by the workflow executor when the review workflow ends. A request
        that is no longer in review (cancelled, or decided by another workflow)
        is left alone. Only an approval by someone other than the requester is
        delivered.
        """
        try:
            row = self._repo.get(self._db, id=UUID(str(request_id)))
        except (TypeError, ValueError):
            row = None
        if row is None or row.status != 'in_review':
            logger.info("Metric view change request %s is not in review; decision ignored",
                        request_id)
            return
        now = _now()
        values: Dict[str, Any] = {'decided_by': responded_by, 'decided_at': now,
                                  'decision_message': self._decision_message(execution_id)}
        own = bool(responded_by) and responded_by.lower() == row.requested_by.lower()
        if approved and not own:
            if self._repo.set_status_if(self._db, row, 'in_review',
                                        {**values, 'status': 'approved'}):
                self._db.commit()
                _audit('METRIC_VIEW_CHANGE_REQUEST_APPROVED', row, responded_by,
                       execution_id=execution_id)
                self.deliver(row)
            return
        if approved:
            values.update(error_code='own_change_request_approval', error_params={
                'message': "The requester can't approve their own change request."})
        elif approved is None:
            values.update(error_code='metric_view_change_no_approval', error_params={
                'message': 'The review ended without an approval decision.'})
        if self._repo.set_status_if(self._db, row, 'in_review', {**values, 'status': 'rejected'}):
            self._db.commit()
            _audit('METRIC_VIEW_CHANGE_REQUEST_REJECTED', row, responded_by,
                   execution_id=execution_id, error_code=values.get('error_code'))

    def _decision_message(self, execution_id: Optional[str]) -> Optional[str]:
        """The reason the approver gave, from the review's last approval step."""
        if not execution_id:
            return None
        try:
            from src.db_models.process_workflows import WorkflowStepExecutionDb
            import json
            steps = self._db.query(WorkflowStepExecutionDb).filter(
                WorkflowStepExecutionDb.execution_id == execution_id,
            ).all()
            for step in reversed(steps):
                data = step.result_data
                data = json.loads(data) if isinstance(data, str) else (data or {})
                if 'approval_result' in data:
                    reason = data.get('reason') or data.get('message')
                    return str(reason)[:4000] if reason else None
        except Exception:
            logger.warning("Could not read the decision of execution %s", execution_id,
                           exc_info=True)
        return None

    # --------------------------------------------------------------- delivery

    def _delivery_modes(self) -> List[str]:
        """The active modes this phase delivers with (Indirect, Manual); Manual when none is."""
        from src.common.config import get_settings
        settings = get_settings()
        modes = [m for m, on in (('indirect', settings.DELIVERY_MODE_INDIRECT),
                                 ('manual', settings.DELIVERY_MODE_MANUAL)) if on]
        return modes or ['manual']

    def deliver(self, row: MetricViewChangeRequestDb) -> None:
        """Deliver an approved request; ``delivered`` or ``failed`` with a coded error."""
        modes = self._delivery_modes()
        ddl = build_ddl(row.metric_view_fqn, row.proposed_definition)
        details: Dict[str, Any] = {}
        references: List[str] = []
        try:
            # A savepoint: a failed delivery drops the notifications it created. The
            # files of Indirect come last (it puts them back itself when a write
            # fails), so no later step can fail and leave them behind.
            with self._db.begin_nested():
                if 'manual' in modes:
                    recipients = self._deliver_manual(row, ddl)
                    details['manual'] = {'recipients': recipients}
                    references += recipients
                if 'indirect' in modes:
                    files = self._deliver_indirect(row, ddl)
                    details['indirect'] = {'files': files}
                    references = files + references
        except Exception as exc:
            e = exc if isinstance(exc, _DeliveryError) else _DeliveryError(
                'metric_view_delivery_failed', 'The change could not be delivered.')
            if not isinstance(exc, _DeliveryError):
                logger.error("Delivery of metric view change request %s failed", row.id,
                             exc_info=True)
            if not self._db.is_active:
                self._db.rollback()
            row.status = 'failed'
            row.delivery_mode = ','.join(modes)
            # Undone: the savepoint dropped the notifications and Indirect put its
            # files back (its error names any it could not)
            row.delivery_details = None
            row.error_code = e.code
            row.error_params = {'message': e.message, **e.params}
            self._db.commit()
            _audit('METRIC_VIEW_CHANGE_REQUEST_DELIVERY_FAILED', row, row.decided_by,
                   success=False, delivery_mode=row.delivery_mode, error_code=e.code)
            self._notify_failed(row)
            return
        row.status = 'delivered'
        row.delivered_at = _now()
        row.delivery_mode = ','.join(modes)
        row.delivery_reference = ', '.join(references)[:1000] or None
        row.delivery_details = details
        self._db.commit()
        _audit('METRIC_VIEW_CHANGE_REQUEST_DELIVERED', row, row.decided_by,
               delivery_mode=row.delivery_mode, delivery_reference=row.delivery_reference)

    def _deliver_indirect(self, row: MetricViewChangeRequestDb, ddl: str) -> List[str]:
        """The YAML and the DDL in the Git working copy (``DeliveryService``)."""
        from src.controller.delivery_service import (
            DeliveryChangeType, DeliveryMode, DeliveryPayload, get_delivery_service,
        )
        try:
            service = get_delivery_service()
        except RuntimeError:
            raise _DeliveryError('metric_view_delivery_git_unavailable',
                                 'The Git repository for Indirect delivery is not available.')
        results = service.deliver(DeliveryPayload(
            change_type=DeliveryChangeType.METRIC_VIEW_UPDATE, entity_type='MetricView',
            entity_id=row.metric_view_fqn, user=row.requested_by,
            data={'request_id': str(row.id), 'fqn': row.metric_view_fqn,
                  'definition': row.proposed_definition, 'ddl': ddl},
        ), modes=[DeliveryMode.INDIRECT]).results
        result = results[0] if results else None
        if result is None or not result.success:
            code = (result.details.get('error_code') if result else None) \
                or 'metric_view_delivery_failed'
            params = (result.details.get('error_params') if result else None) or {}
            message = 'The definition could not be written to the Git repository.'
            if code == 'metric_view_delivery_restore_failed':
                message += (f" These files could not be put back as they were: "
                            f"{params.get('files')}.")
            raise _DeliveryError(code, message, **params)
        return [f"{DELIVERY_SUBDIR}/{name}" for name in result.details.get('files') or []]

    def _deliver_manual(self, row: MetricViewChangeRequestDb, ddl: str) -> List[str]:
        """A notification with the DDL to the asset's owners (else to the approver)."""
        recipients = resolve_owner_emails(self._db, 'asset', str(row.asset_id)) \
            or [r for r in [row.decided_by] if r]
        if not recipients:
            raise _DeliveryError('metric_view_delivery_no_recipient',
                                 'Nobody could be notified to run the statement.')
        description = (
            f"The change request for the metric view {row.metric_view_fqn} was approved. "
            f"Run this statement to apply it:\n\n{ddl}"
        )
        data = notification_i18n_data(MANUAL_TITLE_KEY, MANUAL_DESCRIPTION_KEY,
                                      fqn=row.metric_view_fqn, ddl=ddl)
        try:
            for recipient in recipients:
                notification_repo.create(self._db, obj_in=Notification(
                    id=str(uuid4()), type=NotificationType.ACTION_REQUIRED,
                    title='Apply the metric view change', subtitle=row.metric_view_fqn,
                    description=description, link=f'/assets/{row.asset_id}',
                    recipient=recipient, created_at=_now(), data=data,
                ))
        except Exception:
            logger.error("Could not notify the owners of %s", row.metric_view_fqn,
                         exc_info=True)
            raise _DeliveryError('metric_view_delivery_notification_failed',
                                 'The owners could not be notified.')
        return recipients

    def _notify_failed(self, row: MetricViewChangeRequestDb) -> None:
        try:
            notification_repo.create(self._db, obj_in=Notification(
                id=str(uuid4()), type=NotificationType.WARNING,
                title='Metric view change not delivered', subtitle=row.metric_view_fqn,
                description=(f"The approved change request for the metric view "
                             f"{row.metric_view_fqn} could not be delivered."),
                link=f'/assets/{row.asset_id}', recipient=row.requested_by,
                created_at=_now(),
                data=notification_i18n_data(FAILED_TITLE_KEY, FAILED_DESCRIPTION_KEY,
                                            fqn=row.metric_view_fqn),
            ))
            self._db.commit()
        except Exception:
            logger.error("Could not tell %s that the delivery failed", row.requested_by,
                         exc_info=True)


def adopt_applied_request(
    db: Session, fqn: str, digest: str,
) -> Optional[Tuple[MetricViewChangeRequestDb, datetime]]:
    """The delivered request whose definition Unity Catalog now has, marked applied.

    Called by the drift check with the digest just read: when a delivered
    request proposed exactly this definition, it is the one that was applied
    (by the owner, or by a merged pull request). Returns it with the time, or
    None when no delivered request matches.
    """
    row = metric_view_change_requests_repo.delivered_with_digest(db, fqn, digest)
    if row is None:
        return None
    now = _now()
    row.applied_at = now
    db.flush()
    _audit('METRIC_VIEW_CHANGE_REQUEST_APPLIED', row, None)
    return row, now
