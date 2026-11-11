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

from src.common.logging import get_logger
from src.controller.entity_dict_builder import (
    UC_TABLE_FIELDS,
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
    "not_found": "maturity_uc_table_not_found",
    "permission_denied": "maturity_uc_table_permission_denied",
    "read_failed": "maturity_uc_table_read_failed",
}
_UC_STATUS_MESSAGES = {
    "client_unavailable": "Unity Catalog can't be reached, so the fields of table {tableName} "
                          "are missing.",
    "not_found": "Table {tableName} was not found in Unity Catalog, so its fields are missing.",
    "permission_denied": "The app may not read table {tableName} in Unity Catalog, so its "
                         "fields are missing.",
    "read_failed": "Table {tableName} could not be read from Unity Catalog, so its fields "
                   "are missing.",
}
GATE_ERROR_CODE = "maturity_gate_error"
_UC_FIELD_IN_RULE = re.compile(
    r"\.(" + "|".join(sorted(UC_TABLE_FIELDS, key=len, reverse=True)) + r")\b"
)


def _default_workspace_client():
    from src.common.workspace_client import get_workspace_client
    return get_workspace_client()


class MaturityEvaluator:
    """Evaluates maturity for Data Products, Data Contracts and table/view Assets.

    ``workspace_client`` (a client, or a callable returning one) reads the
    Unity Catalog table behind an asset; by default the app's client is used,
    only when an evaluated asset points to a UC table.
    """

    def __init__(self, workspace_client: Any = None):
        if workspace_client is None:
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
        or a view.
        """
        if entity_type not in _ENTITY_DICT_BUILDERS and entity_type != "Asset":
            logger.warning("No entity dict builder for type: %s", entity_type)
            return None

        entity_dict = self._build_entity_dict(db, entity_type, entity_id)
        if entity_dict is None:
            return None

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
        # A gate on UC table fields ran while the table couldn't be read
        uc_gate_ran = False

        for level in levels:
            gates = level.gates or []
            gate_results = []
            all_required_pass = True

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
                    continue

                passed, message, errored = self._evaluate_gate(
                    policy.rule, entity_dict, policy_name=policy.name,
                )
                uses_uc_fields = bool(uc_notice) and bool(
                    _UC_FIELD_IN_RULE.search(policy.rule or "")
                )
                uc_gate_ran = uc_gate_ran or uses_uc_fields
                if passed:
                    total_gates_passed += 1
                elif gate.required:
                    all_required_pass = False

                # A gate that failed on UC fields the table couldn't provide
                # says so with a code, instead of a plain "value is null".
                notice = uc_notice if (uses_uc_fields and not passed) else None
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
                ))

            level_results.append(LevelResult(
                level_order=level.level_order,
                level_name=level.name,
                level_icon=level.icon,
                level_color=level.color,
                achieved=all_required_pass,
                gates=gate_results,
            ))

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

        if persist and uc_gate_ran:
            # The result depends on table fields that couldn't be read, so it is not a
            # maturity outcome: keep the stored level, and store nothing, change nothing,
            # fire nothing. The gate messages still say why the fields are missing.
            previous = maturity_repo.get_latest_snapshot(
                db, entity_type=entity_type, entity_id=entity_id
            )
            report.achieved_level_order = previous.achieved_level_order if previous else None
            report.achieved_level_name = previous.achieved_level_name if previous else None
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

            self._persist(db, report)

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
    def _persist(db: Session, report: MaturityReport) -> None:
        """Persist a snapshot and update the cached maturity level on the entity."""
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
                details={
                    "from_maturity_level": from_level,
                    "to_maturity_level": to_level,
                },
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
) -> Optional[MaturityReport]:
    """Re-evaluate an asset after it changed (run as a background task).

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
            return MaturityEvaluator(workspace_client).evaluate(
                db, entity_type="Asset", entity_id=str(asset_id),
                persist=True, evaluated_by=evaluated_by,
            )
    except Exception:
        logger.warning("Maturity re-evaluation failed for asset %s", asset_id, exc_info=True)
        return None
