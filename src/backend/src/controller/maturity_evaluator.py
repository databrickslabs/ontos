"""Maturity evaluation engine.

Evaluates an entity against admin-configured maturity levels.
Levels are cumulative: evaluation stops at the first level where a required gate fails.
"""
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from sqlalchemy.orm import Session

from src.common.api_errors import CodedValueError
from src.common.logging import get_logger
from src.common.run_identity import RunIdentity
from src.controller.entity_dict_builder import (
    SNAPSHOT_UC_TABLE_KEY,
    UC_TABLE_FIELDS,
    UC_TABLE_UNAUTHENTICATED,
    build_asset_dict,
    build_data_product_dict,
    build_data_contract_dict,
)
from src.models.maturity import (
    MaturityReport,
    MaturityNotice,
    LevelResult,
    GateResult,
)
from src.repositories.maturity_repository import maturity_repo

logger = get_logger(__name__)

_ENTITY_DICT_BUILDERS = {
    "DataProduct": build_data_product_dict,
    "DataContract": build_data_contract_dict,
}

# Codes for a UC-backed asset whose table couldn't be read (by ``uc_table_status``)
_UC_STATUS_CODES = {
    "client_unavailable": "maturity_uc_table_client_unavailable",
    "unreadable": "maturity_uc_table_unreadable",
    # A refused token reads to the user as an unreadable table
    UC_TABLE_UNAUTHENTICATED: "maturity_uc_table_unreadable",
    "read_failed": "maturity_uc_table_read_failed",
}
_UC_STATUS_MESSAGES = {
    "client_unavailable": "Unity Catalog can't be reached, so the fields of table {tableName} "
                          "are missing.",
    "unreadable": "Table {tableName} can't be read from Unity Catalog, so its fields are missing.",
    UC_TABLE_UNAUTHENTICATED: "Table {tableName} can't be read from Unity Catalog, so its "
                              "fields are missing.",
    "read_failed": "Table {tableName} could not be read from Unity Catalog, so its fields "
                   "are missing.",
}
GATE_ERROR_CODE = "maturity_gate_error"
_UC_FIELD_IN_RULE = re.compile(
    r"\.(" + "|".join(sorted(UC_TABLE_FIELDS, key=len, reverse=True)) + r")\b"
)


class MaturityUcAuthenticationError(CodedValueError):
    """Unity Catalog refused the token the evaluation reads with (expired or revoked)."""

    code = "maturity_uc_authentication_failed"

    def __init__(self, table_name: Optional[str]):
        super().__init__(
            "Unity Catalog refused the token while reading table {tableName}.".format(
                tableName=table_name),
            tableName=table_name,
        )


def _default_workspace_client():
    from src.common.workspace_client import get_workspace_client
    return get_workspace_client()


class MaturityEvaluator:
    """Evaluates maturity for Data Products, Data Contracts and table/view Assets.

    ``workspace_client`` (a client, or a callable returning one) reads the
    Unity Catalog table behind an asset; by default the app's client is used,
    only when an evaluated asset points to a UC table.

    ``run_identity``: whose permissions that table is read with. An evaluation
    a user starts (the asset maturity routes, an asset write) passes theirs, so
    a table they can't read stays unreadable for them; the default, the app's,
    is for runs no user started.
    """

    def __init__(self, workspace_client: Any = None, *,
                 run_identity: Optional[RunIdentity] = None,
                 stop_on_uc_auth_failure: bool = False):
        # A bulk run raises MaturityUcAuthenticationError on a refused token instead of
        # going on with the table as unreadable
        self._stop_on_uc_auth_failure = stop_on_uc_auth_failure
        if run_identity is not None:
            self._get_client = run_identity.workspace_client
        elif workspace_client is None:
            self._get_client: Callable[[], Any] = _default_workspace_client
        elif callable(workspace_client) and not hasattr(workspace_client, "tables"):
            self._get_client = workspace_client
        else:
            self._get_client = lambda: workspace_client

    def _build_entity_dict(self, db: Session, entity_type: str,
                           entity_id: str) -> Optional[Dict[str, Any]]:
        if entity_type == "Asset":
            return build_asset_dict(db, entity_id, get_workspace_client=self._get_client)
        return _ENTITY_DICT_BUILDERS[entity_type](db, entity_id)

    def evaluate(
        self,
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        persist: bool = True,
        evaluated_by: Optional[str] = None,
    ) -> Optional[MaturityReport]:
        """Evaluate maturity for an entity.

        Returns None if the entity is not found. Raises
        ``UnsupportedMaturityAssetTypeError`` for an asset that isn't a table
        or a view, and ``MaturityUcAuthenticationError`` (before storing anything)
        when built with ``stop_on_uc_auth_failure`` and Unity Catalog refuses the token.
        """
        if entity_type not in _ENTITY_DICT_BUILDERS and entity_type != "Asset":
            logger.warning("No entity dict builder for type: %s", entity_type)
            return None

        entity_dict = self._build_entity_dict(db, entity_type, entity_id)
        if entity_dict is None:
            return None
        if (self._stop_on_uc_auth_failure
                and entity_dict.get("uc_table_status") == UC_TABLE_UNAUTHENTICATED):
            raise MaturityUcAuthenticationError(entity_dict.get("uc_table_name"))

        if persist and entity_type == "Asset":
            # Two evaluations of one asset (two quick edits) run one after the other:
            # the second reads the snapshot the first stored, so it can't fire the same
            # change. Taken after the dict is built, so the lock doesn't span the UC read.
            _lock_asset_row(db, entity_id)

        entity_name = entity_dict.get("name")
        uc_notice = _uc_notice(entity_dict)

        # Load levels applicable to this entity type
        levels = maturity_repo.get_all_ordered(db, entity_type=entity_type)
        if not levels:
            return MaturityReport(
                entity_type=entity_type,
                entity_id=entity_id,
                entity_name=entity_name,
                evaluated_at=datetime.now(timezone.utc),
                evaluated_by=evaluated_by,
                notices=[uc_notice] if uc_notice else [],
            )

        level_results = []
        achieved_order = None
        achieved_name = None
        total_gates_passed = 0
        total_gates = 0
        # A required gate on UC table fields ran while the table couldn't be read
        uc_gate_ran = False
        # Levels whose result doesn't depend on UC fields, from the first level up
        prefix_len = 0
        prefix_order = None
        prefix_name = None
        prefix_open = True
        # The first level that isn't certain failed on a gate that doesn't need UC fields
        blocker_certain = False

        for level in levels:
            gates = level.gates or []
            gate_results = []
            all_required_pass = True
            level_certain_failure = False
            level_uses_uc = False

            for gate in gates:
                total_gates += 1
                policy = gate.compliance_policy
                if not policy:
                    gate_results.append(GateResult(
                        gate_id=str(gate.id),
                        policy_id=gate.compliance_policy_id,
                        policy_name="(missing policy)",
                        required=gate.required,
                        passed=False,
                        message="Compliance policy not found",
                    ))
                    if gate.required:
                        all_required_pass = False
                        level_certain_failure = True
                    continue

                passed, message, errored = self._evaluate_gate(
                    policy.rule, entity_dict, policy_name=policy.name,
                )
                uses_uc_fields = bool(uc_notice) and bool(
                    _UC_FIELD_IN_RULE.search(policy.rule or "")
                )
                if uses_uc_fields:
                    # Its result was computed on missing fields: not evaluated, not passed
                    passed, errored = False, False
                uc_gate_ran = uc_gate_ran or (uses_uc_fields and gate.required)
                level_uses_uc = level_uses_uc or (uses_uc_fields and gate.required)
                if passed:
                    total_gates_passed += 1
                elif gate.required:
                    all_required_pass = False
                    level_certain_failure = level_certain_failure or not uses_uc_fields

                # A gate on UC fields the table couldn't provide says so with a
                # code, instead of a plain "value is null".
                notice = uc_notice if uses_uc_fields else None
                if notice is None and errored:
                    # The error itself stays in the server log
                    notice = MaturityNotice(
                        code=GATE_ERROR_CODE,
                        message=f"Gate {policy.name} could not be evaluated.",
                        params={"gateName": policy.name},
                    )
                gate_results.append(GateResult(
                    gate_id=str(gate.id),
                    policy_id=gate.compliance_policy_id,
                    policy_name=policy.name,
                    required=gate.required,
                    passed=passed,
                    message=(notice.message if notice else message) if not passed else None,
                    message_code=notice.code if notice else None,
                    message_params=notice.params if notice else None,
                    evaluated=not uses_uc_fields,
                    failure_message=(policy.failure_message or None) if not passed else None,
                ))

            level_results.append(LevelResult(
                level_order=level.level_order,
                level_name=level.name,
                level_icon=level.icon,
                level_color=level.color,
                achieved=all_required_pass,
                gates=gate_results,
            ))

            if prefix_open:
                if all_required_pass and not level_uses_uc:
                    prefix_len += 1
                    prefix_order = level.level_order
                    prefix_name = level.name
                else:
                    prefix_open = False
                    blocker_certain = (not all_required_pass) and level_certain_failure

            if all_required_pass:
                achieved_order = level.level_order
                achieved_name = level.name
            else:
                # Cumulative: stop evaluating higher levels
                break

        now = datetime.now(timezone.utc)
        report = MaturityReport(
            entity_type=entity_type,
            entity_id=entity_id,
            entity_name=entity_name,
            achieved_level_order=achieved_order,
            achieved_level_name=achieved_name,
            total_levels=len(levels),
            gates_passed=total_gates_passed,
            gates_total=total_gates,
            levels=level_results,
            evaluated_at=now,
            evaluated_by=evaluated_by,
            notices=[uc_notice] if uc_notice else [],
        )

        if uc_gate_ran:
            # The levels up to the first uncertain one don't depend on UC fields, and the
            # first other level adds to them when it certainly fails. The report holds only
            # those certain levels: what this reader's own data proves. A level stored from
            # someone else's UC read never reaches a reader who can't read the table.
            certain_levels = prefix_len + (1 if blocker_certain else 0)
            report.levels = report.levels[:certain_levels]
            report.gates_total = sum(len(lr.gates) for lr in report.levels)
            report.gates_passed = sum(1 for lr in report.levels for gr in lr.gates if gr.passed)
            report.achieved_level_order = prefix_order
            report.achieved_level_name = prefix_name
            report.notices = [uc_notice]
            if not blocker_certain:
                # The table could take the asset higher
                report.notices.append(_partial_notice(uc_notice))
            achieved_order = prefix_order
            achieved_name = prefix_name
            if not persist:
                return report
            # Stored only when certain: the rest of the ladder can't be reached, or the
            # certain levels rise above the stored level. Anything else would be a drop or
            # a rise that the unreadable table could change, so the stored level stays.
            previous = maturity_repo.get_latest_snapshot(
                db, entity_type=entity_type, entity_id=entity_id
            )
            prev_order = previous.achieved_level_order if previous else None
            certain_rise = prefix_order is not None and (
                prev_order is None or prefix_order > prev_order
            )
            if not (blocker_certain or certain_rise):
                logger.warning(
                    "Maturity of %s %s not updated: its UC table could not be read (%s)",
                    entity_type, entity_id, uc_notice.code,
                )
                return report

        if persist:
            # Detect level change for trigger / change log
            prev_snapshot = maturity_repo.get_latest_snapshot(
                db, entity_type=entity_type, entity_id=entity_id
            )
            prev_level = prev_snapshot.achieved_level_order if prev_snapshot else None

            self._persist(db, report, uc_table_name=entity_dict.get("uc_table_name"))
            report.stored = True

            if achieved_order != prev_level:
                self._log_change(
                    db,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    from_level=prev_level,
                    to_level=achieved_order,
                    entity_name=entity_name,
                    evaluated_by=evaluated_by,
                    asset_type=entity_dict.get("asset_type"),
                    entity_data=_trigger_data(entity_type, entity_dict),
                )

        return report

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_gate(rule: str, entity_dict: dict, *,
                       policy_name: Optional[str] = None) -> tuple[bool, Optional[str], bool]:
        """Evaluate a compliance DSL rule against an entity dict.

        Returns ``(passed, message, errored)``. A rule that can't be parsed or
        evaluated fails with ``errored=True`` and no message: the error is logged
        here, and the gate result gets ``maturity_gate_error``.
        """
        from src.common.compliance_dsl import evaluate_rule_on_object
        try:
            passed, message = evaluate_rule_on_object(rule or "", entity_dict)
        except Exception:
            logger.error("Maturity gate %r could not be evaluated", policy_name, exc_info=True)
            return False, None, True
        if passed or (message or "").startswith("Assertion failed:"):
            return passed, message, False
        # A parse/evaluation error or a rule without ASSERT: keep its text out of results
        logger.error("Maturity gate %r could not be evaluated: %s", policy_name, message)
        return False, None, True

    @staticmethod
    def _persist(db: Session, report: MaturityReport, *,
                 uc_table_name: Optional[str] = None) -> None:
        """Persist a snapshot and update the cached maturity level on the entity.

        An asset's gate results also record the UC table they were evaluated
        against (``uc_table_name``, null for none): the history shows a snapshot
        only to readers of that table, even after the asset points elsewhere.
        """
        table_marker = (
            {SNAPSHOT_UC_TABLE_KEY: uc_table_name} if report.entity_type == "Asset" else {}
        )
        gate_results_data = []
        for lr in report.levels:
            for gr in lr.gates:
                gate_results_data.append({
                    "level_order": lr.level_order,
                    "level_name": lr.level_name,
                    "gate_id": gr.gate_id,
                    "policy_id": gr.policy_id,
                    "policy_name": gr.policy_name,
                    "required": gr.required,
                    "passed": gr.passed,
                    "message": gr.message,
                    **({"message_code": gr.message_code,
                        "message_params": gr.message_params} if gr.message_code else {}),
                    **({} if gr.evaluated else {"evaluated": False}),
                    **table_marker,
                })

        maturity_repo.create_snapshot(
            db,
            entity_type=report.entity_type,
            entity_id=report.entity_id,
            achieved_level_order=report.achieved_level_order,
            achieved_level_name=report.achieved_level_name,
            total_levels=report.total_levels,
            gates_passed=report.gates_passed,
            gates_total=report.gates_total,
            gate_results_json=json.dumps(gate_results_data),
            evaluated_by=report.evaluated_by,
        )

        # Update cached maturity on entity table
        _update_entity_cache(
            db,
            entity_type=report.entity_type,
            entity_id=report.entity_id,
            level_order=report.achieved_level_order,
        )

        db.commit()


    @staticmethod
    def _log_change(
        db: Session,
        *,
        entity_type: str,
        entity_id: str,
        from_level: Optional[int],
        to_level: Optional[int],
        entity_name: Optional[str] = None,
        evaluated_by: Optional[str] = None,
        asset_type: Optional[str] = None,
        entity_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Log maturity change to change log and fire workflow trigger."""
        try:
            from src.controller.change_log_manager import ChangeLogManager
            cl = ChangeLogManager()
            cl.log_change_with_details(
                db,
                entity_type=entity_type,
                entity_id=entity_id,
                action="MATURITY_CHANGED",
                username=evaluated_by or "system",
                details=_change_log_details(entity_type, from_level, to_level),
            )
        except Exception as e:
            logger.warning(f"Failed to log maturity change: {e}")

        try:
            from src.common.workflow_triggers import TriggerRegistry
            from src.models.process_workflows import EntityType
            et_map = {
                "DataProduct": EntityType.DATA_PRODUCT,
                "DataContract": EntityType.DATA_CONTRACT,
                # Assets fire as the workflow entity type of their asset type
                "Asset:Table": EntityType.TABLE,
                "Asset:View": EntityType.VIEW,
                "Asset:Metric View": EntityType.METRIC_VIEW,
            }
            key = f"Asset:{asset_type}" if entity_type == "Asset" else entity_type
            et_enum = et_map.get(key)
            # Table/view events carry the UC full name as entity id (as the
            # self-service ones do); the asset id stays in the payload.
            trigger_id = (entity_data or {}).get("uc_table_name") or entity_id
            if et_enum:
                registry = TriggerRegistry(db)
                registry.on_maturity_change(
                    entity_type=et_enum,
                    entity_id=trigger_id,
                    entity_name=entity_name,
                    entity_data=entity_data,
                    from_level=from_level,
                    to_level=to_level,
                    user_email=evaluated_by,
                )
        except Exception as e:
            logger.warning(f"Failed to fire maturity trigger: {e}")


def _lock_asset_row(db: Session, asset_id: str) -> None:
    """Hold the asset's row lock until the evaluation commits (no-op if not a UUID)."""
    from src.db_models.assets import AssetDb
    try:
        asset_uuid = uuid.UUID(str(asset_id))
    except ValueError:
        return
    db.query(AssetDb.id).filter(AssetDb.id == asset_uuid).with_for_update().first()


def _change_log_details(entity_type: str, from_level: Optional[int],
                        to_level: Optional[int]) -> Optional[Dict[str, Any]]:
    """The levels a ``MATURITY_CHANGED`` row records, or None for an asset.

    An asset's levels can come from the evaluator's own Unity Catalog read, and the
    entity timeline shows change rows to every reader of the asset. So an asset's row
    only says that the level changed; the levels stay in the history, which is shown
    only to readers of the table.
    """
    if entity_type == "Asset":
        return None
    return {"from_maturity_level": from_level, "to_maturity_level": to_level}


def _update_entity_cache(db: Session, *, entity_type: str, entity_id: str,
                          level_order: Optional[int]) -> None:
    """Update the cached maturity_level_order on the entity table."""
    now = datetime.now(timezone.utc)
    if entity_type == "DataProduct":
        from src.db_models.data_products import DataProductDb
        db.query(DataProductDb).filter(DataProductDb.id == entity_id).update(
            {"maturity_level_order": level_order, "maturity_evaluated_at": now},
            synchronize_session=False,
        )
    elif entity_type == "DataContract":
        from src.db_models.data_contracts import DataContractDb
        db.query(DataContractDb).filter(DataContractDb.id == entity_id).update(
            {"maturity_level_order": level_order, "maturity_evaluated_at": now},
            synchronize_session=False,
        )


def _uc_notice(entity_dict: Dict[str, Any]) -> Optional[MaturityNotice]:
    """Why the UC table fields of an asset are absent, or None when they aren't."""
    status = entity_dict.get("uc_table_status")
    code = _UC_STATUS_CODES.get(status)
    if not code:
        return None
    table_name = entity_dict.get("uc_table_name")
    return MaturityNotice(
        code=code,
        message=_UC_STATUS_MESSAGES[status].format(tableName=table_name),
        params={"tableName": table_name},
    )


PARTIAL_LEVEL_CODE = "maturity_level_partial"


def _partial_notice(uc_notice: MaturityNotice) -> MaturityNotice:
    """The report counts only the gates that don't need the unreadable table."""
    table_name = uc_notice.params.get("tableName")
    return MaturityNotice(
        code=PARTIAL_LEVEL_CODE,
        message=f"The level counts only the gates that don't need table {table_name}; "
                "the asset may reach a higher level.",
        params={"tableName": table_name},
    )


def _trigger_data(entity_type: str, entity_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """What a maturity workflow gets about an asset (the event id is its UC name)."""
    if entity_type != "Asset":
        return None
    return {
        "asset_id": entity_dict.get("id"),
        "asset_type": entity_dict.get("asset_type"),
        "location": entity_dict.get("location"),
        "uc_table_name": entity_dict.get("uc_table_name"),
    }


def evaluate_asset_maturity_on_change(
    asset_id: str,
    *,
    evaluated_by: Optional[str] = None,
    workspace_client: Any = None,
    run_identity: Optional[RunIdentity] = None,
) -> Optional[MaturityReport]:
    """Re-evaluate an asset after it changed (run as a background task).

    ``run_identity``: the identity of the user whose write triggered it.

    Opens its own session. Does nothing for asset types other than tables and
    views, or when no ``Asset`` maturity level exists, so most asset changes
    cost one query and no Unity Catalog call. Never raises: a failed
    evaluation must not fail the change that triggered it.
    """
    from src.common.database import get_db_session
    from src.controller.entity_dict_builder import MATURITY_ASSET_TYPES
    from src.db_models.assets import AssetDb

    try:
        with get_db_session() as db:
            if not maturity_repo.get_all_ordered(db, entity_type="Asset"):
                return None
            asset = db.get(AssetDb, uuid.UUID(str(asset_id)))
            type_name = asset.asset_type.name if asset and asset.asset_type else None
            if type_name not in MATURITY_ASSET_TYPES:
                return None
            return MaturityEvaluator(workspace_client, run_identity=run_identity).evaluate(
                db, entity_type="Asset", entity_id=str(asset_id),
                persist=True, evaluated_by=evaluated_by,
            )
    except Exception:
        logger.warning("Maturity re-evaluation failed for asset %s", asset_id, exc_info=True)
        return None
